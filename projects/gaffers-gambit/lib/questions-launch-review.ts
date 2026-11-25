import type { Answer, Question } from "./question-types.ts";

type Update = {
  original: string;
  id: string;
  scope: string;
  source: Question["source"];
  additions: Answer[];
  facts?: Record<string, string>;
};
const answer = (
  name: string,
  tier: Answer["tier"],
  fact: string,
  aliases: string[],
): Answer => ({
  id: name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-$/g, ""),
  name,
  tier,
  fact,
  aliases,
});
const rodriAliases = [
  "Rodrigo",
  "Rodrigo Hernandez",
  "Rodrigo Hernandez Cascante",
];
const ballonSource = {
  label: "UEFA · Ballon d’Or winners",
  url: "https://www.uefa.com/ballondor/news/0292-1c27056169a7-bc88d1fdba43-1000--ballon-d-or-laureates-who-has-won-football-s-most-prestig/",
};

// Keep the original question and answer set available to saved matches. Generic
// headlines now include recent qualifying answers instead of a hidden old cutoff.
export const launchUpdates: Update[] = [
  {
    original: "pl-title-managers",
    id: "pl-title-managers-2026",
    scope:
      "1992/93–2025/26. Winning the old First Division alone does not count.",
    source: {
      label: "Premier League · Title-winning managers",
      url: "https://www.premierleague.com/en/news/4660971/every-premier-league-title-winning-manager-in-history",
    },
    additions: [
      answer("Arne Slot", 2, "Led Liverpool to the 2024/25 title.", ["Slot"]),
      answer("Mikel Arteta", 2, "Led Arsenal to the 2025/26 title.", [
        "Arteta",
      ]),
    ],
  },
  {
    original: "pl-manager-award",
    id: "pl-manager-award-2026",
    scope:
      "1993/94–2025/26. The Premier League’s own award, not the LMA award.",
    source: {
      label: "Premier League · Manager of the Season winners",
      url: "https://www.premierleague.com/en/news/3489644/barclays-manager-of-the-season-award",
    },
    additions: [
      answer(
        "Arne Slot",
        2,
        "Won the Premier League Manager of the Season award in 2024/25 with Liverpool.",
        ["Slot"],
      ),
      answer(
        "Mikel Arteta",
        2,
        "Won the Premier League Manager of the Season award in 2025/26 with Arsenal.",
        ["Arteta"],
      ),
    ],
  },
  {
    original: "pl-golden-glove",
    id: "pl-golden-glove-2026",
    scope: "2004/05–2025/26. Shared winners count.",
    source: {
      label: "Premier League · Golden Glove winners",
      url: "https://www.premierleague.com/en/news/1206130",
    },
    additions: [
      answer(
        "Matz Sels",
        4,
        "Shared the 2024/25 Golden Glove with David Raya, with 13 clean sheets for Nottingham Forest.",
        ["Sels"],
      ),
    ],
    facts: {
      "David Raya": "Won in 2023/24, shared in 2024/25 and won in 2025/26.",
    },
  },
  {
    original: "forty-year-old-pl-outfielders",
    id: "forty-year-old-pl-outfielders-2026",
    scope: "1992/93–2025/26. Goalkeepers excluded.",
    source: {
      label: "Premier League · Outfield players aged 40",
      url: "https://www.premierleague.com/en/news/4533009/brighton-midfielder-milner-joins-elite-group",
    },
    additions: [
      answer(
        "James Milner",
        1,
        "Played for Brighton against Manchester City on 7 January 2026, three days after turning 40.",
        ["Milner"],
      ),
    ],
  },
  {
    original: "european-cup-two-clubs-coaches",
    id: "european-cup-two-clubs-coaches-2026",
    scope: "1955/56–2025/26. Head coaches only.",
    source: {
      label: "UEFA · Champions League-winning coaches",
      url: "https://www.uefa.com/uefachampionsleague/news/0275-15407684c988-5b733e851bf5-1000--champions-league-winning-coaches-carlo-ancelotti-leads-th/",
    },
    additions: [
      answer(
        "Luis Enrique",
        2,
        "Won with Barcelona in 2015 and Paris Saint-Germain in 2025 and 2026.",
        ["Enrique", "Luis Enrique Martinez", "Lucho"],
      ),
    ],
  },
  {
    original: "two-own-goals-match",
    id: "two-own-goals-match-2026",
    scope: "1992/93–2025/26. Both own goals must be in the same match.",
    source: {
      label: "Premier League · Two own goals in one match",
      url: "https://www.premierleague.com/en/news/4187041/dawson-equals-unwanted-record-with-two-own-goals",
    },
    additions: [
      answer(
        "Craig Dawson",
        3,
        "Scored two own goals for Wolves against Everton on 4 December 2024.",
        ["Dawson"],
      ),
    ],
  },
  {
    original: "intl-ballon-premier-league-alumni",
    id: "intl-ballon-premier-league-alumni-2026",
    scope:
      "Ballon d’Or awards through 2026; Premier League appearances through 2025/26. The award can have been won at another club.",
    source: ballonSource,
    additions: [
      answer(
        "Rodri",
        1,
        "The 2024 Ballon d’Or winner played for Manchester City.",
        rodriAliases,
      ),
      answer(
        "Harry Kane",
        1,
        "The 2026 Ballon d’Or winner played for Tottenham in the Premier League.",
        ["Kane", "Harry Edward Kane"],
      ),
    ],
  },
  {
    original: "intl-ballon-world-cup-double",
    id: "intl-ballon-world-cup-double-2026",
    scope:
      "Competitive Ballon d’Or awards and men’s World Cups through 2026. Different years count; being in the winning World Cup squad counts.",
    source: ballonSource,
    additions: [
      answer(
        "Ousmane Dembélé",
        2,
        "Won the World Cup with France in 2018 and the Ballon d’Or in 2025.",
        ["Dembele", "Ousmane Dembele", "Dembouz"],
      ),
      answer(
        "Rodri",
        2,
        "Won the Ballon d’Or in 2024 and the World Cup with Spain in 2026.",
        rodriAliases,
      ),
    ],
  },
];

export function refreshLaunchQuestions(bank: Question[]): Question[] {
  const retired = new Set(launchUpdates.map((update) => update.original));
  const replacements = launchUpdates.map((update): Question => {
    const original = bank.find((q) => q.id === update.original);
    if (!original)
      throw new Error(`Missing original question: ${update.original}`);
    return {
      ...original,
      id: update.id,
      active: true,
      scope: update.scope,
      source: update.source,
      answers: [
        ...original.answers.map((a) =>
          update.facts?.[a.name] ? { ...a, fact: update.facts[a.name] } : a,
        ),
        ...update.additions,
      ],
    };
  });
  return [
    ...bank.map((q) => (retired.has(q.id) ? { ...q, active: false } : q)),
    ...replacements,
  ];
}
