import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";

const players = JSON.parse(await readFile(new URL("../data/players.json", import.meta.url), "utf8"));
const lineup = ["nicholas-macouzet", "miguel-larrainzar", "ian-kim", "rishi-kunderan", "idan-garten", "alex-popov"];
const bench = ["james-ashby", "thomas-thornton", "max-born"];
const ids = [...lineup, ...bench];
const basePrices = Object.fromEntries(players.map(({ id }) => [id, 6.5]));
const live = {};
const stats = {};
const events = [1, 2, 3, 4, 7].map((gameweek) => ({ gameweek, deadline: "2099-01-01T00:00:00Z" }));
const runtime = new Miniflare(convertV4MiniflareOptions({
  cf: false,
  workers: [{
    name: "bank-test",
    modulesRoot: new URL("../", import.meta.url).pathname,
    modules: await Promise.all(["worker/index.js", "worker/auth.js", "squad-finances.js"].map(async (path) => ({
      type: "ESModule", path, contents: await readFile(new URL(`../${path}`, import.meta.url), "utf8")
    }))),
    compatibilityDate: "2026-08-29",
    d1Databases: ["DB"],
    serviceBindings: {
      ASSETS: async (request) => {
        const name = new URL(request.url).pathname.split("/").at(-1);
        if (name === "player-prices.csv") return new Response("player_id,player_name,price\n" + players.map(({ id }) => `${id},Player,${basePrices[id]}`).join("\n"));
        if (name === "pricing-report.csv") return new Response("player_id,career_rating\n" + players.map(({ id }) => `${id},0`).join("\n"));
        const data = { "players.json": players, "gameweeks.json": events, "live-scores.json": live, "gameweek-stats.json": stats };
        return Response.json(data[name]);
      }
    }
  }]
}));
try {
  const db = await runtime.getD1Database("DB");
  for (const file of (await readdir(new URL("../migrations/", import.meta.url))).sort()) {
    const sql = await readFile(new URL(`../migrations/${file}`, import.meta.url), "utf8");
    for (const statement of sql.replace(/--[^\n]*/g, "").split(";").filter((part) => part.trim())) {
      await db.prepare(statement).run();
    }
  }
  let token;
  async function request(path, method = "GET", body, status = 200) {
    const response = await runtime.dispatchFetch(`http://localhost${path}`, {
      method, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    const payload = await response.json();
    assert.equal(response.status, status, JSON.stringify(payload));
    return payload;
  }
  const manager = await request("/api/managers", "POST", { managerName: "Bank Test", teamName: "Cash Preserved" }, 201);
  token = manager.token;
  const squad = { players: lineup, bench, captain: "idan-garten", viceCaptain: "ian-kim", bank: 999 };
  assert.equal((await request("/api/squads/1", "PUT", squad)).bank, 1.5);
  for (const gameweek of [1, 2, 3]) { live[gameweek] = { state: "final" }; stats[gameweek] = {}; }
  ids.forEach((id, i) => { stats[1][id] = i === 8 ? { minutes: 40, bonus: 1 } : { minutes: 40, goals: 2 }; });
  await db.prepare("UPDATE squads SET bank = NULL WHERE manager_id = ?").bind(manager.manager.id).run();
  assert.equal((await request("/api/me")).squads[1].bank, 1.5);
  assert.equal((await request("/api/squads/4", "PUT", squad)).bank, 1.5);
  basePrices["kieran-raker"] = 7.9;
  const changed = { ...squad, players: [lineup[0], "kieran-raker", ...lineup.slice(2)] };
  assert.equal((await request("/api/squads/4", "PUT", changed)).bank, 0.5);
  basePrices["miguel-larrainzar"] = 12;
  basePrices["kieran-raker"] = 7.4;
  for (let i = 0; i < 3; i++) assert.equal((await request("/api/squads/4", "PUT", changed)).bank, 0.5);
  basePrices["knox-foster"] = 7.5; // 7.4 current: 0.6 more than James Ashby.
  await request("/api/squads/4", "PUT", { ...changed, bench: ["knox-foster", ...bench.slice(1)] }, 400);
  assert.equal((await request("/api/me")).squads[4].bank, 0.5);
  for (const id of [...changed.players, ...bench]) basePrices[id] = 5;
  assert.equal((await request("/api/squads/7", "PUT", changed)).bank, 0.5);
  assert.equal((await request("/api/me")).squads[7].bank, 0.5);
  console.log("Worker/D1 bank checks passed: migrations, legacy recovery, appreciation, transfers, repeated saves, price falls, overspending, forged balances, and carryover.");
} finally {
  await runtime.dispose();
}
