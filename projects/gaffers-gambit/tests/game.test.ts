import test from "node:test";
import assert from "node:assert/strict";
import { normalize, matchAnswer, edition, utcDay, TIERS } from "../lib/game.ts";
import { questions } from "../lib/questions.ts";
import { questionSet } from "../lib/selection.ts";
import { retiredForAccessibility } from "../lib/question-review.ts";
import { launchUpdates } from "../lib/questions-launch-review.ts";
test("unicode and punctuation normalize consistently", () => {
  assert.equal(normalize("José O’Shea"), normalize("Jose O Shea"));
  assert.equal(normalize("Ødegaard"), "odegaard");
});
test("accepts aliases and one unambiguous typo, rejects guesses and ambiguous surnames", () => {
  const a = [
    { id: "1", name: "Thierry Henry", aliases: ["Henry"] },
    { id: "2", name: "Ashley Cole", aliases: [] },
    { id: "3", name: "Joe Cole", aliases: [] },
  ];
  assert.equal(matchAnswer("henri", a)?.id, "1");
  assert.equal(matchAnswer("THIERRY HENRY", a)?.id, "1");
  assert.equal(matchAnswer("cole", a), null);
  assert.equal(matchAnswer("Arsenal", a), null);
  assert.equal(matchAnswer("", a), null);
  assert.equal(matchAnswer("Thierry", a), null);
});
test("ambiguous fuzzy match is never guessed", () =>
  assert.equal(
    matchAnswer("baker", [
      { id: "a", name: "baler", aliases: [] },
      { id: "b", name: "biker", aliases: [] },
    ]),
    null,
  ));
test("daily changes at UTC midnight", () => {
  assert.equal(utcDay(Date.UTC(2026, 9, 27)), "2026-10-27");
  assert.equal(edition("2026-10-26"), 1);
  assert.equal(edition("2026-10-27"), 2);
});
test("bank is finite, sourced, uniquely identified and valid", () => {
  assert.ok(questions.filter((q) => q.active !== false).length >= 60);
  assert.equal(new Set(questions.map((q) => q.id)).size, questions.length);
  for (const q of questions) {
    assert.ok(q.answers.length >= 4, q.id);
    assert.equal(
      new Set(q.answers.map((a) => a.id)).size,
      q.answers.length,
      q.id,
    );
    assert.ok(q.topic && q.family, `Missing editorial metadata: ${q.id}`);
    assert.ok(q.source.url.startsWith("https://"));
    assert.ok(q.answers.some((a) => a.tier === 5));
    const seen = new Map<string, string>();
    for (const a of q.answers) {
      assert.ok(a.tier >= 1 && a.tier <= 5);
      assert.equal(TIERS[a.tier].points, a.tier * 20);
      assert.ok(a.fact);
      assert.equal(matchAnswer(a.name, q.answers)?.id, a.id);
      for (const s of [a.name, ...a.aliases]) {
        const n = normalize(s);
        assert.equal(
          matchAnswer(s, q.answers)?.id,
          a.id,
          `${q.id}: alias ${s}`,
        );
        assert.ok(
          !seen.has(n) || seen.get(n) === a.id,
          `${q.id} ambiguous ${s}`,
        );
        seen.set(n, a.id);
      }
    }
  }
  const familyTopics = new Map<string, string>();
  for (const q of questions.filter((q) => q.active !== false)) {
    assert.ok(
      !familyTopics.has(q.family!) || familyTopics.get(q.family!) === q.topic,
      `A family must stay within one theme: ${q.family}`,
    );
    familyTopics.set(q.family!, q.topic!);
  }
});

function assertBalanced(ids: string[]) {
  const qs = ids.map((id) => questions.find((q) => q.id === id)!);
  assert.equal(qs.length, 7);
  assert.equal(new Set(ids).size, 7);
  assert.equal(qs.filter((q) => q.difficulty === "Match sharp").length, 4);
  const stretch = qs.filter((q) => q.difficulty === "Proper nerd").length;
  assert.ok(stretch <= 1, "Never stack difficult rounds");
  assert.equal(
    qs.filter((q) => q.difficulty === "Open goal").length,
    3 - stretch,
  );
  assert.equal(
    qs[0].difficulty,
    "Open goal",
    "Start with an approachable prompt",
  );
  assert.equal(qs[1].difficulty, "Match sharp");
  assert.ok(new Set(qs.map((q) => q.topic)).size >= 5);
  for (const topic of new Set(qs.map((q) => q.topic)))
    assert.ok(qs.filter((q) => q.topic === topic).length <= 2);
  assert.equal(new Set(qs.map((q) => q.family)).size, 7);
  assert.ok(qs.every((q) => q.active !== false));
  return qs;
}

test("games have a moderate difficulty budget, varied themes, and only occasional stretch rounds", () => {
  let lineups = 0;
  let hardGames = 0;
  const topics = new Set<string>();
  for (let day = 0; day < 365; day++) {
    const seed = "2026-" + day;
    const ids = questionSet(seed);
    assert.deepEqual(questionSet(seed), ids);
    const qs = assertBalanced(ids);
    hardGames += qs.some((q) => q.difficulty === "Proper nerd") ? 1 : 0;
    assert.equal(
      qs.filter((q) => q.category === "Deep in the squad").length,
      0,
    );
    assert.ok(qs.filter((q) => q.topic === "lineups").length <= 1);
    lineups += qs.filter((q) => q.topic === "lineups").length;
    qs.forEach((q) => topics.add(q.topic!));
  }
  assert.ok(
    hardGames > 0 && hardGames < 365 * 0.4,
    "A stretch round is optional, not mandatory",
  );
  assert.ok(lineups < 365 * 0.3, "Lineups must remain an occasional round");
  assert.ok(
    topics.size >= 12,
    "The bank must cover more than the original handful of themes",
  );
});

