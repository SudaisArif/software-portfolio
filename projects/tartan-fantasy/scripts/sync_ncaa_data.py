"""Sync ESPN-style live scores and exact player box scores from NCAA's DIII feed."""

from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from time import sleep
from zoneinfo import ZoneInfo
import json

from sync_cmu_data import DATA, fetch, slugify, write_json

NCAA_API = "https://ncaa-api.henrygd.me"
NCAA_SCHOOL = "carnegie-mellon"
FULL_APPEARANCE_MINUTES = 40
EASTERN = ZoneInfo("America/New_York")


def fetch_json(url):
    return json.loads(fetch(url))


def score_value(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def truthy(value):
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "y"}


def find_cmu_game(scoreboard):
    for wrapper in scoreboard.get("games", []):
        game = wrapper.get("game", {})
        away = game.get("away", {}).get("names", {}).get("seo")
        home = game.get("home", {}).get("names", {}).get("seo")
        if NCAA_SCHOOL in {away, home}:
            return game
    return None


def live_record(game, event):
    cmu_is_home = game.get("home", {}).get("names", {}).get("seo") == NCAA_SCHOOL
    cmu = game.get("home" if cmu_is_home else "away", {})
    opponent = game.get("away" if cmu_is_home else "home", {})
    state = game.get("gameState", "pre")
    return {
        "gameweek": event["gameweek"],
        "gameId": str(game.get("gameID", "")),
        "state": state,
        "cmuScore": score_value(cmu.get("score")),
        "opponentScore": score_value(opponent.get("score")),
        "opponent": event["opponent"],
        "period": game.get("currentPeriod") or game.get("finalMessage") or "",
        "clock": game.get("contestClock") or "",
        "startTime": game.get("startTime") or f"{event['time']} ET",
        "updatedAt": datetime.now(EASTERN).isoformat(timespec="seconds"),
        "sourceUrl": f"https://www.ncaa.com/game/{game.get('gameID')}",
    }


def parse_ncaa_boxscore(document, game, current_ids):
    cmu_is_home = game.get("home", {}).get("names", {}).get("seo") == NCAA_SCHOOL
    cmu_side = game.get("home" if cmu_is_home else "away", {})
    opponent_side = game.get("away" if cmu_is_home else "home", {})
    cmu_score = score_value(cmu_side.get("score"))
    opponent_score = score_value(opponent_side.get("score"))
    state = game.get("gameState")
    teams = {str(team.get("teamId")): team for team in document.get("teams", [])}
    cmu_team_id = next((team_id for team_id, team in teams.items() if team.get("seoname") == NCAA_SCHOOL), None)
    if not cmu_team_id:
        return {}
    team_boxscore = next((team for team in document.get("teamBoxscore", []) if str(team.get("teamId")) == cmu_team_id), None)
    if not team_boxscore:
        return {}

    output = {}
    for player in team_boxscore.get("playerStats", []):
        if not player.get("participated"):
            continue
        player_id = slugify(f"{player.get('firstName', '')} {player.get('lastName', '')}")
        if player_id not in current_ids:
            continue
        penalties = player.get("penalties") or {}
        goalie = player.get("goalie") or {}
        goalie_saves = score_value(goalie.get("saves"))
        try:
            minutes = int(float(player.get("minutesPlayed") or 0))
        except (TypeError, ValueError):
            minutes = 0
        output[player_id] = {
            "minutes": minutes,
            "started": truthy(player.get("starter")),
            "goals": score_value(player.get("goals")) or 0,
            "assists": score_value(player.get("assists")) or 0,
            "shots": score_value(player.get("shots")) or 0,
            "shotsOnGoal": score_value(player.get("shotsOnGoal")) or 0,
            "yellowCards": score_value(penalties.get("yellowCards")) or 0,
            "redCards": score_value(penalties.get("redCards")) or 0,
            "saves": goalie_saves if goalie_saves is not None else (score_value(player.get("saves")) or 0),
            "cleanSheet": state == "final" and opponent_score == 0 and minutes >= FULL_APPEARANCE_MINUTES,
            "ownGoals": 0,
            "penaltiesMissed": max(0, (score_value(player.get("penaltyShotAttempts")) or 0) - (score_value(player.get("penaltyShotGoals")) or 0)),
            "penaltiesSaved": 0,
            "bonus": 0,
            "source": "NCAA",
            "provisional": state != "final",
            "teamScore": cmu_score,
            "opponentScore": opponent_score,
        }
    return output


def merge_stats(existing_week, parsed):
    merged = dict(existing_week)
    for player_id, stats in parsed.items():
        prior = existing_week.get(player_id, {})
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
        merged[player_id] = record
    return merged


def sync(only_current=False):
    gameweeks_file = DATA / "gameweeks.json"
    live_file = DATA / "live-scores.json"
    stats_file = DATA / "gameweek-stats.json"
    players_file = DATA / "players.json"
    gameweeks = json.loads(gameweeks_file.read_text(encoding="utf-8"))
    players = json.loads(players_file.read_text(encoding="utf-8"))
    live_scores = json.loads(live_file.read_text(encoding="utf-8")) if live_file.exists() else {}
    gameweek_stats = json.loads(stats_file.read_text(encoding="utf-8")) if stats_file.exists() else {}
    current_ids = {player["id"] for player in players}
    today = datetime.now(EASTERN).date().isoformat()
    events = [event for event in gameweeks if event["date"] == today] if only_current else gameweeks
    discovered = 0
    active = 0

    for event in events:
        date_path = event["date"].replace("-", "/")
        try:
            scoreboard = fetch_json(f"{NCAA_API}/scoreboard/soccer-men/d3/{date_path}")
        except Exception as error:
            print(f"NCAA scoreboard unavailable for GW{event['gameweek']}: {error}")
            continue
        game = find_cmu_game(scoreboard)
        if not game:
            continue
        game_id = str(game.get("gameID"))
        event["ncaaGameId"] = game_id
        event["ncaaUrl"] = f"https://www.ncaa.com/game/{game_id}"
        live_scores[str(event["gameweek"])] = live_record(game, event)
        discovered += 1
        if game.get("gameState") in {"live", "final"}:
            active += 1
            try:
                boxscore = fetch_json(f"{NCAA_API}/game/{game_id}/boxscore")
                parsed = parse_ncaa_boxscore(boxscore, game, current_ids)
                if parsed:
                    gameweek_stats[str(event["gameweek"])] = merge_stats(gameweek_stats.get(str(event["gameweek"]), {}), parsed)
            except Exception as error:
                print(f"NCAA box score unavailable for GW{event['gameweek']}: {error}")
        sleep(0.22)

    write_json("gameweeks.json", gameweeks)
    write_json("live-scores.json", live_scores)
    write_json("gameweek-stats.json", gameweek_stats)
    print(f"NCAA sync found {discovered} scheduled CMU games and {active} live/final games.")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Poll today's NCAA score once per minute.")
    args = parser.parse_args()
    if not args.watch:
        sync()
    else:
        print("Watching NCAA DIII live scores every 60 seconds. Press Ctrl-C to stop.")
        try:
            while True:
                sync(only_current=True)
                sleep(60)
        except KeyboardInterrupt:
            print("\nStopped NCAA live-score watcher.")
