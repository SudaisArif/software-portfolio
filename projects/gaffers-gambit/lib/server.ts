import { env } from "cloudflare:workers";
import { questions, type Question } from "./questions";
import { questionSet } from "./selection";
import {
  matchAnswer,
  ROUND_MS,
  ROUND_COUNT,
  utcDay,
  edition,
  type RoundResult,
} from "./game";
export function db() {
  if (!env.DB) throw new Error("Database unavailable");
  return env.DB;
}
export type Run = {
  id: string;
  owner: string;
  day: string;
  mode: string;
  daily_key: string | null;
  question_ids: string;
  answers: string;
  round: number;
  phase: string;
  deadline: number;
  score: number;
  created_at: number;
  finished_at: number | null;
  name: string | null;
  published: number;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export function identity(req: Request) {
  const c = req.headers
    .get("cookie")
    ?.match(/(?:^|;\s*)gg_player=([a-f0-9]{64})(?:;|$)/)?.[1];
  return c ?? null;
}
export function newIdentity() {
  return (
    crypto.randomUUID().replaceAll("-", "") +
    crypto.randomUUID().replaceAll("-", "")
  );
}
export function json(
  data: unknown,
  status = 200,
  cookie?: string,
  req?: Request,
) {
  const headers = new Headers({
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  if (cookie)
    headers.set(
      "Set-Cookie",
      `gg_player=${cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000${req && new URL(req.url).protocol === "https:" ? "; Secure" : ""}`,
    );
  return new Response(JSON.stringify(data), { status, headers });
}
export async function readBody(req: Request) {
  const origin = req.headers.get("origin");
  if (origin && origin !== new URL(req.url).origin)
    throw new ApiError(403, "Please play from the game website.");
  if (!req.headers.get("content-type")?.includes("application/json"))
    throw new ApiError(415, "Expected JSON.");
  const raw = await req.text();
  if (raw.length > 4096) throw new ApiError(413, "That request is too large.");
  try {
    const body = JSON.parse(raw);
    if (!body || typeof body !== "object" || Array.isArray(body))
      throw new Error();
    return body;
  } catch {
    throw new ApiError(400, "Invalid request.");
  }
}
export async function limit(req: Request, kind: string, max: number) {
  const ip =
    identity(req) ?? req.headers.get("cf-connecting-ip") ?? crypto.randomUUID();
  const hour = Math.floor(Date.now() / 3600000);
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`${ip}:${hour}`),
  );
  const hash = Array.from(new Uint8Array(bytes), (x) =>
    x.toString(16).padStart(2, "0"),
  ).join("");
  const key = `${kind}:${hash}`;
  const row = await db()
    .prepare(
      "INSERT INTO rate_limits (key,count,expires) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1 RETURNING count",
    )
    .bind(key, Date.now() + 7200000)
    .first<{ count: number }>();
  if ((row?.count ?? 0) > max)
    throw new ApiError(
      429,
      "A lot of football in one sitting. Please try again in the next hour.",
    );
}
const packCache = new Map<string, Question[]>();
async function dailyPack(day: string): Promise<Question[]> {
  const cached = packCache.get(day);
  if (cached) return cached;
  let row = await db()
    .prepare("SELECT payload FROM daily_packs WHERE day=?")
    .bind(day)
    .first<{ payload: string }>();
  if (!row) {
    const previous = await db()
      .prepare(
        "SELECT payload FROM daily_packs WHERE day<? ORDER BY day DESC LIMIT 7",
      )
      .bind(day)
      .all<{ payload: string }>();
    const packs = previous.results.map(
      (p) => JSON.parse(p.payload) as Question[],
    );
    const ids = questionSet(`${day}:bank-v3-moderate`, {
      recentIds: packs.flatMap((pack) => pack.map((q) => q.id)),
      recentFamilies: packs
        .slice(0, 2)
        .flatMap((pack) =>
          pack.map(
            (q) =>
              questions.find((current) => current.id === q.id)?.family ?? q.id,
          ),
        ),
    });
    const selected = ids.map((id) => questions.find((q) => q.id === id)!);
    await db()
      .prepare("INSERT OR IGNORE INTO daily_packs(day,payload) VALUES(?,?)")
      .bind(day, JSON.stringify(selected))
      .run();
    row = await db()
      .prepare("SELECT payload FROM daily_packs WHERE day=?")
      .bind(day)
      .first<{ payload: string }>();
  }
  if (!row)
    throw new ApiError(503, "Today’s questions are warming up. Try again.");
  const pack = JSON.parse(row.payload) as Question[];
  if (packCache.size > 8) packCache.clear();
  packCache.set(day, pack);
  return pack;
}
async function currentQuestion(run: Run) {
  const ids = JSON.parse(run.question_ids) as string[];
  const bank = run.mode === "daily" ? await dailyPack(run.day) : questions;
  return bank.find((q) => q.id === ids[run.round]);
}
export async function state(run: Run) {
  const q = await currentQuestion(run);
  return {
    id: run.id,
    day: run.day,
    edition: edition(run.day),
    mode: run.mode,
    round: run.round,
    phase: run.phase,
    deadline: run.deadline,
    serverNow: Date.now(),
    score: run.score,
    answers: JSON.parse(run.answers),
    question:
      run.phase === "question" && q
        ? {
            id: q.id,
            category: q.category,
            difficulty: q.difficulty,
            prompt: q.prompt,
            scope: q.scope,
          }
        : null,
    name: run.name,
    published: !!run.published,
  };
}
export async function getRun(id: string, owner: string) {
  if (!/^[a-f0-9-]{36}$/.test(id)) throw new ApiError(400, "Invalid match.");
  const run = await db()
    .prepare("SELECT * FROM runs WHERE id=? AND owner=?")
    .bind(id, owner)
    .first<Run>();
  if (!run)
    throw new ApiError(404, "This match could not be found on this browser.");
  return run;
}
export async function answer(run: Run, input: string, expectedRound: number) {
  if (expectedRound !== run.round || run.phase !== "question") return run;
  const q = await currentQuestion(run);
  if (!q) throw new ApiError(503, "This question is unavailable.");
  const expired = Date.now() > run.deadline + 1500;
  const picked = expired ? null : matchAnswer(input, q.answers);
  const tier = picked?.tier ?? 0;
  const result: RoundResult = {
    questionId: q.id,
    prompt: q.prompt,
    input: input.slice(0, 100),
    name: picked?.name ?? null,
    points: tier * 20,
    tier,
    fact: picked?.fact ?? "",
    reason: expired
      ? "Time’s up"
      : input.trim()
        ? "Not in this answer set"
        : "Passed",
    source: q.source,
    example: !picked
      ? { name: q.answers[0].name, tier: q.answers[0].tier }
      : null,
  };
  const answers = [...JSON.parse(run.answers), result];
  const phase = run.round === ROUND_COUNT - 1 ? "finished" : "reveal";
  await db()
    .prepare(
      "UPDATE runs SET answers=?,score=score+?,phase=?,finished_at=? WHERE id=? AND round=? AND phase='question'",
    )
    .bind(
      JSON.stringify(answers),
      result.points,
      phase,
      phase === "finished" ? Date.now() : null,
      run.id,
      run.round,
    )
    .run();
  return getRun(run.id, run.owner);
}
export async function start(owner: string, mode: string) {
  const day = utcDay(),
    dailyKey = mode === "daily" ? `${owner}:${day}` : null;
  if (dailyKey) {
    const old = await db()
      .prepare("SELECT * FROM runs WHERE daily_key=?")
      .bind(dailyKey)
      .first<Run>();
    if (old) return old;
  }
  if (Math.random() < 0.03)
    await db()
      .prepare(
        "DELETE FROM rate_limits WHERE key IN (SELECT key FROM rate_limits WHERE expires<? LIMIT 100)",
      )
      .bind(Date.now())
      .run();
  const id = crypto.randomUUID();
  // The owner/created_at index keeps this bounded, even after many sessions.
  const previous =
    mode === "practice"
      ? await db()
          .prepare(
            "SELECT question_ids FROM runs WHERE owner=? ORDER BY created_at DESC LIMIT 4",
          )
          .bind(owner)
          .all<{ question_ids: string }>()
      : null;
  const previousIds =
    previous?.results.map((r) => JSON.parse(r.question_ids) as string[]) ?? [];
  const ids =
    mode === "daily"
      ? (await dailyPack(day)).map((q) => q.id)
      : questionSet(id, {
          recentIds: previousIds.flat(),
          recentFamilies: (previousIds[0] ?? []).map(
            (id) => questions.find((q) => q.id === id)?.family ?? id,
          ),
        });
  await db()
    .prepare(
      "INSERT OR IGNORE INTO runs(id,owner,day,mode,daily_key,question_ids,answers,round,phase,deadline,score,created_at,published) VALUES(?,?,?,?,?,?,'[]',0,'question',?,0,?,0)",
    )
    .bind(
      id,
      owner,
      day,
      mode,
      dailyKey,
      JSON.stringify(ids),
      Date.now() + ROUND_MS,
      Date.now(),
    )
    .run();
  const run = dailyKey
    ? await db()
        .prepare("SELECT * FROM runs WHERE daily_key=?")
        .bind(dailyKey)
        .first<Run>()
    : await getRun(id, owner);
  return run!;
}
export function handleError(e: unknown) {
  if (e instanceof ApiError) return json({ error: e.message }, e.status);
  console.error(
    "Game request failed",
    e instanceof Error ? e.message : "Unknown",
  );
  return json(
    {
      error:
        "The floodlights flickered. Please try again; your match is saved.",
    },
    503,
  );
}