test("practice avoids the previous four matches when a varied fresh draw is available", () => {
  const recent: string[][] = [];
  let overlaps = 0;
  for (let match = 0; match < 100; match++) {
    const history = {
      recentIds: recent.flat(),
      recentFamilies: (recent[0] ?? []).map(
        (id) => questions.find((q) => q.id === id)!.family!,
      ),
    };
    const ids = questionSet(`practice-${match}`, history);
    assertBalanced(ids);
    assert.deepEqual(questionSet(`practice-${match}`, history), ids);
    assert.ok(
      !ids.some((id) => recent[0]?.includes(id)),
      "Never repeat the previous match",
    );
    overlaps += ids.filter((id) => history.recentIds.includes(id)).length;
    assert.ok(
      ids.every(
        (id) =>
          !history.recentFamilies.includes(
            questions.find((q) => q.id === id)!.family!,
          ),
      ),
    );
    recent.unshift(ids);
    recent.splice(4);
  }
  assert.equal(
    overlaps,
    0,
    "Four-match question cooldown with the current bank",
  );
});

test("daily cooldown fallback never raises difficulty or recycles yesterday", () => {
  const recent: string[][] = [];
  for (let day = 0; day < 90; day++) {
    const ids = questionSet(`daily-history-${day}`, {
      recentIds: recent.flat(),
      recentFamilies: recent
        .slice(0, 2)
        .flat()
        .map((id) => questions.find((q) => q.id === id)!.family!),
    });
    assert.ok(!ids.some((id) => recent[0]?.includes(id)));
    assertBalanced(ids);
    recent.unshift(ids);
    recent.splice(7);
  }
});

test("specialist recall sets stay out of rotation but remain available to saved matches", () => {
  for (const id of Object.keys(retiredForAccessibility)) {
    const q = questions.find((q) => q.id === id)!;
    assert.ok(q, id);
    assert.equal(q.active, false, id);
    assert.ok(q.answers.length >= 4, "Retirement must not break a saved match");
  }
  const all = questions.filter((q) => q.active !== false).map((q) => q.id);
  // Even an exhausted history must not bring back retired questions or stack hard ones.
  for (let n = 0; n < 50; n++)
    assertBalanced(
      questionSet(`exhausted-${n}`, {
        recentIds: all,
        recentFamilies: questions.map((q) => q.family!),
      }),
    );
});

test("broader replacement questions accept familiar answers and joint scoring leaders", () => {
  const match = (id: string, name: string) =>
    matchAnswer(name, questions.find((q) => q.id === id)!.answers);
  assert.equal(
    match("european-champion-clubs-2026", "PSG")?.name,
    "Paris Saint-Germain",
  );
  assert.equal(
    match("uefa-cup-champion-clubs-2026", "Ipswich")?.name,
    "Ipswich Town",
  );
  assert.equal(
    match("euro-top-scorers-2000-2024", "Schick")?.name,
    "Patrik Schick",
  );
  assert.equal(
    match("euro-top-scorers-2000-2024", "Balotelli")?.name,
    "Mario Balotelli",
  );
  assert.equal(match("euro-top-scorers-2000-2024", "Kane")?.name, "Harry Kane");
  assert.equal(match("euro-top-scorers-2000-2024", "Messi"), null);
});

test("launch refresh accepts recent qualifiers without rewriting saved answer sets", () => {
  for (const update of launchUpdates) {
    const old = questions.find((q) => q.id === update.original)!;
    const current = questions.find((q) => q.id === update.id)!;
    assert.equal(old.active, false);
    assert.equal(current.active, true);
    assert.equal(current.family, old.family);
    assert.equal(current.difficulty, old.difficulty);
    for (const addition of update.additions) {
      assert.equal(
        matchAnswer(addition.name, current.answers)?.id,
        addition.id,
      );
      assert.equal(matchAnswer(addition.name, old.answers), null);
    }
  }
  const double = questions.find(
    (q) => q.id === "intl-ballon-world-cup-double-2026",
  )!;
  assert.equal(matchAnswer("Harry Kane", double.answers), null);
});

test("historical scopes and ambiguous names cannot accept tempting wrong answers", () => {
  const answer = (id: string, name: string) =>
    matchAnswer(name, questions.find((q) => q.id === id)!.answers);
  assert.equal(answer("world-record-transfers-1992-2017", "Ronaldo"), null);
  assert.equal(
    answer("world-record-transfers-1992-2017", "R9")?.name,
    "Ronaldo Nazário",
  );
  assert.equal(
    answer("world-record-transfers-1992-2017", "CR7")?.name,
    "Cristiano Ronaldo",
  );
  assert.equal(
    answer("english-real-madrid-2024", "Trent Alexander-Arnold"),
    null,
  );
  assert.equal(answer("united-number-seven", "George Best"), null);
  assert.equal(answer("etoo-league-career-clubs", "Espanyol"), null);
  assert.equal(answer("ucl-debut-hat-tricks", "Lewandowski"), null);
  assert.equal(answer("original-european-treble-clubs", "Barcelona"), null);
  assert.equal(answer("arsenal-united-direct-transfers", "Andy Cole"), null);
});
