"""Exercise the complete two-manager league flow against a temporary HTTP server."""

from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import os
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_server as app_server

ROOT = Path(__file__).resolve().parent.parent
LINEUP = [
    "nicholas-macouzet",
    "miguel-larrainzar",
    "ian-kim",
    "rishi-kunderan",
    "idan-garten",
    "alex-popov",
]
BENCH = ["james-ashby", "thomas-thornton", "max-born"]
TWO_TRANSFER_LINEUP = [
    "nicholas-macouzet",
    "kieran-raker",
    "ian-kim",
    "spencer-madge",
    "idan-garten",
    "alex-popov",
]
TWO_TRANSFER_BENCH = BENCH
THREE_TRANSFER_BENCH = ["knox-foster", "thomas-thornton", "max-born"]
ALT_TWO_TRANSFER_LINEUP = [
    "nicholas-macouzet", "miguel-larrainzar", "ian-kim",
    "rishi-kunderan", "nicholas-kourakis", "alex-popov",
]
ALT_TWO_TRANSFER_BENCH = ["knox-foster", "thomas-thornton", "max-born"]
LEGACY_FIVE_TRANSFER_LINEUP = [
    "nolan-hughes", "robbie-gresham", "tristan-gonzalez",
    "spencer-madge", "nicholas-kourakis", "alex-popov",
]
LEGACY_FIVE_TRANSFER_BENCH = ["knox-foster", "thomas-thornton", "max-born"]
OVER_BUDGET_LINEUP = [
    "kai-yamamoto", "mateas-fitzwilliam",
    "tristan-gonzalez", "dominic-hoar-weiler", "idan-garten", "justin-fung",
]
OVER_BUDGET_BENCH = ["nathan-yao", "sola-nishimura", "james-ashby"]
BUDGET_PROOF_LINEUP = [
    "buck-magee", "henry-hawthorn", "tristan-gonzalez",
    "ian-kim", "alex-popov", "thomas-thornton",
]
BUDGET_PROOF_BENCH = ["nicholas-macouzet", "miguel-larrainzar", "max-born"]


class QuietHandler(app_server.AppHandler):
    def log_message(self, *_args):
        pass


def request(base, path, method="GET", token=None, body=None, expected=200):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(f"{base}{path}", data=payload, headers=headers, method=method), timeout=5) as response:
            status = response.status
            result = json.loads(response.read())
    except HTTPError as error:
        status = error.code
        result = json.loads(error.read())
    assert status == expected, (path, status, result)
    return result


