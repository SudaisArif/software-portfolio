"""Static app server plus the small SQLite API used by Tartan Fantasy leagues."""

from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo
import csv
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DATA = ROOT / "data"
DATA = Path(os.environ.get("TARTAN_DATA_PATH", SOURCE_DATA))
PORT = int(os.environ.get("PORT", "4173"))
HOST = os.environ.get("TARTAN_HOST", "127.0.0.1")
DATABASE = Path(os.environ.get("TARTAN_DB_PATH", DATA / "tartan-fantasy.db"))
EASTERN = ZoneInfo("America/New_York")
BUDGET = 60.0
POSITION_LIMITS = {"DEF": 2, "MID": 2, "FWD": 2}
BENCH_SIZE = 3
FREE_TRANSFERS = 2
IMPACT_SUB_MULTIPLIER = 1.25
IMPACT_SUB_MINUTES = 20
FULL_APPEARANCE_MINUTES = 40
PRICE_REVIEW_GAMEWEEKS = 3
FRESHMAN_BLOCK_EV = 1.5
MIN_PLAYER_PRICE = 3.5
MAX_PLAYER_PRICE = 12.5
CHIPS = {"tripleCaptain", "benchBoost"}
ALLOW_LOCKED_WRITES = os.environ.get("TARTAN_ALLOW_LOCKED_WRITES") == "1"
LIVE_SYNC = os.environ.get("TARTAN_LIVE_SYNC") == "1"
MUTABLE_DATA_FILES = {"gameweek-stats.json", "gameweeks.json", "live-scores.json"}
PUBLIC_DATA_FILES = {path.name for path in SOURCE_DATA.iterdir() if path.suffix in {".json", ".csv"}}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def seed_runtime_data():
    """Seed a mounted production disk without replacing live match records."""
    if DATA.resolve() == SOURCE_DATA.resolve():
        return
    DATA.mkdir(parents=True, exist_ok=True)
    for source in SOURCE_DATA.iterdir():
        if source.suffix not in {".json", ".csv"}:
            continue
        destination = DATA / source.name
        if source.name in MUTABLE_DATA_FILES and destination.exists():
            continue
        shutil.copy2(source, destination)


def live_sync_loop():
    from sync_ncaa_data import sync

    while True:
        try:
            sync(only_current=True)
        except Exception as error:
            print(f"Live sync error: {error}")
        time.sleep(60)


