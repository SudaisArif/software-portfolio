"""Refresh public CMU men's soccer data without touching manual player prices."""

from html import unescape
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import json
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("TARTAN_DATA_PATH", ROOT / "data"))
ATHLETICS = "https://athletics.cmu.edu/sports/msoc"
FULL_APPEARANCE_MINUTES = 40
SOURCES = {
    "roster": f"{ATHLETICS}/2026-27/roster?dec=printer-decorator",
    "schedule": f"{ATHLETICS}/2026-27/schedule?dec=printer-decorator",
    "field_stats": f"{ATHLETICS}/2025-26/teams/carnegiemellon?tmpl=brief-category-template&pos=kickers&r=0",
    "goalkeeper_stats": f"{ATHLETICS}/2025-26/teams/carnegiemellon?tmpl=brief-category-template&pos=goalie&r=0",
}


def fetch(url):
    request = Request(url, headers={"User-Agent": "TartanFantasy/1.0 (student project; public athletics data)"})
    try:
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as error:
        # Some macOS Python installs do not inherit the Keychain CA bundle.
        # curl uses the system trust store, so it is a safe no-package fallback.
        try:
            result = subprocess.run(
                ["curl", "-L", "--fail", "--max-time", "60", "-s", "-A", request.headers["User-agent"], url],
                check=True,
                capture_output=True,
            )
            return result.stdout.decode("utf-8", errors="replace")
        except (subprocess.CalledProcessError, FileNotFoundError) as curl_error:
            raise RuntimeError(f"Unable to fetch {url}: {error}") from curl_error


def clean(value):
    value = re.sub(r"<script\b[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style\b[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def rows(document):
    output = []
    for match in re.finditer(r"<tr\b[^>]*>([\s\S]*?)</tr>", document, flags=re.I):
        row_html = match.group(1)
        cells = [clean(cell.group(2)) for cell in re.finditer(r"<(td|th)\b[^>]*>([\s\S]*?)</\1>", row_html, flags=re.I)]
        output.append((row_html, cells))
    return output


def slugify(name):
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))


def numeric(value):
    if not value or value == "-":
        return 0
    try:
        return float(f"0{value}" if value.startswith(".") else value)
    except ValueError:
        return 0


def parse_roster(document):
    positions = {"GK": "GK", "D": "DEF", "M": "MID", "F": "FWD"}
    players = []
    for row_html, cells in rows(document):
        if "full bio" not in row_html.lower() or len(cells) < 7:
            continue
        _, number, name, raw_position, year, height, hometown = cells[:7]
        number = re.sub(r"^No\.:\s*", "", number, flags=re.I)
        raw_position = re.sub(r"^Pos\.:\s*", "", raw_position, flags=re.I)
        year = re.sub(r"^Cl\.:\s*", "", year, flags=re.I)
        height = re.sub(r"^Ht\.:\s*", "", height, flags=re.I)
        hometown = re.sub(r"^Hometown/High School:\s*", "", hometown, flags=re.I)
        href_match = re.search(r'href="([^"]*/bios/[^"]+)"', row_html, flags=re.I)
        href = href_match.group(1) if href_match else ""
        players.append({
            "id": slugify(name),
            "number": number,
            "name": name,
            "position": positions.get(raw_position, raw_position),
            "class": year.replace(".", ""),
            "height": height,
            "hometown": hometown,
            "rosterUrl": f"https://athletics.cmu.edu{href}" if href else "",
        })
    return players


def parse_field_stats(document):
    keys = [
        "number", "name", "class", "position", "appearances", "starts", "goals",
        "assists", "ncaaPoints", "shots", "shotPct", "shotsOnGoal", "sogPct",
        "yellowCards", "redCards", "penalties", "gameWinners",
    ]
    stats = []
    for _, cells in rows(document):
        if len(cells) < len(keys) or not re.match(r"^(\d+|00)$", cells[0]):
            continue
        player = dict(zip(keys, cells[:len(keys)]))
        for key in keys[4:]:
            if key != "penalties":
                player[key] = numeric(player[key])
        player["id"] = slugify(player["name"])
        player["minutes"] = None
        stats.append(player)
    return stats


