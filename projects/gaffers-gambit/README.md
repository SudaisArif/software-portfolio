# Gaffer’s Gambit

A daily football rarity game with seven timed, open-answer questions, an original animated stadium, server-authoritative scoring, optional public leaderboard entries, unlimited practice, and spoiler-free sharing.

## Run locally

Node 22.13+ is required. The project uses the Sites Vinext starter, React, Cloudflare Workers and D1.

```sh
npm run install:ci
npm run build
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_stiff_lionheart.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0001_brief_sebastian_shaw.sql
npm run dev -- --port 5173 --hostname 127.0.0.1
```

Apply each migration only once per local database. Preview data is separate from production. Hosted migrations are applied by Sites on deployment. The source-of-truth Site identity and DB binding are in `.openai/hosting.json`.

## Checks

```sh
npx tsc --noEmit
node --experimental-strip-types --test tests/game.test.ts tests/cloudflare.test.ts
node --experimental-strip-types tests/integration.ts
```

The integration test requires the local server. It creates test-only local runs, publishes and removes a leaderboard entry, and waits for one real timer expiry. It never targets production. Checks cover all seven rounds, double submissions, stale requests, score tampering, ownership, origin checks, saved progress, publishing/removal, invalid answers, reports and timeout. Five complete practice matches verify the stored guest history, distinct themes, answer facts and no repeats across the preceding four matches. The concurrency smoke test runs 40 local leaderboard reads; it is not a production load certification.

## Game rules and fairness

- 25 seconds per question, seven questions, one submission each; max 700 metres.
- Editorial tiers: Tap-in 20, First team 40, Cult hero 60, Streets remember 80, Top bins 100. Misses score zero.
- The daily resets at 00:00 UTC. A complete daily pack, including answer tiers, is frozen in D1 when first requested, and reused across deployments.
- One daily run per guest browser. A 256-bit opaque HttpOnly, SameSite cookie identifies the guest; HTTPS uses Secure cookies.
- The server chooses questions, checks ownership, enforces deadlines and computes points. Atomic compare-and-set transitions prevent double scoring or skipping rounds. Scores supplied by a client are ignored.
- Identical scores share the same rank; completion time determines display order within the tie.
- Practice is unranked and may overlap the daily bank. Practice runs resume on the same browser; the clubhouse also offers a fresh training match without having to finish an old one.
- Every new draw has exactly four moderate questions, plus either three approachable questions or two approachable questions and one stretch question. A stretch is eligible in one third of seeded draws and may be omitted to avoid repeats. Difficulty never increases during cooldown fallback. The first round is approachable and the second moderate.
- Seven distinct themes are preferred, with a minimum of five and at most two questions per theme. Difficulty balance takes priority over filling a theme. Themes are shuffled before questions so a large category cannot dominate. Closely related prompts share an editorial family and cannot appear together. Each family belongs to a single theme, which is checked by the bank tests.
- Lineups are eligible in only one quarter of seeded draws, with at most one selected. Bench-only questions and most repeated lineup sets are retired from new games, while saved matches retain their answer sets.
- New daily packs prefer questions absent from the previous seven published packs and ideas absent from the previous two. Practice uses the guest’s previous four matches, with a one-match idea cooldown. Within each freshness stage, the sampler tries seven, six, then five themes. It relaxes the idea cooldown before reusing old questions, and avoids the previous match where possible. It never reintroduces retired questions.
- Accepted aliases ignore accents/punctuation/case. One-letter misspellings are allowed only for unique matches of five or more characters. Partial names do not silently match unrelated people.

This is an anonymous social game, not a verified competition. Clearing cookies or using another device can create another identity. No prizes or guarantees of bot resistance are implied. If cheating becomes material, add a managed challenge and durable account identity rather than trusting browser-generated fingerprints.

## Content and operations

The server-only bank in `lib/questions.ts` combines the original bank with the culture, records, international and accessible question modules, then applies the accessibility and launch reviews. There are 136 stored questions and 1,364 answer rows. Of those, 68 questions / 771 rows across 12 themes and 52 idea families are in active rotation; 68 retired questions remain resolvable for saved matches. Rows repeat when an answer qualifies for multiple questions. The active difficulty mix is 29 Open goal, 34 Match sharp and five Proper nerd.

