import type { Answer, Question } from "./question-types.ts";
type Row = [string, Answer["tier"], string, string[]?];
const answers = (rows: Row[]): Answer[] =>
  rows.map(([name, tier, fact, aliases = []]) => ({
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
  }));

// Broad prompts with familiar ways in and less obvious high-scoring answers.
// New IDs preserve the exact answer sets of older saved matches.
export const accessibleQuestions: Question[] = [
  {
    id: "european-champion-clubs-2026",
    topic: "europe",
    family: "european-champion-clubs",
    category: "Kings of Europe",
    difficulty: "Open goal",
    prompt:
      "Name a club that has won the men’s European Cup or Champions League.",
    scope: "1955/56–2025/26. Both names of the competition count.",
    source: {
      label: "UEFA · European champions",
      url: "https://www.uefa.com/news/0275-1541637ad1db-88aeeefefefd-1000--all-time-european-cup-honours-board/",
    },
    answers: answers([
      [
        "Real Madrid",
        1,
        "Champions in 2024, among many other years.",
        ["Real", "Madrid"],
      ],
      [
        "Barcelona",
        1,
        "Champions in 2015, among other years.",
        ["Barca", "FC Barcelona"],
      ],
      ["Liverpool", 1, "Champions in 2019, among other years.", ["LFC"]],
      [
        "Manchester United",
        1,
        "Champions in 1968, 1999 and 2008.",
        ["Man Utd", "Man United", "MUFC", "United"],
      ],
      [
        "Manchester City",
        1,
        "Champions in 2023.",
        ["Man City", "City", "MCFC"],
      ],
      ["Chelsea", 1, "Champions in 2012 and 2021.", ["Chelsea FC"]],
      [
        "Bayern Munich",
        2,
        "Champions in 2020, among other years.",
        ["Bayern", "Bayern Munchen", "FC Bayern"],
      ],
      ["AC Milan", 2, "Champions in 2007, among other years.", ["Milan"]],
      [
        "Paris Saint-Germain",
        2,
        "First won the competition in 2025.",
        ["PSG", "Paris", "Paris Saint Germain"],
      ],
      [
        "Inter Milan",
        2,
        "Champions in 1964, 1965 and 2010.",
        ["Inter", "Internazionale"],
      ],
      ["Juventus", 3, "Champions in 1985 and 1996.", ["Juve"]],
      [
        "Ajax",
        3,
        "Champions in 1971, 1972, 1973 and 1995.",
        ["AFC Ajax", "Ajax Amsterdam"],
      ],
      ["Borussia Dortmund", 3, "Champions in 1997.", ["Dortmund", "BVB"]],
      ["Porto", 3, "Champions in 1987 and 2004.", ["FC Porto"]],
      [
        "Nottingham Forest",
        3,
        "Champions in 1979 and 1980.",
        ["Forest", "Notts Forest", "Nottm Forest"],
      ],
      ["Aston Villa", 3, "Champions in 1982.", ["Villa"]],
      ["Celtic", 3, "Champions in 1967."],
      ["Benfica", 4, "Champions in 1961 and 1962.", ["SL Benfica"]],
      [
        "Marseille",
        4,
        "Champions in 1993.",
        ["Olympique Marseille", "Olympique de Marseille", "OM"],
      ],
      ["PSV Eindhoven", 4, "Champions in 1988.", ["PSV"]],
      ["Feyenoord", 5, "Champions in 1970.", ["Feyenoord Rotterdam"]],
      ["Hamburg", 5, "Champions in 1983.", ["Hamburger SV", "HSV"]],
      [
        "Red Star Belgrade",
        5,
        "Champions in 1991.",
        ["Red Star", "Crvena Zvezda"],
      ],
      [
        "Steaua București",
        5,
        "Champions in 1986.",
        ["Steaua", "Steaua Bucharest", "FCSB", "CSA Steaua"],
      ],
    ]),
  },
  {
    id: "uefa-cup-champion-clubs-2026",
    topic: "europe",
    family: "european-champion-clubs",
    category: "Thursday night royalty",
    difficulty: "Match sharp",
    prompt: "Name a club that has won the UEFA Cup or Europa League.",
    scope:
      "1971/72–2025/26. Both names count. The separate Fairs Cup and Conference League do not.",
    source: {
      label: "UEFA · UEFA Cup and Europa League winners",
      url: "https://www.uefa.com/uefaeuropaleague/news/0275-152d42886a65-efc6ff0e2d60-1000--uefa-cup-europa-league-roll-of-honour/",
    },
    answers: answers([
      ["Sevilla", 1, "First won in 2006.", ["Sevilla FC"]],
      [
        "Manchester United",
        1,
        "Won in 2017.",
        ["Man Utd", "Man United", "MUFC", "United"],
      ],
      ["Chelsea", 1, "Won in 2013 and 2019."],
      ["Tottenham Hotspur", 1, "First won in 1972.", ["Tottenham", "Spurs"]],
      ["Liverpool", 2, "First won in 1973.", ["LFC"]],
      [
        "Atlético Madrid",
        2,
        "First won in 2010.",
        ["Atletico", "Atleti", "Atletico de Madrid"],
      ],
      ["Villarreal", 2, "Won in 2021.", ["Villarreal CF"]],
      ["Atalanta", 2, "Won in 2024.", ["Atalanta BC"]],
      ["Aston Villa", 2, "Won in 2026.", ["Villa"]],
      ["Inter Milan", 3, "First won in 1991.", ["Inter", "Internazionale"]],
      ["Juventus", 3, "First won in 1977.", ["Juve"]],
      ["Porto", 3, "Won in 2003 and 2011.", ["FC Porto"]],
      [
        "Eintracht Frankfurt",
        3,
        "Won in 1980 and 2022.",
        ["Frankfurt", "Eintracht"],
      ],
      ["Valencia", 3, "Won in 2004.", ["Valencia CF"]],
      ["Feyenoord", 4, "Won in 1974 and 2002."],
      ["Real Madrid", 4, "Won in 1985 and 1986.", ["Real", "Madrid"]],
      ["Ajax", 4, "Won in 1992.", ["AFC Ajax", "Ajax Amsterdam"]],
      [
        "Bayern Munich",
        4,
        "Won in 1996.",
        ["Bayern", "Bayern Munchen", "FC Bayern"],
      ],
      ["Napoli", 4, "Won in 1989.", ["SSC Napoli"]],
      ["Parma", 4, "Won in 1995 and 1999.", ["Parma Calcio"]],
      ["Galatasaray", 4, "Won in 2000.", ["Gala"]],
      [
        "Bayer Leverkusen",
        4,
        "Won in 1988.",
        ["Leverkusen", "Bayer 04 Leverkusen"],
      ],
      [
        "Shakhtar Donetsk",
        4,
        "Won in 2009.",
        ["Shakhtar", "Shakhtar Donets'k"],
      ],
      [
        "Zenit Saint Petersburg",
        4,
        "Won in 2008.",
        ["Zenit", "Zenit St Petersburg", "Zenit Sankt Petersburg"],
      ],
      ["CSKA Moscow", 5, "Won in 2005.", ["CSKA", "CSKA Moskva"]],
      ["Schalke 04", 5, "Won in 1997.", ["Schalke", "FC Schalke 04"]],
      ["PSV Eindhoven", 5, "Won in 1978.", ["PSV"]],
      [
        "Borussia Mönchengladbach",
        5,
        "Won in 1975 and 1979.",
        [
          "Monchengladbach",
          "Moenchengladbach",
          "Gladbach",
          "Borussia Moenchengladbach",
        ],
      ],
      ["Anderlecht", 5, "Won in 1983.", ["RSC Anderlecht"]],
      [
        "IFK Göteborg",
        5,
        "Won in 1982 and 1987.",
        ["IFK Gothenburg", "Gothenburg", "Goteborg", "IFK Goteborg"],
      ],
      ["Ipswich Town", 5, "Won in 1981.", ["Ipswich"]],
    ]),
  },
  {
    id: "euro-top-scorers-2000-2024",
    topic: "goals",
    family: "euro-scoring-leaders",
    category: "Goals on the big stage",
    difficulty: "Match sharp",
    prompt:
      "Name a player who finished as a top scorer at a men’s Euros since 2000.",
    scope:
      "Euro 2000–Euro 2024. Joint top scorers count; you do not need to win an award tie-break.",
    source: {
      label: "UEFA · top scorers at every Euros",
      url: "https://www.uefa.com/uefaeuro/history/news/0259-0e6c1891bd10-d54f17cfd501-1000--euro-top-scorers-alltime-and-for-every-tournament/",
    },
    answers: answers([
      [
        "Cristiano Ronaldo",
        1,
        "Joint top scorer in 2012 and 2020.",
        ["Ronaldo", "Cristiano", "CR7"],
      ],
      ["Harry Kane", 1, "Joint top scorer in 2024.", ["Kane"]],
      ["Antoine Griezmann", 2, "Top scorer in 2016.", ["Griezmann"]],
      ["David Villa", 2, "Top scorer in 2008.", ["Villa"]],
      ["Fernando Torres", 2, "Joint top scorer in 2012.", ["Torres"]],
      ["Mario Balotelli", 3, "Joint top scorer in 2012.", ["Balotelli"]],
      ["Jamal Musiala", 3, "Joint top scorer in 2024.", ["Musiala"]],
      ["Cody Gakpo", 3, "Joint top scorer in 2024.", ["Gakpo"]],
      ["Dani Olmo", 3, "Joint top scorer in 2024.", ["Olmo", "Daniel Olmo"]],
      [
        "Patrik Schick",
        3,
        "Joint top scorer in 2020.",
        ["Schick", "Patrick Schick"],
      ],
      ["Patrick Kluivert", 4, "Joint top scorer in 2000.", ["Kluivert"]],
      ["Milan Baroš", 4, "Top scorer in 2004.", ["Baros"]],
      ["Mario Gomez", 4, "Joint top scorer in 2012.", ["Gomez"]],
      ["Mario Mandžukić", 4, "Joint top scorer in 2012.", ["Mandzukic"]],
      ["Georges Mikautadze", 4, "Joint top scorer in 2024.", ["Mikautadze"]],
      ["Savo Milošević", 5, "Joint top scorer in 2000.", ["Milosevic"]],
      ["Alan Dzagoev", 5, "Joint top scorer in 2012.", ["Dzagoev", "Dzagoyev"]],
      ["Ivan Schranz", 5, "Joint top scorer in 2024.", ["Schranz"]],
    ]),
  },
];