def check_bank_api(base):
    original_price_state = app_server.load_price_state
    ids = LINEUP + BENCH
    prices = {player["id"]: 6.5 for player in app_server.load_json("players.json")}
    state = {"prices": prices, "reviewsById": {}, "reviewedThrough": 0}
    app_server.load_price_state = lambda: state
    manager = None
    try:
        manager = request(base, "/api/managers", "POST", body={
            "managerName": "Bank Test", "teamName": "Cash Preserved"
        }, expected=201)
        token = manager["token"]
        squad = {"players": LINEUP, "bench": BENCH, "captain": "idan-garten", "viceCaptain": "ian-kim", "bank": 999}
        assert request(base, "/api/squads/1", "PUT", token, squad)["bank"] == 1.5
        for i, player_id in enumerate(ids):
            move = 0.1 if i == 8 else 0.3
            prices[player_id] = round(6.5 + move, 1)
            state["reviewsById"][player_id] = [{"throughGameweek": 3, "move": move}]
        assert app_server.squad_value(squad, prices) == 61
        # Simulate a pre-migration squad and verify that GET recovers its cash.
        with app_server.connect() as connection:
            connection.execute("UPDATE squads SET bank = NULL WHERE manager_id = ?", (manager["manager"]["id"],))
        assert request(base, "/api/me", token=token)["squads"]["1"]["bank"] == 1.5
        assert request(base, "/api/squads/4", "PUT", token, squad)["bank"] == 1.5
        prices["kieran-raker"] = 7.8
        changed = {**squad, "players": [LINEUP[0], "kieran-raker", *LINEUP[2:]]}
        assert request(base, "/api/squads/4", "PUT", token, changed)["bank"] == 0.5
        prices["miguel-larrainzar"] = 12.5  # No longer owned: cannot fund transfers.
        prices["kieran-raker"] = 7.3
        for _ in range(3):
            assert request(base, "/api/squads/4", "PUT", token, changed)["bank"] == 0.5
        # Reject overspending even if the client forges its bank.
        prices["knox-foster"] = round(prices[BENCH[0]] + 0.6, 1)
        request(base, "/api/squads/4", "PUT", token, {**changed, "bench": ["knox-foster", *BENCH[1:]]}, expected=400)
        assert request(base, "/api/me", token=token)["squads"]["4"]["bank"] == 0.5
        # A cheaper transfer increases cash, without a fresh 60m allowance.
        prices["knox-foster"] = round(prices[BENCH[0]] - 1, 1)
        cheaper = {**changed, "bench": ["knox-foster", *BENCH[1:]]}
        assert request(base, "/api/squads/4", "PUT", token, cheaper)["bank"] == 1.5
        for player_id in cheaper["players"] + cheaper["bench"]:
            prices[player_id] = 5
        assert request(base, "/api/squads/7", "PUT", token, cheaper)["bank"] == 1.5
        assert request(base, "/api/me", token=token)["squads"]["7"]["bank"] == 1.5
        # Earlier transfers would invalidate saved later cash; role edits are safe.
        prices[BENCH[0]] = 5
        request(base, "/api/squads/4", "PUT", token, changed, expected=409)
        assert request(base, "/api/squads/4", "PUT", token, {**cheaper, "captain": "ian-kim", "viceCaptain": "idan-garten"})["bank"] == 1.5
    finally:
        app_server.load_price_state = original_price_state
        if manager:
            with app_server.connect() as connection:
                connection.execute("DELETE FROM squads WHERE manager_id = ?", (manager["manager"]["id"],))
                connection.execute("DELETE FROM managers WHERE id = ?", (manager["manager"]["id"],))


