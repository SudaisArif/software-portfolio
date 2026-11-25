# Tartan Fantasy

A CMU-styled fantasy soccer app built around the 2026 Carnegie Mellon men’s soccer squad. Each manager selects six starters in a 2–2–2 plus three flexible substitutes. Goalkeepers share the two defensive slots, so selecting one is a strategic choice rather than a requirement.

Live site: [tartan-fantasy-cmu.tartan-fantasy.workers.dev](https://tartan-fantasy-cmu.tartan-fantasy.workers.dev)

The current build includes:

- all 33 players on the official 2026 roster;
- all 18 published 2026 fixtures as individual gameweeks;
- separate saved starters, bench, captain, vice-captain, and chip for each gameweek;
- one-use Triple Captain and Bench Boost chips;
- a 1.25× Impact Sub score for a fantasy starter who enters the real match and plays at least 20 minutes;
- two free transfers per gameweek after GW1, with no rollover or point penalties;
- server-backed managers, six-character mini-league codes, and live rankings;
- deadline-safe player ownership tables listing every fantasy team that owns each player by gameweek;
- automated expected-value price reviews after every three completed gameweeks, with visible reasons and small price moves;
- changing squad worth with a $60.0m starting floor, so price appreciation remains spendable;
- deadline locking one hour before kickoff;
- position and $60.0m budget enforcement;
- an editable player-price CSV;
- official 2023–2025 career appearances, starts, goals, assists, shots, cards, and goalkeeper stats for preseason pricing;
- automatic parsing of completed CMU box scores for goals, assists, shots, cards, saves, clean sheets, and exact minutes from substitutions;
- NCAA Division III live score, clock, game state, and player box-score syncing, with CMU/PrestoSports as the post-match fallback;
- direct live-score and FloCollege video/commentary links on each fixture;
- responsive desktop/mobile layouts, dark mode, player profiles, fixtures, rules, and browser persistence.

## Run it

There are no packages to install. Python includes the SQLite database used by the league system.

## Test it yourself

1. Open Terminal and move into the project:

```bash
cd "projects/tartan-fantasy"
```

2. Start the website:

```bash
make dev
```

3. Keep that terminal open and visit [http://127.0.0.1:4173](http://127.0.0.1:4173).

4. Open **Leagues**, enter your name and fantasy-team name, and press **Create team**.

5. Pick six starters, three substitutes and a captain. You can also activate Triple Captain or Bench Boost on **Pick Team**. Then return to **Leagues**, create a league and click its code to copy it.

6. Open a private/incognito browser window at the same address. This gives you a separate browser session. Create a second team, choose **Join a league**, and enter the first team’s code. Both teams should now appear in the ranking table.

7. Run the automated data and two-manager league tests in another terminal:

```bash
make check
```

Before the season starts, real standings correctly show zero points. The automated league check uses temporary match stats to verify benches, both chips, the two-transfer cap and ranking order; it does not modify the real database.

The server creates `data/tartan-fantasy.db` automatically. That file stores managers, private browser-session tokens, squads, league memberships, and codes. It is ignored by Git and blocked from web downloads.

You can also run the server directly:

```bash
python3 scripts/dev_server.py
```

Do not open `index.html` directly with a `file://` URL; browsers block its JSON/CSV requests. Use the local server.

To test from another device on the same network, run:

```bash
TARTAN_HOST=0.0.0.0 make dev
```

Then open `http://YOUR-COMPUTER-IP:4173` on that device. Your computer’s firewall may ask for permission. Use the normal `127.0.0.1` command when testing only on your own computer.

## Free production hosting

The deployed production version uses one Cloudflare Worker for the website and API plus a D1 database for managers, squads, league codes and rankings. Both fit comfortably inside Cloudflare's free tier for a team-sized game. The Worker checks the NCAA feed every five minutes on match days and persists live scores and box-score data in D1, so no laptop or paid always-on server is required.

The repository contains the full deployment setup:

- `worker/index.js` — league API, scoring, D1 access and match-day updater;
- `migrations/` — production database schema;
- `wrangler.jsonc` — Cloudflare Worker, static assets, D1 and five-minute schedule;
- `scripts/build_site.mjs` — copies only public website/data files into the deployable directory.

This public source snapshot uses a placeholder D1 database ID. Create your own Cloudflare database and update `wrangler.jsonc` before deployment. To publish future price or code changes from this computer, run:

```bash
npm install
npm run deploy
```

Player prices and the other source data remain editable under `data/`; the build command includes the latest versions automatically. Database migrations, if any are added in the future, can be applied with `npm run db:remote` before deployment.

Before sharing a deployment:

1. Visit `/api/health`; it should display `{"ok": true}`.
2. Create a manager and league in a normal browser window.
3. Open an incognito window, create a second manager and join with the code.
4. Save a legal squad for each manager and confirm both appear in the standings.

Manager creation still needs no sign-in. For optional access on multiple devices, open **Account / Leagues → Enable optional sign-in** on the device that already holds the team. Save the generated private team login code, then use **Sign in** on the other device. Signing in loads the existing squad, bank, points, and leagues without creating another manager or uploading that device’s draft. Both devices can remain signed in; refresh to load changes made on the other device.

Treat the login code like a password: anyone with it can control the team. It is shown only when generated and is not saved in browser preferences. A signed-in device can replace a lost code; the old code then stops allowing new sign-ins, while existing sessions stay connected. Signing out revokes only that device’s session and clears its local team cache. If every session and the code are lost, there is no email recovery. Managers who leave sign-in disabled should keep using their original browser and preserve site storage.

Migration `0004_optional_login.sql` adds optional login hashes, separate device sessions, and login-rate counters. Existing managers and their browser tokens stay valid. Codes have 160 bits of generated randomness; the database stores SHA-256 hashes of codes and new session tokens, not the secrets themselves. New device sessions expire after 90 days. Login attempts are capped at 100 per IP per 15-minute window; auth responses are not cacheable. This uses high-entropy generated secrets rather than user-chosen passwords, following the [OWASP session-token guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

## How leagues work

- Creating a league automatically adds its creator.
- Joining is idempotent, so entering the same code twice does not create duplicates.
- Squads are validated again on the server for formation, budget, captaincy, and deadlines.
- On page load, a manager's exact saved squad history is restored from the server; stale, unsaved future snapshots cannot replace the latest gameweek team.
- A saved squad carries forward until that manager makes another gameweek selection.
- After the opening squad, each manager can replace up to two of the nine squad members per gameweek. Moving a player between the pitch and bench does not count.
- Transfers are free and optional. Unused transfers expire at that gameweek's deadline and never roll over; there are no transfer point penalties.
- The one five-transfer Gameweek 2 squad saved before this rule change is grandfathered. Its same nine players remain valid, but any new player replacement must satisfy the two-transfer limit.
- Triple Captain makes the effective captain score 3× for one gameweek. Bench Boost scores all three substitutes for one gameweek. Each chip can be used once, and chips do not carry forward.
- Rankings are calculated on the server from `data/gameweek-stats.json`; browsers never submit their own point totals.
- Team and manager names in league tables open that manager's read-only lineup with a gameweek selector. Each opponent gameweek remains withheld by the server until its deadline, preventing early team copying.
- Guest play stays available. Optional private team login codes connect additional devices to the same manager, with independent sessions. There are no passwords or recovery emails.

## Edit player prices

Open [`data/player-prices.csv`](data/player-prices.csv). It has exactly the requested columns:

```csv
player_id,player_name,price
idan-garten,Idan Garten,12.0
```

Change only the `price` column and save. This remains each player's base price and the sync script never overwrites it. A local `make dev` reload reads it immediately; deploy again to publish a production change.

The preseason prices are reproducible. Run `make history` to refresh the official archived statistics, then `make prices`. The model runs 20,000 simulations for every applicable player-season: 2023–2025 for seniors, 2024–2025 for juniors, 2025 for sophomores, and no invented history for freshmen. It preserves each season’s exact cumulative appearances, starts, goals, assists, cards and goalkeeper saves while simulating the unavailable match-by-match allocation, outfield minutes and clean sheets under this site’s scoring.

Each season is normalized to an 18-match schedule. The career rating is a recency-weighted average, with each older season receiving 55% of the next season’s weight. Returning-player prices use:

```text
price = clamp(4.5, 12.0, 4.0 + 8.0 × (career rating / best rating)^0.80)
```

All current freshmen start at the lower `$4.0m` base price because they have no CMU match history. The full 2023, 2024 and 2025 simulated totals, career rating, price and reason are in [`data/pricing-report.csv`](data/pricing-report.csv). The random seed is fixed, so rerunning the command gives identical prices. Running it will overwrite manual price edits; ordinary `make sync` will not.

The simulation uses the same 40-minute appearance and clean-sheet thresholds as live scoring. To refresh the expected-value report without replacing manually edited base prices, run `python3 scripts/price_players.py --preserve-prices`.

The starting budget is fixed at `60.0` in `app.js`, `scripts/dev_server.py` and `worker/index.js`. Under the nine-player 2–2–2 format, the cheapest legal base-price squad is `$37.3m`. Three `$10.0m+` premiums can fit from `$57.0m`, but four premiums remain outside the initial cap, preserving a tradeoff between stars and squad depth. The automatic picker starts with a legal low-cost team and upgrades it without exceeding that gameweek's available budget. If you substantially reprice players, adjust all three runtime `BUDGET` constants and the validation/pricing constants to the same value.

Ownership shows each player's overall 2026 fantasy points by default, with a separate gameweek dropdown for weekly points. These totals include Impact Sub points, excluding manager-specific captain and chip bonuses.

Transfer form is the average fantasy points over the latest three current-season gameweeks with available box scores and a live or final match status (or fewer at the start of the season). Non-appearances count as zero. It includes Impact Sub points and updates with the live feed; ongoing-match figures are provisional. Transfers use current-season appearances, goals, and assists, and automatic picks use this same form. The 2025 reference statistics retain their historical form index.

### In-season price reviews

Once GWs 1–3 are final and all three box scores are available, the site performs its first automated expected-value review; the same process repeats for GWs 4–6, 7–9, and so on. It compares each player's actual fantasy points (including the Impact Sub calculation) with one-sixth of the preseason 18-match career rating. Freshmen use a transparent starting expectation of 1.5 points per three-match block, so they can move either up or down from their entry price.

The difference produces a change of `$0.0m`, `$0.1m`, `$0.2m`, or `$0.3m` in either direction, with current prices capped to `$3.5m–$12.5m`. A review waits if any of its three final box scores is missing, which prevents a feed outage from lowering everyone. The Ownership page publishes actual points, expected value, and the last move for every player.

Squad worth is the sum of the nine current prices and can therefore change. The first squad must fit `$60.0m`. Unspent cash is stored separately in the bank. Later spending limits equal the latest saved squad’s current value plus its bank; price rises and falls never change cash. Transfers sell and buy at full current prices. For example, a `$58.5m` purchase leaves `$1.5m` in the bank; if those players rise to `$61.0m`, the manager has `$62.5m` total buying power. Saving again, changing captain, or carrying the squad into another gameweek does not reset the bank or top it up to `$60.0m`. Transfers to earlier gameweeks are blocked once a later squad is saved, to protect subsequent balances.

Apply migration `0003_squad_bank.sql` before deploying the bank fix (`npm run db:remote` for Cloudflare; the Python server migrates automatically). Legacy rows have no recorded bank or transaction price snapshots. Their bank is reconstructed from saved gameweek selections and the published review history, applying each review to the following gameweek. This cannot exactly recover transfers made at different prices within the same gameweek or before manually edited base prices. New saves store the server-calculated bank explicitly; client-supplied balances are ignored.

Goalkeepers remain priced from the same simulated expected-points scale as every other position. They now compete with defenders for two combined places but retain goalkeeper scoring, including save points. Kai's premium price therefore reflects his historical minutes, clean sheets and saves without making him mandatory.

## Refresh official data

Run:

```bash
make sync
make check
```

`make sync` pulls the current public roster, all three applicable career-stat seasons, the current schedule, and any completed 2026 box scores from CMU Athletics. It preserves the manually curated venue list, price CSV, and manual fantasy adjustments.

It then checks the NCAA Division III scoreboard, attaches the NCAA game ID to each matching fixture, and refreshes `data/live-scores.json` plus the player-level gameweek stats. The NCAA JSON endpoint used by the script is a community-maintained wrapper around public NCAA.com data—not an official NCAA API—so the CMU/PrestoSports parser remains an independent fallback.

For a completed match, the importer reads the CMU player table plus play-by-play substitutions. It produces per-gameweek minutes, goals, assists, shots, shots on goal, cards, goalkeeper saves, and clean-sheet flags in [`data/gameweek-stats.json`](data/gameweek-stats.json). Rerunning sync preserves the manual `bonus`, `ownGoals`, `penaltiesMissed`, `penaltiesSaved`, and `manualOverrides` fields.

Until the opener is complete, the gameweek stat file is correctly empty and every 2026 fantasy total is zero.

## Live match mode

The deployed Cloudflare Worker checks the NCAA Division III feed every five minutes on match days. It updates live score, clock, game state, minutes, goals, assists, cards, saves and provisional fantasy points in D1. The browser checks these records every 30 seconds. This production automation is configured in `wrangler.jsonc` and does not require a computer to remain running.

For local data maintenance, you can still run:

On match day, keep this running in a terminal on the machine or server hosting the data files:

```bash
make live
```

It polls today’s NCAA Division III scoreboard once per minute. The website checks the local live-score and player-stat files every 30 seconds, so the score, clock, final status, minutes, goals, assists, cards, saves, and provisional fantasy points update without a manual reload.

The local watcher updates the files under `data/`; the production Worker stores its live overlay in D1. Manual `bonus`, `ownGoals`, `penaltiesMissed`, and `penaltiesSaved` values in the repository take precedence when production data is merged.

## Manual gameweek corrections

The generated file uses this structure:

```json
{
  "1": {
    "idan-garten": {
      "minutes": 78,
      "goals": 1,
      "assists": 0,
      "shots": 4,
      "shotsOnGoal": 2,
      "yellowCards": 0,
      "redCards": 0,
      "saves": 0,
      "cleanSheet": false,
      "ownGoals": 0,
      "penaltiesMissed": 0,
      "penaltiesSaved": 0,
      "bonus": 2
    }
  }
}
```

`bonus`, `ownGoals`, `penaltiesMissed`, and `penaltiesSaved` are manager-reviewed fields because the official soccer box score does not assign FPL bonus points or always identify fantasy-specific events in a stable field. If a feed incorrectly records participation or minutes, a `manualOverrides` object can replace those specific generated values and will survive future syncs.

## Scoring

- Appearance under 40 minutes: 1 point
- Appearance at least 40 minutes: 2 points
- Goal: GK/DEF 6, MID 5, FWD 4
- Assist: 3
- Clean sheet after 40 minutes: GK/DEF 4, MID 1
- Every 3 goalkeeper saves: 1
- Goalkeeper penalty save: 5
- Goalkeepers occupy a defender/goalkeeper squad slot; selecting one is optional
- Impact Sub: a fantasy starter who enters the real match and plays 20+ minutes has that score multiplied by 1.25 and rounded up
- Yellow: −1; red: −3
- Own goal: −2; penalty miss: −2
- Manual bonus: 0–3
- Captain: 2×; vice-captain takes over when the captain records no minutes
- Triple Captain: effective captain scores 3× for that gameweek
- Bench Boost: all three substitutes score for that gameweek
- Free transfers: up to two outgoing players per gameweek after GW1
- Transfer rollover / penalties: none

## Data sources

- [Official 2026 CMU roster](https://athletics.cmu.edu/sports/msoc/2026-27/roster)
- [Official 2026 CMU schedule and live coverage links](https://athletics.cmu.edu/sports/msoc/2026-27/schedule)
- [Official 2025 CMU cumulative statistics](https://athletics.cmu.edu/sports/msoc/2025-26/teams/carnegiemellon)
- [Official 2024 CMU cumulative statistics](https://athletics.cmu.edu/sports/msoc/2024-25/teams/carnegiemellon)
- [Official 2023 CMU cumulative statistics](https://athletics.cmu.edu/sports/msoc/2023-24/teams/carnegiemellon)
- [University Athletic Association 2026 schedule](https://uaasports.info/schedule.aspx?schedule=1136)
- [NCAA Division III men’s soccer scoreboard](https://www.ncaa.com/scoreboard/soccer-men/d3)
- [Open-source NCAA.com data proxy used by the sync script](https://ncaa-api.henrygd.me/)
- [FloCollege/FloFC CMU video schedule](https://www.flofc.com/teams/11194390-carnegie-mellon-mens-soccer)

The records in this repository were last verified on August 29, 2026. The local metadata is in [`data/source-metadata.json`](data/source-metadata.json).

## Launch boundary

The Cloudflare build is ready for a private squad launch with shared managers, squads, league codes, live data and standings. Password recovery and commissioner tools are intentionally not part of this simple first version.

Do not present the tartan shield in this repo as an official university mark. It is an original fantasy-project monogram using CMU-inspired colors; the official athletics pages remain the authoritative source.
