"""Validate the local player pool, prices, fixtures, and stat records."""

from pathlib import Path
import csv
from datetime import datetime
from itertools import combinations
import json
import re

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BUDGET = 60.0

players = json.loads((DATA / "players.json").read_text())
gameweeks = json.loads((DATA / "gameweeks.json").read_text())
stats = json.loads((DATA / "stats-2025.json").read_text())
career_history = json.loads((DATA / "stats-history.json").read_text())
gameweek_stats = json.loads((DATA / "gameweek-stats.json").read_text())
live_scores = json.loads((DATA / "live-scores.json").read_text())
with (DATA / "player-prices.csv").open(newline="", encoding="utf-8") as price_file:
    prices = list(csv.DictReader(price_file))
with (DATA / "pricing-report.csv").open(newline="", encoding="utf-8") as report_file:
    pricing_report = list(csv.DictReader(report_file))

issues = []
priced_ids = {row["player_id"] for row in prices}
report_ids = {row["player_id"] for row in pricing_report}
if len(players) != 33:
    issues.append(f"Expected 33 current players, found {len(players)}.")
if len(gameweeks) != 18:
    issues.append(f"Expected 18 gameweeks, found {len(gameweeks)}.")
history_seasons = career_history.get("seasons", [])
if [season.get("year") for season in history_seasons] != [2023, 2024, 2025]:
    issues.append("Career pricing history must contain the 2023, 2024, and 2025 seasons.")
if any(len(season.get("players", [])) < 20 for season in history_seasons):
    issues.append("At least one career-history season has incomplete player coverage.")
if len({player["id"] for player in players}) != len(players):
    issues.append("Player IDs are not unique.")
if len(priced_ids) != len(prices):
    issues.append("Price player IDs are not unique.")
if len({event["gameweek"] for event in gameweeks}) != len(gameweeks):
    issues.append("Gameweek IDs are not unique.")
if any(player["position"] not in {"GK", "DEF", "MID", "FWD"} for player in players):
    issues.append("At least one player has an invalid fantasy position.")
if [event["date"] for event in gameweeks] != sorted(event["date"] for event in gameweeks):
    issues.append("Gameweeks are not in date order.")
for event in gameweeks:
    try:
        datetime.fromisoformat(event["deadline"])
    except ValueError:
        issues.append(f"Invalid deadline for gameweek {event['gameweek']}.")
for player in players:
    if player["id"] not in priced_ids:
        issues.append(f"Missing price for {player['name']}.")
    if player["id"] not in report_ids:
        issues.append(f"Missing pricing simulation report for {player['name']}.")
if priced_ids - {player["id"] for player in players}:
    issues.append("The price file contains players who are not on the current roster.")
if report_ids != {player["id"] for player in players}:
    issues.append("The pricing report does not match the current roster exactly.")
price_by_id = {}
for row in prices:
    try:
        price = float(row["price"])
        if not 4.0 <= price <= 12.0:
            raise ValueError
        price_by_id[row["player_id"]] = price
    except ValueError:
        issues.append(f"Invalid price for {row.get('player_name', row.get('player_id', 'unknown player'))}.")
for player in players:
    if player.get("class") == "Fr" and price_by_id.get(player["id"]) != 4.0:
        issues.append(f"Freshman entry price for {player['name']} is not 4.0.")

