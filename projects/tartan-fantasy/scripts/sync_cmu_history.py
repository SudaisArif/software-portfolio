"""Download official CMU cumulative statistics for career-based pricing."""

from pathlib import Path
import json

from sync_cmu_data import fetch, parse_field_stats, parse_goalkeeper_stats


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEASONS = ("2023-24", "2024-25", "2025-26")
BASE = "https://athletics.cmu.edu/sports/msoc"


def season_stats(season):
    endpoint = f"{BASE}/{season}/teams/carnegiemellon?tmpl=brief-category-template"
    players = parse_field_stats(fetch(f"{endpoint}&pos=kickers&r=0"))
    goalkeepers = parse_goalkeeper_stats(fetch(f"{endpoint}&pos=goalie&r=0"))
    for player in players:
        player.update(goalkeepers.get(player["id"], {}))
    if len(players) < 20:
        raise RuntimeError(f"Only {len(players)} stat lines were found for {season}; history was not changed.")
    return players


def main():
    seasons = []
    for season in SEASONS:
        players = season_stats(season)
        seasons.append({
            "season": season,
            "year": int(season[:4]),
            "source": f"{BASE}/{season}/teams/carnegiemellon",
            "players": players,
        })
        print(f"Downloaded {len(players)} official {season} CMU stat lines.")

    payload = {"seasons": seasons}
    destination = DATA / "stats-history.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"Updated {destination.relative_to(ROOT)} with {len(seasons)} completed seasons.")


if __name__ == "__main__":
    main()
