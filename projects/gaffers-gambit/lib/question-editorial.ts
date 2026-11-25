import type { Question, Topic } from "./question-types.ts";

// Keep retired sets resolvable for saved matches; only new draws use active sets.
const featuredLineups = new Set([
  "liverpool-2005",
  "united-1999",
  "wigan-2013",
  "greece-2004",
  "qpr-9320",
  "england-squad-2006",
]);
export function annotateOriginal(q: Question): Question {
  let topic: Topic = "club-history";
  let family = q.id;
  let active = true;
  if (
    ["Famous nights", "Deep in the squad"].includes(q.category) ||
    q.id.startsWith("england-squad")
  ) {
    topic = "lineups";
    family = "remember-the-team";
    active = featuredLineups.has(q.id);
  } else if (q.id.includes("manager")) {
    topic = "managers";
    family = q.id.includes("award")
      ? "pl-manager-award"
      : "pl-winning-managers";
  } else if (q.id === "pl-scoring-keepers" || q.id === "pl-five-goals") {
    topic = "records";
  } else if (q.id.startsWith("pl-ten-goals")) {
    topic = "goals";
    family = "pl-season-goals";
  } else if (q.category === "Individual honours" || /boot|glove/.test(q.id)) {
    topic = "awards";
    family = q.id.startsWith("ballon")
      ? "ballon-winners"
      : q.id.startsWith("pl-player-award")
        ? "pl-player-award"
        : /pl-.*boot/.test(q.id)
          ? "pl-golden-boot"
          : q.id;
    if (["pl-boot-90s", "pl-boot-00s"].includes(q.id)) active = false;
  } else if (q.category === "World Cup goals") {
    topic = "goals";
    family = "world-cup-team-scorers";
  } else if (q.category === "Scoreline folklore") {
    topic = "goals";
    family = "famous-rout-scorers";
  } else if (q.category === "Away days") {
    topic = "grounds";
  } else if (q.id === "world-cup-winners" || q.id === "euro-winning-nations") {
    topic = "international";
    family = "international-winning-nations";
  } else if (q.id === "pl-clubs-2012" || q.id === "pl-founding-clubs") {
    family = "pl-season-membership";
    active = q.id === "pl-founding-clubs";
  }
  return { ...q, topic, family, active };
}
