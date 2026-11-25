import type { Answer, Question } from "./question-types.ts";
type Row = [string, Answer["tier"], string[], string];
const answers = (rows: Row[]): Answer[] =>
  rows.map(([name, tier, aliases, fact]) => ({
    id: name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/-$/g, ""),
    name,
    tier,
    aliases,
    fact,
  }));

export const cultureQuestions: Question[] = [
  {
    id: "ucl-debut-hat-tricks",
    topic: "europe",
    family: "ucl-debut-scoring",
    category: "Some introduction",
    difficulty: "Match sharp",
    prompt:
      "Name a player who scored a hat-trick on their Champions League debut.",
    scope:
      "1992/93–2023/24. First appearance in the competition proper, not a debut for a new club. Qualifiers excluded.",
    source: {
      label: "UEFA · Champions League hat-trick records",
      url: "https://www.uefa.com/uefachampionsleague/news/0257-0e99f0d0d91b-eb0f4ba7a8f7-1000--champions-league-hat-tricks-who-has-the-most-when-was-the-fa/",
    },
    answers: answers([
      [
        "Wayne Rooney",
        1,
        ["Rooney"],
        "Three for Manchester United against Fenerbahçe on his 2004 debut.",
      ],
      [
        "Erling Haaland",
        1,
        ["Haaland"],
        "Three for Salzburg against Genk in 2019.",
      ],
      [
        "Sébastien Haller",
        3,
        ["Haller"],
        "Four for Ajax against Sporting in 2021.",
      ],
      [
        "Marco van Basten",
        3,
        ["Van Basten"],
        "Four for Milan against IFK Göteborg in 1992.",
      ],
      [
        "Faustino Asprilla",
        3,
        ["Asprilla", "Tino Asprilla"],
        "Three for Newcastle against Barcelona in 1997.",
      ],
      [
        "Yakubu Aiyegbeni",
        4,
        ["Yakubu", "Aiyegbeni"],
        "Three for Maccabi Haifa against Olympiacos in 2002.",
      ],
      ["Grafite", 4, [], "Three for Wolfsburg against CSKA Moscow in 2009."],
      [
        "Yacine Brahimi",
        5,
        ["Brahimi"],
        "Three for Porto against BATE Borisov in 2014.",
      ],
      [
        "Mislav Oršić",
        5,
        ["Orsic"],
        "Three for Dinamo Zagreb against Atalanta in 2019.",
      ],
      [
        "Vincenzo Iaquinta",
        5,
        ["Iaquinta"],
        "Three for Udinese against Panathinaikos on his group-stage debut.",
      ],
    ]),
  },
  {
    id: "old-european-cup-only",
    topic: "europe",
    family: "european-champion-clubs",
    category: "Before the rebrand",
    difficulty: "Match sharp",
    prompt:
      "Name a European Cup winner that has NEVER won the Champions League era competition.",
    scope:
      "As of the end of 2023/24. Won before 1992/93, but not from 1992/93 onwards. Clubs, not countries.",
    source: {
      label: "UEFA · European champions honours board",
      url: "https://www.uefa.com/news/0275-1541637ad1db-88aeeefefefd-1000--all-time-european-cup-honours-board/",
    },
    answers: answers([
      [
        "Nottingham Forest",
        1,
        ["Forest", "Notts Forest"],
        "European champions in 1979 and 1980.",
      ],
      ["Aston Villa", 2, ["Villa"], "Beat Bayern in the 1982 final."],
      ["Celtic", 2, [], "The Lisbon Lions won in 1967."],
      [
        "Benfica",
        3,
        ["SL Benfica"],
        "Won consecutive European Cups in 1961 and 1962.",
      ],
      ["PSV Eindhoven", 4, ["PSV"], "Won the 1988 final on penalties."],
      [
        "Hamburg",
        4,
        ["Hamburger SV", "HSV"],
        "Beat Juventus in the 1983 final.",
      ],
      [
        "Feyenoord",
        4,
        ["Feyenoord Rotterdam"],
        "The first Dutch European champions, in 1970.",
      ],
      [
        "Red Star Belgrade",
        5,
        ["Crvena Zvezda", "Red Star", "FK Crvena Zvezda"],
        "Won the 1991 final on penalties.",
      ],
      [
        "Steaua București",
        5,
        ["Steaua", "Steaua Bucharest", "FCSB", "CSA Steaua"],
        "The 1986 champions beat Barcelona on penalties.",
      ],
    ]),
  },
  {
    id: "ucl-finalists-without-win-2024",
    topic: "europe",
    family: "european-final-heartbreak",
    category: "So near, so far",
    difficulty: "Open goal",
    prompt:
      "Name a Champions League finalist that had NEVER won the European Cup by 2024.",
    scope:
      "Reached a final in 1992/93–2023/24; no European Cup or Champions League title by 1 June 2024. Later wins do not count.",
    source: {
      label: "UEFA · final records and statistics",
      url: "https://www.uefa.com/uefachampionsleague/news/0252-0e98c715bb79-dea77f56e2bd-1000--champions-league-final-records-and-statistics/",
    },
    answers: answers([
      ["Arsenal", 1, ["Arsenal FC"], "Lost the 2006 final to Barcelona."],
      [
        "Tottenham Hotspur",
        1,
        ["Tottenham", "Spurs"],
        "Lost the 2019 final to Liverpool.",
      ],
      [
        "Paris Saint-Germain",
        2,
        ["PSG", "Paris Saint Germain", "Paris"],
        "Lost to Bayern in 2020; still without a title at this question’s 2024 cutoff.",
      ],
      [
        "Atlético Madrid",
        3,
        ["Atletico", "Atleti", "Atletico de Madrid"],
        "Lost the 2014 and 2016 Champions League finals to Real Madrid.",
      ],
      [
        "Valencia",
        4,
        ["Valencia CF"],
        "Lost consecutive finals in 2000 and 2001.",
      ],
      [
        "Bayer Leverkusen",
        4,
        ["Leverkusen", "Bayer 04 Leverkusen"],
        "Lost the 2002 final to Real Madrid.",
      ],
      ["Monaco", 5, ["AS Monaco"], "Lost the 2004 final to Porto."],
    ]),
  },
  {
    id: "original-european-treble-clubs",
    topic: "club-history",
    family: "european-trophy-sweep",
    category: "Complete the cabinet",
    difficulty: "Proper nerd",
    prompt:
      "Name a club that won ALL THREE original major UEFA club competitions.",
    scope:
      "European Cup/Champions League + UEFA Cup/Europa League + Cup Winners’ Cup. Men’s teams, through 2023/24. Fairs Cup excluded.",
    source: {
      label: "UEFA · the European clean sweep",
      url: "https://www.uefa.com/uefachampionsleague/news/025d-0f5b873cb860-61d680b0f8bc-1000--who-s-won-a-european-clean-sweep/",
    },
    answers: answers([
      [
        "Manchester United",
        1,
        ["Man United", "Man Utd", "MUFC", "United"],
        "Completed the set with the Europa League in 2017.",
      ],
      [
        "Chelsea",
        2,
        ["Chelsea FC"],
        "Completed the set with the Europa League in 2013.",
      ],
      [
        "Juventus",
        3,
        ["Juve"],
        "Completed the set with the European Cup in 1985.",
      ],
      [
        "Bayern Munich",
        4,
        ["Bayern", "Bayern Munchen", "FC Bayern"],
        "Completed the set with the UEFA Cup in 1996.",
      ],
      [
        "Ajax",
        5,
        ["Ajax Amsterdam", "AFC Ajax"],
        "Completed the set with the UEFA Cup in 1992.",
      ],
    ]),
  },
  {
    id: "english-real-madrid-2024",
    topic: "careers",
    family: "english-abroad",
    category: "An Englishman abroad",
    difficulty: "Open goal",
    prompt:
      "Name an English player who played for Real Madrid before summer 2024.",
    scope:
      "Men’s first-team appearances, through 2023/24. Later signings are excluded.",
    source: {
      label: "AS · Real Madrid’s English players",
      url: "https://en.as.com/soccer/jude-bellingham-signs-with-real-madrid-what-other-english-players-have-played-with-los-blancos-n/",
    },
    answers: answers([
      [
        "Jude Bellingham",
        1,
        ["Bellingham"],
        "Joined from Borussia Dortmund in 2023.",
      ],
      [
        "David Beckham",
        1,
        ["Beckham", "Becks"],
        "Joined from Manchester United in 2003.",
      ],
      ["Michael Owen", 2, ["Owen"], "Joined from Liverpool in 2004."],
      [
        "Steve McManaman",
        3,
        ["McManaman", "Macca"],
        "Joined from Liverpool in 1999.",
      ],
      ["Jonathan Woodgate", 4, ["Woodgate"], "Joined from Newcastle in 2004."],
      [
        "Laurie Cunningham",
        5,
        ["Cunningham"],
        "Joined from West Brom in 1979.",
      ],
    ]),
  },
  {
    id: "arsenal-united-direct-transfers",
    topic: "transfers",
    family: "direct-rival-transfers",
    category: "Crossing the divide",
    difficulty: "Match sharp",
    prompt:
      "Name a player transferred DIRECTLY between Arsenal and Manchester United in the Premier League era.",
    scope:
      "1992/93–2023/24, either direction. Men’s senior players; no club in between. Youth-only moves excluded.",
    source: {
      label: "Arsenal · played for both clubs",
      url: "https://www.arsenal.com/feature/played-for-both-arsenal-and-manchester-united-aVItg8P1Y7ht",
    },
    answers: answers([
      [
        "Robin van Persie",
        1,
        ["Van Persie", "RVP"],
        "Arsenal to United in 2012.",
      ],
      [
        "Alexis Sánchez",
        2,
        ["Alexis", "Sanchez"],
        "Arsenal to United in the January 2018 swap.",
      ],
      ["Danny Welbeck", 3, ["Welbeck"], "United to Arsenal in 2014."],
      [
        "Henrikh Mkhitaryan",
        4,
        ["Mkhitaryan", "Mkhitarian", "Micki", "Miki"],
        "United to Arsenal in the January 2018 swap.",
      ],
      ["Mikaël Silvestre", 5, ["Silvestre"], "United to Arsenal in 2008."],
    ]),
  },
  {
    id: "united-number-seven",
    topic: "club-history",
    family: "iconic-shirt-numbers",
    category: "The weight of the shirt",
    difficulty: "Match sharp",
    prompt:
      "Name a Manchester United player assigned the number 7 in the permanent squad-number era.",
    scope:
      "Men’s first team, 1993/94–2023/24. Not players who wore it before permanent squad numbers began.",
    source: {
      label: "GOAL · United’s number sevens",
      url: "https://www.goal.com/en/lists/cantona-to-ronaldo-beckham-to-alexis---a-history-of-man-utds-no7s/1rcob73dm9a5m11zoypcch2mra",
    },
    answers: answers([
      [
        "Cristiano Ronaldo",
        1,
        ["Ronaldo", "CR7", "Cristiano"],
        "Number 7 in both his United spells.",
      ],
      [
        "David Beckham",
        1,
        ["Beckham", "Becks"],
        "Took number 7 after Cantona retired in 1997.",
      ],
      [
        "Eric Cantona",
        2,
        ["Cantona", "King Eric"],
        "United’s permanent number 7 from 1993.",
      ],
      ["Mason Mount", 2, ["Mount"], "Received number 7 on joining in 2023."],
      [
        "Edinson Cavani",
        3,
        ["Cavani"],
        "Wore number 7 before Ronaldo returned in 2021.",
      ],
      [
        "Alexis Sánchez",
        3,
        ["Alexis", "Sanchez"],
        "Given number 7 on his 2018 arrival.",
      ],
      [
        "Ángel Di María",
        4,
        ["Di Maria", "Angel Di Maria"],
        "Wore number 7 in 2014/15.",
      ],
      [
        "Memphis Depay",
        4,
        ["Depay", "Memphis"],
        "Took number 7 when he arrived in 2015.",
      ],
      ["Michael Owen", 4, ["Owen"], "Inherited number 7 in 2009."],
      [
        "Antonio Valencia",
        5,
        ["Valencia"],
        "Wore number 7 for 2012/13, then returned to 25.",
      ],
    ]),
  },
  {
    id: "world-record-transfers-1992-2017",
    topic: "transfers",
    family: "transfer-fee-records",
    category: "Break the bank",
    difficulty: "Open goal",
    prompt:
      "Name a player whose transfer broke the WORLD transfer-fee record between 1992 and 2017.",
    scope:
      "Men’s football. Record fees measured in pounds sterling, including Neymar’s 2017 move. Specify which Ronaldo.",
    source: {
      label: "Sky Sports · world-record transfer timeline",
      url: "https://www.skysports.com/football/news/10962312/the-soaring-world-record-fee",
    },
    answers: answers([
      [
        "Neymar",
        1,
        ["Neymar Jr", "Neymar Junior"],
        "Barcelona to Paris Saint-Germain, 2017.",
      ],
      [
        "Cristiano Ronaldo",
        1,
        ["Cristiano", "CR7"],
        "Manchester United to Real Madrid, 2009.",
      ],
      ["Gareth Bale", 2, ["Bale"], "Tottenham to Real Madrid, 2013."],
      ["Paul Pogba", 2, ["Pogba"], "Juventus to Manchester United, 2016."],
      [
        "Zinedine Zidane",
        2,
        ["Zidane", "Zizou"],
        "Juventus to Real Madrid, 2001.",
      ],
      [
        "Ronaldo Nazário",
        3,
        ["R9", "Brazilian Ronaldo", "Ronaldo Nazario de Lima"],
        "PSV to Barcelona in 1996; Barcelona to Inter in 1997.",
      ],
      ["Luís Figo", 3, ["Figo"], "Barcelona to Real Madrid, 2000."],
      ["Alan Shearer", 3, ["Shearer"], "Blackburn to Newcastle, 1996."],
      ["Kaká", 3, ["Ricardo Kaka"], "AC Milan to Real Madrid, 2009."],
      ["Hernán Crespo", 4, ["Crespo"], "Parma to Lazio, 2000."],
      ["Christian Vieri", 4, ["Vieri", "Bobo Vieri"], "Lazio to Inter, 1999."],
      [
        "Denílson",
        5,
        ["Denilson de Oliveira"],
        "São Paulo to Real Betis, 1998.",
      ],
      [
        "Jean-Pierre Papin",
        4,
        ["Papin", "JPP"],
        "Marseille to AC Milan, 1992.",
      ],
      ["Gianluca Vialli", 4, ["Vialli"], "Sampdoria to Juventus, 1992."],
      [
        "Gianluigi Lentini",
        5,
        ["Lentini", "Gigi Lentini"],
        "Torino to AC Milan, 1992.",
      ],
    ]),
  },
  {
    id: "etoo-league-career-clubs",
    topic: "careers",
    family: "journeyman-career-clubs",
    category: "The scenic route",
    difficulty: "Match sharp",
    prompt: "Name a club Samuel Eto’o played a senior LEAGUE match for.",
    scope:
      "His complete playing career. Senior league appearances only. Loans count; youth and reserve teams do not.",
    source: {
      label: "FotMob · Samuel Eto’o career",
      url: "https://www.fotmob.com/players/33639/samuel-etoo",
    },
    answers: answers([
      [
        "Barcelona",
        1,
        ["Barca", "FC Barcelona"],
        "Played league football for Barcelona from 2004 to 2009.",
      ],
      [
        "Inter Milan",
        2,
        ["Inter", "Internazionale", "Internazionale Milano"],
        "Played league football for Inter from 2009 to 2011.",
      ],
      [
        "Chelsea",
        2,
        ["Chelsea FC"],
        "Played for Chelsea in the 2013/14 Premier League.",
      ],
      ["Everton", 3, ["Everton FC"], "Played for Everton during 2014/15."],
      [
        "Real Madrid",
        3,
        ["Real", "Real Madrid CF", "Madrid"],
        "Made senior La Liga appearances for Real Madrid.",
      ],
      [
        "Mallorca",
        3,
        ["RCD Mallorca", "Real Mallorca"],
        "Played league football for Mallorca from 2000 to 2004.",
      ],
      [
        "Anzhi Makhachkala",
        4,
        ["Anzhi", "Anji", "Anji Makhachkala"],
        "Played in Russia for Anzhi from 2011 to 2013.",
      ],
      [
        "Sampdoria",
        4,
        ["Samp", "UC Sampdoria"],
        "Played in Serie A for Sampdoria in 2015.",
      ],
      [
        "Antalyaspor",
        4,
        ["Antalya"],
        "Played in Turkey for Antalyaspor from 2015 to 2018.",
      ],
      [
        "Leganés",
        5,
        ["Leganes", "CD Leganes"],
        "Played on loan in Spain’s second division in 1997/98.",
      ],
      ["Konyaspor", 5, ["Konya"], "Played for Konyaspor in 2018."],
      [
        "Qatar SC",
        5,
        ["Qatar Sports Club", "Qatar Sport Club"],
        "Finished his league career with Qatar SC in 2018/19.",
      ],
    ]),
  },
  {
    id: "euro-2004-grounds",
    topic: "grounds",
    family: "european-tournament-grounds",
    category: "Passport and scarf",
    difficulty: "Proper nerd",
    prompt: "Name a stadium that hosted a match at Euro 2004.",
    scope:
      "The men’s finals in Portugal. Stadium names, not just the city or home club; familiar shortened names accepted.",
    source: {
      label: "UEFA · Euro 2004 venues",
      url: "https://www.uefa.com/uefaeuro/history/news/025a-0ebef0f75f67-835dd959282d-1000--euro-2004-all-you-need-to-know/",
    },
    answers: answers([
      [
        "Estádio da Luz",
        1,
        ["Da Luz", "Luz", "Estadio do Sport Lisboa e Benfica"],
        "Lisbon venue; hosted the final.",
      ],
      [
        "Estádio do Dragão",
        2,
        ["Dragao", "Do Dragao"],
        "One of the two Porto venues.",
      ],
      [
        "Estádio José Alvalade",
        3,
        ["Jose Alvalade", "Alvalade", "Alvalade XXI"],
        "Lisbon’s other tournament venue.",
      ],
      [
        "Estádio Municipal de Braga",
        4,
        ["Municipal de Braga", "Braga Municipal Stadium", "A Pedreira"],
        "The tournament’s Braga venue.",
      ],
      [
        "Estádio do Bessa",
        4,
        ["Bessa", "Bessa XXI", "Estadio do Bessa XXI"],
        "Porto’s other tournament venue.",
      ],
      [
        "Estádio Algarve",
        4,
        ["Algarve Stadium", "Algarve"],
        "The Faro/Loulé venue.",
      ],
      [
        "Estádio Municipal de Aveiro",
        5,
        ["Municipal de Aveiro", "Aveiro Municipal Stadium"],
        "The tournament’s Aveiro venue.",
      ],
      [
        "Estádio Cidade de Coimbra",
        5,
        ["Cidade de Coimbra", "Coimbra City Stadium"],
        "The tournament’s Coimbra venue.",
      ],
      [
        "Estádio D. Afonso Henriques",
        5,
        ["D Afonso Henriques", "Afonso Henriques", "Dom Afonso Henriques"],
        "The tournament’s Guimarães venue.",
      ],
      [
        "Estádio Dr. Magalhães Pessoa",
        5,
        ["Dr Magalhaes Pessoa", "Magalhaes Pessoa"],
        "The tournament’s Leiria venue.",
      ],
    ]),
  },
];
