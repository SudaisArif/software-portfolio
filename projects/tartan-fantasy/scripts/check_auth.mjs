import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";
import { secretHash } from "../worker/auth.js";

const runtime = new Miniflare(convertV4MiniflareOptions({
  cf: false,
  workers: [{
    name: "auth-test",
    modulesRoot: new URL("../", import.meta.url).pathname,
    modules: await Promise.all(["worker/index.js", "worker/auth.js", "squad-finances.js"].map(async (path) => ({
      type: "ESModule", path, contents: await readFile(new URL(`../${path}`, import.meta.url), "utf8")
    }))),
    compatibilityDate: "2026-08-29",
    bindings: { ALLOW_LOCKED_WRITES: "1" },
    d1Databases: ["DB"],
    serviceBindings: { ASSETS: async (request) => new Response(await readFile(new URL(`../data/${new URL(request.url).pathname.split("/").at(-1)}`, import.meta.url))) }
  }]
}));
try {
  const db = await runtime.getD1Database("DB");
  for (const file of (await readdir(new URL("../migrations/", import.meta.url))).sort()) {
    const sql = await readFile(new URL(`../migrations/${file}`, import.meta.url), "utf8");
    for (const statement of sql.replace(/--[^\n]*/g, "").split(";").filter((part) => part.trim())) await db.prepare(statement).run();
  }
  async function request(path, { token, body, status = 200, method = body ? "POST" : "GET" } = {}) {
    const response = await runtime.dispatchFetch(`http://localhost${path}`, {
      method, headers: { "Content-Type": "application/json", "CF-Connecting-IP": "203.0.113.10", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    const payload = await response.json();
    assert.equal(response.status, status, `${path}: ${JSON.stringify(payload)}`);
    assert.equal(response.headers.get("cache-control"), "no-store");
    return payload;
  }
  const guest = await request("/api/managers", { body: { managerName: "Guest Manager", teamName: "Existing Squad" }, status: 201 });
  assert.equal((await request("/api/me", { token: guest.token })).manager.loginEnabled, false);
  const squad = { players: ["nicholas-macouzet", "miguel-larrainzar", "ian-kim", "rishi-kunderan", "idan-garten", "alex-popov"], bench: ["james-ashby", "thomas-thornton", "max-born"], captain: "idan-garten", viceCaptain: "ian-kim" };
  await request("/api/squads/1", { token: guest.token, method: "PUT", body: squad });
  await request("/api/leagues", { token: guest.token, body: { name: "Same League" }, status: 201 });
  const before = await request("/api/me", { token: guest.token });
  await request("/api/auth/enable", { body: {}, status: 401 });
  await request("/api/auth/rotate", { token: guest.token, body: {}, status: 409 });
  const enabled = await request("/api/auth/enable", { token: guest.token, body: {} });
  assert.match(enabled.code, /^TF-(?:[A-Z2-9]{8}-){3}[A-Z2-9]{8}$/);
  assert.equal(enabled.manager.loginEnabled, true);
  await request("/api/auth/enable", { token: guest.token, body: {}, status: 409 });
  const saved = await db.prepare("SELECT * FROM manager_logins WHERE manager_id = ?").bind(guest.manager.id).first();
  assert.equal(saved.code_hash, await secretHash(enabled.code.replaceAll("-", "").slice(2)));
  assert.ok(!JSON.stringify(saved).includes(enabled.code));
  for (const code of ["WRONG", "TF-" + "A".repeat(32), null, "x".repeat(129), {}]) {
    await request("/api/auth/login", { body: { code }, status: 401 });
  }
  const phone = await request("/api/auth/login", { body: { code: enabled.code.toLowerCase() } });
  const laptop = await request("/api/auth/login", { body: { code: enabled.code.replaceAll("-", " ") } });
  assert.equal(phone.manager.id, guest.manager.id);
  assert.notEqual(phone.token, laptop.token);
  assert.notEqual(phone.token, guest.token);
  assert.deepEqual(phone.squads, before.squads);
  assert.deepEqual(phone.leagues, before.leagues);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM managers").first()).n, 1);
  assert.equal((await request("/api/me", { token: guest.token })).manager.loginEnabled, true);
  await request("/api/me", { token: phone.token, method: "PUT", body: { teamName: "Shared Change" } });
  assert.equal((await request("/api/me", { token: laptop.token })).manager.teamName, "Shared Change");
  const replacement = await request("/api/auth/rotate", { token: laptop.token, body: {} });
  await request("/api/auth/login", { body: { code: enabled.code }, status: 401 });
  const third = await request("/api/auth/login", { body: { code: replacement.code } });
  assert.equal(third.manager.id, guest.manager.id);
  await request("/api/auth/logout", { token: phone.token, body: {} });
  await request("/api/me", { token: phone.token, status: 401 });
  await request("/api/me", { token: laptop.token });
  await request("/api/auth/logout", { token: guest.token, body: {} });
  await request("/api/me", { token: guest.token, status: 401 });
  await request("/api/me", { token: laptop.token });
  await db.prepare("UPDATE manager_sessions SET expires_at = 0 WHERE token_hash = ?").bind(await secretHash(third.token)).run();
  await request("/api/me", { token: third.token, status: 401 });
  await db.prepare("UPDATE login_attempts SET attempts = 100").run();
  await request("/api/auth/login", { body: { code: replacement.code }, status: 429 });
  await db.prepare("UPDATE login_attempts SET window_start = 0").run();
  await request("/api/auth/login", { body: { code: replacement.code } });
  assert.deepEqual((await request("/api/me", { token: laptop.token })).squads, before.squads);
  console.log("Optional-login API checks passed: guest compatibility, existing squads/bank/leagues, independent devices, code hashing/replacement, invalid codes, logout, expiry, and rate limiting.");
} finally {
  await runtime.dispose();
}
