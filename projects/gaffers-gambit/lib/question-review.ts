import type { Question } from "./question-types.ts";

// Difficulty means finding ONE valid answer in 25 seconds, not finding a
// 100-point answer. Famous names do not make an arbitrary statistic accessible.
export const retiredForAccessibility: Record<string, string> = {
  "pl-five-thousand-milestones":
    "Arbitrary goal numbers, with no useful route to an answer.",
  "three-reds-one-season":
    "Exact disciplinary totals require specialist statistical recall.",
  "fourteen-bookings-season":
    "Exact disciplinary totals require specialist statistical recall.",
  "eight-team-reds-season":
    "Exact disciplinary totals require specialist statistical recall.",
  "pl-away-winless-season":
    "An obscure season record rather than a familiar football category.",
  "english-title-two-clubs-managers": "Tiny, mostly historical intersection.",
  "hat-tricks-three-pl-clubs":
    "Requires combining several separate career records.",
  "pl-hat-trick-in-defeat":
    "Too narrow a four-person set for the main rotation.",
  "champions-straight-after-promotion":
    "Requires largely pre-Premier-League promotion history.",
  "all-four-english-tier-champions": "Specialist lower-division title history.",
  "hat-trick-single-digit-career": "Two unrelated statistical conditions.",
  "first-top-flight-in-pl-era":
    "Easy to confuse a Premier League debut with a first-ever top-flight season.",
  "pl-manager-award-no-title":
    "Award-plus-season-result intersection is too narrow.",
  "pl-player-award-early":
    "Old award-era slice adds recall burden without a new idea.",
  "ballon-80s":
    "Older era slice; broader and more recent awards remain available.",
  "wigan-2013": "Niche starting XI.",
  "greece-2004": "Niche starting XI.",
  "qpr-9320": "Niche starting XI.",
  "united-roma-7-1-scorers":
    "Exact scorers from a less widely remembered match.",
  "qatar-2022-stadiums": "Venue-name recall is a specialist round.",
  "euro-2004-grounds": "Venue-name recall is a specialist round.",
  "original-european-treble-clubs":
    "Three-competition intersection and obsolete tournament definitions.",
  "old-european-cup-only":
    "Replaced by the broader European champions question.",
  "intl-wc-final-referees": "Referee-name recall is a specialist round.",
  "intl-wc-first-semis-1990":
    "First-ever qualification and old format exceptions are unnecessarily fiddly.",
  "intl-brazil-first-group-defeats":
    "First versus second group stages creates a historical trap.",
  "intl-wc-conceded-eight": "An obscure scoreline threshold.",
  "intl-wc-twenty-appearances":
    "An exact appearance threshold adds unnecessary statistical recall.",
  "intl-wc-ucl-winning-finals-double":
    "Same-year and actual-final-appearance intersection is too narrow.",
  "intl-wc-opening-goal":
    "Exact tournament-opening goals require specialist recall.",
  "intl-wc-own-goals-2018":
    "Single-tournament own-goal credits are too specific.",
  "intl-u17-golden-ball-1999-2017":
    "Age-group award history is specialist material.",
  "intl-u20-golden-ball-1999-2017":
    "Age-group award history is specialist material.",
  "intl-euro-golden-boots":
    "Replaced by top scorers including ties, without award tie-break traps.",
};

const approachable = new Set([
  "liverpool-2005",
  "united-1999",
  "england-squad-2006",
  "united-number-seven",
  "etoo-league-career-clubs",
  "arsenal-united-direct-transfers",
  "intl-wc-final-red-cards",
  "argentina-goals-2022",
]);
// Memorable events with recognisable entry points, used only occasionally.
const stretch = new Set([
  "ucl-debut-hat-tricks",
  "pl-four-assists-match",
  "two-own-goals-match",
  "bottom-christmas-survivors",
  "fa-cup-outside-top-flight",
]);
const moderate = new Set([
  "seven-pl-red-cards",
  "eight-goal-pl-winning-margin",
  "ucl-finalists-without-win-2024",
]);
export function reviewQuestion(q: Question): Question {
  if (retiredForAccessibility[q.id]) return { ...q, active: false };
  const difficulty = stretch.has(q.id)
    ? "Proper nerd"
    : approachable.has(q.id)
      ? "Open goal"
      : moderate.has(q.id) || q.difficulty === "Proper nerd"
        ? "Match sharp"
        : q.difficulty;
  return { ...q, difficulty };
}
