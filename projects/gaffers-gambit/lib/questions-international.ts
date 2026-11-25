import type { Question } from "./question-types.ts";

// Server-side, finite historical sets. Tiers are editorial recall ratings, never pick percentages.
type Row = [
  name: string,
  tier: 1 | 2 | 3 | 4 | 5,
  fact: string,
  aliases?: string,
];
const slug = (name: string) =>
  name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
const q = (spec: Omit<Question, "answers">, rows: Row[]): Question => ({
  ...spec,
  answers: rows.map(([name, tier, fact, aliases]) => ({
    id: slug(name),
    name,
    tier,
    fact,
    aliases: aliases?.split(";") || [],
  })),
});
const src = (url: string, label: string) => ({ url, label });
const fifaFinals = src(
  "https://www.thesoccerworldcups.com/finals/results_with_goalscorers.php",
  "The Soccer World Cups · Every final and goalscorer",
);
const worldCupArchive = src(
  "https://www.rsssf.org/tablesw/worldcup.html",
  "RSSSF · Complete World Cup tournament archive",
);
const ballon = src(
  "https://rsssf.org/miscellaneous/europa-poy.html",
  "RSSSF · France Football award rankings",
);
const euroAwards = src(
  "https://www.uefa.com/uefaeuro/history/news/0259-0e6c1891bd10-d54f17cfd501-1000--euro-top-scorers-alltime-and-for-every-tournament/",
  "UEFA · EURO scoring and player awards",
);

