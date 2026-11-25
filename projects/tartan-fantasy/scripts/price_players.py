"""Price the current roster from simulated fantasy points across CMU careers."""

from itertools import combinations
from pathlib import Path
import argparse
import csv
import json
import math
import random
import statistics


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CURRENT_YEAR = 2025
TARGET_GAMES = 18
DEFAULT_ITERATIONS = 20_000
DEFAULT_SEED = 20260829
RECENCY_DECAY = 0.55
FRESHMAN_PRICE = 4.0
RETURNER_FLOOR = 4.5
RETURNER_CEILING = 12.0
PRICE_SPREAD = RETURNER_CEILING - 4.0
PRICE_CURVE = 0.80
IMPACT_SUB_MULTIPLIER = 1.25
IMPACT_SUB_MINUTES = 20
FULL_APPEARANCE_MINUTES = 40
BUDGET = 60.0
PREMIUM_PRICE = 10.0
STARTER_MINUTES = (45, 78, 90)
SUB_MINUTES = (6, 22, 45)
GOAL_POINTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
STARTER_LIMITS = {"DEF": 2, "MID": 2, "FWD": 2}
BENCH_SIZE = 3


def percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def round_tenth(value):
    return round(value * 10 + 1e-9) / 10


def relevant_years(class_year):
    season_count = {"Fr": 0, "So": 1, "Jr": 2, "Sr": 3}.get(class_year, 1)
    return list(range(CURRENT_YEAR - season_count + 1, CURRENT_YEAR + 1))


def clean_sheet_probability(season_rows, team_games):
    goalkeepers = [row for row in season_rows if row.get("position") == "GK"]
    goals_against = sum(float(row.get("goalsAgainst") or 0) for row in goalkeepers)
    if team_games <= 0:
        return 0.40
    # The archived HTML does not reliably expose its shutout column. Under a
    # Poisson goals-against model, P(no goals allowed) is exp(-GA/game).
    return max(0.20, min(0.60, math.exp(-goals_against / team_games)))


def allocate_events(rng, games, count, field):
    if count <= 0 or not games:
        return
    weights = [max(1, game["minutes"]) for game in games]
    for index in rng.choices(range(len(games)), weights=weights, k=count):
        games[index][field] += 1


def impact_sub_score(raw_points, game):
    if not game["started"] and game["minutes"] >= IMPACT_SUB_MINUTES and raw_points > 0:
        return math.ceil(raw_points * IMPACT_SUB_MULTIPLIER)
    return raw_points


def simulate_historical_season(player, row, team_games, clean_probability, iterations, rng):
    """Score one completed season while simulating unavailable match detail.

    Cumulative goals, assists, cards and saves remain exact. Only their match
    allocation, outfield minutes and clean-sheet allocation are simulated.
    """
    if not row or not float(row.get("appearances") or 0):
        return {"mean": 0.0, "p10": 0, "p90": 0, "normalized": 0.0}

    appearances = int(float(row.get("appearances") or 0))
    starts = min(appearances, int(float(row.get("starts") or 0)))
    totals = []
    for _ in range(iterations):
        games = []
        for index in range(appearances):
            started = index < starts
            low, mode, high = STARTER_MINUTES if started else SUB_MINUTES
            minutes = max(1, min(90, round(rng.triangular(low, high, mode))))
            games.append({
                "started": started,
                "minutes": minutes,
                "goals": 0,
                "assists": 0,
                "yellowCards": 0,
                "redCards": 0,
                "saves": 0,
            })

        for field in ("goals", "assists", "yellowCards", "redCards", "saves"):
            allocate_events(rng, games, int(float(row.get(field) or 0)), field)

        season_total = 0
        for game in games:
            minutes = game["minutes"]
            points = 2 if minutes >= FULL_APPEARANCE_MINUTES else 1
            points += game["goals"] * GOAL_POINTS[player["position"]]
            points += game["assists"] * 3
            if minutes >= FULL_APPEARANCE_MINUTES and rng.random() < clean_probability:
                points += CLEAN_SHEET_POINTS[player["position"]]
            if player["position"] == "GK":
                points += game["saves"] // 3
            points -= game["yellowCards"]
            points -= game["redCards"] * 3
            season_total += impact_sub_score(points, game)
        totals.append(season_total)

    mean = statistics.fmean(totals)
    return {
        "mean": mean,
        "p10": percentile(totals, 0.10),
        "p90": percentile(totals, 0.90),
        "normalized": mean * TARGET_GAMES / max(1, team_games),
    }


def career_rating(player, projections):
    years = relevant_years(player.get("class"))
    if not years:
        return 0.0
    weighted = 0.0
    weight_total = 0.0
    for year in years:
        weight = RECENCY_DECAY ** (CURRENT_YEAR - year)
        weighted += projections.get(year, {}).get("normalized", 0.0) * weight
        weight_total += weight
    return weighted / weight_total


def player_price(player, rating, maximum_rating):
    if player.get("class") == "Fr":
        return FRESHMAN_PRICE, "fixed freshman entry price"
    if rating <= 0 or maximum_rating <= 0:
        return RETURNER_FLOOR, "returner with no career fantasy points"
    normalized = min(1.0, rating / maximum_rating)
    raw_price = 4.0 + PRICE_SPREAD * normalized ** PRICE_CURVE
    price = max(RETURNER_FLOOR, min(RETURNER_CEILING, round_tenth(raw_price)))
    return price, "returner: 4.0 + 8.0 × (career_rating / max_rating)^0.80"


def starter_combinations(players):
    by_position = {
        position: [
            player["id"] for player in players
            if ("DEF" if player["position"] == "GK" else player["position"]) == position
        ]
        for position in STARTER_LIMITS
    }
    for defenders in combinations(by_position["DEF"], 2):
        for midfielders in combinations(by_position["MID"], 2):
            for forwards in combinations(by_position["FWD"], 2):
                yield defenders + midfielders + forwards


