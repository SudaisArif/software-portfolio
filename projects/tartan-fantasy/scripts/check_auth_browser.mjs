import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { money, restoreBanks, spendingLimit } from "../squad-finances.js";

const stored = new Map();
const context = createContext({
  assert, money, restoreBanks, spendingLimit,
  roster: JSON.parse(readFileSync(new URL("../data/players.json", import.meta.url), "utf8")),
  document: { querySelector: () => ({ addEventListener() {} }), addEventListener() {} },
  window: { addEventListener() {} }, location: { hash: "#leagues" },
  localStorage: { getItem: () => null, setItem: (key, value) => stored.set(key, value) },
  FormData: class { constructor(form) { this.values = form.values; } get(key) { return this.values[key]; } }
});
runInContext(readFileSync(new URL("../app.js", import.meta.url), "utf8").replace(/^import .*\n/, "").replace(/initialize\(\);\s*$/, ""), context);
await runInContext(`(async () => {
  data = { players: roster, playerById: new Map(roster.map(player => [player.id, player])), priceById: new Map(roster.map(player => [player.id, 6.5])), statsById: new Map(), priceReviewsById: new Map(), gameweeks: [] };
  showToast = () => {};
  renderPage = () => {};
  assert.ok(renderLeagues().includes('data-form="account-login"'));
  assert.ok(renderLeagues().includes('data-form="manager-setup"'));
  const team = { players: ["nicholas-macouzet", "miguel-larrainzar", "ian-kim", "rishi-kunderan", "idan-garten", "alex-popov"], bench: ["james-ashby", "thomas-thornton", "max-born"], captain: "idan-garten", viceCaptain: "ian-kim", chip: null, bank: 1.5 };
  preferences.manager = { id: "existing", token: "original-device", loginEnabled: false };
  preferences.teams = { 1: team };
  assert.ok(renderAccountAccess().includes('data-action="enable-login"'));
  assert.ok(!renderAccountAccess().includes('data-action="account-logout"'));
  apiRequest = async () => ({ code: "TF-ABCDEFGH-JKLMNPQR-STUVWXYZ-23456789", manager: { id: "existing", loginEnabled: true } });
  await manageAccount("enable-login");
  assert.equal(preferences.teams[1].bank, 1.5);
  assert.equal(preferences.manager.loginEnabled, true);
  assert.ok(renderAccountAccess().includes('data-action="account-logout"'));
  assert.ok(accountUi.code);
  const originalDashboard = loadLeagueDashboard;
  loadLeagueDashboard = async () => {};
  const paths = [];
  preferences.teams = { 12: team }; // An unrelated local draft on the second device.
  ui.draftPlayers = ["wrong-team"];
  apiRequest = async (path) => {
    paths.push(path);
    return { token: "second-device", manager: { id: "target", teamName: "Saved Team", loginEnabled: true }, squads: { 1: team, 7: team }, leagues: [{ code: "LEAGUE", name: "Saved League" }] };
  };
  await signInToTeam({ values: { code: "TF-ABCDEFGH-JKLMNPQR-STUVWXYZ-23456789" }, reset() {} });
  assert.equal(preferences.manager.id, "target");
  assert.equal(preferences.manager.token, "second-device");
  assert.equal(Object.keys(preferences.teams).join(','), '1,7');
  assert.equal(preferences.teams[7].bank, 1.5);
  assert.equal(ui.draftPlayers, null);
  assert.equal(accountUi.code, null);
  assert.equal(paths.join(','), '/api/auth/login'); // Never auto-upload a draft.
  const before = JSON.stringify(preferences);
  apiRequest = async () => { throw new Error("Invalid login code"); };
  await assert.rejects(signInToTeam({ values: { code: "wrong" } }));
  assert.equal(JSON.stringify(preferences), before);
  await manageAccount("account-logout"); // Network failure must keep the usable session.
  assert.equal(JSON.stringify(preferences), before);
  apiRequest = async () => ({ ok: true });
  await manageAccount("account-logout");
  assert.equal(preferences.manager, null);
  assert.equal(Object.keys(preferences.teams).length, 0);
  assert.equal(syncedGameweeks.size, 0);
  assert.equal(leagueUi.standings, null);
  // An old profile response must not sign out a newly signed-in account.
  loadLeagueDashboard = originalDashboard;
  preferences.manager = { id: "old", token: "old-token" };
  ui.route = "overview";
  let rejectOld;
  apiRequest = () => new Promise((resolve, reject) => { rejectOld = reject; });
  const pending = loadLeagueDashboard();
  preferences.manager = { id: "new", token: "new-token" };
  rejectOld(Object.assign(new Error("Expired"), { status: 401 }));
  await pending;
  assert.equal(preferences.manager.token, "new-token");
})()`, context);
for (const value of stored.values()) assert.ok(!value.includes("TF-ABCDEFGH"));
console.log("Browser sign-in checks passed: optional guest flow, login forms, no squad overwrite, secret not stored, failed login/logout, local cache cleanup, and stale-response protection.");
