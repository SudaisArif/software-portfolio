import {
  db,
  identity,
  newIdentity,
  json,
  readBody,
  limit,
  start,
  state,
  getRun,
  answer,
  ApiError,
  handleError,
  type Run,
} from "@/lib/server";
import { ROUND_MS, utcDay } from "@/lib/game";
export async function GET(req: Request) {
  try {
    const owner = identity(req);
    if (!owner) return json({ game: null });
    const id = new URL(req.url).searchParams.get("id");
    const run = id
      ? await getRun(id, owner)
      : await db()
          .prepare("SELECT * FROM runs WHERE daily_key=?")
          .bind(`${owner}:${utcDay()}`)
          .first<Run>();
    return json({ game: run ? await state(run) : null });
  } catch (e) {
    return handleError(e);
  }
}
export async function POST(req: Request) {
  try {
    const body = await readBody(req);
    const owner = identity(req) ?? newIdentity();
    let run: Run;
    if (body.action === "start") {
      await limit(req, "start", 80);
      run = await start(owner, body.mode === "practice" ? "practice" : "daily");
    } else {
      if (!identity(req)) throw new ApiError(401, "Start a match first.");
      run = await getRun(String(body.id ?? ""), owner);
      if (body.action === "answer") {
        if (
          typeof body.answer !== "string" ||
          body.answer.length > 100 ||
          !Number.isInteger(body.round)
        )
          throw new ApiError(400, "Invalid answer.");
        run = await answer(run, body.answer, body.round);
      } else if (body.action === "next") {
        if (run.phase === "reveal" && body.round === run.round) {
          await db()
            .prepare(
              "UPDATE runs SET round=round+1,phase='question',deadline=? WHERE id=? AND round=? AND phase='reveal'",
            )
            .bind(Date.now() + ROUND_MS, run.id, run.round)
            .run();
          run = await getRun(run.id, owner);
        }
      } else if (body.action === "publish") {
        if (run.phase !== "finished" || run.mode !== "daily")
          throw new ApiError(400, "Finish the daily match first.");
        const name = String(body.name ?? "").trim();
        if (!/^[\p{L}\p{N} _.-]{2,20}$/u.test(name))
          throw new ApiError(
            400,
            "Use 2–20 letters, numbers, spaces, dots or underscores.",
          );
        if (/(?:nigg|fagg|hitler|nazi|cunt|fuck|shit)/i.test(name))
          throw new ApiError(400, "Choose another football name.");
        await limit(req, "publish", 15);
        await db()
          .prepare("UPDATE runs SET name=?,published=1 WHERE id=?")
          .bind(name, run.id)
          .run();
        run = await getRun(run.id, owner);
      } else if (body.action === "unpublish") {
        await db()
          .prepare("UPDATE runs SET published=0,name=NULL WHERE id=?")
          .bind(run.id)
          .run();
        run = await getRun(run.id, owner);
      } else throw new ApiError(400, "Unknown match action.");
    }
    return json({ game: await state(run) }, 200, owner, req);
  } catch (e) {
    return handleError(e);
  }
}