def parse_goalkeeper_stats(document):
    header_match = re.search(r"<thead\b[\s\S]*?</thead>", document, flags=re.I)
    if not header_match:
        return {}
    headers = [clean(match.group(1)).lower() for match in re.finditer(r"<th\b[^>]*>([\s\S]*?)</th>", header_match.group(), flags=re.I)]
    goalkeepers = {}
    for _, cells in rows(document):
        if len(cells) < 10 or not re.match(r"^(\d+|00)$", cells[0]):
            continue
        values = dict(zip(headers, cells))
        goalkeepers[slugify(cells[1])] = {
            "minutes": numeric(values.get("min", "0")),
            "goalsAgainst": numeric(values.get("ga", "0")),
            "saves": numeric(values.get("sv", "0")),
            "savePct": numeric(values.get("sv%", "0")),
            "shutouts": numeric(values.get("sho", values.get("so", "0"))),
        }
    return goalkeepers


def clock_seconds(value):
    try:
        minutes, seconds = value.strip().split(":", 1)
        return int(minutes) * 60 + int(seconds)
    except (ValueError, AttributeError):
        return 0


def display_name(last, first):
    return re.sub(r"\s+", " ", f"{first.strip()} {last.strip()}").strip()


def boxscore_links(schedule_document):
    links = []
    for match in re.finditer(r'<tr\b[^>]*class="[^"]*event-row[^"]*"[^>]*>([\s\S]*?)</tr>', schedule_document, flags=re.I):
        href = re.search(r'href="([^"]*boxscores/[^"]+\.xml)"', match.group(1), flags=re.I)
        links.append(f"{urljoin(SOURCES['schedule'], href.group(1))}?dec=printer-decorator" if href else None)
    return links


def parse_schedule(schedule_document, existing):
    months = {
        "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
        "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
    }
    known_venues = {
        "Grove City": "Don Lyle Field · Grove City, PA",
        "Otterbein": "Memorial Stadium · Westerville, OH",
        "John Carroll": "Don Shula Stadium · University Heights, OH",
        "Ohio Northern": "Kerscher Stadium · Ada, OH",
        "Denison": "Barclay-Thomsen Field · Granville, OH",
        "Emory": "Woodruff PE Center · Atlanta, GA",
        "UChicago": "Stagg Field · Chicago, IL",
        "Rochester (N.Y.)": "Edwin Fauver Stadium · Rochester, NY",
        "Case Western Reserve": "DiSanto Field · Cleveland, OH",
    }
    existing_by_opponent = {re.sub(r"\s*\*$", "", event["opponent"]): event for event in existing}
    active_month = 9
    events = []
    token_pattern = re.compile(r'<tr\b[^>]*class="[^"]*(month-title|event-row)[^"]*"[^>]*>[\s\S]*?</tr>', flags=re.I)
    for token in token_pattern.finditer(schedule_document):
        row_html = token.group()
        if token.group(1).lower() == "month-title":
            month_name = clean(row_html)
            active_month = months.get(month_name, active_month)
            continue
        parsed_rows = rows(row_html)
        if not parsed_rows or len(parsed_rows[0][1]) < 5:
            continue
        cells = parsed_rows[0][1]
        day_match = re.search(r"\d+", cells[0])
        if not day_match:
            continue
        day = int(day_match.group())
        home = bool(re.search(r"event-location-badge[^>]*>\s*VS\s*<", row_html, flags=re.I))
        conference_marker = bool(re.search(r"\*\s*$", cells[1]))
        opponent = re.sub(r"\s*\*$", "", re.sub(r"^(AT|VS)\s+", "", cells[1], flags=re.I)).strip()
        published_time = cells[4].strip() or "TBA"
        previous = existing_by_opponent.get(opponent, {})
        date_value = datetime(2026, active_month, day)
        if published_time != "TBA":
            zone_match = re.search(r"\s+([ECMP][DS]T)$", published_time, flags=re.I)
            zone_code = zone_match.group(1).upper() if zone_match else "ET"
            clock_value = re.sub(r"\s+[A-Z]{2,3}$", "", published_time).strip()
            kickoff_time = datetime.strptime(clock_value, "%I:%M %p").time()
            source_zone = {
                "CDT": "America/Chicago", "CST": "America/Chicago",
                "MDT": "America/Denver", "MST": "America/Denver",
                "PDT": "America/Los_Angeles", "PST": "America/Los_Angeles",
            }.get(zone_code, "America/New_York")
            kickoff_local = datetime.combine(date_value.date(), kickoff_time, ZoneInfo(source_zone))
            kickoff = kickoff_local.astimezone(ZoneInfo("America/New_York"))
            time_value = kickoff.strftime("%I:%M %p").lstrip("0")
            deadline = (kickoff - timedelta(hours=1)).isoformat()
        else:
            time_value = "TBA"
            deadline = previous.get("deadline", f"{date_value.date().isoformat()}T12:00:00-04:00")
        coverage = []
        for anchor in re.finditer(r"<a\b([^>]*)>([\s\S]*?)</a>", row_html, flags=re.I):
            label = clean(anchor.group(2)).lower()
            href = re.search(r'href="([^"]+)"', anchor.group(1), flags=re.I)
            if not href or label not in {"live stats", "video"}:
                continue
            coverage.append({"type": label.replace(" ", ""), "url": urljoin(SOURCES["schedule"], href.group(1))})
        event = {
            "gameweek": len(events) + 1,
            "date": date_value.date().isoformat(),
            "time": time_value,
            "deadline": deadline,
            "opponent": opponent,
            "home": home,
            "location": known_venues.get(opponent, previous.get("location", "CMU Soccer Field · Pittsburgh, PA" if home else "Away venue · See official schedule")),
            "conference": conference_marker or previous.get("conference", False),
            "coverage": coverage or previous.get("coverage", [{"type": "livestats", "url": SOURCES["schedule"]}]),
        }
        if previous.get("ncaaGameId"):
            event["ncaaGameId"] = previous["ncaaGameId"]
            event["ncaaUrl"] = previous.get("ncaaUrl", f"https://www.ncaa.com/game/{previous['ncaaGameId']}")
        events.append(event)
    return events


