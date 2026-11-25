import assert from "node:assert/strict";
import { testing } from "../worker/index.js";

assert.equal(testing.rawPoints("GK", {
  minutes: 90,
  goals: 1,
  assists: 1,
  cleanSheet: true,
  saves: 7,
  yellowCards: 1,
  bonus: 2
}), 18);
assert.equal(testing.rawPoints("FWD", { minutes: 30, goals: 1, redCards: 1 }), 2);
assert.equal(testing.rawPoints("DEF", { minutes: 39, cleanSheet: true }), 1);
assert.equal(testing.rawPoints("DEF", { minutes: 40, cleanSheet: true }), 6);
assert.equal(testing.rawPoints("MID", { minutes: 56, cleanSheet: false, opponentScore: 0 }), 3);
assert.equal(testing.rawPoints("GK", { minutes: 90, penaltiesSaved: 1 }), 7);
assert.equal(testing.impactSubPoints(1, { minutes: 20, started: false }), 2);
assert.equal(testing.impactSubPoints(1, { minutes: 19, started: false }), 1);
assert.equal(testing.impactSubPoints(1, { minutes: 30, started: true }), 1);
assert.deepEqual(testing.mergeStatRecord({
  penaltiesSaved: 1,
  manualOverrides: { minutes: 0, started: false, cleanSheet: false }
}, {
  minutes: 45,
  started: false,
  cleanSheet: true,
  penaltiesSaved: 0
}), {
  penaltiesSaved: 1,
  manualOverrides: { minutes: 0, started: false, cleanSheet: false },
  minutes: 0,
  started: false,
  cleanSheet: false,
  bonus: 0,
  ownGoals: 0,
  penaltiesMissed: 0
});

const reviewPlayers = [
  { id: "freshman", position: "FWD" },
  { id: "returner", position: "MID" }
];
const reviewReport = [
  { player_id: "freshman", career_rating: "0" },
  { player_id: "returner", career_rating: "60" }
];
const reviewStats = {
  "1": { freshman: { minutes: 10, goals: 1 } },
  "2": {},
  "3": {}
};
const reviewLive = { "1": { state: "final" }, "2": { state: "final" }, "3": { state: "final" } };
const reviewGameweeks = [1, 2, 3].map((gameweek) => ({ gameweek }));
const priceReview = testing.calculatePriceReviews(
  reviewPlayers,
  { freshman: 4, returner: 12.4 },
  reviewReport,
  reviewStats,
  reviewLive,
  reviewGameweeks
);
assert.equal(priceReview.reviewedThrough, 3);
assert.equal(priceReview.prices.freshman, 4.2);
assert.equal(priceReview.reviewsById.freshman[0].expected, 1.5);
assert.equal(priceReview.reviewsById.freshman[0].actual, 5);
assert.equal(priceReview.prices.returner, 12.1);
assert.equal(priceReview.reviewsById.returner[0].move, -0.3);
assert.equal(testing.calculatePriceReviews(
  reviewPlayers,
  { freshman: 4, returner: 12.4 },
  reviewReport,
  { "1": {}, "2": {} },
  reviewLive,
  reviewGameweeks
).reviewedThrough, 0);

const previous = {
  players_json: JSON.stringify(["a", "b", "c", "d", "e", "f", "g"]),
  bench_json: JSON.stringify(["h", "i", "j"])
};
const current = {
  players_json: JSON.stringify(["a", "b", "c", "d", "e", "k", "l"]),
  bench_json: JSON.stringify(["m", "n", "o"])
};
assert.equal(testing.transferCount(current, previous), 5);
assert.equal(testing.transferCount({
  players_json: JSON.stringify(["a", "b", "c", "d", "e", "f", "k"]),
  bench_json: JSON.stringify(["h", "i", "l"])
}, previous), 2);

const game = {
  gameID: "123",
  gameState: "final",
  home: { names: { seo: "carnegie-mellon" }, score: "2" },
  away: { names: { seo: "opponent" }, score: "0" }
};
assert.equal(testing.findCmuGame({ games: [{ game }] }), game);
const parsed = testing.parseNcaaBoxscore({
  teams: [{ teamId: 1, seoname: "carnegie-mellon" }],
  teamBoxscore: [{
    teamId: 1,
    playerStats: [{
      participated: true,
      firstName: "Idan",
      lastName: "Garten",
      minutesPlayed: "70",
      starter: true,
      goals: "1",
      assists: "1",
      shots: "3",
      shotsOnGoal: "2",
      saves: "0",
      goalie: { saves: "3" },
      penalties: { yellowCards: "1", redCards: "0" }
    }]
  }]
}, game, new Set(["idan-garten"]));
assert.equal(parsed["idan-garten"].goals, 1);
assert.equal(parsed["idan-garten"].assists, 1);
assert.equal(parsed["idan-garten"].cleanSheet, true);
assert.equal(parsed["idan-garten"].saves, 3);

console.log("Worker scoring and NCAA parser checks passed.");
