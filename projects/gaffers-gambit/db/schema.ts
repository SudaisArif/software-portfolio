import {
  sqliteTable,
  text,
  integer,
  index,
  uniqueIndex,
} from "drizzle-orm/sqlite-core";
export const runs = sqliteTable(
  "runs",
  {
    id: text("id").primaryKey(),
    owner: text("owner").notNull(),
    day: text("day").notNull(),
    mode: text("mode").notNull(),
    dailyKey: text("daily_key"),
    questionIds: text("question_ids").notNull(),
    answers: text("answers").notNull().default("[]"),
    round: integer("round").notNull().default(0),
    phase: text("phase").notNull().default("question"),
    deadline: integer("deadline").notNull(),
    score: integer("score").notNull().default(0),
    createdAt: integer("created_at").notNull(),
    finishedAt: integer("finished_at"),
    name: text("name"),
    published: integer("published").notNull().default(0),
  },
  (t) => [
    uniqueIndex("runs_daily_unique").on(t.dailyKey),
    index("runs_board").on(t.day, t.published, t.score),
    index("runs_owner").on(t.owner, t.createdAt),
  ],
);
export const rateLimits = sqliteTable(
  "rate_limits",
  {
    key: text("key").primaryKey(),
    count: integer("count").notNull(),
    expires: integer("expires").notNull(),
  },
  (t) => [index("rate_expiry").on(t.expires)],
);
export const reports = sqliteTable("reports", {
  id: text("id").primaryKey(),
  questionId: text("question_id").notNull(),
  answer: text("answer").notNull(),
  note: text("note").notNull(),
  createdAt: integer("created_at").notNull(),
});
export const dailyPacks = sqliteTable("daily_packs", {
  day: text("day").primaryKey(),
  payload: text("payload").notNull(),
});