def parse_boxscore(document, current_ids):
    players = {}
    opponent_goals = 0
    tables = re.findall(r"<table\b[\s\S]*?</table>", document, flags=re.I)

    for table in tables:
        caption_match = re.search(r"<caption\b[\s\S]*?</caption>", table, flags=re.I)
        caption = clean(caption_match.group()) if caption_match else ""
        is_goalkeeper_table = "Goalies" in caption
        is_cmu_table = caption.startswith("Carnegie Mellon")
        is_field_table = "PLAYER" in clean(re.search(r"<thead\b[\s\S]*?</thead>", table, flags=re.I).group()) if re.search(r"<thead\b[\s\S]*?</thead>", table, flags=re.I) else False

        if is_field_table and (is_cmu_table or (caption and caption not in {"Scoring Summary", "Penalty Summary"})):
            table_goal_total = 0
            for row_html, cells in rows(table):
                name_match = re.search(r'class="player-name"[^>]*>([\s\S]*?)</(?:a|span)>', row_html, flags=re.I)
                if not name_match or len(cells) < 5:
                    continue
                name = clean(name_match.group(1))
                goals = int(numeric(cells[3]))
                table_goal_total += goals
                if is_cmu_table and slugify(name) in current_ids:
                    players[slugify(name)] = {
                        "minutes": 0,
                        "goals": goals,
                        "assists": int(numeric(cells[4])),
                        "shots": int(numeric(cells[1])),
                        "shotsOnGoal": int(numeric(cells[2])),
                        "yellowCards": len(re.findall(r"penalty-card yellow", row_html, flags=re.I)),
                        "redCards": len(re.findall(r"penalty-card red", row_html, flags=re.I)),
                        "saves": 0,
                        "cleanSheet": False,
                    }
            if not is_cmu_table:
                opponent_goals = max(opponent_goals, table_goal_total)

        if is_cmu_table and is_goalkeeper_table:
            for row_html, cells in rows(table):
                name_match = re.search(r'class="player-name"[^>]*>([\s\S]*?)</(?:a|span)>', row_html, flags=re.I)
                if not name_match or len(cells) < 5:
                    continue
                player_id = slugify(clean(name_match.group(1)))
                if player_id not in current_ids:
                    continue
                players.setdefault(player_id, {"goals": 0, "assists": 0, "shots": 0, "shotsOnGoal": 0, "yellowCards": 0, "redCards": 0})
                players[player_id]["saves"] = int(numeric(cells[-2]))
                players[player_id]["minutes"] = round(clock_seconds(cells[-1]) / 60)

    lineup_match = re.search(r"FOR CMU:\s*,?\s*((?:#(?:\d+|00)[\s\S]*?))(?:</td>|$)", document, flags=re.I)
    starters = []
    if lineup_match:
        for match in re.finditer(r"#(?:\d+|00)\s+([^,#]+),\s*([^,#.]+?)(?=,\s*#|\.)", clean(lineup_match.group(1))):
            player_id = slugify(display_name(match.group(1), match.group(2)))
            if player_id in current_ids:
                starters.append(player_id)

    on_field = {player_id: 0 for player_id in starters}
    played_seconds = {player_id: 0 for player_id in players}
    match_end = 90 * 60
    play_rows = []
    for row_html, cells in rows(document):
        if len(cells) != 2 or not re.match(r"^\d+:\d{2}$", cells[0]):
            continue
        play_rows.append((clock_seconds(cells[0]), cells[1]))
        if "End of period" in cells[1]:
            match_end = max(match_end, clock_seconds(cells[0]))

    for elapsed, description in play_rows:
        substitution = re.search(r"CMU substitution:\s*([^,]+),\s*(.*?)\s+for\s+([^,]+),\s*(.*?)\.$", description, flags=re.I)
        if not substitution:
            continue
        incoming = slugify(display_name(substitution.group(1), substitution.group(2)))
        outgoing = slugify(display_name(substitution.group(3), substitution.group(4)))
        if outgoing in on_field:
            played_seconds[outgoing] = played_seconds.get(outgoing, 0) + max(0, elapsed - on_field.pop(outgoing))
        if incoming in current_ids and incoming not in on_field:
            on_field[incoming] = elapsed

    for player_id, entered_at in on_field.items():
        played_seconds[player_id] = played_seconds.get(player_id, 0) + max(0, match_end - entered_at)

    for player_id, stat in players.items():
        derived_minutes = round(played_seconds.get(player_id, 0) / 60)
        if derived_minutes or not stat.get("minutes"):
            stat["minutes"] = derived_minutes
        stat["started"] = player_id in starters
        stat["cleanSheet"] = opponent_goals == 0 and stat["minutes"] >= FULL_APPEARANCE_MINUTES
        stat.setdefault("ownGoals", 0)
        stat.setdefault("penaltiesMissed", 0)
        stat.setdefault("penaltiesSaved", 0)
        stat.setdefault("bonus", 0)
    return players


