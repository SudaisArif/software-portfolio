export const ROUND_MS = 25_000;
export const ROUND_COUNT = 7;
export const TIERS = [
  { name: "Off target", points: 0, color: "#b8bdb1", emoji: "⬛" },
  { name: "Tap-in", points: 20, color: "#b8bdb1", emoji: "⬜" },
  { name: "First team", points: 40, color: "#a6cda4", emoji: "🟩" },
  { name: "Cult hero", points: 60, color: "#7fcbd4", emoji: "🟦" },
  { name: "Streets remember", points: 80, color: "#c5ace8", emoji: "🟪" },
  { name: "Top bins", points: 100, color: "#f3b56d", emoji: "🟧" },
];
export function normalize(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/ø/g, "o")
    .replace(/ł/g, "l")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]/g, "");
}
export function distance(a: string, b: string): number {
  const d = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = d[0];
    d[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const old = d[j];
      d[j] = Math.min(
        d[j] + 1,
        d[j - 1] + 1,
        prev + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
      prev = old;
    }
  }
  return d[b.length];
}
export function matchAnswer<
  T extends { id: string; name: string; aliases: string[] },
>(input: string, answers: T[]): T | null {
  const s = normalize(input);
  if (!s) return null;
  const exact = answers.filter((a) =>
    [a.name, ...a.aliases].some((v) => normalize(v) === s),
  );
  if (exact.length === 1) return exact[0];
  if (exact.length > 1) return null;
  if (s.length < 5) return null;
  const fuzzy = answers.filter((a) =>
    [a.name, ...a.aliases].some((v) => {
      const n = normalize(v);
      return (
        n.length >= 5 &&
        Math.abs(n.length - s.length) <= 1 &&
        distance(s, n) === 1
      );
    }),
  );
  return fuzzy.length === 1 ? fuzzy[0] : null;
}
export function utcDay(now = Date.now()) {
  return new Date(now).toISOString().slice(0, 10);
}
export function edition(day: string) {
  return Math.max(
    1,
    Math.floor(
      (Date.parse(day + "T00:00:00Z") - Date.UTC(2026, 9, 26)) / 86400000,
    ) + 1,
  );
}
export function seededShuffle<T>(items: T[], seed: string): T[] {
  let h = 2166136261;
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  const result = [...items];
  for (let i = result.length - 1; i > 0; i--) {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    const j = (h >>> 0) % (i + 1);
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}
export type RoundResult = {
  questionId: string;
  prompt: string;
  input: string;
  name: string | null;
  points: number;
  tier: number;
  fact: string;
  reason: string;
  source: { label: string; url: string };
  example: { name: string; tier: number } | null;
};
export type GameState = {
  id: string;
  day: string;
  edition: number;
  mode: string;
  round: number;
  phase: string;
  deadline: number;
  serverNow: number;
  score: number;
  answers: RoundResult[];
  question: {
    id: string;
    category: string;
    difficulty: string;
    prompt: string;
    scope: string;
  } | null;
  name: string | null;
  published: boolean;
};
