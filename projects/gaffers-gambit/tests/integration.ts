import assert from "node:assert/strict";
import { questions } from "../lib/questions.ts";
const origin = "http://127.0.0.1:5173";
let cookie = "";
async function call(
  path: string,
  body?: unknown,
  options: { cookie?: string; origin?: string; status?: number } = {},
) {
  const res = await fetch(origin + path, {
    method: body ? "POST" : "GET",
    headers: {
      "Content-Type": "application/json",
      Origin: options.origin ?? origin,
      Cookie: options.cookie ?? cookie,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const raw = await res.text();
  let data: any;
  try {
    data = JSON.parse(raw);
  } catch {
    data = { error: raw };
  }
  assert.equal(res.status, options.status ?? 200, JSON.stringify(data));
  const sc = res.headers.get("set-cookie");
  if (sc && !options.cookie) cookie = sc.split(";")[0];
  return data;
}
let g = (await call("/api/game", { action: "start", mode: "daily" })).game;
assert.equal(g.round, 0);
assert.equal(g.phase, "question");
assert.ok(g.question && !("answers" in g.question));
assert.ok(!JSON.stringify(g).includes("question_ids"));
let repeat = (await call("/api/game", { action: "start", mode: "daily" })).game;
assert.equal(repeat.id, g.id, "Daily resumes");
assert.equal(repeat.deadline, g.deadline, "Timer cannot reset");
await call(`/api/game?id=${g.id}`, undefined, {
  cookie: "gg_player=" + "a".repeat(64),
  status: 404,
});
await call(
  "/api/game",
  { action: "answer", id: g.id, round: 0, answer: "Henry" },
  { origin: "https://evil.invalid", status: 403 },
);
await call(
  "/api/game",
  { action: "publish", id: g.id, name: "Too early" },
  { status: 400 },
);
for (let i = 0; i < 7; i++) {
  const q = questions.find((q) => q.id === g.question.id)!;
  const pick = q.answers.find((a) => a.tier === 5)!;
  const body = {
    action: "answer",
    id: g.id,
    round: i,
    answer: pick.name,
    score: 999999,
  };
  const [one, two] = await Promise.all([
    call("/api/game", body),
    call("/api/game", body),
  ]);
  g = one.game;
  assert.equal(g.score, (i + 1) * 100, "Server score ignores claimed score");
  assert.equal(g.answers.length, i + 1, "Concurrent replay not double counted");
  assert.equal(two.game.score, g.score);
  assert.equal(g.answers.at(-1).name, pick.name);
  const check = (await call("/api/game?id=" + g.id)).game;
  assert.equal(check.score, g.score, "Persistence");
  if (i < 6) {
    const nextBody = { action: "next", id: g.id, round: i };
    const [a, b] = await Promise.all([
      call("/api/game", nextBody),
      call("/api/game", nextBody),
    ]);
    g = a.game;
    assert.equal(g.round, i + 1);
    assert.equal(b.game.round, i + 1);
  }
}
assert.equal(g.score, 700);
assert.equal(g.phase, "finished");
await call(
  "/api/game",
  { action: "publish", id: g.id, name: "<script>" },
  { status: 400 },
);
g = (
  await call("/api/game", {
    action: "publish",
    id: g.id,
    name: "QA Test Gaffer",
  })
).game;
assert.equal(g.published, true);
let board = await call("/api/leaderboard");
assert.ok(board.rows.find((r: any) => r.id === g.id && r.score === 700));
assert.ok(!JSON.stringify(board).includes("owner"));
await call("/api/report", {
  id: g.id,
  questionId: g.answers[0].questionId,
  note: "Automated test: review workflow is connected.",
});
await call("/api/game", { action: "unpublish", id: g.id });
board = await call("/api/leaderboard");
assert.ok(!board.rows.find((r: any) => r.id === g.id));
const practice = (
  await call("/api/game", { action: "start", mode: "practice" })
).game;
assert.notEqual(practice.id, g.id);
assert.equal(practice.mode, "practice");
const miss = (
  await call("/api/game", {
    action: "answer",
    id: practice.id,
    round: 0,
    answer: "This answer does not exist",
  })
).game;
assert.equal(miss.score, 0);
assert.equal(miss.answers[0].tier, 0);
assert.ok(miss.answers[0].example);
const practiceHistory: string[][] = [];
for (let match = 0; match < 5; match++) {
  let training = (
    await call("/api/game", { action: "start", mode: "practice" })
  ).game;
  const seen: string[] = [];
  for (let round = 0; round < 7; round++) {
    const q = questions.find((q) => q.id === training.question.id)!;
    assert.notEqual(q.active, false);
    seen.push(q.id);
    assert.ok(
      !practiceHistory.flat().includes(q.id),
      "Server uses the guest’s recent-question history",
    );
    const pick = q.answers.find((a) => a.tier === 5)!;
    training = (
      await call("/api/game", {
        action: "answer",
        id: training.id,
        round,
        answer: pick.name,
      })
    ).game;
    assert.equal(training.answers.at(-1).fact, pick.fact);
    if (round < 6)
      training = (
        await call("/api/game", { action: "next", id: training.id, round })
      ).game;
  }
  assert.equal(training.score, 700);
  const selected = seen.map((id) => questions.find((q) => q.id === id)!);
  assert.ok(new Set(selected.map((q) => q.topic)).size >= 5);
  assert.equal(selected[0].difficulty, "Open goal");
  assert.equal(
    selected.filter((q) => q.difficulty === "Match sharp").length,
    4,
  );
  assert.ok(selected.filter((q) => q.difficulty === "Proper nerd").length <= 1);
  practiceHistory.unshift(seen);
  practiceHistory.splice(4);
}
console.log(
  "PASS: five complete practice matches, moderate difficulty budgets, varied themes, facts/scoring, and four-match cooldown.",
);
console.log(
  "PASS: full 700-point match, persistence, daily lock, concurrent replay, score tampering, ownership, CSRF, leaderboard publish/remove, report, invalid answer and practice.",
);
const timings: number[] = [];
await Promise.all(
  Array.from({ length: 40 }, async () => {
    const start = performance.now();
    const r = await fetch(origin + "/api/leaderboard");
    assert.equal(r.status, 200);
    timings.push(performance.now() - start);
  }),
);
timings.sort((a, b) => a - b);
console.log(
  `PASS: 40 simultaneous local leaderboard reads; p50 ${Math.round(timings[20])}ms, p95 ${Math.round(timings[38])}ms. This is a local smoke test, not production capacity certification.`,
);

const timed = (await call("/api/game", { action: "start", mode: "practice" }))
  .game;
const tq = questions.find((q) => q.id === timed.question.id)!;
console.log("Checking a real expired 25-second deadline…");
await new Promise((r) => setTimeout(r, 26700));
const expired = (
  await call("/api/game", {
    action: "answer",
    id: timed.id,
    round: 0,
    answer: tq.answers[0].name,
  })
).game;
assert.equal(expired.score, 0);
assert.equal(expired.answers[0].reason, "Time’s up");
console.log("PASS: a valid answer after expiry scores zero.");
