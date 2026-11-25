import {
  db,
  identity,
  json,
  readBody,
  limit,
  ApiError,
  handleError,
  getRun,
} from "@/lib/server";
export async function POST(req: Request) {
  try {
    const body = await readBody(req),
      owner = identity(req);
    if (!owner) throw new ApiError(401, "Play a match first.");
    await limit(req, "report", 10);
    const run = await getRun(String(body.id ?? ""), owner);
    const result = JSON.parse(run.answers).find(
      (a: { questionId: string }) => a.questionId === body.questionId,
    );
    if (!result) throw new ApiError(400, "Play this question first.");
    const note = String(body.note ?? "")
      .trim()
      .slice(0, 500);
    if (note.length < 8)
      throw new ApiError(400, "Add a little detail or a source link.");
    await db()
      .prepare(
        "INSERT INTO reports(id,question_id,answer,note,created_at) VALUES(?,?,?,?,?)",
      )
      .bind(
        crypto.randomUUID(),
        result.questionId,
        result.input,
        note,
        Date.now(),
      )
      .run();
    return json({ ok: true });
  } catch (e) {
    return handleError(e);
  }
}