def connect():
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS managers (
                id TEXT PRIMARY KEY,
                token TEXT NOT NULL UNIQUE,
                manager_name TEXT NOT NULL,
                team_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leagues (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                owner_manager_id TEXT NOT NULL REFERENCES managers(id),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS league_members (
                league_id TEXT NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
                manager_id TEXT NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (league_id, manager_id)
            );
            CREATE TABLE IF NOT EXISTS squads (
                manager_id TEXT NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
                gameweek INTEGER NOT NULL,
                players_json TEXT NOT NULL,
                bench_json TEXT NOT NULL DEFAULT '[]',
                captain TEXT NOT NULL,
                vice_captain TEXT NOT NULL,
                chip TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (manager_id, gameweek)
            );
            CREATE INDEX IF NOT EXISTS idx_league_members_manager ON league_members(manager_id);
            """
        )
        squad_columns = {row["name"] for row in connection.execute("PRAGMA table_info(squads)")}
        if "bench_json" not in squad_columns:
            connection.execute("ALTER TABLE squads ADD COLUMN bench_json TEXT NOT NULL DEFAULT '[]'")
        if "bank" not in squad_columns:
            connection.execute("ALTER TABLE squads ADD COLUMN bank REAL")
        if "chip" not in squad_columns:
            connection.execute("ALTER TABLE squads ADD COLUMN chip TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_squads_one_chip ON squads(manager_id, chip) WHERE chip IS NOT NULL"
        )
        connection.executescript((ROOT / "migrations" / "0004_optional_login.sql").read_text())


def now_iso():
    return datetime.now(EASTERN).isoformat(timespec="seconds")


def clean_text(value, label, minimum=2, maximum=40):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if not minimum <= len(value) <= maximum:
        raise ApiError(400, f"{label} must be {minimum}–{maximum} characters.")
    return value


def public_manager(row):
    return {
        "id": row["id"],
        "managerName": row["manager_name"],
        "teamName": row["team_name"],
        "loginEnabled": bool(row["login_enabled"]) if "login_enabled" in row.keys() else False,
    }


def public_squad(row):
    return {
        "players": json.loads(row["players_json"]),
        "bench": json.loads(row["bench_json"] or "[]"),
        "captain": row["captain"],
        "viceCaptain": row["vice_captain"],
        "chip": row["chip"] or None,
        "bank": row["bank"],
    }


def league_summary(row, manager_id):
    return {
        "code": row["code"],
        "name": row["name"],
        "isOwner": row["owner_manager_id"] == manager_id,
    }


def manager_from_token(token):
    if not token or len(token) > 128:
        raise ApiError(401, "Create your manager first.")
    with connect() as connection:
        row = connection.execute("""
            SELECT m.*, CASE WHEN l.manager_id IS NULL THEN 0 ELSE 1 END AS login_enabled
            FROM managers m LEFT JOIN manager_logins l ON l.manager_id = m.id WHERE m.token = ?
        """, (token,)).fetchone()
        if not row:
            row = connection.execute("""
                SELECT m.*, CASE WHEN l.manager_id IS NULL THEN 0 ELSE 1 END AS login_enabled
                FROM manager_sessions s JOIN managers m ON m.id = s.manager_id
                LEFT JOIN manager_logins l ON l.manager_id = m.id
                WHERE s.token_hash = ? AND s.expires_at > ?
            """, (secret_hash(token), int(time.time()))).fetchone()
    if not row:
        raise ApiError(401, "This manager session is no longer valid.")
    return row


def secret_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_login_code(manager, replace=False):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(32))
    with connect() as connection:
        if replace:
            result = connection.execute(
                "UPDATE manager_logins SET code_hash = ?, created_at = ? WHERE manager_id = ?",
                (secret_hash(code), now_iso(), manager["id"]),
            )
            if not result.rowcount:
                raise ApiError(409, "Enable optional sign-in for this team first.")
        else:
            result = connection.execute(
                "INSERT OR IGNORE INTO manager_logins (manager_id, code_hash, created_at) VALUES (?, ?, ?)",
                (manager["id"], secret_hash(code), now_iso()),
            )
            if not result.rowcount:
                raise ApiError(409, "Sign-in is already enabled. Use Replace login code if you need a new code.")
    return "TF-" + "-".join(code[index:index + 8] for index in range(0, 32, 8))


def login_with_code(value, client_ip):
    now = int(time.time())
    window = now // 900 * 900
    with connect() as connection:
        row = connection.execute("""
            INSERT INTO login_attempts (bucket, window_start, attempts) VALUES (?, ?, 1)
            ON CONFLICT(bucket) DO UPDATE SET
                attempts = CASE WHEN window_start = excluded.window_start THEN attempts + 1 ELSE 1 END,
                window_start = excluded.window_start
            RETURNING attempts
        """, (secret_hash("login:" + client_ip), window)).fetchone()
        connection.execute("DELETE FROM login_attempts WHERE window_start < ?", (window - 900,))
    if row["attempts"] > 100:
        raise ApiError(429, "Too many sign-in attempts. Try again in 15 minutes.")
    if not isinstance(value, str) or len(value) > 128:
        raise ApiError(401, "That login code is not valid.")
    code = re.sub(r"[\s-]", "", value.upper())
    if len(code) == 34 and code.startswith("TF"):
        code = code[2:]
    if not re.fullmatch(r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{32}", code):
        raise ApiError(401, "That login code is not valid.")
    with connect() as connection:
        manager = connection.execute("""
            SELECT m.*, 1 AS login_enabled FROM manager_logins l
            JOIN managers m ON m.id = l.manager_id WHERE l.code_hash = ?
        """, (secret_hash(code),)).fetchone()
        if not manager:
            raise ApiError(401, "That login code is not valid.")
        token = secrets.token_urlsafe(32)
        connection.execute("DELETE FROM manager_sessions WHERE expires_at <= ?", (now,))
        connection.execute(
            "INSERT INTO manager_sessions (token_hash, manager_id, expires_at) VALUES (?, ?, ?)",
            (secret_hash(token), manager["id"], now + 90 * 24 * 60 * 60),
        )
    return manager, token


def logout_session(manager, token):
    with connect() as connection:
        connection.execute("DELETE FROM manager_sessions WHERE token_hash = ? AND manager_id = ?", (secret_hash(token), manager["id"]))
        connection.execute("UPDATE managers SET token = ? WHERE id = ? AND token = ?", (secrets.token_urlsafe(32), manager["id"], token))


def manager_profile(manager):
    return {
        "manager": public_manager(manager),
        "leagues": manager_leagues(manager["id"]),
        "squads": manager_squads(manager["id"]),
    }


def manager_leagues(manager_id):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT l.* FROM leagues l
            JOIN league_members lm ON lm.league_id = l.id
            WHERE lm.manager_id = ?
            ORDER BY l.created_at, l.name
            """,
            (manager_id,),
        ).fetchall()
    return [league_summary(row, manager_id) for row in rows]


def manager_squads(manager_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM squads WHERE manager_id = ? ORDER BY gameweek",
            (manager_id,),
        ).fetchall()
    teams = restore_banks([
        {**public_squad(row), "gameweek": row["gameweek"]} for row in rows
    ], load_price_state())
    return {str(team["gameweek"]): {key: value for key, value in team.items() if key != "gameweek"} for team in teams}


def generate_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def load_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def load_base_prices():
    with (DATA / "player-prices.csv").open(newline="", encoding="utf-8") as source:
        return {row["player_id"]: float(row["price"]) for row in csv.DictReader(source)}


def load_pricing_report():
    with (DATA / "pricing-report.csv").open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def price_review_move(actual, expected):
    difference = actual - expected
    if difference >= 4:
        return 0.3
    if difference >= 2:
        return 0.2
    if difference >= 0.75:
        return 0.1
    if difference <= -4:
        return -0.3
    if difference <= -2:
        return -0.2
    if difference <= -0.75:
        return -0.1
    return 0.0


def calculate_price_reviews(player_list, base_prices, pricing_report, gameweek_stats, live_scores, gameweeks):
    prices = dict(base_prices)
    report_by_id = {row["player_id"]: row for row in pricing_report}
    reviews_by_id = {player["id"]: [] for player in player_list}
    events = sorted(gameweeks, key=lambda event: event["gameweek"])
    completed_blocks = []
    for start in range(0, len(events) - PRICE_REVIEW_GAMEWEEKS + 1, PRICE_REVIEW_GAMEWEEKS):
        block = events[start:start + PRICE_REVIEW_GAMEWEEKS]
        ready = all(
            live_scores.get(str(event["gameweek"]), {}).get("state") == "final"
            and str(event["gameweek"]) in gameweek_stats
            for event in block
        )
        if not ready:
            break
        completed_blocks.append(block)

    for block_index, block in enumerate(completed_blocks, start=1):
        for player in player_list:
            career_rating = float(report_by_id.get(player["id"], {}).get("career_rating") or 0)
            expected = max(FRESHMAN_BLOCK_EV, career_rating / 6)
            actual = 0
            for event in block:
                stats = gameweek_stats.get(str(event["gameweek"]), {}).get(player["id"], {})
                actual += impact_sub_points(raw_points(player["position"], stats), stats)
            previous_price = prices.get(player["id"], 5.0)
            next_price = min(MAX_PLAYER_PRICE, max(
                MIN_PLAYER_PRICE,
                round(previous_price + price_review_move(actual, expected), 1),
            ))
            prices[player["id"]] = next_price
            reviews_by_id[player["id"]].append({
                "block": block_index,
                "fromGameweek": block[0]["gameweek"],
                "throughGameweek": block[-1]["gameweek"],
                "actual": actual,
                "expected": round(expected, 1),
                "move": round(next_price - previous_price, 1),
                "price": next_price,
            })
    return {
        "prices": prices,
        "reviewsById": reviews_by_id,
        "reviewedThrough": completed_blocks[-1][-1]["gameweek"] if completed_blocks else 0,
    }


def load_price_state():
    return calculate_price_reviews(
        load_json("players.json"),
        load_base_prices(),
        load_pricing_report(),
        load_json("gameweek-stats.json"),
        load_json("live-scores.json"),
        load_json("gameweeks.json"),
    )


def load_prices():
    return load_price_state()["prices"]


def squad_value(team, prices):
    return round(sum(prices[player_id] for player_id in team["players"] + team["bench"]), 1)


def spending_limit_for(team, prices):
    return round(squad_value(team, prices) + team["bank"], 1) if team else BUDGET


def restore_banks(teams, price_state):
    # Legacy fallback: reviews after GW3 first apply to GW4. Old transaction
    # timestamps/prices were not retained, so reconstruction uses GW history.
    restored = []
    previous = None
    for team in sorted(teams, key=lambda team: team["gameweek"]):
        bank = team.get("bank")
        if bank is None:
            prices = {
                player_id: round(price - sum(
                    review["move"] for review in price_state["reviewsById"].get(player_id, [])
                    if review["throughGameweek"] >= team["gameweek"]
                ), 1)
                for player_id, price in price_state["prices"].items()
            }
            bank = max(0, round(spending_limit_for(previous, prices) - squad_value(team, prices), 1))
        previous = {**team, "bank": bank}
        restored.append(previous)
    return restored


def validate_squad(gameweek, payload):
    events = {event["gameweek"]: event for event in load_json("gameweeks.json")}
    event = events.get(gameweek)
    if not event:
        raise ApiError(404, "Unknown gameweek.")
    if not ALLOW_LOCKED_WRITES and datetime.now(EASTERN) >= datetime.fromisoformat(event["deadline"]):
        raise ApiError(409, "That gameweek is locked.")

    players = payload.get("players")
    bench = payload.get("bench")
    captain = payload.get("captain")
    vice_captain = payload.get("viceCaptain")
    chip = payload.get("chip") or None
    if not isinstance(players, list) or len(players) != 6 or len(set(players)) != 6:
        raise ApiError(400, "The starting lineup must contain six different players.")
    if not isinstance(bench, list) or len(bench) != BENCH_SIZE or len(set(bench)) != BENCH_SIZE:
        raise ApiError(400, "The bench must contain three different players.")
    squad_ids = players + bench
    if len(set(squad_ids)) != 6 + BENCH_SIZE:
        raise ApiError(400, "A player cannot be both a starter and a substitute.")
    player_pool = {player["id"]: player for player in load_json("players.json")}
    if any(player_id not in player_pool for player_id in squad_ids):
        raise ApiError(400, "The squad contains an unknown player.")
    counts = {position: 0 for position in POSITION_LIMITS}
    for player_id in players:
        player_position = player_pool[player_id]["position"]
        squad_position = "DEF" if player_position == "GK" else player_position
        counts[squad_position] += 1
    if counts != POSITION_LIMITS:
        raise ApiError(400, "Use the 2–2–2 formation; goalkeepers count as defenders.")
    if captain not in players or vice_captain not in players or captain == vice_captain:
        raise ApiError(400, "Captain and vice-captain must be different selected players.")
    if chip not in CHIPS | {None}:
        raise ApiError(400, "Unknown chip selection.")
    price_state = load_price_state()
    prices = price_state["prices"]
    squad_cost = squad_value({"players": players, "bench": bench}, prices)
    return players, bench, captain, vice_captain, chip, squad_cost, price_state


def raw_points(position, stats):
    minutes = int(float(stats.get("minutes") or 0))
    points = 2 if minutes >= FULL_APPEARANCE_MINUTES else 1 if minutes > 0 else 0
    points += int(stats.get("goals") or 0) * {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}.get(position, 4)
    points += int(stats.get("assists") or 0) * 3
    if earned_clean_sheet(stats, minutes):
        points += {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}.get(position, 0)
    if position == "GK":
        points += int(stats.get("saves") or 0) // 3
        points += int(stats.get("penaltiesSaved") or 0) * 5
    points -= int(stats.get("yellowCards") or 0)
    points -= int(stats.get("redCards") or 0) * 3
    points -= int(stats.get("ownGoals") or 0) * 2
    points -= int(stats.get("penaltiesMissed") or 0) * 2
    points += int(stats.get("bonus") or 0)
    return points


def earned_clean_sheet(stats, minutes=None):
    minutes = int(float(stats.get("minutes") or 0)) if minutes is None else minutes
    shutout = stats.get("cleanSheet") is True or stats.get("opponentScore") in {0, "0"}
    return shutout and minutes >= FULL_APPEARANCE_MINUTES


def impact_sub_points(points, stats):
    minutes = int(float(stats.get("minutes") or 0))
    if stats.get("started") is False and minutes >= IMPACT_SUB_MINUTES and points > 0:
        return math.ceil(points * IMPACT_SUB_MULTIPLIER)
    return points


def squad_points(squad, gameweek, positions, gameweek_stats):
    records = gameweek_stats.get(str(gameweek), {})
    captain_stats = records.get(squad["captain"], {})
    effective_captain = squad["captain"] if int(float(captain_stats.get("minutes") or 0)) > 0 else squad["vice_captain"]
    chip = squad["chip"] if squad["gameweek"] == gameweek else None
    starters = json.loads(squad["players_json"])
    bench = json.loads(squad["bench_json"] or "[]")
    scoring_players = starters + (bench if chip == "benchBoost" else [])
    captain_multiplier = 3 if chip == "tripleCaptain" else 2
    total = 0
    for player_id in scoring_players:
        player_stats = records.get(player_id, {})
        points = raw_points(positions[player_id], player_stats)
        if player_id in starters:
            points = impact_sub_points(points, player_stats)
        total += points * (captain_multiplier if player_id == effective_captain else 1)
    return total


def squad_player_ids(squad):
    return set(json.loads(squad["players_json"])) | set(json.loads(squad["bench_json"] or "[]"))


def transfer_count(current_squad, previous_squad):
    return len(squad_player_ids(previous_squad) - squad_player_ids(current_squad))


def current_gameweek():
    events = load_json("gameweeks.json")
    live = load_json("live-scores.json")
    for event in events:
        if live.get(str(event["gameweek"]), {}).get("state") == "live":
            return event["gameweek"]
    today = datetime.now(EASTERN).date().isoformat()
    for event in events:
        if event["date"] == today:
            return event["gameweek"]
    for event in events:
        if datetime.fromisoformat(event["deadline"]) > datetime.now(EASTERN):
            return event["gameweek"]
    return events[-1]["gameweek"]


def league_standings(code, manager_id):
    with connect() as connection:
        league = connection.execute("SELECT * FROM leagues WHERE code = ?", (code,)).fetchone()
        if not league:
            raise ApiError(404, "League code not found.")
        membership = connection.execute(
            "SELECT 1 FROM league_members WHERE league_id = ? AND manager_id = ?",
            (league["id"], manager_id),
        ).fetchone()
        if not membership:
            raise ApiError(403, "Join this league before viewing it.")
        members = connection.execute(
            """
            SELECT m.* FROM managers m
            JOIN league_members lm ON lm.manager_id = m.id
            WHERE lm.league_id = ?
            """,
            (league["id"],),
        ).fetchall()
        squads = connection.execute(
            "SELECT * FROM squads WHERE manager_id IN (SELECT manager_id FROM league_members WHERE league_id = ?)",
            (league["id"],),
        ).fetchall()

    positions = {player["id"]: player["position"] for player in load_json("players.json")}
    stats = load_json("gameweek-stats.json")
    live_scores = load_json("live-scores.json")
    gameweek_events = load_json("gameweeks.json")
    prices = load_prices()
    gameweeks = sorted(event["gameweek"] for event in gameweek_events)
    active_gameweek = current_gameweek()
    active_event = next(event for event in gameweek_events if event["gameweek"] == active_gameweek)
    other_squads_visible = datetime.now(EASTERN) >= datetime.fromisoformat(active_event["deadline"])
    squads_by_manager = {}
    for squad in squads:
        squads_by_manager.setdefault(squad["manager_id"], {})[squad["gameweek"]] = squad

    entries = []
    for member in members:
        member_squads = squads_by_manager.get(member["id"], {})
        weekly = {}
        transfers = {}
        active_squad = None
        previous_squad = None
        squad_history = {}
        for gameweek in gameweeks:
            active_squad = member_squads.get(gameweek, active_squad)
            event = next(candidate for candidate in gameweek_events if candidate["gameweek"] == gameweek)
            can_view_gameweek = member["id"] == manager_id or datetime.now(EASTERN) >= datetime.fromisoformat(event["deadline"])
            if active_squad and can_view_gameweek:
                squad_history[str(gameweek)] = {
                    "players": json.loads(active_squad["players_json"]),
                    "bench": json.loads(active_squad["bench_json"] or "[]"),
                    "captain": active_squad["captain"],
                    "viceCaptain": active_squad["vice_captain"],
                    "chip": active_squad["chip"] if active_squad["gameweek"] == gameweek else None,
                }
            scored = str(gameweek) in stats or live_scores.get(str(gameweek), {}).get("state") in {"live", "final"}
            if active_squad and scored:
                made = transfer_count(active_squad, previous_squad) if gameweek > 1 and previous_squad else 0
                transfers[gameweek] = made
                weekly[gameweek] = squad_points(active_squad, gameweek, positions, stats)
            if active_squad:
                previous_squad = active_squad
        can_view_squad = member["id"] == manager_id or other_squads_visible
        latest_visible_gameweek = max(map(int, squad_history), default=None)
        latest_visible_squad = squad_history.get(str(latest_visible_gameweek)) if latest_visible_gameweek else None
        squad_value = round(sum(
            prices[player_id]
            for player_id in (latest_visible_squad["players"] + latest_visible_squad["bench"])
        ), 1) if latest_visible_squad else None
        entries.append({
            "managerId": member["id"],
            "managerName": member["manager_name"],
            "teamName": member["team_name"],
            "totalPoints": sum(weekly.values()),
            "gameweekPoints": weekly.get(active_gameweek, 0),
            "transfersMade": transfers.get(active_gameweek, 0),
            "squadValue": squad_value,
            "canViewSquad": can_view_squad,
            "squad": squad_history.get(str(active_gameweek)),
            "squads": squad_history,
            "weeklyPoints": weekly,
            "transfersByGameweek": transfers,
        })
    entries.sort(key=lambda entry: (-entry["totalPoints"], entry["teamName"].lower(), entry["managerName"].lower()))
    previous_points = None
    previous_rank = 0
    for index, entry in enumerate(entries, start=1):
        if entry["totalPoints"] != previous_points:
            previous_rank = index
        entry["rank"] = previous_rank
        previous_points = entry["totalPoints"]
    return {
        "league": league_summary(league, manager_id),
        "memberCount": len(entries),
        "currentGameweek": active_gameweek,
        "freeTransfers": FREE_TRANSFERS,
        "standings": entries,
    }


class AppHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
    }

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def translate_path(self, path):
        requested = unquote(urlparse(path).path)
        if requested.startswith("/data/"):
            name = requested.removeprefix("/data/")
            if name in PUBLIC_DATA_FILES:
                return str(DATA / name)
        return super().translate_path(path)

    def json_response(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def request_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiError(400, "Invalid request length.") from error
        if length > 100_000:
            raise ApiError(413, "Request is too large.")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ApiError(400, "Request body must be a JSON object.")
            return payload
        except json.JSONDecodeError as error:
            raise ApiError(400, "Request body must be valid JSON.") from error

    def token(self):
        value = self.headers.get("Authorization", "")
        return value[7:].strip() if value.startswith("Bearer ") else ""

    def api(self, callback):
        try:
            callback()
        except ApiError as error:
            self.json_response(error.status, {"error": error.message})
        except Exception as error:
            print(f"API error: {error}")
            self.json_response(500, {"error": "The league server hit an unexpected error."})

    def do_GET(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            if re.search(r"\.db(?:$|-)", unquote(path), flags=re.I):
                return self.send_error(404)
            return super().do_GET()
        self.api(lambda: self.handle_api_get(path))

    def do_HEAD(self):
        path = urlparse(self.path).path
        if re.search(r"\.db(?:$|-)", unquote(path), flags=re.I):
            return self.send_error(404)
        return super().do_HEAD()

    def handle_api_get(self, path):
        if path == "/api/health":
            return self.json_response(200, {"ok": True})
        manager = manager_from_token(self.token())
        if path == "/api/me":
            return self.json_response(200, manager_profile(manager))

        match = re.fullmatch(r"/api/leagues/([A-Za-z0-9]+)", path)
        if match:
            return self.json_response(200, league_standings(match.group(1).upper(), manager["id"]))
        raise ApiError(404, "API route not found.")

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self.send_error(405)
        self.api(lambda: self.handle_api_post(path))

    def handle_api_post(self, path):
        payload = self.request_json()
        if path == "/api/auth/login":
            manager, token = login_with_code(payload.get("code"), self.client_address[0])
            return self.json_response(200, {**manager_profile(manager), "token": token})
        if path == "/api/managers":
            manager_name = clean_text(payload.get("managerName"), "Your name")
            team_name = clean_text(payload.get("teamName"), "Team name")
            manager_id = str(uuid.uuid4())
            token = secrets.token_urlsafe(32)
            with connect() as connection:
                connection.execute(
                    "INSERT INTO managers VALUES (?, ?, ?, ?, ?)",
                    (manager_id, token, manager_name, team_name, now_iso()),
                )
            return self.json_response(201, {
                "manager": {"id": manager_id, "managerName": manager_name, "teamName": team_name},
                "token": token,
            })

        manager = manager_from_token(self.token())
        if path in {"/api/auth/enable", "/api/auth/rotate"}:
            code = create_login_code(manager, path == "/api/auth/rotate")
            return self.json_response(200, {"code": code, "manager": {**public_manager(manager), "loginEnabled": True}})
        if path == "/api/auth/logout":
            logout_session(manager, self.token())
            return self.json_response(200, {"ok": True})
        if path == "/api/leagues":
            name = clean_text(payload.get("name"), "League name")
            league_id = str(uuid.uuid4())
            with connect() as connection:
                for _ in range(20):
                    code = generate_code()
                    try:
                        connection.execute(
                            "INSERT INTO leagues VALUES (?, ?, ?, ?, ?)",
                            (league_id, code, name, manager["id"], now_iso()),
                        )
                        break
                    except sqlite3.IntegrityError:
                        continue
                else:
                    raise ApiError(500, "Could not generate a league code.")
                connection.execute(
                    "INSERT INTO league_members VALUES (?, ?, ?)",
                    (league_id, manager["id"], now_iso()),
                )
                league = connection.execute("SELECT * FROM leagues WHERE id = ?", (league_id,)).fetchone()
            return self.json_response(201, {"league": league_summary(league, manager["id"])})

        if path == "/api/leagues/join":
            code = re.sub(r"[^A-Z0-9]", "", str(payload.get("code") or "").upper())
            if len(code) != 6:
                raise ApiError(400, "Enter the six-character league code.")
            with connect() as connection:
                league = connection.execute("SELECT * FROM leagues WHERE code = ?", (code,)).fetchone()
                if not league:
                    raise ApiError(404, "League code not found.")
                connection.execute(
                    "INSERT OR IGNORE INTO league_members VALUES (?, ?, ?)",
                    (league["id"], manager["id"], now_iso()),
                )
            return self.json_response(200, {"league": league_summary(league, manager["id"])})
        raise ApiError(404, "API route not found.")

    def do_PUT(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self.send_error(405)
        self.api(lambda: self.handle_api_put(path))

    def handle_api_put(self, path):
        manager = manager_from_token(self.token())
        payload = self.request_json()
        if path == "/api/me":
            manager_name = clean_text(payload.get("managerName", manager["manager_name"]), "Your name")
            team_name = clean_text(payload.get("teamName", manager["team_name"]), "Team name")
            with connect() as connection:
                connection.execute(
                    "UPDATE managers SET manager_name = ?, team_name = ? WHERE id = ?",
                    (manager_name, team_name, manager["id"]),
                )
                updated = connection.execute("SELECT * FROM managers WHERE id = ?", (manager["id"],)).fetchone()
            return self.json_response(200, {"manager": public_manager(updated)})

        match = re.fullmatch(r"/api/squads/(\d+)", path)
        if match:
            gameweek = int(match.group(1))
            players, bench, captain, vice_captain, chip, squad_cost, price_state = validate_squad(gameweek, payload)
            prices = price_state["prices"]
            with connect() as connection:
                if chip:
                    used = connection.execute(
                        "SELECT gameweek FROM squads WHERE manager_id = ? AND chip = ? AND gameweek != ?",
                        (manager["id"], chip, gameweek),
                    ).fetchone()
                    if used:
                        raise ApiError(409, f"That chip was already used in Gameweek {used['gameweek']}.")
                previous_squad = connection.execute(
                    """
                    SELECT * FROM squads
                    WHERE manager_id = ? AND gameweek < ?
                    ORDER BY gameweek DESC LIMIT 1
                    """,
                    (manager["id"], gameweek),
                ).fetchone()
                existing_squad = connection.execute(
                    "SELECT * FROM squads WHERE manager_id = ? AND gameweek = ?",
                    (manager["id"], gameweek),
                ).fetchone()
                next_squad = connection.execute(
                    """
                    SELECT * FROM squads
                    WHERE manager_id = ? AND gameweek > ?
                    ORDER BY gameweek LIMIT 1
                    """,
                    (manager["id"], gameweek),
                ).fetchone()
                candidate = {
                    "players_json": json.dumps(players),
                    "bench_json": json.dumps(bench),
                }
                history = connection.execute(
                    "SELECT * FROM squads WHERE manager_id = ? AND gameweek <= ? ORDER BY gameweek",
                    (manager["id"], gameweek),
                ).fetchall()
                teams = restore_banks([
                    {**public_squad(row), "gameweek": row["gameweek"]} for row in history
                ], price_state)
                spending_limit = spending_limit_for(teams[-1] if teams else None, prices)
                if squad_cost > spending_limit + 1e-9:
                    raise ApiError(400, f"The squad is over this gameweek's ${spending_limit:.1f}m budget.")
                bank = round(spending_limit - squad_cost, 1)
                keeps_grandfathered_squad = (
                    previous_squad
                    and existing_squad
                    and transfer_count(existing_squad, previous_squad) > FREE_TRANSFERS
                    and transfer_count(candidate, existing_squad) == 0
                )
                if (
                    previous_squad
                    and transfer_count(candidate, previous_squad) > FREE_TRANSFERS
                    and not keeps_grandfathered_squad
                ):
                    raise ApiError(400, f"You can make at most {FREE_TRANSFERS} transfers per gameweek.")
                if next_squad and transfer_count(next_squad, candidate) > FREE_TRANSFERS:
                    raise ApiError(
                        400,
                        f"This change would leave Gameweek {next_squad['gameweek']} over its {FREE_TRANSFERS}-transfer limit.",
                    )
                if next_squad and (not existing_squad or transfer_count(candidate, existing_squad) != 0):
                    raise ApiError(409, "Make transfers in your latest saved gameweek so later squads keep the correct bank.")
                connection.execute(
                    """
                    INSERT INTO squads (
                        manager_id, gameweek, players_json, bench_json,
                        captain, vice_captain, chip, updated_at, bank
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(manager_id, gameweek) DO UPDATE SET
                        players_json = excluded.players_json,
                        bench_json = excluded.bench_json,
                        captain = excluded.captain,
                        vice_captain = excluded.vice_captain,
                        chip = excluded.chip,
                        updated_at = excluded.updated_at,
                        bank = excluded.bank
                    """,
                    (
                        manager["id"], gameweek, json.dumps(players), json.dumps(bench),
                        captain, vice_captain, chip, now_iso(), bank,
                    ),
                )
            return self.json_response(200, {"ok": True, "gameweek": gameweek, "bank": bank})
        raise ApiError(404, "API route not found.")


def run_server():
    os.chdir(ROOT)
    seed_runtime_data()
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    if LIVE_SYNC:
        threading.Thread(target=live_sync_loop, name="ncaa-live-sync", daemon=True).start()
    print(f"Tartan Fantasy is running at http://{HOST}:{server.server_port}")
    print(f"League data: {DATABASE}")
    print(f"Public data: {DATA}")
    if LIVE_SYNC:
        print("NCAA live-score sync is enabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped Tartan Fantasy.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
