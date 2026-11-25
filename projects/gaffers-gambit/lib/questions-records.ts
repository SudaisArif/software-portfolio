import type { Answer, Question } from "./question-types";

// Historical answer sets are frozen at their stated cutoff. Tiers are editorial,
// not a claim about measured community submission rates.
type Row = [
  name: string,
  tier: Answer["tier"],
  fact: string,
  aliases?: string[],
];
const answers = (rows: Row[]): Answer[] =>
  rows.map(([name, tier, fact, aliases = []]) => ({
    id: name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, ""),
    name,
    tier,
    fact,
    aliases,
  }));
const plRecords = {
  label: "Premier League · official records",
  url: "https://www.premierleague.com/en/stats/records",
};
const discipline = {
  label: "Opta Analyst · disciplinary records",
  url: "https://theanalyst.com/articles/premier-league-record-breaking-red-card-season",
};
const euroCoaches = {
  label: "UEFA · European Cup-winning coaches",
  url: "https://www.uefa.com/uefachampionsleague/news/0275-15407684c988-5b733e851bf5-1000--champions-league-winning-coaches-carlo-ancelotti-leads-th/",
};

export const recordQuestions: Question[] = [
  {
    id: "seven-pl-red-cards",
    topic: "discipline",
    family: "career-dismissals",
    category: "Early bath",
    difficulty: "Open goal",
    prompt:
      "Name a player sent off at least seven times in the Premier League.",
    scope:
      "1992/93–2023/24. Official red-card totals; overturned dismissals do not count.",
    source: {
      label: "Opta Analyst · most Premier League red cards",
      url: "https://theanalyst.com/articles/most-premier-league-red-cards",
    },
    answers: answers([
      ["Patrick Vieira", 1, "Eight Premier League dismissals.", ["vieira"]],
      ["Roy Keane", 1, "Seven Premier League dismissals.", ["keane"]],
      [
        "Duncan Ferguson",
        2,
        "Eight Premier League dismissals.",
        ["ferguson", "big dunc"],
      ],
      ["Richard Dunne", 3, "Eight Premier League dismissals.", ["dunne"]],
      [
        "Vinnie Jones",
        3,
        "Seven Premier League dismissals.",
        ["jones", "vinny jones"],
      ],
      ["Lee Cattermole", 4, "Seven Premier League dismissals.", ["cattermole"]],
      [
        "Alan Smith",
        5,
        "Seven Premier League dismissals; the Leeds and Manchester United player.",
        ["smith"],
      ],
    ]),
  },
  {
    id: "three-reds-one-season",
    topic: "discipline",
    family: "season-dismissals",
    category: "Three early baths",
    difficulty: "Proper nerd",
    prompt: "Name a player sent off three times in one Premier League season.",
    scope: "Completed seasons through 2022/23. Overturned dismissals excluded.",
    source: discipline,
    answers: answers([
      ["Vinnie Jones", 1, "Wimbledon, 1995/96.", ["jones", "vinny jones"]],
      ["Victor Wanyama", 2, "Southampton, 2015/16.", ["wanyama"]],
      ["Wes Brown", 3, "Sunderland, 2013/14.", ["brown"]],
      ["Slaven Bilić", 3, "Everton, 1997/98.", ["bilic"]],
      ["David Batty", 4, "Newcastle, 1997/98.", ["batty"]],
      [
        "Franck Queudrue",
        5,
        "Middlesbrough, 2002/03.",
        ["queudrue", "frank queudrue"],
      ],
      ["Craig Short", 5, "Blackburn, 2001/02.", ["short"]],
    ]),
  },
  {
    id: "fourteen-bookings-season",
    topic: "discipline",
    family: "season-bookings",
    category: "Walking a tightrope",
    difficulty: "Proper nerd",
    prompt:
      "Name a player who collected 14 yellow cards in one Premier League season.",
    scope: "Completed seasons through 2022/23.",
    source: discipline,
    answers: answers([
      ["João Palhinha", 1, "Fulham, 2022/23.", ["palhinha"]],
      ["Lee Cattermole", 2, "Sunderland, 2014/15.", ["cattermole"]],
      ["Robbie Savage", 2, "Leicester, 2001/02.", ["savage"]],
      ["Cheick Tioté", 3, "Newcastle, 2010/11.", ["tiote"]],
      ["José Holebas", 4, "Watford, 2016/17.", ["holebas"]],
      ["Étienne Capoue", 4, "Watford, 2018/19.", ["capoue"]],
      ["Mark Hughes", 5, "Southampton, 1998/99.", ["hughes", "sparky"]],
    ]),
  },
  {
    id: "eight-team-reds-season",
    topic: "discipline",
    family: "club-dismissals",
    category: "Lost their heads",
    difficulty: "Proper nerd",
    prompt:
      "Name a club shown at least eight red cards in a single Premier League season.",
    scope: "Completed seasons through 2022/23.",
    source: discipline,
    answers: answers([
      ["Sunderland", 2, "Nine in 2009/10.", ["sunderland afc"]],
      ["Queens Park Rangers", 2, "Nine in 2011/12.", ["qpr", "queens park"]],
      ["Newcastle United", 3, "Eight in 2008/09.", ["newcastle", "nufc"]],
      ["Blackburn Rovers", 4, "Eight in 1998/99.", ["blackburn"]],
      ["West Ham United", 4, "Eight in 1999/00.", ["west ham", "whu"]],
      ["Leicester City", 5, "Eight in 1994/95.", ["leicester"]],
    ]),
  },
  {
    id: "pl-away-winless-season",
    topic: "club-history",
    family: "away-season-records",
    category: "Travel sickness",
    difficulty: "Proper nerd",
    prompt:
      "Name a club that finished a full Premier League season without an away win.",
    scope: "1992/93–2023/24.",
    source: plRecords,
    answers: answers([
      ["Derby County", 1, "Winless away in 2007/08.", ["derby"]],
      ["Norwich City", 2, "Winless away in 2004/05.", ["norwich"]],
      ["Hull City", 3, "Winless away in 2009/10.", ["hull"]],
      [
        "Wolverhampton Wanderers",
        3,
        "Winless away in 2003/04.",
        ["wolves", "wolverhampton"],
      ],
      ["Coventry City", 4, "Winless away in 1999/00.", ["coventry"]],
      ["Leeds United", 5, "Winless away in 1992/93.", ["leeds"]],
    ]),
  },
  {
    id: "bottom-christmas-survivors",
    topic: "club-history",
    family: "relegation-escapes",
    category: "Great escapes",
    difficulty: "Match sharp",
    prompt:
      "Name a Premier League club that survived after being bottom at Christmas.",
    scope: "1992/93–2023/24.",
    source: plRecords,
    answers: answers([
      ["Leicester City", 1, "Escaped in 2014/15.", ["leicester"]],
      [
        "West Bromwich Albion",
        2,
        "Escaped in 2004/05.",
        ["west brom", "wba", "west bromwich"],
      ],
      ["Sunderland", 3, "Escaped in 2013/14.", ["sunderland afc"]],
      [
        "Wolverhampton Wanderers",
        5,
        "Escaped in 2022/23.",
        ["wolves", "wolverhampton"],
      ],
    ]),
  },
  {
    id: "pl-five-thousand-milestones",
    topic: "records",
    family: "milestone-goals",
    category: "Round numbers",
    difficulty: "Proper nerd",
    prompt:
      "Name a scorer of the Premier League’s 5,000th, 10,000th, 15,000th, 20,000th, 25,000th or 30,000th goal.",
    scope: "The six 5,000-goal milestones from 1996 to 2021.",
    source: plRecords,
    answers: answers([
      [
        "Zlatan Ibrahimović",
        1,
        "25,000th: Manchester United, 2016.",
        ["zlatan", "ibrahimovic", "ibra"],
      ],
      ["Chris Wood", 2, "30,000th: Burnley, 2021.", ["wood"]],
      [
        "Les Ferdinand",
        3,
        "10,000th: Tottenham, 2001.",
        ["ferdinand", "sir les"],
      ],
      ["Marc Albrighton", 4, "20,000th: Aston Villa, 2011.", ["albrighton"]],
      ["Chris Sutton", 4, "5,000th: Blackburn, 1996.", ["sutton"]],
      ["Moritz Volz", 5, "15,000th: Fulham, 2006.", ["volz"]],
    ]),
  },
  {
    id: "two-own-goals-match",
    topic: "records",
    family: "own-goal-misfortune",
    category: "Wrong end",
    difficulty: "Match sharp",
    prompt:
      "Name a player who scored two own goals in the same Premier League match.",
    scope: "1992/93–2023/24.",
    source: {
      label: "Opta Analyst · own-goal records",
      url: "https://theanalyst.com/articles/most-premier-league-own-goals-by-a-player",
    },
    answers: answers([
      ["Wout Faes", 1, "Leicester against Liverpool, December 2022.", ["faes"]],
      [
        "Jamie Carragher",
        2,
        "Liverpool against Manchester United, September 1999.",
        ["carragher", "carra"],
      ],
      [
        "Jonathan Walters",
        3,
        "Stoke against Chelsea, January 2013.",
        ["walters", "jon walters"],
      ],
      [
        "Michael Proctor",
        5,
        "Sunderland against Charlton, February 2003.",
        ["proctor"],
      ],
    ]),
  },
  {
    id: "european-cup-two-clubs-coaches",
    topic: "managers",
    family: "multi-club-european-champions",
    category: "Portable genius",
    difficulty: "Open goal",
    prompt:
      "Name a manager who won the European Cup or Champions League with two different clubs.",
    scope: "1955/56–2023/24. Head coaches only.",
    source: euroCoaches,
    answers: answers([
      [
        "Carlo Ancelotti",
        1,
        "Champions with AC Milan and Real Madrid.",
        ["ancelotti", "carlo"],
      ],
      [
        "José Mourinho",
        1,
        "Champions with Porto and Inter.",
        ["mourinho", "jose", "the special one"],
      ],
      [
        "Pep Guardiola",
        2,
        "Champions with Barcelona and Manchester City.",
        ["guardiola", "pep"],
      ],
      [
        "Jupp Heynckes",
        3,
        "Champions with Real Madrid and Bayern.",
        ["heynckes"],
      ],
      [
        "Ottmar Hitzfeld",
        4,
        "Champions with Dortmund and Bayern.",
        ["hitzfeld"],
      ],
      ["Ernst Happel", 5, "Champions with Feyenoord and Hamburg.", ["happel"]],
    ]),
  },
  {
    id: "european-cup-player-and-coach",
    topic: "careers",
    family: "player-to-european-coach",
    category: "Boots to dugout",
    difficulty: "Match sharp",
    prompt:
      "Name someone who won the European Cup or Champions League as both a player and a head coach.",
    scope: "Through the 2024 final.",
    source: {
      label: "UEFA · European Cup winners as player and coach",
      url: "https://www.uefa.com/uefachampionsleague/news/0250-0c51196decb5-ce25aa1fbc43-1000--zidane-completes-player-coach-double-double/",
    },
    answers: answers([
      [
        "Zinedine Zidane",
        1,
        "Real Madrid player in 2002; winning coach from 2016.",
        ["zidane", "zizou"],
      ],
      [
        "Pep Guardiola",
        1,
        "Barcelona player in 1992; winning coach from 2009.",
        ["pep", "guardiola"],
      ],
      [
        "Carlo Ancelotti",
        2,
        "Milan player in 1989; winning coach from 2003.",
        ["ancelotti", "carlo"],
      ],
      [
        "Johan Cruyff",
        3,
        "Ajax player in 1971; Barcelona coach in 1992.",
        ["cruyff", "cruijff", "johan cruijff"],
      ],
      [
        "Frank Rijkaard",
        4,
        "Milan player in 1989; Barcelona coach in 2006.",
        ["rijkaard"],
      ],
      [
        "Giovanni Trapattoni",
        5,
        "Milan player in 1963; Juventus coach in 1985.",
        ["trapattoni", "trap"],
      ],
      [
        "Miguel Muñoz",
        5,
        "Real Madrid player in 1956; winning coach in 1960.",
        ["munoz"],
      ],
    ]),
  },
  {
    id: "english-title-two-clubs-managers",
    topic: "managers",
    family: "multi-club-english-champions",
    category: "Do it somewhere else",
    difficulty: "Proper nerd",
    prompt:
      "Name a manager who won the English top-flight title with two different clubs.",
    scope: "Football League and Premier League, through 2023/24.",
    source: {
      label: "Liverpool FC · Tom Watson and English title history",
      url: "https://www.liverpoolfc.com/news/innovator-man-intertwined-history-liverpool-and-sunderland",
    },
    answers: answers([
      [
        "Kenny Dalglish",
        1,
        "Champions with Liverpool and Blackburn.",
        ["dalglish", "king kenny"],
      ],
      [
        "Brian Clough",
        2,
        "Champions with Derby and Nottingham Forest.",
        ["clough", "cloughie"],
      ],
      [
        "Herbert Chapman",
        4,
        "Champions with Huddersfield and Arsenal.",
        ["chapman"],
      ],
      [
        "Tom Watson",
        5,
        "Champions with Sunderland and Liverpool.",
        ["watson", "thomas watson"],
      ],
    ]),
  },
  {
    id: "pl-five-club-managers",
    topic: "managers",
    family: "managerial-journeymen",
    category: "Been around the block",
    difficulty: "Match sharp",
    prompt:
      "Name a manager who took charge of at least five different Premier League clubs.",
    scope:
      "1992/93–2023/24. Must have managed a Premier League match for each club.",
    source: {
      label: "Premier League · managers with multiple PL clubs",
      url: "https://www.premierleague.com/en/news/644410",
    },
    answers: answers([
      [
        "Sam Allardyce",
        1,
        "His ninth Premier League club was Leeds in 2023.",
        ["allardyce", "big sam"],
      ],
      [
        "Roy Hodgson",
        2,
        "His sixth Premier League club was Watford in 2022.",
        ["hodgson"],
      ],
      [
        "Harry Redknapp",
        2,
        "West Ham, Portsmouth, Southampton, Tottenham and QPR.",
        ["redknapp"],
      ],
      [
        "Mark Hughes",
        3,
        "Blackburn, Manchester City, Fulham, QPR, Stoke and Southampton.",
        ["hughes", "sparky"],
      ],
      [
        "Steve Bruce",
        4,
        "Birmingham, Wigan, Sunderland, Hull and Newcastle.",
        ["bruce"],
      ],
      [
        "Alan Pardew",
        5,
        "West Ham, Charlton, Newcastle, Crystal Palace and West Brom.",
        ["pardew"],
      ],
    ]),
  },
  {
    id: "hat-tricks-three-pl-clubs",
    topic: "goals",
    family: "multi-club-hat-tricks",
    category: "Three for three",
    difficulty: "Proper nerd",
    prompt:
      "Name a player who scored Premier League hat-tricks for three different clubs.",
    scope:
      "1992/93–2023/24. A four-goal or five-goal game also counts as a hat-trick.",
    source: {
      label: "Opta Analyst · hat-trick records",
      url: "https://theanalyst.com/articles/final-day-hat-tricks-premier-league",
    },
    answers: answers([
      [
        "Nicolas Anelka",
        1,
        "Arsenal, Manchester City and Chelsea.",
        ["anelka"],
      ],
      [
        "Teddy Sheringham",
        2,
        "Tottenham, Manchester United and Portsmouth.",
        ["sheringham"],
      ],
      [
        "Yakubu",
        3,
        "Portsmouth, Everton and Blackburn.",
        ["yakubu ayegbeni", "ayegbeni", "the yak"],
      ],
      [
        "Les Ferdinand",
        4,
        "QPR, Newcastle and Tottenham.",
        ["ferdinand", "sir les"],
      ],
      [
        "Kevin Campbell",
        5,
        "Arsenal, Nottingham Forest and Everton.",
        ["campbell", "super kev"],
      ],
    ]),
  },
  {
    id: "pl-hat-trick-in-defeat",
    topic: "goals",
    family: "losing-hat-tricks",
    category: "Match ball, no points",
    difficulty: "Proper nerd",
    prompt:
      "Name a player who scored a Premier League hat-trick and still lost the match.",
    scope: "1992/93–2023/24. A defeat, not a draw.",
    source: {
      label: "Sky Sports · Premier League hat-tricks without a win",
      url: "https://www.skysports.com/football/news/9795058/hat-trick-heroes-the-15-men-to-hit-a-premier-league-hat-trick-and-still-not-be-on-the-winning-side",
    },
    answers: answers([
      [
        "Matt Le Tissier",
        1,
        "Southampton lost despite his hat-tricks in 1993 and 1995.",
        ["le tissier", "letissier", "le tiss", "matthew le tissier"],
      ],
      [
        "Dwight Yorke",
        2,
        "Aston Villa lost 4–3 at Newcastle in 1996.",
        ["yorke"],
      ],
      [
        "Roque Santa Cruz",
        4,
        "Blackburn lost 5–3 at Wigan in 2007.",
        ["santa cruz", "santacruz"],
      ],
      [
        "Dion Dublin",
        5,
        "Coventry lost 4–3 to Sheffield Wednesday in 1995.",
        ["dublin"],
      ],
    ]),
  },
  {
    id: "pl-four-assists-match",
    topic: "records",
    family: "single-match-assists",
    category: "Serving them up",
    difficulty: "Match sharp",
    prompt:
      "Name a player credited with four assists in one Premier League match.",
    scope:
      "1992/93–2023/24. Official Premier League/Opta assists, not Fantasy assists.",
    source: {
      label: "Opta Analyst · Premier League assist records",
      url: "https://theanalyst.com/articles/most-premier-league-assists-players",
    },
    answers: answers([
      ["Harry Kane", 1, "Tottenham against Southampton, 2020.", ["kane"]],
      ["Paul Pogba", 1, "Manchester United against Leeds, 2021.", ["pogba"]],
      [
        "Jérémy Doku",
        2,
        "Manchester City against Bournemouth, 2023.",
        ["doku"],
      ],
      [
        "Cesc Fàbregas",
        2,
        "Arsenal against Blackburn, 2009.",
        ["fabregas", "cesc", "francesc fabregas"],
      ],
      ["Dennis Bergkamp", 3, "Arsenal against Leicester, 1999.", ["bergkamp"]],
      [
        "Santi Cazorla",
        3,
        "Arsenal against Wigan, 2013.",
        ["cazorla", "santiago cazorla"],
      ],
      [
        "Emmanuel Adebayor",
        4,
        "Tottenham against Newcastle, 2012.",
        ["adebayor"],
      ],
      [
        "José Antonio Reyes",
        5,
        "Arsenal against Middlesbrough, 2006.",
        ["reyes", "jose reyes"],
      ],
    ]),
  },
  {
    id: "fa-cup-outside-top-flight",
    topic: "club-history",
    family: "cup-underdogs",
    category: "Cup upsets",
    difficulty: "Match sharp",
    prompt:
      "Name a club that won the FA Cup while playing outside the top flight.",
    scope:
      "From the Football League’s foundation in 1888 through the 2024 final. Division during the winning season.",
    source: {
      label: "RSSSF · FA Cup finalists by division",
      url: "https://rsssf.org/rssbest/fa2.html",
    },
    answers: answers([
      [
        "West Ham United",
        1,
        "Second Division winners of the 1980 final.",
        ["west ham", "whu"],
      ],
      [
        "Sunderland",
        2,
        "Second Division winners of the 1973 final.",
        ["sunderland afc"],
      ],
      [
        "Southampton",
        2,
        "Second Division winners of the 1976 final.",
        ["saints"],
      ],
      [
        "Tottenham Hotspur",
        3,
        "Southern League winners of the 1901 final.",
        ["tottenham", "spurs"],
      ],
      [
        "Wolverhampton Wanderers",
        4,
        "Second Division winners of the 1908 final.",
        ["wolves", "wolverhampton"],
      ],
      [
        "West Bromwich Albion",
        4,
        "Second Division winners of the 1931 final.",
        ["west brom", "west bromwich", "wba"],
      ],
      [
        "Barnsley",
        5,
        "Second Division winners of the 1912 final.",
        ["barnsley fc"],
      ],
      [
        "Notts County",
        5,
        "Second Division winners of the 1894 final.",
        ["notts", "notts county fc"],
      ],
    ]),
  },
  {
    id: "forty-year-old-pl-outfielders",
    topic: "careers",
    family: "late-career-appearances",
    category: "Still got it",
    difficulty: "Match sharp",
    prompt:
      "Name an outfield player who played in the Premier League after turning 40.",
    scope: "1992/93–2023/24. Goalkeepers excluded.",
    source: {
      label: "Premier League · outfield appearances after 40",
      url: "https://www.premierleague.com/en/news/4533009/brighton-midfielder-milner-joins-elite-group",
    },
    answers: answers([
      [
        "Ryan Giggs",
        1,
        "Six Premier League appearances aged 40 for Manchester United.",
        ["giggs"],
      ],
      [
        "Teddy Sheringham",
        2,
        "Still playing Premier League football at 40 in 2006.",
        ["sheringham"],
      ],
      [
        "Kevin Phillips",
        4,
        "Four Premier League appearances aged 40 for Crystal Palace.",
        ["phillips"],
      ],
      [
        "Gordon Strachan",
        5,
        "Six Premier League appearances aged 40 for Coventry.",
        ["strachan"],
      ],
    ]),
  },
  {
    id: "champions-straight-after-promotion",
    topic: "club-history",
    family: "promoted-champions",
    category: "Up, then all the way up",
    difficulty: "Proper nerd",
    prompt:
      "Name a club that won the English top-flight title in its first season after promotion.",
    scope:
      "Football League history through 2023/24. Promotion from the second tier, not election to the league.",
    source: {
      label: "RSSSF · English league tables archive",
      url: "https://rsssf.org/engpaul/FLA/league.html",
    },
    answers: answers([
      [
        "Nottingham Forest",
        1,
        "Promoted in 1977; champions in 1977/78.",
        ["nottingham", "forest", "nottm forest"],
      ],
      [
        "Ipswich Town",
        2,
        "Promoted in 1961; champions in 1961/62.",
        ["ipswich"],
      ],
      [
        "Tottenham Hotspur",
        3,
        "Promoted in 1950; champions in 1950/51.",
        ["tottenham", "spurs"],
      ],
      ["Everton", 4, "Promoted in 1931; champions in 1931/32.", ["everton fc"]],
      [
        "Liverpool",
        5,
        "Promoted in 1905; champions in 1905/06.",
        ["lfc", "liverpool fc"],
      ],
    ]),
  },
  {
    id: "all-four-english-tier-champions",
    topic: "club-history",
    family: "four-tier-champions",
    category: "Completed the pyramid",
    difficulty: "Proper nerd",
    prompt:
      "Name a club that has been champion of all four top tiers of English football.",
    scope:
      "Through 2023/24. Historical division names count; regional third-division titles count.",
    source: {
      label: "Football Club History Database · divisional honours",
      url: "https://www.fchd.info/PORTSMOU.HTM",
    },
    answers: answers([
      [
        "Wolverhampton Wanderers",
        1,
        "Completed the set with the 1987/88 Fourth Division title.",
        ["wolves", "wolverhampton"],
      ],
      [
        "Burnley",
        2,
        "Completed the set with the 1991/92 Fourth Division title.",
        ["burnley fc"],
      ],
      [
        "Portsmouth",
        3,
        "Completed the set with the 2016/17 League Two title.",
        ["pompey"],
      ],
      [
        "Sheffield United",
        4,
        "Completed the set with the 2016/17 League One title.",
        ["sheff united", "sheff utd", "sheffield utd", "blades"],
      ],
      [
        "Preston North End",
        5,
        "Completed the set with the fourth-tier title in 1995/96.",
        ["preston", "pne"],
      ],
    ]),
  },
  {
    id: "first-top-flight-in-pl-era",
    topic: "club-history",
    family: "top-flight-debutants",
    category: "First time at the top",
    difficulty: "Match sharp",
    prompt:
      "Name a club whose first-ever English top-flight season came in the Premier League era.",
    scope:
      "Debuts from 1992/93 through 2023/24. Clubs that played in the old First Division do not qualify.",
    source: {
      label: "Premier League clubs · historical membership record",
      url: "https://en.wikipedia.org/wiki/List_of_Premier_League_clubs",
    },
    answers: answers([
      [
        "AFC Bournemouth",
        1,
        "First top-flight season: 2015/16.",
        ["bournemouth"],
      ],
      ["Wigan Athletic", 2, "First top-flight season: 2005/06.", ["wigan"]],
      ["Hull City", 3, "First top-flight season: 2008/09.", ["hull"]],
      ["Reading", 3, "First top-flight season: 2006/07.", ["reading fc"]],
      ["Barnsley", 4, "First top-flight season: 1997/98.", ["barnsley fc"]],
      ["Swindon Town", 5, "First top-flight season: 1993/94.", ["swindon"]],
    ]),
  },
  {
    id: "eight-goal-pl-winning-margin",
    topic: "records",
    family: "record-winning-margins",
    category: "Stop the count",
    difficulty: "Open goal",
    prompt:
      "Name a club that won a Premier League match by at least eight goals.",
    scope: "1992/93–2023/24. Winning margin, so 8–1 does not count.",
    source: {
      label: "Opta Analyst · biggest Premier League wins",
      url: "https://theanalyst.com/articles/biggest-premier-league-wins",
    },
    answers: answers([
      [
        "Manchester United",
        1,
        "Beat Ipswich 9–0 in 1995.",
        ["man united", "man utd", "manchester utd", "mufc"],
      ],
      [
        "Liverpool",
        1,
        "Beat Bournemouth 9–0 in 2022.",
        ["lfc", "liverpool fc"],
      ],
      ["Leicester City", 2, "Won 9–0 at Southampton in 2019.", ["leicester"]],
      [
        "Tottenham Hotspur",
        2,
        "Beat Wigan 9–1 in 2009.",
        ["tottenham", "spurs"],
      ],
      ["Manchester City", 3, "Beat Watford 8–0 in 2019.", ["man city", "mcfc"]],
      ["Chelsea", 3, "Beat Wigan 8–0 in 2010.", ["chelsea fc"]],
      [
        "Newcastle United",
        4,
        "Won 8–0 at Sheffield United in 2023.",
        ["newcastle", "nufc"],
      ],
      ["Southampton", 5, "Beat Sunderland 8–0 in 2014.", ["saints"]],
    ]),
  },
  {
    id: "english-league-fa-cup-double",
    topic: "club-history",
    family: "league-cup-doubles",
    category: "The original Double",
    difficulty: "Open goal",
    prompt:
      "Name a club that won the English top-flight title and FA Cup in the same season.",
    scope:
      "1888/89–2023/24. The league-and-FA-Cup Double; other trophies do not matter.",
    source: {
      label: "FA Cup · league-and-cup doubles record",
      url: "https://en.wikipedia.org/wiki/FA_Cup",
    },
    answers: answers([
      [
        "Manchester United",
        1,
        "First completed the Double in 1993/94.",
        ["man united", "man utd", "manchester utd", "mufc"],
      ],
      ["Arsenal", 1, "First completed the Double in 1970/71.", ["arsenal fc"]],
      [
        "Manchester City",
        1,
        "First completed the Double in 2018/19.",
        ["man city", "mcfc"],
      ],
      ["Chelsea", 2, "Completed the Double in 2009/10.", ["chelsea fc"]],
      [
        "Liverpool",
        2,
        "Completed the Double in 1985/86.",
        ["lfc", "liverpool fc"],
      ],
      [
        "Tottenham Hotspur",
        3,
        "Completed the Double in 1960/61.",
        ["tottenham", "spurs"],
      ],
      ["Aston Villa", 4, "Completed the Double in 1896/97.", ["villa", "avfc"]],
      [
        "Preston North End",
        5,
        "Completed the Double in 1888/89.",
        ["preston", "pne"],
      ],
    ]),
  },
  {
    id: "hat-trick-single-digit-career",
    topic: "goals",
    family: "fleeting-goalscoring-heroes",
    category: "One glorious afternoon",
    difficulty: "Proper nerd",
    prompt:
      "Name a Premier League hat-trick scorer who had fewer than ten career goals in the competition.",
    scope:
      "Career totals at the end of 2023/24. Must have scored at least one hat-trick.",
    source: {
      label: "Opta Analyst · hat-tricks and career totals",
      url: "https://theanalyst.com/articles/final-day-hat-tricks-premier-league",
    },
    answers: answers([
      [
        "Shinji Kagawa",
        1,
        "Six Premier League goals; one hat-trick.",
        ["kagawa"],
      ],
      [
        "Ferran Torres",
        2,
        "Nine Premier League goals; one hat-trick.",
        ["ferran", "torres"],
      ],
      [
        "Gordon Strachan",
        3,
        "Seven Premier League goals; one hat-trick.",
        ["strachan"],
      ],
      [
        "Somen Tchoyi",
        4,
        "Seven Premier League goals; one hat-trick.",
        ["tchoyi"],
      ],
      [
        "Fredi Bobic",
        4,
        "Four Premier League goals; one hat-trick.",
        ["bobic", "freddi bobic"],
      ],
      [
        "Aruna Dindane",
        5,
        "Eight Premier League goals; one hat-trick.",
        ["dindane"],
      ],
      [
        "Clive Mendonca",
        5,
        "Eight Premier League goals; one hat-trick.",
        ["mendonca"],
      ],
    ]),
  },
];
