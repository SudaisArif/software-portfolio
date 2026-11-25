import { questions } from "./questions.ts";
import type { Question } from "./question-types.ts";
import { seededShuffle, ROUND_COUNT } from "./game.ts";

export type SelectionHistory = {
  recentIds?: string[];
  recentFamilies?: string[];
};
type Quota = [number, number, number];
const levels = ["Open goal", "Match sharp", "Proper nerd"] as const;
const levelOf = (q: Question) => levels.indexOf(q.difficulty);

// A theme contributes one or two questions, with different editorial families.
// For a given difficulty combination, use the first suitable seeded choices.
function themeOptions(group: Question[]): Question[][] {
  const options: Question[][] = [];
  const combinations = new Set<string>();
  const add = (option: Question[]) => {
    const key = option.map(levelOf).sort().join(":");
    if (!combinations.has(key)) {
      combinations.add(key);
      options.push(option);
    }
  };
  for (const q of group) add([q]);
  for (let i = 0; i < group.length; i++) {
    for (let j = i + 1; j < group.length; j++) {
      if (group[i].family !== group[j].family) add([group[i], group[j]]);
    }
  }
  return options;
}

function balancedDraw(
  pool: Question[],
  topics: Question["topic"][],
  quota: Quota,
  minThemes: number,
): Question[] | null {
  const groups = topics
    .map((topic) => pool.filter((q) => q.topic === topic))
    .filter((group) => group.length);
  if (groups.length < minThemes) return null;
  const options = groups.map(themeOptions);
  const failed = new Set<string>();
  // Families belong to one theme (validated with the bank), so these counts
  // fully describe a state. Memoization bounds the work on sparse cooldown pools.
  const visit = (
    index: number,
    remaining: Quota,
    themes: number,
  ): Question[] | null => {
    const slots = remaining.reduce((a, b) => a + b, 0);
    if (!slots) return themes >= minThemes ? [] : null;
    if (
      index === groups.length ||
      themes + Math.min(slots, groups.length - index) < minThemes ||
      (groups.length - index) * 2 < slots
    )
      return null;
    const key = [index, ...remaining, themes].join(":");
    if (failed.has(key)) return null;
    for (const option of options[index]) {
      const next = [...remaining] as Quota;
      for (const q of option) next[levelOf(q)]--;
      if (next.some((count) => count < 0)) continue;
      const tail = visit(index + 1, next, themes + 1);
      if (tail) return [...option, ...tail];
    }
    const tail = visit(index + 1, remaining, themes);
    if (tail) return tail;
    failed.add(key);
    return null;
  };
  return visit(0, quota, 0);
}

export function questionSet(seed: string, history: SelectionHistory = {}) {
  const recent = new Set(history.recentIds ?? []);
  const families = new Set(history.recentFamilies ?? []);
  const allowLineup = seededShuffle(
    [true, false, false, false],
    seed + ":lineup",
  )[0];
  const allowStretch = seededShuffle(
    [true, false, false],
    seed + ":stretch",
  )[0];
  const eligible = questions.filter(
    (q) => q.active !== false && (q.topic !== "lineups" || allowLineup),
  );
  const topics = seededShuffle(
    [...new Set(eligible.map((q) => q.topic))],
    seed + ":themes",
  );
  const pool = topics.flatMap((topic) =>
    seededShuffle(
      eligible.filter((q) => q.topic === topic),
      seed + ":" + topic,
    ),
  );
  const fresh = pool.filter((q) => !recent.has(q.id));
  const recentOrder = history.recentIds ?? [];
  const oldestFirst = pool
    .filter((q) => recent.has(q.id))
    .sort((a, b) => recentOrder.indexOf(b.id) - recentOrder.indexOf(a.id));
  const previousGame = new Set(recentOrder.slice(0, ROUND_COUNT));
  const stages = [
    fresh.filter((q) => !families.has(q.family!)),
    fresh,
    [...fresh, ...oldestFirst.filter((q) => !previousGame.has(q.id))],
    [...fresh, ...oldestFirst],
  ];
  // Four moderate rounds, with either three approachable rounds or two plus
  // one optional stretch. Cooldown fallback NEVER increases difficulty.
  const quotas: Quota[] = allowStretch
    ? [
        [2, 4, 1],
        [3, 4, 0],
      ]
    : [[3, 4, 0]];
  for (const stage of stages) {
    for (const quota of quotas) {
      // Prefer seven themes, but do not force niche content just to fill a theme.
      for (const minThemes of [7, 6, 5]) {
        const chosen = balancedDraw(stage, topics, quota, minThemes);
        if (!chosen) continue;
        const shuffled = seededShuffle(chosen, seed + ":order");
        const opener = shuffled.find((q) => q.difficulty === "Open goal")!;
        const second = shuffled.find((q) => q.difficulty === "Match sharp")!;
        return [
          opener,
          second,
          ...shuffled.filter((q) => q !== opener && q !== second),
        ].map((q) => q.id);
      }
    }
  }
  throw new Error("Question bank cannot provide a balanced seven-round game");
}
