from __future__ import annotations

import posixpath
import re
import ssl
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from .models import Game


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"x": MAIN_NS, "r": REL_NS}


class ScheduleError(RuntimeError):
    pass


MAX_GOOGLE_SHEET_BYTES = 25 * 1024 * 1024


def google_sheet_export_url(url: str) -> str:
    """Convert a normal Google Sheets sharing URL into an XLSX export URL."""
    parsed = urlparse(url.strip())
    if (parsed.hostname or "").casefold() != "docs.google.com":
        raise ScheduleError("Paste a complete docs.google.com Google Sheets link")
    match = re.search(r"/spreadsheets/(?:u/\d+/)?d/([A-Za-z0-9_-]+)", parsed.path)
    if not match:
        raise ScheduleError("The Google Sheets link does not contain a spreadsheet ID")
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    gid = (query.get("gid") or fragment.get("gid") or ["0"])[0]
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?{urlencode({'format': 'xlsx', 'gid': gid})}"


def download_google_sheet(url: str, destination: Path) -> Path:
    """Download a link-shared Google Sheet as an XLSX workbook."""
    export_url = google_sheet_export_url(url)
    default_paths = ssl.get_default_verify_paths()
    candidates = (
        default_paths.cafile,
        "/etc/ssl/cert.pem",
        "/private/etc/ssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
    )
    ca_file = next((value for value in candidates if value and Path(value).is_file()), None)
    context = ssl.create_default_context(cafile=ca_file)
    request = Request(
        export_url,
        headers={"User-Agent": "Soccer-Recorder/0.3 (+authorized team video operations)"},
    )
    try:
        with urlopen(request, timeout=45, context=context) as response:
            content = response.read(MAX_GOOGLE_SHEET_BYTES + 1)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ScheduleError(
                "Google denied the download. Share the Sheet as 'Anyone with the link' or download it as Excel."
            ) from exc
        raise ScheduleError(f"Google Sheets download failed (HTTP {exc.code})") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ScheduleError(f"Could not download the Google Sheet: {exc}") from exc
    if len(content) > MAX_GOOGLE_SHEET_BYTES:
        raise ScheduleError("The Google Sheet export is larger than 25 MB")
    if not content.startswith(b"PK"):
        raise ScheduleError(
            "Google did not return an Excel workbook. Share the Sheet as 'Anyone with the link' or download it as Excel."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination


def _column_index(cell_reference: str) -> int:
    letters = re.match(r"[A-Za-z]+", cell_reference)
    if not letters:
        raise ScheduleError(f"Invalid Excel cell reference: {cell_reference}")
    result = 0
    for char in letters.group(0).upper():
        result = result * 26 + ord(char) - 64
    return result


def _normalize_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _is_green(rgb: str | None) -> bool:
    if not rgb:
        return False
    value = rgb.strip().lstrip("#")
    if len(value) == 8:
        value = value[2:]
    if len(value) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return False
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return green >= 128 and green > red * 1.25 and green > blue * 1.25


def _parse_date(value: object, year_hint: int) -> date:
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.search(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>\d{2,4}))?", text)
    if match:
        parsed_year = int(match.group("year")) if match.group("year") else year_hint
        if parsed_year < 100:
            parsed_year += 2000
        return date(parsed_year, int(match.group("month")), int(match.group("day")))
    raise ScheduleError(f"Could not parse game date {value!r}")


