"""Exercise the deployed Cloudflare/D1 API without touching production data by default."""

from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import os

BASE = os.environ.get("TARTAN_TEST_URL", "http://127.0.0.1:8787").rstrip("/")
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
OVER_BUDGET_LINEUP = [
    "kai-yamamoto",
    "mateas-fitzwilliam",
    "tristan-gonzalez",
    "dominic-hoar-weiler",
    "idan-garten",
    "justin-fung",
]
OVER_BUDGET_BENCH = ["nathan-yao", "sola-nishimura", "james-ashby"]
BUDGET_PROOF_LINEUP = [
    "buck-magee", "henry-hawthorn", "tristan-gonzalez",
    "ian-kim", "alex-popov", "thomas-thornton",
]
BUDGET_PROOF_BENCH = ["nicholas-macouzet", "miguel-larrainzar", "max-born"]


def request(path, method="GET", token=None, body=None, expected=200):
    headers = {"Content-Type": "application/json", "User-Agent": "TartanFantasyTest/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(f"{BASE}{path}", data=payload, headers=headers, method=method), timeout=10) as response:
            status = response.status
            result = json.loads(response.read())
    except HTTPError as error:
        status = error.code
        result = json.loads(error.read())
    assert status == expected, (path, status, result)
    return result


def squad(players=LINEUP, bench=BENCH, captain="idan-garten", vice="ian-kim", chip=None):
    return {
        "players": players,
        "bench": bench,
        "captain": captain,
        "viceCaptain": vice,
        "chip": chip,
    }


def main():
    suffix = os.urandom(3).hex()
    assert request("/api/health") == {"ok": True}
    first = request(
        "/api/managers",
        "POST",
        body={"managerName": f"Alex {suffix}", "teamName": f"Tartan {suffix}"},
        expected=201,
    )
    second = request(
        "/api/managers",
        "POST",
        body={"managerName": f"Jordan {suffix}", "teamName": f"Plaid {suffix}"},
        expected=201,
    )
    budget_manager = request(
        "/api/managers",
        "POST",
        body={"managerName": f"Casey {suffix}", "teamName": f"Budget {suffix}"},
        expected=201,
    )
    request("/api/me", expected=401)
    league = request(
        "/api/leagues", "POST", first["token"], {"name": f"CMU Test {suffix}"}, 201
    )["league"]
    assert len(league["code"]) == 6 and league["isOwner"]
    request("/api/leagues/join", "POST", second["token"], {"code": league["code"]})
    request("/api/leagues/join", "POST", second["token"], {"code": league["code"]})
    request("/api/leagues/join", "POST", second["token"], {"code": "BAD999"}, 404)
    request("/api/squads/1", "PUT", first["token"], squad(chip="tripleCaptain"))
    request("/api/squads/1", "PUT", second["token"], squad(chip="benchBoost"))
    request("/api/squads/1", "PUT", second["token"], squad(captain="ian-kim", vice="idan-garten", chip="benchBoost"))
    request(
        "/api/squads/2",
        "PUT",
        second["token"],
        squad(TWO_TRANSFER_LINEUP, TWO_TRANSFER_BENCH, captain="ian-kim", vice="idan-garten"),
    )
    request(
        "/api/squads/2",
        "PUT",
        second["token"],
        squad(TWO_TRANSFER_LINEUP, THREE_TRANSFER_BENCH, captain="ian-kim", vice="idan-garten"),
        expected=400,
    )
    request(
        "/api/squads/2", "PUT", first["token"], squad(chip="tripleCaptain"), expected=409
    )
    request(
        "/api/squads/1",
        "PUT",
        budget_manager["token"],
        squad(BUDGET_PROOF_LINEUP, BUDGET_PROOF_BENCH, captain="tristan-gonzalez", vice="buck-magee"),
    )
    request(
        "/api/squads/1",
        "PUT",
        budget_manager["token"],
        squad(OVER_BUDGET_LINEUP, OVER_BUDGET_BENCH, vice="tristan-gonzalez"),
        expected=400,
    )
    updated = request(
        "/api/me",
        "PUT",
        second["token"],
        {"managerName": f"Jordan Lee {suffix}", "teamName": f"Plaid FC {suffix}"},
    )
    assert updated["manager"]["teamName"] == f"Plaid FC {suffix}"
    table = request(f"/api/leagues/{league['code']}", token=first["token"])
    assert table["memberCount"] == 2
    assert table["freeTransfers"] == 2
    assert {row["managerId"] for row in table["standings"]} == {
        first["manager"]["id"],
        second["manager"]["id"],
    }
    first_entry = next(row for row in table["standings"] if row["managerId"] == first["manager"]["id"])
    second_entry = next(row for row in table["standings"] if row["managerId"] == second["manager"]["id"])
    assert first_entry["canViewSquad"] is True and len(first_entry["squad"]["players"]) == 6
    assert isinstance(first_entry["squadValue"], (int, float))
    assert second_entry["canViewSquad"] is (second_entry["squad"] is not None)
    assert isinstance(first_entry["squads"], dict) and isinstance(first_entry["weeklyPoints"], dict)
    assert "transferPenalty" not in first_entry
    profile = request("/api/me", token=second["token"])
    assert profile["leagues"][0]["code"] == league["code"]
    assert set(profile["squads"]) == {"1", "2"}
    assert profile["squads"]["1"]["captain"] == "ian-kim"
    print(
        "Cloudflare check passed: authentication, manager updates, profile squad sync, create/join league, "
        "duplicate joins, squad upserts, budget, chips, two-transfer cap, history, squad value, and standings."
    )


if __name__ == "__main__":
    main()