def cheapest_valid_squad(players, prices):
    cheapest = None
    for starters in starter_combinations(players):
        bench = sorted(
            (player["id"] for player in players if player["id"] not in starters),
            key=lambda player_id: (prices[player_id], player_id),
        )[:BENCH_SIZE]
        squad = starters + tuple(bench)
        cost = sum(prices[player_id] for player_id in squad)
        if cheapest is None or cost < cheapest[0]:
            cheapest = (cost, squad)
    return cheapest


def maximum_affordable_premiums(players, prices):
    premium_ids = {player_id for player_id, price in prices.items() if price >= PREMIUM_PRICE}
    maximum = 0
    minimum_by_count = {}
    for starters in starter_combinations(players):
        starter_premiums = sum(player_id in premium_ids for player_id in starters)
        remaining = [player["id"] for player in players if player["id"] not in starters]
        remaining_premium = sorted((player_id for player_id in remaining if player_id in premium_ids), key=prices.get)
        remaining_value = sorted((player_id for player_id in remaining if player_id not in premium_ids), key=prices.get)
        for bench_premiums in range(BENCH_SIZE + 1):
            if len(remaining_premium) < bench_premiums or len(remaining_value) < BENCH_SIZE - bench_premiums:
                continue
            bench = remaining_premium[:bench_premiums] + remaining_value[:BENCH_SIZE - bench_premiums]
            count = starter_premiums + bench_premiums
            cost = sum(prices[player_id] for player_id in starters) + sum(prices[player_id] for player_id in bench)
            minimum_by_count[count] = min(cost, minimum_by_count.get(count, math.inf))
            if cost <= BUDGET + 1e-9:
                maximum = max(maximum, count)
    return maximum, minimum_by_count


def write_outputs(rows, preserve_prices=False):
    price_path = DATA / "player-prices.csv"
    report_path = DATA / "pricing-report.csv"
    if not preserve_prices:
        with price_path.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.DictWriter(destination, fieldnames=("player_id", "player_name", "price"), lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({"player_id": row["player_id"], "player_name": row["player_name"], "price": row["price"]})
    with report_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return price_path, report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--preserve-prices", action="store_true", help="refresh only the EV report without replacing manual base prices")
    args = parser.parse_args()
    if args.iterations < 100:
        parser.error("--iterations must be at least 100")

    players = json.loads((DATA / "players.json").read_text(encoding="utf-8"))
    history = json.loads((DATA / "stats-history.json").read_text(encoding="utf-8"))["seasons"]
    rng = random.Random(args.seed)
    projections = {player["id"]: {} for player in players}

    for season in history:
        year = int(season["year"])
        season_rows = season["players"]
        team_games = max(int(float(row.get("appearances") or 0)) for row in season_rows)
        clean_probability = clean_sheet_probability(season_rows, team_games)
        rows_by_id = {row["id"]: row for row in season_rows}
        for player in players:
            if year not in relevant_years(player.get("class")):
                continue
            projections[player["id"]][year] = simulate_historical_season(
                player, rows_by_id.get(player["id"]), team_games,
                clean_probability, args.iterations, rng,
            )

    ratings = {player["id"]: career_rating(player, projections[player["id"]]) for player in players}
    maximum_rating = max(ratings.values())
    rows = []
    prices = {}
    for player in players:
        price, basis = player_price(player, ratings[player["id"]], maximum_rating)
        row = {
            "player_id": player["id"],
            "player_name": player["name"],
            "position": player["position"],
            "class": player["class"],
            "2023_simulated_points": f'{projections[player["id"]].get(2023, {}).get("mean", 0):.2f}',
            "2024_simulated_points": f'{projections[player["id"]].get(2024, {}).get("mean", 0):.2f}',
            "2025_simulated_points": f'{projections[player["id"]].get(2025, {}).get("mean", 0):.2f}',
            "career_rating": f'{ratings[player["id"]]:.2f}',
            "price": f"{price:.1f}",
            "pricing_basis": basis,
        }
        rows.append(row)
        prices[player["id"]] = price

    price_path, report_path = write_outputs(rows, preserve_prices=args.preserve_prices)
    cheapest_cost, _ = cheapest_valid_squad(players, prices)
    maximum_premiums, minimum_by_premium_count = maximum_affordable_premiums(players, prices)
    assert cheapest_cost <= BUDGET, f"No valid squad fits the ${BUDGET:.1f}m budget"
    assert maximum_premiums <= 3, f"A ${BUDGET:.1f}m squad can still hold {maximum_premiums} premium players"

    print(f"Priced {len(rows)} players from three official seasons with {args.iterations:,} simulations per applicable player-season.")
    print(f"Cheapest valid squad: ${cheapest_cost:.1f}m; budget ${BUDGET:.1f}m.")
    print(f"Maximum players priced at least ${PREMIUM_PRICE:.1f}m in any legal squad: {maximum_premiums}.")
    if 3 in minimum_by_premium_count:
        print(f"Cheapest legal squad containing three premiums: ${minimum_by_premium_count[3]:.1f}m.")
    if args.preserve_prices:
        print(f"Preserved {price_path.relative_to(ROOT)}; updated {report_path.relative_to(ROOT)}")
    else:
        print(f"Updated {price_path.relative_to(ROOT)} and {report_path.relative_to(ROOT)}")
    print("Top career ratings:")
    for row in sorted(rows, key=lambda item: float(item["career_rating"]), reverse=True)[:10]:
        print(f'  {row["player_name"]:<22} {row["position"]:<3} rating {float(row["career_rating"]):5.1f}  ${row["price"]}m')


if __name__ == "__main__":
    main()