# Prove the 2-2-2 plus three-bench budget creates the intended tradeoff:
# three premium players can fit only alongside value picks, while four cannot.
if len(price_by_id) == len(players):
    position_limits = {"DEF": 2, "MID": 2, "FWD": 2}
    by_position = {
        position: [
            player["id"] for player in players
            if ("DEF" if player["position"] == "GK" else player["position"]) == position
        ]
        for position in position_limits
    }
    premium_ids = {player_id for player_id, price in price_by_id.items() if price >= 10.0}
    mid_price_ids = {player_id for player_id, price in price_by_id.items() if 7.0 <= price < 10.0}
    tier = lambda player_id: "premium" if player_id in premium_ids else "mid" if player_id in mid_price_ids else "value"
    cheapest_by_mix = {}
    for defenders in combinations(by_position["DEF"], 2):
        for midfielders in combinations(by_position["MID"], 2):
            for forwards in combinations(by_position["FWD"], 2):
                starters = defenders + midfielders + forwards
                remaining = [player["id"] for player in players if player["id"] not in starters]
                remaining_by_tier = {
                    name: sorted((player_id for player_id in remaining if tier(player_id) == name), key=price_by_id.get)
                    for name in ("premium", "mid", "value")
                }
                starter_counts = {name: sum(tier(player_id) == name for player_id in starters) for name in remaining_by_tier}
                for bench_premiums in range(4):
                    for bench_mids in range(4 - bench_premiums):
                        bench_values = 3 - bench_premiums - bench_mids
                        requested = {"premium": bench_premiums, "mid": bench_mids, "value": bench_values}
                        if any(len(remaining_by_tier[name]) < count for name, count in requested.items()):
                            continue
                        bench = sum((remaining_by_tier[name][:count] for name, count in requested.items()), [])
                        mix = tuple(starter_counts[name] + requested[name] for name in ("premium", "mid", "value"))
                        cost = sum(price_by_id[player_id] for player_id in starters + tuple(bench))
                        cheapest_by_mix[mix] = min(cost, cheapest_by_mix.get(mix, float("inf")))
    cheapest_valid_cost = min(cheapest_by_mix.values(), default=None)
    if cheapest_valid_cost is None or cheapest_valid_cost > BUDGET:
        issues.append(f"No legal nine-player squad fits the {BUDGET:.1f} budget.")
    if len(premium_ids) < 2:
        issues.append("The pricing curve does not create enough premium players.")
    cheapest_three_premiums = min((cost for mix, cost in cheapest_by_mix.items() if mix[0] >= 3), default=None)
    if cheapest_three_premiums is None or cheapest_three_premiums > BUDGET:
        issues.append("The budget cannot fit three $10.0m premium players.")
    cheapest_four_premiums = min((cost for mix, cost in cheapest_by_mix.items() if mix[0] >= 4), default=None)
    if cheapest_four_premiums is None or cheapest_four_premiums <= BUDGET:
        issues.append("A legal squad can still afford four $10.0m premium players.")
    cheapest_two_premium_mid = min((cost for mix, cost in cheapest_by_mix.items() if mix[0] == 2 and mix[1] >= 1), default=None)
    if cheapest_two_premium_mid is None or cheapest_two_premium_mid > BUDGET:
        issues.append("The budget cannot fit two premiums plus a mid-price player.")
    cheapest_one_premium_three_mids = min((cost for mix, cost in cheapest_by_mix.items() if mix[0] == 1 and mix[1] >= 3), default=None)
    if cheapest_one_premium_three_mids is None or cheapest_one_premium_three_mids > BUDGET:
        issues.append("The budget cannot fit one premium plus three mid-price players.")
player_ids = {player["id"] for player in players}
gameweek_ids = {event["gameweek"] for event in gameweeks}
for gameweek, records in gameweek_stats.items():
    if int(gameweek) not in gameweek_ids:
        issues.append(f"Stats contain unknown gameweek {gameweek}.")
    for player_id in records:
        if player_id not in player_ids:
            issues.append(f"Gameweek {gameweek} contains unknown player {player_id}.")
for gameweek, record in live_scores.items():
    if int(gameweek) not in gameweek_ids:
        issues.append(f"Live scores contain unknown gameweek {gameweek}.")
    if int(record.get("gameweek", -1)) != int(gameweek):
        issues.append(f"Live-score gameweek key {gameweek} does not match its record.")
ncaa_ids = [event["ncaaGameId"] for event in gameweeks if event.get("ncaaGameId")]
if len(ncaa_ids) != len(set(ncaa_ids)):
    issues.append("NCAA game IDs are not unique.")

index = (ROOT / "index.html").read_text(encoding="utf-8")
for reference in re.findall(r'(?:src|href)="([^"#]+)"', index):
    if reference.startswith(("http://", "https://")):
        continue
    if not (ROOT / reference).exists():
        issues.append(f"index.html references missing file {reference}.")

if issues:
    raise SystemExit("\n".join(issues))
print(f"Data check passed: {len(players)} players, {len(history_seasons)} career seasons, {len(gameweeks)} gameweeks, {len(prices)} prices, {len(live_scores)} NCAA live records; cheapest squad ${cheapest_valid_cost:.1f}m, three-premium floor ${cheapest_three_premiums:.1f}m, and four-premium floor ${cheapest_four_premiums:.1f}m.")
