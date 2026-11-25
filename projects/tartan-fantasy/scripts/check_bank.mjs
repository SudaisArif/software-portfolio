import assert from "node:assert/strict";
import { money, restoreBanks, spendingLimit, squadValue } from "../squad-finances.js";

const team = { gameweek: 1, players: ["a", "b", "c", "d", "e", "f"], bench: ["g", "h", "i"] };
const ids = [...team.players, ...team.bench];
const initialPrices = Object.fromEntries(ids.map((id) => [id, 6.5]));
const bank = money(spendingLimit(null, initialPrices) - squadValue(team, initialPrices));
assert.equal(bank, 1.5);
const owned = { ...team, bank };
const raisedPrices = Object.fromEntries(ids.map((id, i) => [id, i === 8 ? 6.6 : 6.8]));
assert.equal(squadValue(owned, raisedPrices), 61);
assert.equal(spendingLimit(owned, raisedPrices), 62.5);
assert.equal(money(spendingLimit(owned, raisedPrices) - squadValue(owned, raisedPrices)), 1.5);
const belowCap = { ...initialPrices, a: 7 };
assert.equal(spendingLimit(owned, belowCap), 60.5);
const fallenPrices = Object.fromEntries(ids.map((id) => [id, 6]));
assert.equal(spendingLimit(owned, fallenPrices), 55.5);
assert.equal(money(spendingLimit(owned, fallenPrices) - squadValue(owned, fallenPrices)), 1.5);

// Buying a player for 1.0 more consumes cash once; later savings use the
// current squad, so movements of already-sold players cannot create cash.
raisedPrices.j = 7.8;
const transferred = { ...owned, players: ["j", ...team.players.slice(1)] };
transferred.bank = money(spendingLimit(owned, raisedPrices) - squadValue(transferred, raisedPrices));
assert.equal(transferred.bank, 0.5);
raisedPrices.a = 12.5;
raisedPrices.j = 7.3;
for (let i = 0; i < 5; i++) {
  transferred.bank = money(spendingLimit(transferred, raisedPrices) - squadValue(transferred, raisedPrices));
  assert.equal(transferred.bank, 0.5);
}
const carried = { ...transferred, gameweek: 7 };
assert.equal(spendingLimit(carried, raisedPrices), spendingLimit(transferred, raisedPrices));

const legacyPrices = Object.fromEntries(ids.map((id, i) => [id, i === 8 ? 6.6 : 6.8]));
const reviewsById = Object.fromEntries(ids.map((id, i) => [id, [{ throughGameweek: 3, move: i === 8 ? 0.1 : 0.3 }]]));
const restored = restoreBanks([team, { ...team, gameweek: 4 }], { prices: legacyPrices, reviewsById });
assert.deepEqual(restored.map((entry) => entry.bank), [1.5, 1.5]);
assert.equal(spendingLimit(restored.at(-1), legacyPrices), 62.5);
assert.equal(restoreBanks([{ ...team, bank: 0 }], { prices: legacyPrices, reviewsById })[0].bank, 0);
assert.equal(restoreBanks([{ ...team, gameweek: 4, bank: null }], { prices: initialPrices, reviewsById: {} })[0].bank, 1.5);
console.log("Bank checks passed: 58.5 + 1.5, rises above/below 60, falls, transfers, repeated saves, carryover, and legacy reconstruction.");

// Exercise browser state handling too: normalization, copied gameweeks,
// profile reloads, successful saves, and rejected saves must preserve cash.
const { readFile } = await import("node:fs/promises");
const { createContext, runInContext } = await import("node:vm");
const roster = JSON.parse(await readFile(new URL("../data/players.json", import.meta.url), "utf8"));
const context = createContext({
  money, restoreBanks, spendingLimit, assert, roster,
  document: { querySelector: () => ({ addEventListener() {} }), addEventListener() {} },
  window: { addEventListener() {} }, location: { hash: "" },
  localStorage: { getItem: () => null, setItem() {} },
});
const source = await readFile(new URL("../app.js", import.meta.url), "utf8");
runInContext(source.replace(/^import .*\n/, "").replace(/initialize\(\);\s*$/, ""), context);
await runInContext(`(async () => {
  const players = ["nicholas-macouzet", "miguel-larrainzar", "ian-kim", "rishi-kunderan", "idan-garten", "alex-popov"];
  const bench = ["james-ashby", "thomas-thornton", "max-born"];
  const selected = [...players, ...bench];
  data = {
    players: roster, playerById: new Map(roster.map(player => [player.id, player])),
    priceById: new Map(roster.map(player => [player.id, 6.5])),
    priceReviewsById: new Map(), statsById: new Map()
  };
  const team = { players, bench, captain: "idan-garten", viceCaptain: "ian-kim", chip: null, bank: 1.5 };
  applyManagerProfile({ manager: { id: "manager", teamName: "Test" }, squads: { 1: team } });
  selected.forEach((id, i) => data.priceById.set(id, i === 8 ? 6.6 : 6.8));
  assert.equal(ensureTeam(4).bank, 1.5);
  assert.equal(transferBudget(4), 62.5);
  data.priceById.set("kieran-raker", 7.8);
  ui.gameweek = 4;
  ui.draftGameweek = 4;
  ui.draftPlayers = [players[0], "kieran-raker", ...players.slice(2)];
  ui.draftBench = [...bench];
  showToast = () => {};
  apiRequest = async () => ({ bank: 0.5 });
  await saveTransfers();
  assert.equal(preferences.teams[4].bank, 0.5);
  assert.equal(ensureTeam(7).bank, 0.5);
  assert.equal(transferBudget(7), 62.5);
  data.priceById.set("kieran-raker", 7.3);
  assert.equal(transferBudget(7), 62);
  ui.draftPlayers = [...players];
  apiRequest = async () => { throw new Error("Rejected"); };
  await saveTransfers();
  assert.equal(preferences.teams[4].bank, 0.5);
  assert.equal(preferences.teams[4].players[1], "kieran-raker");
  // An unsaved suggested team does not earn money before a first API save.
  preferences.teams = { 1: team };
  syncedGameweeks = new Set();
  assert.equal(transferBudget(1), 60);
})()`, context);
console.log("Browser bank checks passed: profiles, normalization, gameweek carryover, transfer saves, rollback, and unsaved teams.");