def check_optional_login_api(base):
    manager = request(base, "/api/managers", "POST", body={"managerName": "Login Test", "teamName": "Same Team"}, expected=201)
    token = manager["token"]
    manager_id = manager["manager"]["id"]
    try:
        squad = {"players": LINEUP, "bench": BENCH, "captain": "idan-garten", "viceCaptain": "ian-kim"}
        request(base, "/api/squads/1", "PUT", token, squad)
        request(base, "/api/leagues", "POST", token, {"name": "Login Test League"}, expected=201)
        before = request(base, "/api/me", token=token)
        assert before["manager"]["loginEnabled"] is False
        request(base, "/api/auth/enable", "POST", body={}, expected=401)
        request(base, "/api/auth/rotate", "POST", token, {}, expected=409)
        enabled = request(base, "/api/auth/enable", "POST", token, {})
        assert enabled["manager"]["loginEnabled"] is True
        request(base, "/api/auth/enable", "POST", token, {}, expected=409)
        for code in ["wrong", "TF-" + "A" * 32, None, "x" * 129, {}]:
            request(base, "/api/auth/login", "POST", body={"code": code}, expected=401)
        phone = request(base, "/api/auth/login", "POST", body={"code": enabled["code"].lower()})
        laptop = request(base, "/api/auth/login", "POST", body={"code": enabled["code"].replace("-", " ")})
        assert phone["manager"]["id"] == manager_id
        assert len({token, phone["token"], laptop["token"]}) == 3
        assert phone["squads"] == before["squads"]
        assert phone["leagues"] == before["leagues"]
        with app_server.connect() as connection:
            row = connection.execute("SELECT code_hash FROM manager_logins WHERE manager_id = ?", (manager_id,)).fetchone()
            assert row["code_hash"] == app_server.secret_hash(enabled["code"].replace("-", "")[2:])
        request(base, "/api/me", "PUT", phone["token"], {"teamName": "Synced Team"})
        assert request(base, "/api/me", token=laptop["token"])["manager"]["teamName"] == "Synced Team"
        replacement = request(base, "/api/auth/rotate", "POST", laptop["token"], {})
        request(base, "/api/auth/login", "POST", body={"code": enabled["code"]}, expected=401)
        request(base, "/api/auth/login", "POST", body={"code": replacement["code"]})
        request(base, "/api/auth/logout", "POST", phone["token"], {})
        request(base, "/api/me", token=phone["token"], expected=401)
        request(base, "/api/auth/logout", "POST", token, {})
        request(base, "/api/me", token=token, expected=401)
        assert request(base, "/api/me", token=laptop["token"])["squads"] == before["squads"]
        with app_server.connect() as connection:
            connection.execute("UPDATE manager_sessions SET expires_at = 0 WHERE token_hash = ?", (app_server.secret_hash(laptop["token"]),))
            connection.execute("UPDATE login_attempts SET attempts = 100")
        request(base, "/api/me", token=laptop["token"], expected=401)
        request(base, "/api/auth/login", "POST", body={"code": replacement["code"]}, expected=429)
        with app_server.connect() as connection:
            connection.execute("UPDATE login_attempts SET window_start = 0")
        request(base, "/api/auth/login", "POST", body={"code": replacement["code"]})
    finally:
        with app_server.connect() as connection:
            connection.execute("DELETE FROM squads WHERE manager_id = ?", (manager_id,))
            connection.execute("DELETE FROM leagues WHERE owner_manager_id = ?", (manager_id,))
            connection.execute("DELETE FROM managers WHERE id = ?", (manager_id,))


