export type Topic =
  | "awards"
  | "goals"
  | "discipline"
  | "managers"
  | "world-cup"
  | "international"
  | "europe"
  | "careers"
  | "transfers"
  | "club-history"
  | "records"
  | "grounds"
  | "lineups";
export type Answer = {
  id: string;
  name: string;
  aliases: string[];
  tier: 1 | 2 | 3 | 4 | 5;
  fact: string;
};
export type Question = {
  id: string;
  category: string;
  difficulty: "Open goal" | "Match sharp" | "Proper nerd";
  prompt: string;
  scope: string;
  source: { label: string; url: string };
  answers: Answer[];
  topic?: Topic;
  family?: string;
  active?: boolean;
};