def _parse_time(value: object) -> time:
    if isinstance(value, (int, float)):
        seconds = round((float(value) % 1) * 24 * 60 * 60)
        seconds %= 24 * 60 * 60
        return time(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    text = str(value).strip().replace(".", "")
    for fmt in ("%I:%M %p", "%I %p", "%H:%M", "%H%M"):
        try:
            return datetime.strptime(text.upper(), fmt).time()
        except ValueError:
            pass
    raise ScheduleError(f"Could not parse kickoff time {value!r}")


class XlsxScheduleReader:
    """Small dependency-free XLSX reader focused on schedule tables."""

    def __init__(self, workbook: Path | str, timezone: str = "America/New_York") -> None:
        self.workbook = Path(workbook)
        self.timezone = timezone
        self.link_issues: list[tuple[int, str, str]] = []

    def read_games(self, selected_only: bool = True) -> list[Game]:
        self.link_issues = []
        if not self.workbook.exists():
            raise ScheduleError(f"Workbook not found: {self.workbook}")
        try:
            with zipfile.ZipFile(self.workbook) as archive:
                shared_strings = self._read_shared_strings(archive)
                style_colors = self._read_style_colors(archive)
                sheet_path = self._first_sheet_path(archive)
                hyperlink_targets = self._read_hyperlinks(archive, sheet_path)
                root = ET.fromstring(archive.read(sheet_path))
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise ScheduleError(f"Cannot read Excel workbook {self.workbook}: {exc}") from exc

        raw_rows: list[tuple[int, dict[int, object], dict[int, str | None]]] = []
        for row_node in root.findall(".//x:sheetData/x:row", NS):
            row_number = int(row_node.attrib["r"])
            values: dict[int, object] = {}
            colors: dict[int, str | None] = {}
            for cell in row_node.findall("x:c", NS):
                reference = cell.attrib.get("r", "")
                column = _column_index(reference)
                style_id = int(cell.attrib.get("s", "0"))
                colors[column] = style_colors[style_id] if style_id < len(style_colors) else None
                value = self._cell_value(cell, shared_strings)
                if reference in hyperlink_targets:
                    value = hyperlink_targets[reference]
                values[column] = value
            raw_rows.append((row_number, values, colors))

        if not raw_rows:
            return []
        _, headers, _ = raw_rows[0]
        header_columns = {_normalize_header(value): column for column, value in headers.items() if value is not None}
        aliases = {
            "date": ("date",),
            "home": ("hometeam", "home"),
            "away": ("awayteam", "away"),
            "time": ("kickofftime", "kickoff", "time"),
            "url": ("livestreamlink", "livestream", "streamlink", "url"),
        }
        columns: dict[str, int] = {}
        for field, candidates in aliases.items():
            for candidate in candidates:
                if candidate in header_columns:
                    columns[field] = header_columns[candidate]
                    break
        missing = sorted(set(aliases) - set(columns))
        if missing:
            raise ScheduleError(f"Workbook is missing required columns: {', '.join(missing)}")

        year_hint = datetime.now().year
        for _, values, _ in raw_rows[1:]:
            raw_date = values.get(columns["date"])
            if isinstance(raw_date, (int, float)):
                year_hint = _parse_date(raw_date, year_hint).year
                break

        games: list[Game] = []
        required_columns = tuple(columns.values())
        for row_number, values, colors in raw_rows[1:]:
            if selected_only and not any(_is_green(colors.get(column)) for column in required_columns):
                continue
            raw_values = {field: values.get(column) for field, column in columns.items()}
            if any(raw_values[field] in (None, "") for field in ("date", "home", "away", "time")):
                continue
            if raw_values["url"] in (None, ""):
                self.link_issues.append((row_number, "", "Livestream link is missing"))
                continue
            url = str(raw_values["url"]).strip()
            parsed_url = urlparse(url)
            if parsed_url.scheme.casefold() not in {"http", "https"} or not parsed_url.netloc:
                self.link_issues.append((row_number, url, "Link must be a complete http:// or https:// URL"))
                continue
            try:
                game = Game(
                    row=row_number,
                    game_date=_parse_date(raw_values["date"], year_hint),
                    home_team=str(raw_values["home"]).strip(),
                    away_team=str(raw_values["away"]).strip(),
                    kickoff=_parse_time(raw_values["time"]),
                    livestream_url=url,
                    timezone=self.timezone,
                )
            except (ScheduleError, ValueError):
                continue
            games.append(game)
        return games

    @staticmethod
    def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
        try:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        return ["".join(node.text or "" for node in item.findall(".//x:t", NS)) for item in root.findall("x:si", NS)]

    @staticmethod
    def _read_style_colors(archive: zipfile.ZipFile) -> list[str | None]:
        root = ET.fromstring(archive.read("xl/styles.xml"))
        fill_colors: list[str | None] = []
        for fill in root.findall("x:fills/x:fill", NS):
            foreground = fill.find("x:patternFill/x:fgColor", NS)
            fill_colors.append(foreground.attrib.get("rgb") if foreground is not None else None)
        style_colors: list[str | None] = []
        for style in root.findall("x:cellXfs/x:xf", NS):
            fill_id = int(style.attrib.get("fillId", "0"))
            style_colors.append(fill_colors[fill_id] if fill_id < len(fill_colors) else None)
        return style_colors

    @staticmethod
    def _first_sheet_path(archive: zipfile.ZipFile) -> str:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find("x:sheets/x:sheet", NS)
        if sheet is None:
            raise ScheduleError("Workbook contains no sheets")
        relationship_id = sheet.attrib[f"{{{REL_NS}}}id"]
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for relationship in relationships.findall(f"{{{PKG_REL_NS}}}Relationship"):
            if relationship.attrib.get("Id") == relationship_id:
                target = relationship.attrib["Target"].lstrip("/")
                return target if target.startswith("xl/") else posixpath.normpath(posixpath.join("xl", target))
        raise ScheduleError("Cannot locate the first worksheet")

    @staticmethod
    def _read_hyperlinks(archive: zipfile.ZipFile, sheet_path: str) -> dict[str, str]:
        directory, filename = posixpath.split(sheet_path)
        rels_path = posixpath.join(directory, "_rels", f"{filename}.rels")
        try:
            relationships = ET.fromstring(archive.read(rels_path))
            sheet = ET.fromstring(archive.read(sheet_path))
        except KeyError:
            return {}
        targets = {
            node.attrib["Id"]: node.attrib.get("Target", "")
            for node in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
        }
        result: dict[str, str] = {}
        for link in sheet.findall(".//x:hyperlink", NS):
            relationship_id = link.attrib.get(f"{{{REL_NS}}}id")
            if relationship_id and relationship_id in targets:
                result[link.attrib["ref"]] = targets[relationship_id]
        return result

    @staticmethod
    def _cell_value(cell: ET.Element, shared_strings: list[str]) -> object | None:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(".//x:t", NS))
        value_node = cell.find("x:v", NS)
        if value_node is None or value_node.text is None:
            return None
        raw = value_node.text
        if cell_type == "s":
            index = int(raw)
            return shared_strings[index] if index < len(shared_strings) else ""
        if cell_type in {"str", "e"}:
            return raw
        try:
            return float(raw)
        except ValueError:
            return raw