The accessibility review retires 34 formerly active specialist prompts: goal-number milestones, exact card totals, obscure stadiums/referees, youth awards and narrow historical intersections. Three broader replacements cover European champions, UEFA Cup/Europa League winners, and Euros top scorers including ties. Rare answers remain valuable within recognisable questions. Difficulty is judged by finding one valid answer in 25 seconds, separately from finding a 100-point answer.

Each answer has a fact and each question a source and explicit scope. `research-launch.txt` records the final audit of all 68 active sets and eight replacements that include recent qualifying answers. `research-accessibility.txt` records the difficulty review; `research-culture.txt`, `research-records.txt` and `research-international.txt` retain the earlier factual audits. Editorial tiers and prompt difficulty are estimates, not measured community success rates. `research.txt` retains the initial evidence and limits of the SDS research.

The bank favours English football and international/European history. It remains finite; cooldowns spread repeats rather than promising endless unseen questions. Add complete sourced answer sets, assign a theme and family, and test before shipping. Never mutate an existing daily pack mid-day: an update affects fresh practice matches immediately and daily packs that have not yet been created. Historical results store the awarded score and explanation.

Use the Sites database tools to inspect the `reports` table for answer corrections and `runs` for actual pick frequencies. Reports are saved for manual review, not emailed or automatically approved. Only leaderboard nicknames and scores are public; raw submitted answers and guest IDs have no public list endpoint. The owner may ask Codex to inspect reports through the authenticated Sites connector. Optional entries can be removed by their player from the result screen.

The indexed D1 leaderboard is limited to 50 entries and cached for up to 30 seconds. Rate limits use an hourly guest hash, with a network hash fallback for first-time guests. Expired limiter rows are removed in bounded batches. No paid third-party API, analytics or advertising service is required.

Before a major promotion, confirm the actual Sites/Cloudflare account limits, run a representative hosted load test, monitor error rates and D1 latency, and agree an operating budget if free quotas are exceeded. Platform quotas, ongoing editorial work and long-term moderation cannot be guaranteed by a one-time implementation. Guest run records currently remain until owner-directed maintenance; do not advertise automatic deletion or a retention period that has not been implemented.

## Publishing

Use the installed Sites skill and its `site-workflow.mjs` source helper to commit/push, build/package and deploy this project. Preserve `.openai/hosting.json` and append migrations instead of altering already applied SQL. The generated `dist` archive must match the pushed commit. This app is intended for public, anonymous access.

The public sharing address is https://gaffers-gambit.tartan-fantasy.workers.dev, configured in `app/layout.tsx`. The small Worker in `deploy/cloudflare/` serves the existing public Site and its D1 database through this address. It is a fixed-origin proxy, preserves guest cookies, enforces same-origin submissions before forwarding, rewrites upstream redirects, and never caches personal game responses. New guests get independent anonymous identities before their first POST so Cloudflare's shared cross-zone address cannot put all newcomers in one rate-limit bucket. No paid plan or purchased domain was enabled.

The backend continues to deploy through Sites. Deploy changes to the address Worker separately with `node node_modules/wrangler/bin/wrangler.js deploy --config deploy/cloudflare/wrangler.jsonc` after signing into the same Cloudflare account. Browser cookies/local storage are origin-specific: existing players at the old address will have a fresh guest identity at the new address, while the public leaderboard and frozen daily pack remain shared. Monitor the actual Free plan quotas; the concurrency smoke tests are not a viral-traffic capacity guarantee.

Social preview assets are original SVG/PNG and can be regenerated with `node scripts/create-social.mjs`. The versioned `social-launch.png` avoids reusing an old cached preview image. Its absolute Open Graph/Twitter metadata, image dimensions and accessible alt text use the public sharing address. The stadium is original Canvas artwork; sound is synthesized locally after opt-in.