export const internationalQuestions: Question[] = [
  q(
    {
      id: "intl-ballon-podium-2000s",
      topic: "awards",
      family: "ballon-podium",
      category: "On the podium",
      difficulty: "Match sharp",
      prompt:
        "Name a player who finished in the men’s Ballon d’Or top three in the 2000s.",
      scope:
        "2000–2009 inclusive. First, second or third counts. Use Cristiano Ronaldo or Ronaldo Nazário to distinguish the two.",
      source: ballon,
    },
    [
      ["Luís Figo", 3, "Winner in 2000.", "Figo;Luis Figo"],
      ["Zinedine Zidane", 2, "Runner-up in 2000.", "Zidane;Zizou"],
      [
        "Andriy Shevchenko",
        3,
        "Third in 2000 and winner in 2004.",
        "Shevchenko;Andrei Shevchenko;Sheva",
      ],
      ["Michael Owen", 3, "Winner in 2001.", "Owen"],
      [
        "Raúl",
        5,
        "Runner-up in 2001.",
        "Raul;Raul Gonzalez;Raul Gonzalez Blanco",
      ],
      ["Oliver Kahn", 5, "Third in both 2001 and 2002.", "Kahn"],
      ["Ronaldo Nazário", 2, "Winner in 2002.", "Ronaldo Nazario;R9"],
      ["Roberto Carlos", 5, "Runner-up in 2002.", "Carlos"],
      ["Pavel Nedvěd", 4, "Winner in 2003.", "Nedved;Pavel Nedved"],
      ["Thierry Henry", 2, "Second in 2003 and third in 2006.", "Henry"],
      ["Paolo Maldini", 4, "Third in 2003.", "Maldini"],
      ["Deco", 5, "Runner-up in 2004.", "Anderson Luis de Souza"],
      [
        "Ronaldinho",
        2,
        "Third in 2004 and winner in 2005.",
        "Ronaldinho Gaucho",
      ],
      ["Frank Lampard", 3, "Runner-up in 2005.", "Lampard"],
      ["Steven Gerrard", 3, "Third in 2005.", "Gerrard"],
      ["Fabio Cannavaro", 4, "Winner in 2006.", "Cannavaro"],
      ["Gianluigi Buffon", 4, "Runner-up in 2006.", "Buffon;Gigi Buffon"],
      ["Kaká", 3, "Winner in 2007.", "Kaka;Ricardo Kaka"],
      [
        "Cristiano Ronaldo",
        1,
        "Second in 2007 and 2009; winner in 2008.",
        "Cristiano;CR7",
      ],
      [
        "Lionel Messi",
        1,
        "Third in 2007, second in 2008 and winner in 2009.",
        "Messi;Leo Messi",
      ],
      ["Fernando Torres", 4, "Third in 2008.", "Torres"],
      ["Xavi", 4, "Third in 2009.", "Xavi Hernandez"],
    ],
  ),
  q(
    {
      id: "intl-ballon-podium-2010s",
      topic: "awards",
      family: "ballon-podium",
      category: "On the podium",
      difficulty: "Open goal",
      prompt:
        "Name a player who finished in the men’s Ballon d’Or top three in the 2010s.",
      scope:
        "2010–2019 inclusive, including the FIFA Ballon d’Or years. First, second or third counts.",
      source: src(
        "https://ballondor.com/fr/all-rankings",
        "Ballon d’Or · Official historical rankings",
      ),
    },
    [
      [
        "Lionel Messi",
        1,
        "Won in 2010, 2011, 2012, 2015 and 2019 within this decade.",
        "Messi;Leo Messi",
      ],
      [
        "Cristiano Ronaldo",
        1,
        "Won in 2013, 2014, 2016 and 2017 within this decade.",
        "Ronaldo;Cristiano;CR7",
      ],
      [
        "Andrés Iniesta",
        3,
        "Second in 2010 and third in 2012.",
        "Iniesta;Andres Iniesta",
      ],
      ["Xavi", 4, "Third in 2010 and 2011.", "Xavi Hernandez"],
      ["Franck Ribéry", 4, "Third in 2013.", "Ribery;Franck Ribery"],
      ["Manuel Neuer", 5, "Third in 2014.", "Neuer"],
      ["Neymar", 3, "Third in 2015 and 2017.", "Neymar Jr;Neymar Junior"],
      ["Antoine Griezmann", 4, "Third in 2016 and 2018.", "Griezmann"],
      ["Luka Modrić", 3, "Winner in 2018.", "Modric;Luka Modric"],
      ["Virgil van Dijk", 3, "Runner-up in 2019.", "Van Dijk;VVD"],
    ],
  ),
  q(
    {
      id: "intl-wc-final-scorers-1982-2022",
      topic: "world-cup",
      family: "world-cup-finals",
      category: "The biggest stage",
      difficulty: "Open goal",
      prompt:
        "Name a player who scored in a men’s World Cup final between 1982 and 2022.",
      scope:
        "Both end tournaments included. Either team counts. Extra-time goals count; shoot-out penalties and own goals do not.",
      source: fifaFinals,
    },
    [
      [
        "Paolo Rossi",
        3,
        "Scored Italy’s first goal in the 1982 final.",
        "Rossi",
      ],
      [
        "Marco Tardelli",
        4,
        "Scored Italy’s second goal in the 1982 final.",
        "Tardelli",
      ],
      [
        "Alessandro Altobelli",
        5,
        "Scored Italy’s third goal in the 1982 final.",
        "Altobelli",
      ],
      [
        "Paul Breitner",
        5,
        "Scored West Germany’s goal in the 1982 final.",
        "Breitner",
      ],
      [
        "José Luis Brown",
        5,
        "Scored Argentina’s first goal in the 1986 final.",
        "Brown;Jose Luis Brown;Tata Brown",
      ],
      [
        "Jorge Valdano",
        4,
        "Scored Argentina’s second goal in the 1986 final.",
        "Valdano",
      ],
      [
        "Jorge Burruchaga",
        4,
        "Scored Argentina’s winner in the 1986 final.",
        "Burruchaga",
      ],
      [
        "Karl-Heinz Rummenigge",
        4,
        "Scored West Germany’s first goal in the 1986 final.",
        "Rummenigge;Karl Heinz Rummenigge",
      ],
      [
        "Rudi Völler",
        4,
        "Scored West Germany’s second goal in the 1986 final.",
        "Voller;Voeller;Rudi Voller;Rudolf Voller",
      ],
      [
        "Andreas Brehme",
        4,
        "Scored the decisive penalty during the 1990 final.",
        "Brehme;Andy Brehme",
      ],
      [
        "Zinedine Zidane",
        1,
        "Scored twice in the 1998 final and once in 2006.",
        "Zidane;Zizou",
      ],
      [
        "Emmanuel Petit",
        3,
        "Scored France’s third goal in the 1998 final.",
        "Petit",
      ],
      [
        "Ronaldo Nazário",
        1,
        "Scored both Brazil goals in the 2002 final.",
        "Ronaldo;Ronaldo Nazario;R9",
      ],
      [
        "Marco Materazzi",
        3,
        "Scored Italy’s equaliser in the 2006 final.",
        "Materazzi",
      ],
      [
        "Andrés Iniesta",
        1,
        "Scored Spain’s extra-time winner in 2010.",
        "Iniesta;Andres Iniesta",
      ],
      [
        "Mario Götze",
        2,
        "Scored Germany’s extra-time winner in 2014.",
        "Gotze;Goetze;Mario Gotze",
      ],
      [
        "Antoine Griezmann",
        3,
        "Scored a penalty during the 2018 final.",
        "Griezmann",
      ],
      [
        "Paul Pogba",
        3,
        "Scored France’s third goal in the 2018 final.",
        "Pogba",
      ],
      [
        "Kylian Mbappé",
        1,
        "Scored once in the 2018 final and a hat-trick in 2022.",
        "Mbappe;Kylian Mbappe",
      ],
      [
        "Ivan Perišić",
        4,
        "Scored Croatia’s first goal in the 2018 final.",
        "Perisic;Ivan Perisic",
      ],
      [
        "Mario Mandžukić",
        3,
        "Scored Croatia’s second goal in 2018, as well as an earlier own goal.",
        "Mandzukic;Mario Mandzukic",
      ],
      [
        "Lionel Messi",
        1,
        "Scored twice for Argentina in the 2022 final.",
        "Messi;Leo Messi",
      ],
      [
        "Ángel Di María",
        2,
        "Scored Argentina’s second goal in the 2022 final.",
        "Di Maria;Angel Di Maria",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-hattricks-1990-2022",
      topic: "world-cup",
      family: "world-cup-hat-tricks",
      category: "Take the match ball",
      difficulty: "Match sharp",
      prompt:
        "Name a player who scored a men’s World Cup hat-trick from 1990 to 2022.",
      scope:
        "Three or more goals in one finals-tournament match. Both end tournaments included; shoot-outs excluded.",
      source: src(
        "https://theanalyst.com/articles/world-cup-hat-tricks-fifa",
        "Opta Analyst · Every World Cup hat-trick",
      ),
    },
    [
      [
        "Míchel",
        5,
        "Scored three for Spain against South Korea in 1990.",
        "Michel;Jose Miguel Gonzalez;Michel Gonzalez",
      ],
      [
        "Tomáš Skuhravý",
        5,
        "Scored three headers for Czechoslovakia against Costa Rica in 1990.",
        "Skuhravy;Tomas Skuhravy",
      ],
      [
        "Gabriel Batistuta",
        3,
        "Scored hat-tricks against Greece in 1994 and Jamaica in 1998.",
        "Batistuta;Batigol",
      ],
      [
        "Oleg Salenko",
        4,
        "Scored five for Russia against Cameroon in 1994.",
        "Salenko",
      ],
      [
        "Miroslav Klose",
        2,
        "Scored three for Germany against Saudi Arabia in 2002.",
        "Klose",
      ],
      [
        "Pauleta",
        5,
        "Scored three for Portugal against Poland in 2002.",
        "Pedro Pauleta;Pedro Miguel Pauleta",
      ],
      [
        "Gonzalo Higuaín",
        4,
        "Scored three for Argentina against South Korea in 2010.",
        "Higuain;Gonzalo Higuain",
      ],
      [
        "Thomas Müller",
        3,
        "Scored three for Germany against Portugal in 2014.",
        "Muller;Mueller;Thomas Muller;Thomas Mueller",
      ],
      [
        "Xherdan Shaqiri",
        4,
        "Scored three for Switzerland against Honduras in 2014.",
        "Shaqiri",
      ],
      [
        "Cristiano Ronaldo",
        1,
        "Scored all Portugal’s goals in the 3–3 draw with Spain in 2018.",
        "Ronaldo;Cristiano;CR7",
      ],
      [
        "Harry Kane",
        2,
        "Scored three for England against Panama in 2018.",
        "Kane",
      ],
      [
        "Gonçalo Ramos",
        3,
        "Scored three for Portugal against Switzerland in 2022.",
        "Ramos;Goncalo Ramos",
      ],
      [
        "Kylian Mbappé",
        1,
        "Scored a hat-trick for France in the 2022 final.",
        "Mbappe;Kylian Mbappe",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-winning-captains",
      topic: "world-cup",
      family: "world-cup-captains",
      category: "Lift it, skipper",
      difficulty: "Open goal",
      prompt:
        "Name a captain who lifted the men’s World Cup from 1982 to 2022.",
      scope:
        "The captain of the winning team in the final. Both end tournaments included.",
      source: src(
        "https://www.fifa.com/en/tournaments/mens/worldcup/articles/youngest-captains",
        "FIFA · World Cup-winning captains",
      ),
    },
    [
      ["Dino Zoff", 5, "Captained Italy to the 1982 title.", "Zoff"],
      [
        "Diego Maradona",
        2,
        "Captained Argentina to the 1986 title.",
        "Maradona",
      ],
      [
        "Lothar Matthäus",
        4,
        "Captained West Germany to the 1990 title.",
        "Matthaus;Matthaeus;Lothar Matthaus",
      ],
      [
        "Dunga",
        5,
        "Captained Brazil to the 1994 title.",
        "Carlos Dunga;Carlos Caetano Bledorn Verri",
      ],
      [
        "Didier Deschamps",
        3,
        "Captained France to the 1998 title.",
        "Deschamps",
      ],
      [
        "Cafu",
        3,
        "Captained Brazil to the 2002 title.",
        "Marcos Evangelista de Morais",
      ],
      ["Fabio Cannavaro", 3, "Captained Italy to the 2006 title.", "Cannavaro"],
      ["Iker Casillas", 2, "Captained Spain to the 2010 title.", "Casillas"],
      ["Philipp Lahm", 3, "Captained Germany to the 2014 title.", "Lahm"],
      ["Hugo Lloris", 2, "Captained France to the 2018 title.", "Lloris"],
      [
        "Lionel Messi",
        1,
        "Captained Argentina to the 2022 title.",
        "Messi;Leo Messi",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-final-referees",
      topic: "world-cup",
      family: "world-cup-officials",
      category: "Man in the middle",
      difficulty: "Proper nerd",
      prompt:
        "Name a referee who took charge of a men’s World Cup final from 1990 to 2022.",
      scope:
        "The on-field referee, not assistants, fourth officials or VAR officials. Both end tournaments included.",
      source: src(
        "https://www.sportingnews.com/in/football/news/referee-world-cup-final-officiate-2022-fifa-title-match/oyjc8qxh8klgtwb7qz46dxyd",
        "Sporting News · World Cup final referees",
      ),
    },
    [
      [
        "Edgardo Codesal",
        5,
        "Refereed West Germany v Argentina in 1990.",
        "Codesal;Edgardo Codesal Mendez",
      ],
      [
        "Sándor Puhl",
        5,
        "Refereed Brazil v Italy in 1994.",
        "Puhl;Sandor Puhl",
      ],
      [
        "Said Belqola",
        5,
        "Refereed France v Brazil in 1998.",
        "Belqola;Said Belkola",
      ],
      ["Pierluigi Collina", 1, "Refereed Brazil v Germany in 2002.", "Collina"],
      ["Horacio Elizondo", 4, "Refereed Italy v France in 2006.", "Elizondo"],
      ["Howard Webb", 1, "Refereed Netherlands v Spain in 2010.", "Webb"],
      ["Nicola Rizzoli", 3, "Refereed Germany v Argentina in 2014.", "Rizzoli"],
      [
        "Néstor Pitana",
        3,
        "Refereed France v Croatia in 2018.",
        "Pitana;Nestor Pitana",
      ],
      [
        "Szymon Marciniak",
        2,
        "Refereed Argentina v France in 2022.",
        "Marciniak",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-first-semis-1990",
      topic: "world-cup",
      family: "world-cup-breakthroughs",
      category: "New territory",
      difficulty: "Match sharp",
      prompt:
        "Name a country that played its first men’s World Cup semi-final between 1990 and 2022.",
      scope:
        "First appearance in an actual semi-final match, not a top-four finish in a final group. Historical national teams are treated separately.",
      source: worldCupArchive,
    },
    [
      [
        "Bulgaria",
        5,
        "Reached a first semi-final in 1994, losing 2–1 to Italy.",
        "Balgariya",
      ],
      [
        "Croatia",
        3,
        "Reached a first semi-final in 1998, losing 2–1 to France.",
        "Hrvatska",
      ],
      [
        "Turkey",
        4,
        "Reached a first semi-final in 2002, losing 1–0 to Brazil.",
        "Turkiye;Türkiye",
      ],
      [
        "South Korea",
        3,
        "Reached a first semi-final in 2002, losing 1–0 to Germany.",
        "Korea Republic;Republic of Korea",
      ],
      [
        "Spain",
        4,
        "Played a first semi-final in 2010 and beat Germany 1–0; 1950 used a final group.",
        "Espana;España",
      ],
      [
        "Morocco",
        1,
        "Reached a first semi-final in 2022, losing 2–0 to France.",
        "Maroc",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-host-countries",
      topic: "world-cup",
      family: "world-cup-hosts",
      category: "Home advantage",
      difficulty: "Open goal",
      prompt: "Name a country that hosted the men’s World Cup before 2026.",
      scope:
        "1930–2022 inclusive. Both 2002 co-hosts count. West Germany is accepted as Germany.",
      source: worldCupArchive,
    },
    [
      ["Uruguay", 4, "Hosted the first tournament in 1930."],
      ["Italy", 3, "Hosted in 1934 and 1990.", "Italia"],
      ["France", 2, "Hosted in 1938 and 1998."],
      ["Brazil", 1, "Hosted in 1950 and 2014.", "Brasil"],
      ["Switzerland", 5, "Hosted the 1954 tournament.", "Swiss;Schweiz;Suisse"],
      ["Sweden", 5, "Hosted the 1958 tournament.", "Sverige"],
      ["Chile", 5, "Hosted the 1962 tournament."],
      ["England", 2, "Hosted the 1966 tournament."],
      ["Mexico", 3, "Hosted in 1970 and 1986 within this cutoff.", "México"],
      [
        "Germany",
        2,
        "West Germany hosted in 1974; Germany hosted in 2006.",
        "West Germany;Deutschland",
      ],
      ["Argentina", 4, "Hosted the 1978 tournament."],
      ["Spain", 4, "Hosted the 1982 tournament.", "Espana;España"],
      [
        "United States",
        3,
        "Hosted the 1994 tournament.",
        "USA;US;United States of America;America",
      ],
      [
        "South Korea",
        3,
        "Co-hosted the 2002 tournament with Japan.",
        "Korea Republic;Republic of Korea",
      ],
      ["Japan", 3, "Co-hosted the 2002 tournament with South Korea.", "Nippon"],
      ["South Africa", 2, "Hosted the 2010 tournament.", "RSA"],
      ["Russia", 2, "Hosted the 2018 tournament."],
      ["Qatar", 1, "Hosted the 2022 tournament."],
    ],
  ),
  q(
    {
      id: "intl-brazil-first-group-defeats",
      topic: "world-cup",
      family: "world-cup-upsets",
      category: "Beating Brazil",
      difficulty: "Proper nerd",
      prompt:
        "Name a country that beat Brazil in a men’s World Cup FIRST group stage.",
      scope:
        "1930–2022. Opening group stage only: later group rounds, including 1950’s final group, do not count. Historical team names apply.",
      source: src(
        "https://www.thesoccerworldcups.com/national_teams/brazil_results.php",
        "The Soccer World Cups · Every Brazil result",
      ),
    },
    [
      [
        "Yugoslavia",
        5,
        "Beat Brazil 2–1 in the opening group at Uruguay 1930.",
        "Jugoslavia",
      ],
      [
        "Hungary",
        4,
        "Beat Brazil 3–1 in the opening group at England 1966.",
        "Magyarorszag",
      ],
      ["Portugal", 2, "Beat Brazil 3–1 in the opening group at England 1966."],
      ["Norway", 3, "Beat Brazil 2–1 in Group A at France 1998.", "Norge"],
      ["Cameroon", 1, "Beat Brazil 1–0 in Group G at Qatar 2022.", "Cameroun"],
    ],
  ),
  q(
    {
      id: "intl-wc-shootout-winning-nations",
      topic: "world-cup",
      family: "world-cup-shoot-outs",
      category: "From twelve yards",
      difficulty: "Match sharp",
      prompt:
        "Name a country that won a men’s World Cup penalty shoot-out by the end of 2022.",
      scope:
        "Finals tournaments only, 1982–2022. Qualifying play-offs do not count. West Germany is accepted as Germany.",
      source: src(
        "https://www.rsssf.org/miscellaneous/penaltiestour.html",
        "RSSSF · Complete World Cup shoot-out list",
      ),
    },
    [
      [
        "Germany",
        1,
        "Won against France in 1982, Mexico in 1986, England in 1990 and Argentina in 2006.",
        "West Germany;Deutschland",
      ],
      ["France", 2, "Won against Brazil in 1986 and Italy in 1998."],
      ["Belgium", 5, "Beat Spain on penalties in the 1986 quarter-final."],
      [
        "Republic of Ireland",
        5,
        "Beat Romania on penalties in the 1990 round of 16.",
        "Ireland;Eire;Éire",
      ],
      [
        "Argentina",
        1,
        "Won six World Cup shoot-outs through 2022, including the 2022 final.",
      ],
      ["Bulgaria", 5, "Beat Mexico on penalties in the 1994 round of 16."],
      [
        "Sweden",
        5,
        "Beat Romania on penalties in the 1994 quarter-final.",
        "Sverige",
      ],
      ["Brazil", 2, "Won the 1994 final shoot-out against Italy.", "Brasil"],
      [
        "Spain",
        4,
        "Beat the Republic of Ireland on penalties in 2002.",
        "Espana;España",
      ],
      [
        "South Korea",
        4,
        "Beat Spain on penalties in the 2002 quarter-final.",
        "Korea Republic;Republic of Korea",
      ],
      [
        "Ukraine",
        5,
        "Beat Switzerland 3–0 on penalties in the 2006 round of 16.",
        "Ukraina",
      ],
      ["Portugal", 3, "Beat England on penalties in the 2006 quarter-final."],
      ["Italy", 2, "Won the 2006 final shoot-out against France.", "Italia"],
      ["Paraguay", 5, "Beat Japan on penalties in the 2010 round of 16."],
      ["Uruguay", 3, "Beat Ghana on penalties in the 2010 quarter-final."],
      ["Costa Rica", 4, "Beat Greece on penalties in the 2014 round of 16."],
      [
        "Netherlands",
        3,
        "Beat Costa Rica on penalties in the 2014 quarter-final.",
        "Holland;The Netherlands",
      ],
      ["Russia", 4, "Beat Spain on penalties in the 2018 round of 16."],
      [
        "Croatia",
        1,
        "Won four shoot-outs across the 2018 and 2022 tournaments.",
        "Hrvatska",
      ],
      ["England", 2, "Beat Colombia on penalties in the 2018 round of 16."],
      [
        "Morocco",
        2,
        "Beat Spain 3–0 on penalties in the 2022 round of 16.",
        "Maroc",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-conceded-eight",
      topic: "world-cup",
      family: "world-cup-scorelines",
      category: "A long afternoon",
      difficulty: "Proper nerd",
      prompt:
        "Name a country that conceded at least eight goals in one men’s World Cup match.",
      scope:
        "1930–2022 finals tournaments. Historical team names count; West Germany is accepted as Germany.",
      source: src(
        "https://theanalyst.com/articles/the-biggest-world-cup-wins",
        "Opta Analyst · Biggest World Cup wins",
      ),
    },
    [
      ["El Salvador", 2, "Lost 10–1 to Hungary in 1982.", "Salvador"],
      [
        "South Korea",
        3,
        "Lost 9–0 to Hungary in 1954.",
        "Korea Republic;Republic of Korea",
      ],
      [
        "Zaire",
        4,
        "Lost 9–0 to Yugoslavia in 1974.",
        "DR Congo;Democratic Republic of the Congo;Congo DR",
      ],
      ["Cuba", 5, "Lost 8–0 to Sweden in the 1938 quarter-final."],
      ["Bolivia", 5, "Lost 8–0 to Uruguay in 1950."],
      [
        "Germany",
        4,
        "West Germany lost 8–3 to Hungary in the 1954 group stage, then beat them in the final.",
        "West Germany;Deutschland",
      ],
      ["Saudi Arabia", 1, "Lost 8–0 to Germany in 2002.", "Saudi;KSA"],
    ],
  ),
  q(
    {
      id: "intl-wc-golden-glove",
      topic: "awards",
      family: "world-cup-individual-awards",
      category: "Safe hands",
      difficulty: "Open goal",
      prompt: "Name a men’s World Cup Golden Glove winner from 1994 to 2022.",
      scope:
        "Includes the award’s earlier Lev Yashin name. Both end tournaments included.",
      source: src(
        "https://www.fifa.com/fr/tournaments/mens/worldcup/articles/gants-or-coupe-du-monde",
        "FIFA · Every World Cup Golden Glove",
      ),
    },
    [
      [
        "Michel Preud’homme",
        5,
        "Won the 1994 award for Belgium.",
        "Preudhomme;Preud homme;Michel Preudhomme",
      ],
      ["Fabien Barthez", 4, "Won the 1998 award for France.", "Barthez"],
      ["Oliver Kahn", 3, "Won the 2002 award for Germany.", "Kahn"],
      [
        "Gianluigi Buffon",
        2,
        "Won the 2006 award for Italy.",
        "Buffon;Gigi Buffon",
      ],
      ["Iker Casillas", 2, "Won the 2010 award for Spain.", "Casillas"],
      ["Manuel Neuer", 2, "Won the 2014 award for Germany.", "Neuer"],
      ["Thibaut Courtois", 3, "Won the 2018 award for Belgium.", "Courtois"],
      [
        "Emiliano Martínez",
        1,
        "Won the 2022 award for Argentina.",
        "Martinez;Emiliano Martinez;Emi Martinez;Dibu Martinez;Dibu",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-best-young",
      topic: "awards",
      family: "world-cup-individual-awards",
      category: "The next big thing",
      difficulty: "Match sharp",
      prompt:
        "Name an official men’s World Cup Best Young Player award winner from 2006 to 2022.",
      scope:
        "The five awards presented at those tournaments, not retrospective selections for earlier World Cups.",
      source: src(
        "https://www.fifa.com/de/tournaments/mens/worldcup/articles/wm-young-player-award-bester-junger-spieler-gewinner",
        "FIFA · Young Player award winners",
      ),
    },
    [
      [
        "Lukas Podolski",
        5,
        "Won the inaugural official award with Germany in 2006.",
        "Podolski",
      ],
      [
        "Thomas Müller",
        3,
        "Won the 2010 award with Germany.",
        "Muller;Mueller;Thomas Muller;Thomas Mueller",
      ],
      ["Paul Pogba", 3, "Won the 2014 award with France.", "Pogba"],
      [
        "Kylian Mbappé",
        1,
        "Won the 2018 award with France.",
        "Mbappe;Kylian Mbappe",
      ],
      [
        "Enzo Fernández",
        2,
        "Won the 2022 award with Argentina.",
        "Enzo;Fernandez;Enzo Fernandez",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-twenty-appearances",
      topic: "world-cup",
      family: "world-cup-longevity",
      category: "Tournament regulars",
      difficulty: "Proper nerd",
      prompt:
        "Name a player who had made at least 20 men’s World Cup appearances by the end of 2022.",
      scope:
        "Finals matches played, not squad selections or qualifiers. The total is frozen after Qatar 2022.",
      source: src(
        "https://theanalyst.com/articles/most-world-cup-appearances-by-a-player",
        "Opta Analyst · World Cup appearances",
      ),
    },
    [
      [
        "Lionel Messi",
        1,
        "Had 26 appearances through the 2022 final.",
        "Messi;Leo Messi",
      ],
      [
        "Lothar Matthäus",
        2,
        "Made 25 appearances from 1982 to 1998.",
        "Matthaus;Matthaeus;Lothar Matthaus",
      ],
      ["Miroslav Klose", 2, "Made 24 appearances from 2002 to 2014.", "Klose"],
      ["Paolo Maldini", 3, "Made 23 appearances from 1990 to 2002.", "Maldini"],
      [
        "Cristiano Ronaldo",
        1,
        "Had 22 appearances through Qatar 2022.",
        "Ronaldo;Cristiano;CR7",
      ],
      [
        "Diego Maradona",
        3,
        "Made 21 appearances from 1982 to 1994.",
        "Maradona",
      ],
      ["Uwe Seeler", 5, "Made 21 appearances from 1958 to 1970.", "Seeler"],
      [
        "Władysław Żmuda",
        5,
        "Made 21 appearances for Poland from 1974 to 1986.",
        "Zmuda;Wladyslaw Zmuda;Wladislaw Zmuda",
      ],
      [
        "Cafu",
        3,
        "Made 20 appearances from 1994 to 2006.",
        "Marcos Evangelista de Morais",
      ],
      [
        "Grzegorz Lato",
        5,
        "Made 20 appearances for Poland from 1974 to 1982.",
        "Lato",
      ],
      [
        "Javier Mascherano",
        4,
        "Made 20 appearances from 2006 to 2018.",
        "Mascherano",
      ],
      ["Philipp Lahm", 4, "Made 20 appearances from 2006 to 2014.", "Lahm"],
      [
        "Bastian Schweinsteiger",
        4,
        "Made 20 appearances from 2006 to 2014.",
        "Schweinsteiger;Bastian",
      ],
      ["Hugo Lloris", 3, "Made 20 appearances from 2010 to 2022.", "Lloris"],
    ],
  ),
  q(
    {
      id: "intl-wc-five-tournaments",
      topic: "world-cup",
      family: "world-cup-longevity",
      category: "Five stamps in the passport",
      difficulty: "Match sharp",
      prompt:
        "Name a player who played at five different men’s World Cups by the end of 2022.",
      scope:
        "Must have taken the field at five finals tournaments. Merely being in a squad does not count.",
      source: src(
        "https://www.fifpro.org/en/articles/2022/11/five-star-guardado-messi-and-ronaldo-make-mens-world-cup-history",
        "FIFPRO · The six five-tournament players",
      ),
    },
    [
      [
        "Antonio Carbajal",
        5,
        "Played for Mexico at every tournament from 1950 to 1966.",
        "Carbajal;La Tota",
      ],
      [
        "Lothar Matthäus",
        3,
        "Played for Germany at every tournament from 1982 to 1998.",
        "Matthaus;Matthaeus;Lothar Matthaus",
      ],
      [
        "Rafael Márquez",
        3,
        "Played for Mexico at every tournament from 2002 to 2018.",
        "Marquez;Rafael Marquez;Rafa Marquez",
      ],
      [
        "Andrés Guardado",
        5,
        "Played for Mexico at every tournament from 2006 to 2022.",
        "Guardado;Andres Guardado",
      ],
      [
        "Lionel Messi",
        1,
        "Played for Argentina at every tournament from 2006 to 2022.",
        "Messi;Leo Messi",
      ],
      [
        "Cristiano Ronaldo",
        1,
        "Played for Portugal at every tournament from 2006 to 2022.",
        "Ronaldo;Cristiano;CR7",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-four-editions-scored",
      topic: "world-cup",
      family: "world-cup-longevity",
      category: "Goals across generations",
      difficulty: "Match sharp",
      prompt:
        "Name a player who scored in at least four different men’s World Cups by the end of 2022.",
      scope:
        "Finals tournaments only. Qualifiers and penalty shoot-outs excluded.",
      source: src(
        "https://old.socceramerica.com/publications/article/94821/top-multiple-world-cup-scorers.html?edition=29079",
        "Soccer America · All five multiple-tournament scorers, December 2022",
      ),
    },
    [
      [
        "Cristiano Ronaldo",
        1,
        "Scored in 2006, 2010, 2014, 2018 and 2022.",
        "Ronaldo;Cristiano;CR7",
      ],
      [
        "Lionel Messi",
        1,
        "Scored in 2006, 2014, 2018 and 2022, but not in 2010.",
        "Messi;Leo Messi",
      ],
      [
        "Pelé",
        2,
        "Scored in 1958, 1962, 1966 and 1970.",
        "Pele;Edson Arantes do Nascimento",
      ],
      ["Miroslav Klose", 3, "Scored in 2002, 2006, 2010 and 2014.", "Klose"],
      ["Uwe Seeler", 5, "Scored in 1958, 1962, 1966 and 1970.", "Seeler"],
    ],
  ),
  q(
    {
      id: "intl-wc-ten-goal-club",
      topic: "world-cup",
      family: "world-cup-scoring-records",
      category: "Double figures",
      difficulty: "Open goal",
      prompt:
        "Name a player who had scored at least 10 men’s World Cup goals by the end of 2022.",
      scope:
        "Career goals in finals tournaments through Qatar 2022. Qualifiers and shoot-out penalties excluded. Specify Gerd or Thomas Müller.",
      source: src(
        "https://theanalyst.com/articles/most-world-cup-goals",
        "Opta Analyst · World Cup scoring records",
      ),
    },
    [
      ["Miroslav Klose", 1, "Scored 16 World Cup goals.", "Klose"],
      [
        "Ronaldo Nazário",
        1,
        "Scored 15 World Cup goals.",
        "Ronaldo;Ronaldo Nazario;R9",
      ],
      [
        "Gerd Müller",
        3,
        "Scored 14 World Cup goals.",
        "Gerd Muller;Gerd Mueller",
      ],
      [
        "Just Fontaine",
        4,
        "Scored 13 goals, all at the 1958 tournament.",
        "Fontaine",
      ],
      [
        "Lionel Messi",
        1,
        "Had 13 goals through the 2022 final.",
        "Messi;Leo Messi",
      ],
      [
        "Kylian Mbappé",
        2,
        "Had 12 goals through the 2022 final.",
        "Mbappe;Kylian Mbappe",
      ],
      [
        "Pelé",
        2,
        "Scored 12 World Cup goals.",
        "Pele;Edson Arantes do Nascimento",
      ],
      [
        "Sándor Kocsis",
        5,
        "Scored 11 goals, all at the 1954 tournament.",
        "Kocsis;Sandor Kocsis",
      ],
      [
        "Jürgen Klinsmann",
        4,
        "Scored 11 World Cup goals.",
        "Klinsmann;Jurgen Klinsmann",
      ],
      [
        "Helmut Rahn",
        5,
        "Scored 10 goals across the 1954 and 1958 tournaments.",
        "Rahn",
      ],
      [
        "Gary Lineker",
        3,
        "Scored 10 goals across the 1986 and 1990 tournaments.",
        "Lineker",
      ],
      [
        "Gabriel Batistuta",
        4,
        "Scored 10 goals across the 1994, 1998 and 2002 tournaments.",
        "Batistuta;Batigol",
      ],
      [
        "Teófilo Cubillas",
        5,
        "Scored 10 goals for Peru.",
        "Cubillas;Teofilo Cubillas",
      ],
      ["Grzegorz Lato", 5, "Scored 10 goals for Poland.", "Lato"],
      [
        "Thomas Müller",
        3,
        "Had 10 goals through 2022, all scored in 2010 and 2014.",
        "Thomas Muller;Thomas Mueller",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-winning-managers",
      topic: "world-cup",
      family: "world-cup-managers",
      category: "Masterminds",
      difficulty: "Open goal",
      prompt:
        "Name a head coach who won the men’s World Cup from 1982 to 2022.",
      scope:
        "Head coach of the winning team at the tournament, not assistants or winners as players. Both end tournaments included.",
      source: src(
        "https://www.fifa.com/en/tournaments/mens/worldcup/articles/world-cup-champions-1982-2026-italy-argentina-germany-brazil-france-spain",
        "FIFA · Champion teams, 1982 onward",
      ),
    },
    [
      ["Enzo Bearzot", 5, "Led Italy to the 1982 title.", "Bearzot"],
      [
        "Carlos Bilardo",
        4,
        "Led Argentina to the 1986 title.",
        "Bilardo;Carlos Salvador Bilardo",
      ],
      [
        "Franz Beckenbauer",
        3,
        "Led West Germany to the 1990 title.",
        "Beckenbauer",
      ],
      [
        "Carlos Alberto Parreira",
        5,
        "Led Brazil to the 1994 title.",
        "Parreira",
      ],
      [
        "Aimé Jacquet",
        5,
        "Led France to the 1998 title.",
        "Jacquet;Aime Jacquet",
      ],
      [
        "Luiz Felipe Scolari",
        3,
        "Led Brazil to the 2002 title.",
        "Scolari;Felipao;Big Phil",
      ],
      ["Marcello Lippi", 3, "Led Italy to the 2006 title.", "Lippi"],
      ["Vicente del Bosque", 2, "Led Spain to the 2010 title.", "Del Bosque"],
      [
        "Joachim Löw",
        2,
        "Led Germany to the 2014 title.",
        "Low;Loew;Joachim Low;Jogi Low",
      ],
      ["Didier Deschamps", 1, "Led France to the 2018 title.", "Deschamps"],
      ["Lionel Scaloni", 1, "Led Argentina to the 2022 title.", "Scaloni"],
    ],
  ),
  q(
    {
      id: "intl-wc-finalists-without-title",
      topic: "world-cup",
      family: "world-cup-finalists",
      category: "So close",
      difficulty: "Match sharp",
      prompt:
        "Name a country that reached a men’s World Cup final but had never won the tournament by the end of 2022.",
      scope:
        "1930–2022. Historical national teams are named as they competed; Czechoslovakia is a separate answer from its successor states.",
      source: worldCupArchive,
    },
    [
      [
        "Netherlands",
        1,
        "Lost the finals in 1974, 1978 and 2010.",
        "Holland;The Netherlands",
      ],
      ["Croatia", 2, "Lost the 2018 final to France.", "Hrvatska"],
      ["Hungary", 4, "Lost the finals in 1938 and 1954.", "Magyarorszag"],
      [
        "Czechoslovakia",
        5,
        "Lost the finals in 1934 and 1962.",
        "Czechoslovak Republic",
      ],
      ["Sweden", 4, "Lost the 1958 final to Brazil.", "Sverige"],
    ],
  ),
  q(
    {
      id: "intl-wc-final-red-cards",
      topic: "world-cup",
      family: "world-cup-final-discipline",
      category: "Early bath",
      difficulty: "Proper nerd",
      prompt:
        "Name a player sent off in a men’s World Cup final by the end of 2022.",
      scope:
        "The final match itself. Straight reds and second-yellow dismissals count.",
      source: src(
        "https://www.sportingnews.com/ca/soccer/news/world-cup-final-red-cards-history-ejections-fifa/k7sfis2w8blbkab2yo9edtpz",
        "Sporting News · Every World Cup final dismissal",
      ),
    },
    [
      [
        "Pedro Monzón",
        5,
        "Sent off for Argentina in the 1990 final.",
        "Monzon;Pedro Monzon",
      ],
      [
        "Gustavo Dezotti",
        5,
        "Argentina’s second player sent off in the 1990 final.",
        "Dezotti",
      ],
      [
        "Marcel Desailly",
        3,
        "Sent off for a second booking in France’s 1998 final win.",
        "Desailly",
      ],
      [
        "Zinedine Zidane",
        1,
        "Sent off in extra time during the 2006 final.",
        "Zidane;Zizou",
      ],
      [
        "John Heitinga",
        4,
        "Sent off for a second booking in the 2010 final.",
        "Heitinga;Johnny Heitinga",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-ucl-winning-finals-double",
      topic: "world-cup",
      family: "global-career-crossover",
      category: "Club and country",
      difficulty: "Proper nerd",
      prompt:
        "Name a player who played in winning European Cup AND World Cup finals in the same year.",
      scope:
        "Through 2022. European Cup includes the Champions League. Must have taken the field in both finals that year, not simply been in both squads.",
      source: src(
        "https://www.uefa.com/uefachampionsleague/news/024d-0e98dfcc2153-58a26dbcbccf-1000--champions-league-world-cup-double/",
        "UEFA · Players who featured in both winning finals",
      ),
    },
    [
      [
        "Sepp Maier",
        4,
        "Played in Bayern and West Germany’s winning finals in 1974.",
        "Maier;Josef Maier",
      ],
      [
        "Paul Breitner",
        4,
        "Played in Bayern and West Germany’s winning finals in 1974.",
        "Breitner",
      ],
      [
        "Hans-Georg Schwarzenbeck",
        5,
        "Played in Bayern and West Germany’s winning finals in 1974.",
        "Schwarzenbeck;Hans Georg Schwarzenbeck",
      ],
      [
        "Franz Beckenbauer",
        2,
        "Captained Bayern and West Germany to the two trophies in 1974.",
        "Beckenbauer",
      ],
      [
        "Gerd Müller",
        2,
        "Scored in Bayern’s final replay and West Germany’s final in 1974.",
        "Muller;Mueller;Gerd Muller;Gerd Mueller",
      ],
      [
        "Uli Hoeneß",
        5,
        "Played in Bayern and West Germany’s winning finals in 1974.",
        "Hoeness;Uli Hoeness;Ulrich Hoeness;Uli Hoeneß",
      ],
      [
        "Christian Karembeu",
        5,
        "Played in Real Madrid and France’s winning finals in 1998.",
        "Karembeu",
      ],
      [
        "Roberto Carlos",
        2,
        "Played in Real Madrid and Brazil’s winning finals in 2002.",
        "Carlos",
      ],
      [
        "Raphaël Varane",
        1,
        "Played in Real Madrid and France’s winning finals in 2018.",
        "Varane;Raphael Varane",
      ],
    ],
  ),
  q(
    {
      id: "intl-ballon-world-cup-double",
      topic: "awards",
      family: "global-career-crossover",
      category: "The full collection",
      difficulty: "Open goal",
      prompt:
        "Name a player who won both the men’s Ballon d’Or and the men’s World Cup.",
      scope:
        "Competitive Ballon d’Or awards through 2023 and World Cups through 2022. Different years count; being in the winning World Cup squad counts.",
      source: src(
        "https://www.uefa.com/ballondor/news/0292-1c27056169a7-bc88d1fdba43-1000--ballon-d-or-laureates-who-has-won-football-s-most-prestig/",
        "UEFA · Ballon d’Or winners; checked against World Cup squads",
      ),
    },
    [
      [
        "Bobby Charlton",
        4,
        "Won both the World Cup and Ballon d’Or in 1966.",
        "Charlton;Sir Bobby Charlton",
      ],
      [
        "Gerd Müller",
        4,
        "Won the Ballon d’Or in 1970 and World Cup in 1974.",
        "Muller;Mueller;Gerd Muller;Gerd Mueller",
      ],
      [
        "Franz Beckenbauer",
        3,
        "Ballon d’Or winner in 1972 and 1976; World Cup winner in 1974.",
        "Beckenbauer",
      ],
      ["Paolo Rossi", 5, "Won both awards in 1982.", "Rossi"],
      [
        "Lothar Matthäus",
        4,
        "Won both awards in 1990.",
        "Matthaus;Matthaeus;Lothar Matthaus",
      ],
      ["Zinedine Zidane", 2, "Won both awards in 1998.", "Zidane;Zizou"],
      [
        "Ronaldo Nazário",
        1,
        "Ballon d’Or winner in 1997 and 2002; in Brazil’s 1994 and 2002 winning squads.",
        "Ronaldo;Ronaldo Nazario;R9",
      ],
      ["Rivaldo", 4, "Won the Ballon d’Or in 1999 and World Cup in 2002."],
      [
        "Ronaldinho",
        2,
        "Won the World Cup in 2002 and Ballon d’Or in 2005.",
        "Ronaldinho Gaucho",
      ],
      ["Fabio Cannavaro", 3, "Won both awards in 2006.", "Cannavaro"],
      [
        "Kaká",
        4,
        "In Brazil’s 2002 winning squad; won the Ballon d’Or in 2007.",
        "Kaka;Ricardo Kaka",
      ],
      [
        "Lionel Messi",
        1,
        "Won the World Cup in 2022 and eight Ballons d’Or through 2023.",
        "Messi;Leo Messi",
      ],
    ],
  ),
  q(
    {
      id: "intl-ballon-premier-league-alumni",
      topic: "awards",
      family: "ballon-careers",
      category: "They played here",
      difficulty: "Match sharp",
      prompt:
        "Name a men’s Ballon d’Or winner who also played in the Premier League.",
      scope:
        "Ballon d’Or awards through 2023; Premier League appearances from 1992/93 through 2023/24. The award can have been won at another club.",
      source: src(
        "https://www.uefa.com/ballondor/news/0292-1c27056169a7-bc88d1fdba43-1000--ballon-d-or-laureates-who-has-won-football-s-most-prestig/",
        "UEFA · Winners, cross-checked against Premier League careers",
      ),
    },
    [
      [
        "Ruud Gullit",
        5,
        "The 1987 winner played for Chelsea in the Premier League.",
        "Gullit",
      ],
      [
        "George Weah",
        5,
        "The 1995 winner played for Chelsea and Manchester City in 2000.",
        "Weah",
      ],
      [
        "Michael Owen",
        2,
        "The 2001 winner played for Liverpool, Newcastle, Manchester United and Stoke.",
        "Owen",
      ],
      [
        "Andriy Shevchenko",
        4,
        "The 2004 winner played for Chelsea.",
        "Shevchenko;Andrei Shevchenko;Sheva",
      ],
      [
        "Cristiano Ronaldo",
        1,
        "The five-time winner played for Manchester United.",
        "Ronaldo;Cristiano;CR7",
      ],
      [
        "Luka Modrić",
        3,
        "The 2018 winner played for Tottenham.",
        "Modric;Luka Modric",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-opening-goal",
      topic: "world-cup",
      family: "world-cup-openers",
      category: "First on the scoresheet",
      difficulty: "Proper nerd",
      prompt:
        "Name a player credited with the first goal of a men’s World Cup from 1982 to 2022.",
      scope:
        "The first goal of the entire tournament. Both end tournaments included. An own goal counts here.",
      source: src(
        "https://www.fifa.com/en/tournaments/mens/worldcup/articles/players-who-scored-opening-goal",
        "FIFA · Every tournament’s opening goalscorer",
      ),
    },
    [
      [
        "Erwin Vandenbergh",
        5,
        "Scored Belgium’s winner against Argentina to open the scoring in 1982.",
        "Vandenbergh",
      ],
      [
        "Alessandro Altobelli",
        5,
        "Scored for Italy against Bulgaria to open the scoring in 1986.",
        "Altobelli",
      ],
      [
        "François Omam-Biyik",
        4,
        "Scored Cameroon’s winner against Argentina in the 1990 opener.",
        "Omam Biyik;Omam-Biyik;Francois Omam Biyik",
      ],
      [
        "Jürgen Klinsmann",
        3,
        "Scored Germany’s winner against Bolivia in the 1994 opener.",
        "Klinsmann;Jurgen Klinsmann",
      ],
      [
        "César Sampaio",
        5,
        "Scored Brazil’s first goal against Scotland in the 1998 opener.",
        "Sampaio;Cesar Sampaio",
      ],
      [
        "Papa Bouba Diop",
        3,
        "Scored Senegal’s winner against France in the 2002 opener.",
        "Diop;Bouba Diop;Papa Diop",
      ],
      [
        "Philipp Lahm",
        2,
        "Scored Germany’s first goal against Costa Rica in the 2006 opener.",
        "Lahm",
      ],
      [
        "Siphiwe Tshabalala",
        1,
        "Scored South Africa’s goal against Mexico in the 2010 opener.",
        "Tshabalala",
      ],
      [
        "Marcelo",
        4,
        "His own goal for Brazil against Croatia opened the scoring at the 2014 tournament.",
        "Marcelo Vieira",
      ],
      [
        "Yury Gazinsky",
        5,
        "Scored Russia’s first goal against Saudi Arabia in the 2018 opener.",
        "Gazinsky;Gazinskiy;Yuri Gazinsky;Yuriy Gazinskiy;Yury Gazinskiy",
      ],
      [
        "Enner Valencia",
        2,
        "Scored Ecuador’s first goal against Qatar in the 2022 opener.",
        "Valencia",
      ],
    ],
  ),
  q(
    {
      id: "intl-wc-own-goals-2018",
      topic: "world-cup",
      family: "world-cup-own-goals",
      category: "Wrong end",
      difficulty: "Proper nerd",
      prompt:
        "Name a player who scored an own goal at the 2018 men’s World Cup.",
      scope:
        "Russia 2018 only. Official own-goal attribution, not merely a deflected shot.",
      source: src(
        "https://www.rsssf.org/tables/2018full.html",
        "RSSSF · Every Russia 2018 match and scorer",
      ),
    },
    [
      [
        "Aziz Bouhaddouz",
        4,
        "His own goal gave Iran a 1–0 win over Morocco.",
        "Bouhaddouz",
      ],
      [
        "Aziz Behich",
        5,
        "His own goal gave France a 2–1 win over Australia.",
        "Behich",
      ],
      [
        "Oghenekaro Etebo",
        5,
        "Scored an own goal in Nigeria’s 2–0 defeat by Croatia.",
        "Etebo;Peter Etebo;Oghenekaro Peter Etebo",
      ],
      [
        "Thiago Cionek",
        5,
        "Scored an own goal in Poland’s 2–1 defeat by Senegal.",
        "Cionek",
      ],
      [
        "Ahmed Fathi",
        5,
        "Scored an own goal in Egypt’s 3–1 defeat by Russia.",
        "Fathi;Ahmed Fathy;Fathy",
      ],
      [
        "Denis Cheryshev",
        3,
        "Scored an own goal in Russia’s 3–0 defeat by Uruguay.",
        "Cheryshev",
      ],
      [
        "Edson Álvarez",
        4,
        "Scored an own goal in Mexico’s 3–0 defeat by Sweden.",
        "Alvarez;Edson Alvarez",
      ],
      [
        "Yann Sommer",
        3,
        "A Bryan Ruiz penalty rebounded off him for Costa Rica’s late equaliser against Switzerland.",
        "Sommer",
      ],
      [
        "Yassine Meriah",
        5,
        "Scored an own goal in Tunisia’s 2–1 win over Panama.",
        "Meriah;Yassine Meryah",
      ],
      [
        "Sergei Ignashevich",
        4,
        "Scored an own goal against Spain before Russia won the round-of-16 shoot-out.",
        "Ignashevich;Sergey Ignashevich",
      ],
      [
        "Fernandinho",
        2,
        "Scored an own goal in Brazil’s 2–1 quarter-final defeat by Belgium.",
        "Fernando Luiz Roza",
      ],
      [
        "Mario Mandžukić",
        1,
        "Scored an own goal in the final, then also scored for Croatia.",
        "Mandzukic;Mario Mandzukic",
      ],
    ],
  ),
  q(
    {
      id: "intl-euro-golden-boots",
      topic: "awards",
      family: "euro-individual-awards",
      category: "European marksmen",
      difficulty: "Match sharp",
      prompt:
        "Name a men’s EURO Golden Boot winner from Euro 2000 to Euro 2020.",
      scope:
        "Official trophy winners after any tie-breaks; the shared 2000 award counts. Euro 2020 was played in 2021.",
      source: euroAwards,
    },
    [
      [
        "Patrick Kluivert",
        4,
        "Shared the Euro 2000 award with five goals.",
        "Kluivert",
      ],
      [
        "Savo Milošević",
        5,
        "Shared the Euro 2000 award with five goals for Yugoslavia.",
        "Milosevic;Savo Milosevic",
      ],
      [
        "Milan Baroš",
        4,
        "Won the Euro 2004 award with five goals.",
        "Baros;Milan Baros",
      ],
      ["David Villa", 3, "Won the Euro 2008 award with four goals.", "Villa"],
      [
        "Fernando Torres",
        3,
        "Won the Euro 2012 award on tie-breakers with three goals.",
        "Torres",
      ],
      [
        "Antoine Griezmann",
        2,
        "Won the Euro 2016 award with six goals.",
        "Griezmann",
      ],
      [
        "Cristiano Ronaldo",
        1,
        "Won the Euro 2020 award with five goals and one assist.",
        "Ronaldo;Cristiano;CR7",
      ],
    ],
  ),
  q(
    {
      id: "intl-euro-player-of-tournament",
      topic: "awards",
      family: "euro-individual-awards",
      category: "Kings of the summer",
      difficulty: "Match sharp",
      prompt:
        "Name an official men’s EURO Player of the Tournament from 1996 to Euro 2020.",
      scope:
        "UEFA’s official award, introduced in 1996. Euro 2020 was played in 2021.",
      source: euroAwards,
    },
    [
      ["Matthias Sammer", 5, "Won the award at Euro 1996.", "Sammer"],
      ["Zinedine Zidane", 2, "Won the award at Euro 2000.", "Zidane;Zizou"],
      [
        "Theodoros Zagorakis",
        5,
        "Won the award at Euro 2004.",
        "Zagorakis;Theo Zagorakis",
      ],
      ["Xavi", 3, "Won the award at Euro 2008.", "Xavi Hernandez"],
      [
        "Andrés Iniesta",
        2,
        "Won the award at Euro 2012.",
        "Iniesta;Andres Iniesta",
      ],
      ["Antoine Griezmann", 3, "Won the award at Euro 2016.", "Griezmann"],
      [
        "Gianluigi Donnarumma",
        1,
        "Won the award at Euro 2020.",
        "Donnarumma;Gigio Donnarumma",
      ],
    ],
  ),
  q(
    {
      id: "intl-u17-golden-ball-1999-2017",
      topic: "awards",
      family: "youth-golden-ball",
      category: "Wonderkids",
      difficulty: "Proper nerd",
      prompt:
        "Name a men’s Under-17 World Cup Golden Ball winner from 1999 to 2017.",
      scope:
        "Best player of the tournament, not top scorer. Includes the competition’s World Championship name. Both end editions included.",
      source: src(
        "https://www.fifa.com/en/tournaments/mens/u17worldcup/qatar-2025/articles/dates-teams-groups-information-qatar-2025",
        "FIFA · U-17 Golden Ball winners",
      ),
    },
    [
      ["Landon Donovan", 4, "Won the 1999 award for the USA.", "Donovan"],
      [
        "Florent Sinama-Pongolle",
        4,
        "Won the 2001 award for France.",
        "Sinama Pongolle;Sinama-Pongolle;Pongolle",
      ],
      [
        "Cesc Fàbregas",
        2,
        "Won the 2003 award for Spain.",
        "Fabregas;Cesc;Cesc Fabregas;Francesc Fabregas",
      ],
      [
        "Anderson",
        3,
        "Won the 2005 award for Brazil.",
        "Anderson Luis de Abreu Oliveira",
      ],
      ["Toni Kroos", 2, "Won the 2007 award for Germany.", "Kroos"],
      [
        "Sani Emmanuel",
        5,
        "Won the 2009 award for Nigeria.",
        "Emmanuel;Emmanuel Sani",
      ],
      ["Julio Gómez", 5, "Won the 2011 award for Mexico.", "Gomez;Julio Gomez"],
      ["Kelechi Iheanacho", 3, "Won the 2013 award for Nigeria.", "Iheanacho"],
      ["Kelechi Nwakali", 5, "Won the 2015 award for Nigeria.", "Nwakali"],
      ["Phil Foden", 1, "Won the 2017 award for England.", "Foden"],
    ],
  ),
  q(
    {
      id: "intl-u20-golden-ball-1999-2017",
      topic: "awards",
      family: "youth-golden-ball",
      category: "Before they were famous",
      difficulty: "Proper nerd",
      prompt:
        "Name a men’s Under-20 World Cup Golden Ball winner from 1999 to 2017.",
      scope:
        "Best player of the tournament, not top scorer. Includes the competition’s World Youth Championship name. Both end editions included.",
      source: src(
        "https://www.fifa.com/es/tournaments/mens/u20worldcup/chile-2025/articles/messi-pogba-maradona-y-mas-ganadores-balon-de-oro-copa-mundial-sub-20-fifa",
        "FIFA · Every U-20 Golden Ball winner",
      ),
    },
    [
      ["Seydou Keita", 4, "Won the 1999 award for Mali.", "Keita"],
      ["Javier Saviola", 3, "Won the 2001 award for Argentina.", "Saviola"],
      [
        "Ismail Matar",
        5,
        "Won the 2003 award for the United Arab Emirates.",
        "Matar;Ismael Matar;Ismaeil Matar",
      ],
      [
        "Lionel Messi",
        1,
        "Won the 2005 award for Argentina.",
        "Messi;Leo Messi",
      ],
      [
        "Sergio Agüero",
        2,
        "Won the 2007 award for Argentina.",
        "Aguero;Sergio Aguero;Kun Aguero",
      ],
      ["Dominic Adiyiah", 5, "Won the 2009 award for Ghana.", "Adiyiah"],
      [
        "Henrique Almeida",
        5,
        "Won the 2011 award for Brazil.",
        "Henrique;Henrique Almeida Caixeta Neto",
      ],
      ["Paul Pogba", 2, "Won the 2013 award for France.", "Pogba"],
      [
        "Adama Traoré",
        5,
        "Mali’s playmaker, born 28 June 1995, won the 2015 award.",
        "Adama Traore;Traore;Adama Traore Mali",
      ],
      ["Dominic Solanke", 3, "Won the 2017 award for England.", "Solanke"],
    ],
  ),
];