def merge_manual_stats(prior, stats):
    record = {
        **prior,
        **stats,
        "bonus": prior.get("bonus", stats.get("bonus", 0)),
        "ownGoals": prior.get("ownGoals", stats.get("ownGoals", 0)),
        "penaltiesMissed": prior.get("penaltiesMissed", stats.get("penaltiesMissed", 0)),
        "penaltiesSaved": prior.get("penaltiesSaved", stats.get("penaltiesSaved", 0)),
    }
    manual_overrides = prior.get("manualOverrides", stats.get("manualOverrides"))
    if isinstance(manual_overrides, dict):
        record.update(manual_overrides)
        record["manualOverrides"] = manual_overrides
    return record


def sync_gameweek_stats(schedule_document, current_players):
    gameweek_file = DATA / "gameweek-stats.json"
    existing = json.loads(gameweek_file.read_text(encoding="utf-8")) if gameweek_file.exists() else {}
    current_ids = {player["id"] for player in current_players}
    synced = dict(existing)
    completed = 0
    for index, url in enumerate(boxscore_links(schedule_document), start=1):
        if not url:
            continue
        try:
            parsed = parse_boxscore(fetch(url), current_ids)
        except RuntimeError:
            # Home live-stat URLs can point at an empty future box score.
            continue
        if not parsed:
            continue
        old_week = existing.get(str(index), {})
        synced[str(index)] = dict(old_week)
        for player_id, stats in parsed.items():
            synced[str(index)][player_id] = merge_manual_stats(old_week.get(player_id, {}), stats)
        completed += 1
    write_json("gameweek-stats.json", synced)
    return completed


def write_json(name, value):
    path = DATA / name
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    documents = {name: fetch(url) for name, url in SOURCES.items()}
    players = parse_roster(documents["roster"])
    stats = parse_field_stats(documents["field_stats"])
    goalkeeper_stats = parse_goalkeeper_stats(documents["goalkeeper_stats"])
    for player in stats:
        player.update(goalkeeper_stats.get(player["id"], {}))

    existing_schedule = json.loads((DATA / "gameweeks.json").read_text(encoding="utf-8"))
    schedule = parse_schedule(documents["schedule"], existing_schedule)

    if len(players) < 20:
        raise RuntimeError(f"Roster parser found only {len(players)} players; local data was not changed.")
    if len(stats) < 20:
        raise RuntimeError(f"Stats parser found only {len(stats)} players; local data was not changed.")
    if len(schedule) < 10:
        raise RuntimeError(f"Schedule parser found only {len(schedule)} gameweeks; local data was not changed.")

    write_json("players.json", players)
    write_json("stats-2025.json", stats)
    write_json("gameweeks.json", schedule)
    completed_gameweeks = sync_gameweek_stats(documents["schedule"], players)
    print(f"Synced {len(players)} current players, {len(stats)} prior-season stat lines, and {completed_gameweeks} completed 2026 gameweeks.")
    print("Manual schedule locations, fantasy overrides, and data/player-prices.csv were preserved.")
