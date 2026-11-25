import { db, json, handleError } from "@/lib/server";
import { utcDay, edition } from "@/lib/game";
export async function GET() {
  try {
    const day = utcDay();
    const rows = await db()
      .prepare(
        "SELECT id,name,score,finished_at FROM runs WHERE day=? AND mode='daily' AND published=1 AND phase='finished' ORDER BY score DESC,finished_at ASC LIMIT 50",
      )
      .bind(day)
      .all();
    const count = await db()
      .prepare(
        "SELECT COUNT(*) AS n FROM runs WHERE day=? AND mode='daily' AND published=1 AND phase='finished'",
      )
      .bind(day)
      .first<{ n: number }>();
    const res = json({
      day,
      edition: edition(day),
      rows: rows.results,
      total: count?.n ?? 0,
    });
    res.headers.set("Cache-Control", "public, max-age=15, s-maxage=30");
    return res;
  } catch (e) {
    return handleError(e);
  }
}