def main():
    os.chdir(ROOT)
    assert app_server.impact_sub_points(1, {"minutes": 20, "started": False}) == 2
    assert app_server.impact_sub_points(1, {"minutes": 19, "started": False}) == 1
    assert app_server.impact_sub_points(1, {"minutes": 30, "started": True}) == 1
    assert app_server.raw_points("DEF", {"minutes": 39, "cleanSheet": True}) == 1
    assert app_server.raw_points("DEF", {"minutes": 40, "cleanSheet": True}) == 6
    assert app_server.raw_points("MID", {"minutes": 56, "cleanSheet": False, "opponentScore": 0}) == 3
    assert app_server.raw_points("GK", {"minutes": 90, "penaltiesSaved": 1}) == 7
    review = app_server.calculate_price_reviews(
        [{"id": "freshman", "position": "FWD"}, {"id": "returner", "position": "MID"}],
        {"freshman": 4.0, "returner": 12.4},
        [{"player_id": "freshman", "career_rating": "0"}, {"player_id": "returner", "career_rating": "60"}],
        {"1": {"freshman": {"minutes": 10, "goals": 1}}, "2": {}, "3": {}},
        {"1": {"state": "final"}, "2": {"state": "final"}, "3": {"state": "final"}},
        [{"gameweek": 1}, {"gameweek": 2}, {"gameweek": 3}],
    )
    assert review["reviewedThrough"] == 3
    assert review["prices"] == {"freshman": 4.2, "returner": 12.1}
    assert review["reviewsById"]["freshman"][0]["expected"] == 1.5
    real_load_json = app_server.load_json

    def test_load_json(name):
        if name == "gameweeks.json":
            return [
                {
                    **event,
                    "date": "2000-09-01" if event["gameweek"] == 1 else f"2099-09-{min(event['gameweek'], 28):02d}",
                    "deadline": "2000-09-01T12:00:00-04:00" if event["gameweek"] == 1 else f"2099-09-{min(event['gameweek'], 28):02d}T12:00:00-04:00",
                }
                for event in real_load_json(name)
            ]
        if name == "gameweek-stats.json":
            return {
                "1": {
                    "idan-garten": {"minutes": 90, "goals": 1},
                    "ian-kim": {"minutes": 90, "started": True, "assists": 1},
                    "james-ashby": {"minutes": 90, "goals": 1},
                    "alex-popov": {"minutes": 30, "started": False},
                    "thomas-thornton": {"minutes": 30, "started": False},
                },
                "2": {
                    "idan-garten": {"minutes": 90, "goals": 1},
                    "ian-kim": {"minutes": 90, "started": True, "assists": 1},
                }
            }
        if name == "live-scores.json":
            return {"1": {"state": "final"}, "2": {"state": "live"}}
        return real_load_json(name)

    temporary_db = None
    with TemporaryDirectory() as temporary:
        app_server.DATA = Path(temporary) / "runtime-data"
        app_server.seed_runtime_data()
        assert (app_server.DATA / "players.json").exists()
        (app_server.DATA / "live-scores.json").write_text('{"sentinel": true}\n', encoding="utf-8")
        app_server.seed_runtime_data()
        assert json.loads((app_server.DATA / "live-scores.json").read_text())["sentinel"] is True
        temporary_db = Path(temporary) / "league-test.db"
        app_server.DATABASE = temporary_db
        app_server.ALLOW_LOCKED_WRITES = True
        app_server.load_json = test_load_json
        with sqlite3.connect(app_server.DATABASE) as legacy:
            legacy.execute(
                """
                CREATE TABLE squads (
                    manager_id TEXT NOT NULL,
                    gameweek INTEGER NOT NULL,
                    players_json TEXT NOT NULL,
                    captain TEXT NOT NULL,
                    vice_captain TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (manager_id, gameweek)
                )
                """
            )
        app_server.init_db()
        with app_server.connect() as migrated:
            columns = {row["name"] for row in migrated.execute("PRAGMA table_info(squads)")}
            assert {"bench_json", "chip", "bank"} <= columns
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            assert request(base, "/api/health") == {"ok": True}
            check_bank_api(base)
            check_optional_login_api(base)
            with urlopen(f"{base}/data/player-prices.csv", timeout=5) as response:
                assert response.status == 200
                assert response.read().startswith(b"player_id,player_name,price")
            first = request(base, "/api/managers", "POST", body={"managerName": "Alex", "teamName": "Tartan Army"}, expected=201)
            second = request(base, "/api/managers", "POST", body={"managerName": "Jordan", "teamName": "Plaid Press"}, expected=201)
            budget_manager = request(base, "/api/managers", "POST", body={"managerName": "Casey", "teamName": "Budget Proof"}, expected=201)
            league = request(base, "/api/leagues", "POST", first["token"], {"name": "CMU Soccer"}, 201)["league"]
            assert len(league["code"]) == 6 and league["isOwner"]
            request(base, "/api/leagues/join", "POST", second["token"], {"code": league["code"]})
            request(base, "/api/leagues/join", "POST", second["token"], {"code": league["code"]})
            request(base, "/api/leagues/join", "POST", second["token"], {"code": "BAD999"}, expected=404)
            request(base, "/api/squads/1", "PUT", first["token"], {
                "players": LINEUP, "bench": BENCH, "captain": "idan-garten",
                "viceCaptain": "ian-kim", "chip": "tripleCaptain"
            })
            request(base, "/api/squads/1", "PUT", second["token"], {
                "players": LINEUP, "bench": BENCH, "captain": "idan-garten",
                "viceCaptain": "ian-kim", "chip": "benchBoost"
            })
            # Saving the same gameweek again updates the team instead of adding
            # a duplicate record.
            request(base, "/api/squads/1", "PUT", second["token"], {
                "players": LINEUP, "bench": BENCH, "captain": "ian-kim",
                "viceCaptain": "idan-garten", "chip": "benchBoost"
            })
            request(base, "/api/squads/2", "PUT", second["token"], {
                "players": TWO_TRANSFER_LINEUP, "bench": TWO_TRANSFER_BENCH, "captain": "ian-kim",
                "viceCaptain": "idan-garten", "chip": None
            })
            request(base, "/api/squads/2", "PUT", second["token"], {
                "players": TWO_TRANSFER_LINEUP, "bench": THREE_TRANSFER_BENCH, "captain": "ian-kim",
                "viceCaptain": "idan-garten", "chip": None
            }, expected=400)
            request(base, "/api/squads/2", "PUT", first["token"], {
                "players": LINEUP, "bench": BENCH, "captain": "idan-garten",
                "viceCaptain": "ian-kim", "chip": "tripleCaptain"
            }, expected=409)
            request(base, "/api/squads/2", "PUT", first["token"], {
                "players": LINEUP, "bench": BENCH, "captain": "idan-garten",
                "viceCaptain": "ian-kim", "chip": None
            })
            request(base, "/api/squads/3", "PUT", first["token"], {
                "players": TWO_TRANSFER_LINEUP, "bench": THREE_TRANSFER_BENCH,
                "captain": "ian-kim", "viceCaptain": "idan-garten", "chip": None
            }, expected=400)
            request(base, "/api/squads/3", "PUT", first["token"], {
                "players": TWO_TRANSFER_LINEUP, "bench": TWO_TRANSFER_BENCH,
                "captain": "ian-kim", "viceCaptain": "idan-garten", "chip": None
            })
            # Editing an earlier gameweek cannot make an already-saved later
            # squad exceed its own two-transfer allowance.
            request(base, "/api/squads/2", "PUT", first["token"], {
                "players": ALT_TWO_TRANSFER_LINEUP, "bench": ALT_TWO_TRANSFER_BENCH,
                "captain": "ian-kim", "viceCaptain": "alex-popov", "chip": None
            }, expected=400)
            # A squad genuinely saved before this rule change remains usable
            # with the same nine players, but cannot add another replacement.
            with app_server.connect() as legacy_connection:
                legacy_connection.execute(
                    """
                    INSERT INTO squads (
                        manager_id, gameweek, players_json, bench_json,
                        captain, vice_captain, chip, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        first["manager"]["id"], 4,
                        json.dumps(LEGACY_FIVE_TRANSFER_LINEUP), json.dumps(LEGACY_FIVE_TRANSFER_BENCH),
                        "tristan-gonzalez", "spencer-madge", None, "2026-09-02T12:00:00-04:00",
                    ),
                )
            request(base, "/api/squads/4", "PUT", first["token"], {
                "players": LEGACY_FIVE_TRANSFER_LINEUP, "bench": LEGACY_FIVE_TRANSFER_BENCH,
                "captain": "spencer-madge", "viceCaptain": "tristan-gonzalez", "chip": None
            })
            request(base, "/api/squads/4", "PUT", first["token"], {
                "players": ["miguel-larrainzar", *LEGACY_FIVE_TRANSFER_LINEUP[1:]],
                "bench": LEGACY_FIVE_TRANSFER_BENCH,
                "captain": "spencer-madge", "viceCaptain": "tristan-gonzalez", "chip": None
            }, expected=400)
            # This legal squad costs $57.4m, proving the raised $60m cap is
            # enforced by the API rather than only displayed in the browser.
            request(base, "/api/squads/1", "PUT", budget_manager["token"], {
                "players": BUDGET_PROOF_LINEUP, "bench": BUDGET_PROOF_BENCH,
                "captain": "tristan-gonzalez", "viceCaptain": "buck-magee", "chip": None
            })
            request(base, "/api/squads/1", "PUT", budget_manager["token"], {
                "players": OVER_BUDGET_LINEUP, "bench": OVER_BUDGET_BENCH,
                "captain": "idan-garten", "viceCaptain": "tristan-gonzalez", "chip": None
            }, expected=400)
            # A price rise must not trap an existing squad above the original
            # $60m floor. Its current value remains available for later moves.
            with app_server.connect() as appreciated_connection:
                appreciated_connection.execute(
                    """
                    INSERT INTO squads (
                        manager_id, gameweek, players_json, bench_json,
                        captain, vice_captain, chip, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        budget_manager["manager"]["id"], 4,
                        json.dumps(OVER_BUDGET_LINEUP), json.dumps(OVER_BUDGET_BENCH),
                        "idan-garten", "tristan-gonzalez", None, "2026-09-02T12:00:00-04:00",
                    ),
                )
            appreciated_bench = ["max-born", *OVER_BUDGET_BENCH[1:]]
            request(base, "/api/squads/5", "PUT", budget_manager["token"], {
                "players": OVER_BUDGET_LINEUP, "bench": appreciated_bench,
                "captain": "idan-garten", "viceCaptain": "tristan-gonzalez", "chip": None
            })
            updated = request(base, "/api/me", "PUT", second["token"], {
                "managerName": "Jordan Lee", "teamName": "Plaid Press FC"
            })
            assert updated["manager"]["managerName"] == "Jordan Lee"
            assert updated["manager"]["teamName"] == "Plaid Press FC"
            table = request(base, f"/api/leagues/{league['code']}", token=first["token"])
            assert table["memberCount"] == 2
            assert table["freeTransfers"] == 2
            first_entry = next(row for row in table["standings"] if row["managerId"] == first["manager"]["id"])
            second_entry = next(row for row in table["standings"] if row["managerId"] == second["manager"]["id"])
            assert first_entry["canViewSquad"] is True
            assert first_entry["squadValue"] is not None
            assert first_entry["squad"]["captain"] == "idan-garten"
            assert len(first_entry["squad"]["players"]) == 6
            assert len(first_entry["squad"]["bench"]) == 3
            assert {"1", "2", "3", "4"} <= set(first_entry["squads"])
            assert first_entry["squads"]["1"]["chip"] == "tripleCaptain"
            assert first_entry["squads"]["2"]["chip"] is None
            assert second_entry["canViewSquad"] is False
            assert second_entry["squadValue"] is not None
            assert second_entry["squad"] is None
            assert set(second_entry["squads"]) == {"1"}
            assert second_entry["squads"]["1"]["chip"] == "benchBoost"
            assert "2" not in second_entry["squads"]
            assert "transferPenalty" not in first_entry
            assert [(row["teamName"], row["totalPoints"], row["rank"], row["transfersMade"]) for row in table["standings"]] == [
                ("Tartan Army", 42, 1, 0),
                ("Plaid Press FC", 41, 2, 2),
            ]
            profile = request(base, "/api/me", token=second["token"])
            assert profile["leagues"][0]["code"] == league["code"]
            assert profile["manager"]["teamName"] == "Plaid Press FC"
            assert set(profile["squads"]) == {"1", "2"}
            assert profile["squads"]["1"]["captain"] == "ian-kim"
            request(base, "/api/me", expected=401)
            with app_server.connect() as test_database:
                assert test_database.execute("SELECT COUNT(*) FROM managers").fetchone()[0] == 3
                assert test_database.execute("SELECT COUNT(*) FROM leagues").fetchone()[0] == 1
                assert test_database.execute("SELECT COUNT(*) FROM league_members").fetchone()[0] == 2
                assert test_database.execute("SELECT COUNT(*) FROM squads").fetchone()[0] == 9
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    assert temporary_db is not None and not temporary_db.exists()
    print("League check passed and temporary data reset: create/join, profile squad sync, bank preservation, legacy bank recovery, appreciation budget, chips, two-transfer cap, no rollover, history privacy, optional multi-device sign-in, authentication, and rankings.")


if __name__ == "__main__":
    main()
