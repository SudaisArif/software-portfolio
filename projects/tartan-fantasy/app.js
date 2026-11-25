import { money, restoreBanks, spendingLimit } from "./squad-finances.js";

const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: "⌂" },
  { id: "pick-team", label: "Pick Team", icon: "♟" },
  { id: "transfers", label: "Transfers", icon: "⇄" },
  { id: "leagues", label: "Leagues", icon: "≡" },
  { id: "ownership", label: "Ownership", icon: "%" },
  { id: "fixtures", label: "Fixtures", icon: "□" },
  { id: "statistics", label: "Players", icon: "↗" },
  { id: "rules", label: "Rules & Data", icon: "i" }
];

const PAGE_TITLES = Object.fromEntries(NAV_ITEMS.map((item) => [item.id, item.label]));
const MOBILE_NAV = ["overview", "pick-team", "transfers", "leagues", "ownership", "statistics", "rules"].map((id) => {
  const item = NAV_ITEMS.find((item) => item.id === id);
  return id === "rules" ? { ...item, label: "Rules" } : item;
});
const PLAYER_POSITION_ORDER = ["GK", "DEF", "MID", "FWD"];
const POSITION_ORDER = ["DEF", "MID", "FWD"];
const POSITION_LIMITS = { DEF: 2, MID: 2, FWD: 2 };
const POSITION_NAMES = { GK: "Goalkeeper", DEF: "Defender", MID: "Midfielder", FWD: "Forward" };
const SQUAD_POSITION_NAMES = { DEF: "Defender / goalkeeper", MID: "Midfielder", FWD: "Forward" };
const BUDGET = 60;
const BENCH_SIZE = 3;
const STARTER_COUNT = Object.values(POSITION_LIMITS).reduce((total, count) => total + count, 0);
const SQUAD_SIZE = STARTER_COUNT + BENCH_SIZE;
const FREE_TRANSFERS = 2;
const IMPACT_SUB_MULTIPLIER = 1.25;
const IMPACT_SUB_MINUTES = 20;
const FULL_APPEARANCE_MINUTES = 40;
const PRICE_REVIEW_GAMEWEEKS = 3;
const FRESHMAN_BLOCK_EV = 1.5;
const MIN_PLAYER_PRICE = 3.5;
const MAX_PLAYER_PRICE = 12.5;
const CHIP_NAMES = { tripleCaptain: "Triple Captain", benchBoost: "Bench Boost" };
const STORAGE_KEY = "tartan-fantasy-v2";
const DEFAULT_LINEUP = [
  "kai-yamamoto",
  "mateas-fitzwilliam",
  "tristan-gonzalez",
  "dominic-hoar-weiler",
  "idan-garten",
  "justin-fung"
];
const DEFAULT_BENCH = ["nathan-yao", "sola-nishimura", "james-ashby"];

const app = document.querySelector("#app");
const pageTitle = document.querySelector("#page-title");
const teamNameLabel = document.querySelector("#team-name-label");
const dialog = document.querySelector("#player-dialog");
const dialogContent = document.querySelector("#player-dialog-content");
const toast = document.querySelector("#toast");

let data;
let toastTimer;
let countdownTimer;
let liveRefreshTimer;
let preferences = loadPreferences();
let syncedGameweeks = new Set();
let accountUi = { code: null, busy: false };
let leagueUi = {
  loading: false,
  error: "",
  leagues: [],
  activeCode: null,
  standings: null
};
let ui = {
  route: validRoute(location.hash.slice(1)) || "overview",
  gameweek: null,
  marketPosition: "ALL",
  marketSearch: "",
  marketSort: "form",
  statsPosition: "ALL",
  statsSearch: "",
  statsSort: "goals",
  statsSeason: "2026",
  ownershipGameweek: null,
  ownershipPointsGameweek: "overall",
  draftGameweek: null,
  draftPlayers: null,
  draftBench: null
};

function loadPreferences() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return {
      teamName: stored?.teamName || "Scotty’s Select",
      teams: stored?.teams || {},
      theme: stored?.theme || "light",
      manager: stored?.manager || null,
      activeLeagueCode: stored?.activeLeagueCode || null
    };
  } catch {
    return { teamName: "Scotty’s Select", teams: {}, theme: "light", manager: null, activeLeagueCode: null };
  }
}

function savePreferences() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  teamNameLabel.textContent = preferences.teamName;
}

async function apiRequest(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (preferences.manager?.token) headers.Authorization = `Bearer ${preferences.manager.token}`;
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || "League request failed.");
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function syncSquad(gameweek, { discardFuture = true } = {}) {
  if (!preferences.manager) {
    if (discardFuture) discardUnsavedFutureTeams(gameweek);
    return;
  }
  const sessionToken = preferences.manager.token;
  const team = ensureTeam(gameweek);
  const result = await apiRequest(`/api/squads/${gameweek}`, { method: "PUT", body: team });
  if (preferences.manager?.token !== sessionToken) return;
  team.bank = result.bank;
  savePreferences();
  syncedGameweeks.add(Number(gameweek));
  if (discardFuture) discardUnsavedFutureTeams(gameweek);
}

async function syncExistingSquads() {
  let failures = 0;
  for (const gameweek of Object.keys(preferences.teams).map(Number).sort((a, b) => a - b)) {
    try {
      await syncSquad(gameweek, { discardFuture: false });
    } catch {
      failures += 1;
    }
  }
  return failures;
}

function validRoute(route) {
  return NAV_ITEMS.some((item) => item.id === route) ? route : null;
}

function parseCsv(text) {
  const [header, ...lines] = text.trim().split(/\r?\n/);
  const keys = header.split(",");
  return lines.filter(Boolean).map((line) => Object.fromEntries(line.split(",").map((value, index) => [keys[index], value])));
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initials(name) {
  return name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

function surname(name) {
  return name.split(/\s+/).slice(-1)[0];
}

function firstName(name) {
  return name.trim().split(/\s+/)[0];
}

function fieldName(player) {
  const first = firstName(player.name);
  const duplicate = data.players.some((candidate) => candidate.id !== player.id && firstName(candidate.name) === first);
  return duplicate ? `${first} ${surname(player.name)[0]}.` : first;
}

function squadPosition(player) {
  return player?.position === "GK" ? "DEF" : player?.position;
}

function priceOf(playerId) {
  return data.priceById.get(playerId) ?? 5;
}

function statsOf(playerId) {
  return data.statsById.get(playerId) || {
    appearances: 0,
    starts: 0,
    goals: 0,
    assists: 0,
    ncaaPoints: 0,
    shots: 0,
    shotsOnGoal: 0,
    yellowCards: 0,
    redCards: 0,
    minutes: null,
    saves: 0,
    penaltiesSaved: 0,
    shutouts: 0
  };
}

function currentStatsOf(playerId) {
  const totals = {
    appearances: 0,
    starts: 0,
    goals: 0,
    assists: 0,
    shots: 0,
    shotsOnGoal: 0,
    yellowCards: 0,
    redCards: 0,
    minutes: 0,
    saves: 0,
    penaltiesSaved: 0,
    shutouts: 0,
    fantasyPoints: 0
  };
  const player = data.playerById.get(playerId);
  for (const event of data.gameweeks) {
    const stats = gameweekPlayerStats(playerId, event.gameweek);
    if (!stats) continue;
    const minutes = Number(stats.minutes || 0);
    if (minutes > 0) totals.appearances += 1;
    if (stats.started) totals.starts += 1;
    totals.minutes += minutes;
    totals.goals += Number(stats.goals || 0);
    totals.assists += Number(stats.assists || 0);
    totals.shots += Number(stats.shots || 0);
    totals.shotsOnGoal += Number(stats.shotsOnGoal || 0);
    totals.yellowCards += Number(stats.yellowCards || 0);
    totals.redCards += Number(stats.redCards || 0);
    totals.saves += Number(stats.saves || 0);
    totals.penaltiesSaved += Number(stats.penaltiesSaved || 0);
    if (earnedCleanSheet(stats, minutes)) totals.shutouts += 1;
    if (player) totals.fantasyPoints += rawFantasyPoints(player, event.gameweek);
  }
  return totals;
}

function historicalFormScore(player) {
  const stats = statsOf(player.id);
  const goalValue = { GK: 6, DEF: 6, MID: 5, FWD: 4 }[player.position] || 4;
  return Math.round(
    (stats.goals || 0) * goalValue +
    (stats.assists || 0) * 3 +
    (stats.appearances || 0) -
    (stats.yellowCards || 0) -
    (stats.redCards || 0) * 3 +
    (stats.shutouts || 0) * 2
  );
}

function recentFormGameweeks() {
  return (data.gameweeks || [])
    .filter((event) => ["live", "final"].includes(liveScoreFor(event.gameweek)?.state)
      && Object.prototype.hasOwnProperty.call(data.gameweekStats || {}, String(event.gameweek)))
    .sort((a, b) => a.gameweek - b.gameweek)
    .slice(-3);
}

function formScore(player) {
  const events = recentFormGameweeks();
  if (!events.length) return 0;
  const points = events.reduce((total, event) => total + playerPointsForPeriod(player, event.gameweek), 0);
  return Math.round(points / events.length * 10) / 10;
}

function fixtureFor(gameweek) {
  return data.gameweeks.find((event) => event.gameweek === Number(gameweek));
}

function liveScoreFor(gameweek) {
  return data.liveScores?.[String(gameweek)] || null;
}

function easternToday() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function liveLabel(record) {
  if (!record) return "";
  if (record.state === "live") return [record.clock, record.period].filter(Boolean).join(" · ") || "LIVE";
  if (record.state === "final") return "FINAL";
  return "SCHEDULED";
}

function hasScore(record) {
  return record && record.cmuScore !== null && record.opponentScore !== null && record.state !== "pre";
}

function deadlineDate(gameweek) {
  return new Date(fixtureFor(gameweek).deadline);
}

function isLocked(gameweek) {
  return Date.now() >= deadlineDate(gameweek).getTime();
}

function findLiveGameweek() {
  const liveEvent = data.gameweeks.find((event) => liveScoreFor(event.gameweek)?.state === "live");
  if (liveEvent) return liveEvent.gameweek;
  const todayEvent = data.gameweeks.find((event) => event.date === easternToday());
  if (todayEvent) return todayEvent.gameweek;
  return data.gameweeks.find((event) => new Date(event.deadline).getTime() > Date.now())?.gameweek || data.gameweeks.at(-1).gameweek;
}

function affordableSquadSelection(maxBudget = BUDGET) {
  const slots = [];
  const selected = new Set();
  for (const position of POSITION_ORDER) {
    const options = data.players
      .filter((player) => squadPosition(player) === position)
      .sort((a, b) => priceOf(a.id) - priceOf(b.id) || formScore(b) - formScore(a) || a.name.localeCompare(b.name));
    for (const player of options.slice(0, POSITION_LIMITS[position])) {
      slots.push({ role: "starter", position, playerId: player.id });
      selected.add(player.id);
    }
  }
  const bench = data.players
    .filter((player) => !selected.has(player.id))
    .sort((a, b) => priceOf(a.id) - priceOf(b.id) || formScore(b) - formScore(a) || a.name.localeCompare(b.name))
    .slice(0, BENCH_SIZE);
  for (const player of bench) {
    slots.push({ role: "bench", position: null, playerId: player.id });
    selected.add(player.id);
  }
  if (slots.length !== STARTER_COUNT + BENCH_SIZE || lineupCost([...selected]) > maxBudget) return null;

  // Begin with the cheapest legal squad, then spend the available budget on
  // positive form upgrades. Bench form is discounted because substitutes do
  // not normally score, but they still receive some value for Bench Boost.
  while (true) {
    let bestSwap = null;
    const currentCost = lineupCost(slots.map((slot) => slot.playerId));
    const currentIds = new Set(slots.map((slot) => slot.playerId));
    slots.forEach((slot, slotIndex) => {
      const current = data.playerById.get(slot.playerId);
      const roleWeight = slot.role === "starter" ? 1 : 0.25;
      for (const candidate of data.players) {
        if (currentIds.has(candidate.id) || (slot.position && squadPosition(candidate) !== slot.position)) continue;
        const gain = (formScore(candidate) - formScore(current)) * roleWeight;
        const extraCost = priceOf(candidate.id) - priceOf(current.id);
        if (gain <= 0 || currentCost + extraCost > maxBudget + 1e-9) continue;
        const efficiency = extraCost <= 0 ? gain * 1000 : gain / extraCost;
        if (!bestSwap || efficiency > bestSwap.efficiency || (efficiency === bestSwap.efficiency && gain > bestSwap.gain)) {
          bestSwap = { slotIndex, playerId: candidate.id, efficiency, gain };
        }
      }
    });
    if (!bestSwap) break;
    slots[bestSwap.slotIndex].playerId = bestSwap.playerId;
  }

  const players = slots.filter((slot) => slot.role === "starter").map((slot) => slot.playerId);
  const substitutes = slots.filter((slot) => slot.role === "bench").map((slot) => slot.playerId);
  const captainOrder = [...players].sort((a, b) => formScore(data.playerById.get(b)) - formScore(data.playerById.get(a)));
  return { players, bench: substitutes, captain: captainOrder[0], viceCaptain: captainOrder[1], chip: null };
}

function defaultTeam() {
  const affordable = affordableSquadSelection();
  if (affordable) return affordable;
  const validPlayers = DEFAULT_LINEUP.filter((id) => data.playerById.has(id));
  const bench = DEFAULT_BENCH.filter((id) => data.playerById.has(id) && !validPlayers.includes(id));
  return {
    players: validPlayers,
    bench,
    captain: validPlayers.includes("idan-garten") ? "idan-garten" : validPlayers[0] || null,
    viceCaptain: validPlayers.includes("tristan-gonzalez") ? "tristan-gonzalez" : validPlayers[1] || null,
    chip: null
  };
}

function normalizeTeam(team) {
  const fallback = defaultTeam();
  const players = [...new Set((team?.players || []).filter((id) => data.playerById.has(id)))];
  const validStarters = players.length === STARTER_COUNT
    && POSITION_ORDER.every((position) => lineupCounts(players)[position] === POSITION_LIMITS[position]);
  let starters = validStarters ? players : fallback.players;
  const bench = [...new Set((team?.bench || []).filter((id) => data.playerById.has(id) && !starters.includes(id)))];
  const candidates = [...DEFAULT_BENCH, ...[...data.players].sort((a, b) => formScore(b) - formScore(a)).map((player) => player.id)];
  for (const playerId of candidates) {
    if (bench.length >= BENCH_SIZE) break;
    if (!starters.includes(playerId) && !bench.includes(playerId) && data.playerById.has(playerId)) bench.push(playerId);
  }
  if (bench.length !== BENCH_SIZE) {
    starters = [...fallback.players];
    bench.splice(0, bench.length, ...fallback.bench);
  }
  const captain = starters.includes(team?.captain)
    ? team.captain
    : starters.includes(fallback.captain) ? fallback.captain : starters[0];
  const viceCaptain = starters.includes(team?.viceCaptain) && team.viceCaptain !== captain
    ? team.viceCaptain
    : starters.find((id) => id !== captain);
  return {
    players: [...starters],
    bench: bench.slice(0, BENCH_SIZE),
    captain,
    viceCaptain,
    chip: Object.prototype.hasOwnProperty.call(CHIP_NAMES, team?.chip) ? team.chip : null,
    bank: Number.isFinite(team?.bank) ? team.bank : null
  };
}

function ensureTeam(gameweek) {
  const key = String(gameweek);
  if (preferences.teams[key]) {
    const normalized = normalizeTeam(preferences.teams[key]);
    if (JSON.stringify(normalized) !== JSON.stringify(preferences.teams[key])) {
      preferences.teams[key] = normalized;
      savePreferences();
    }
    return preferences.teams[key];
  }
  const earlierKey = Object.keys(preferences.teams)
    .map(Number)
    .filter((value) => value < Number(gameweek))
    .sort((a, b) => b - a)[0];
  const template = normalizeTeam(earlierKey ? preferences.teams[String(earlierKey)] : defaultTeam());
  preferences.teams[key] = {
    players: [...template.players],
    bench: [...(template.bench || [])],
    captain: template.captain,
    viceCaptain: template.viceCaptain,
    chip: null,
    bank: earlierKey
      ? restoredTeams().find((team) => team.gameweek === earlierKey).bank
      : money(BUDGET - lineupCost([...template.players, ...template.bench]))
  };
  preferences.teams[key] = normalizeTeam(preferences.teams[key]);
  savePreferences();
  return preferences.teams[key];
}

function discardUnsavedFutureTeams(savedGameweek) {
  let changed = false;
  for (const key of Object.keys(preferences.teams)) {
    const gameweek = Number(key);
    if (gameweek > Number(savedGameweek) && !syncedGameweeks.has(gameweek)) {
      delete preferences.teams[key];
      changed = true;
    }
  }
  if (changed) {
    ui.draftGameweek = null;
    ui.draftPlayers = null;
    ui.draftBench = null;
    savePreferences();
  }
}

function applyManagerProfile(profile) {
  preferences.manager = { ...preferences.manager, ...profile.manager };
  preferences.teamName = profile.manager.teamName;
  if (profile.squads && typeof profile.squads === "object") {
    const serverTeams = {};
    for (const [gameweek, team] of Object.entries(profile.squads)) {
      serverTeams[String(Number(gameweek))] = normalizeTeam(team);
    }
    const changed = JSON.stringify(serverTeams) !== JSON.stringify(preferences.teams);
    preferences.teams = serverTeams;
    syncedGameweeks = new Set(Object.keys(serverTeams).map(Number));
    if (changed) {
      ui.draftGameweek = null;
      ui.draftPlayers = null;
      ui.draftBench = null;
    }
  }
  savePreferences();
}

function gameweekPlayerStats(playerId, gameweek) {
  return data.gameweekStats?.[String(gameweek)]?.[playerId] || null;
}

function rawFantasyPoints(player, gameweek) {
  const stats = gameweekPlayerStats(player.id, gameweek);
  if (!stats) return 0;
  let points = 0;
  const minutes = Number(stats.minutes || 0);
  if (minutes > 0) points += minutes >= FULL_APPEARANCE_MINUTES ? 2 : 1;
  points += Number(stats.goals || 0) * ({ GK: 6, DEF: 6, MID: 5, FWD: 4 }[player.position] || 4);
  points += Number(stats.assists || 0) * 3;
  if (earnedCleanSheet(stats, minutes)) points += ({ GK: 4, DEF: 4, MID: 1, FWD: 0 }[player.position] || 0);
  if (player.position === "GK") {
    points += Math.floor(Number(stats.saves || 0) / 3);
    points += Number(stats.penaltiesSaved || 0) * 5;
  }
  points -= Number(stats.yellowCards || 0);
  points -= Number(stats.redCards || 0) * 3;
  points -= Number(stats.ownGoals || 0) * 2;
  points -= Number(stats.penaltiesMissed || 0) * 2;
  points += Number(stats.bonus || 0);
  return points;
}

function earnedCleanSheet(stats, minutes = Number(stats?.minutes || 0)) {
  const shutout = stats?.cleanSheet === true || stats?.opponentScore === 0 || stats?.opponentScore === "0";
  return shutout && minutes >= FULL_APPEARANCE_MINUTES;
}

function impactSubFantasyPoints(player, gameweek, raw) {
  const stats = gameweekPlayerStats(player.id, gameweek);
  const eligible = stats?.started === false && Number(stats.minutes || 0) >= IMPACT_SUB_MINUTES;
  return eligible && raw > 0 ? Math.ceil(raw * IMPACT_SUB_MULTIPLIER) : raw;
}

function playerPointsForPeriod(player, period = "overall") {
  const events = period === "overall"
    ? data.gameweeks
    : data.gameweeks.filter((event) => event.gameweek === Number(period));
  return events.reduce((total, event) => total + impactSubFantasyPoints(
    player, event.gameweek, rawFantasyPoints(player, event.gameweek)
  ), 0);
}

function priceReviewMove(actual, expected) {
  const difference = actual - expected;
  if (difference >= 4) return 0.3;
  if (difference >= 2) return 0.2;
  if (difference >= 0.75) return 0.1;
  if (difference <= -4) return -0.3;
  if (difference <= -2) return -0.2;
  if (difference <= -0.75) return -0.1;
  return 0;
}

function recalculatePrices() {
  const prices = new Map(data.basePriceById);
  const reviewsById = new Map(data.players.map((player) => [player.id, []]));
  const reportById = new Map(data.pricingReport.map((row) => [row.player_id, row]));
  const sortedEvents = [...data.gameweeks].sort((a, b) => a.gameweek - b.gameweek);
  const completedBlocks = [];

  for (let start = 0; start + PRICE_REVIEW_GAMEWEEKS <= sortedEvents.length; start += PRICE_REVIEW_GAMEWEEKS) {
    const events = sortedEvents.slice(start, start + PRICE_REVIEW_GAMEWEEKS);
    const ready = events.every((event) => liveScoreFor(event.gameweek)?.state === "final"
      && Object.prototype.hasOwnProperty.call(data.gameweekStats, String(event.gameweek)));
    if (!ready) break;
    completedBlocks.push(events);
  }

  completedBlocks.forEach((events, blockIndex) => {
    data.players.forEach((player) => {
      const careerRating = Number(reportById.get(player.id)?.career_rating || 0);
      const expected = Math.max(FRESHMAN_BLOCK_EV, careerRating / 6);
      const actual = events.reduce((total, event) => {
        const raw = rawFantasyPoints(player, event.gameweek);
        return total + impactSubFantasyPoints(player, event.gameweek, raw);
      }, 0);
      const move = priceReviewMove(actual, expected);
      const previousPrice = prices.get(player.id) ?? 5;
      const currentPrice = Math.min(MAX_PLAYER_PRICE, Math.max(MIN_PLAYER_PRICE, Math.round((previousPrice + move) * 10) / 10));
      const appliedMove = Math.round((currentPrice - previousPrice) * 10) / 10;
      prices.set(player.id, currentPrice);
      reviewsById.get(player.id).push({
        block: blockIndex + 1,
        fromGameweek: events[0].gameweek,
        throughGameweek: events.at(-1).gameweek,
        actual,
        expected: Math.round(expected * 10) / 10,
        move: appliedMove,
        price: currentPrice
      });
    });
  });

  data.priceById = prices;
  data.priceReviewsById = reviewsById;
  data.reviewedThrough = completedBlocks.at(-1)?.at(-1)?.gameweek || 0;
}

function lastPriceReview(playerId) {
  return data.priceReviewsById.get(playerId)?.at(-1) || null;
}

function priceMoveLabel(move) {
  if (!move) return "No change";
  return `${move > 0 ? "+" : "−"}$${Math.abs(move).toFixed(1)}m`;
}

function playerFantasyPoints(player, gameweek, team = ensureTeam(gameweek)) {
  const raw = impactSubFantasyPoints(player, gameweek, rawFantasyPoints(player, gameweek));
  const captainMinutes = Number(gameweekPlayerStats(team.captain, gameweek)?.minutes || 0);
  const effectiveCaptain = captainMinutes > 0 ? team.captain : team.viceCaptain;
  if (effectiveCaptain === player.id) return raw * (team.chip === "tripleCaptain" ? 3 : 2);
  return raw;
}

function previousTeam(gameweek) {
  const earlier = Object.keys(preferences.teams)
    .map(Number)
    .filter((value) => value < Number(gameweek))
    .sort((a, b) => b - a)[0];
  return earlier ? ensureTeam(earlier) : null;
}

function teamPoints(gameweek) {
  const team = ensureTeam(gameweek);
  const starters = team.players.reduce((total, id) => total + playerFantasyPoints(data.playerById.get(id), gameweek, team), 0);
  const bench = team.chip === "benchBoost"
    ? team.bench.reduce((total, id) => total + rawFantasyPoints(data.playerById.get(id), gameweek), 0)
    : 0;
  return starters + bench;
}

function lineupCost(playerIds) {
  return money(playerIds.reduce((sum, id) => sum + priceOf(id), 0));
}

function restoredTeams() {
  return restoreBanks(Object.entries(preferences.teams).map(([gameweek, team]) => ({
    ...team, gameweek: Number(gameweek)
  })), {
    prices: Object.fromEntries(data.priceById),
    reviewsById: Object.fromEntries(data.priceReviewsById)
  }, BUDGET);
}

function transferBudget(gameweek) {
  const team = restoredTeams().filter((entry) => entry.gameweek <= Number(gameweek)
    && (!preferences.manager || syncedGameweeks.has(entry.gameweek))).at(-1);
  return spendingLimit(team, Object.fromEntries(data.priceById), BUDGET);
}

function lineupCounts(playerIds) {
  return playerIds.reduce((counts, id) => {
    const position = squadPosition(data.playerById.get(id));
    if (position) counts[position] += 1;
    return counts;
  }, { DEF: 0, MID: 0, FWD: 0 });
}

function isComplete(playerIds, bench = []) {
  const counts = lineupCounts(playerIds);
  const allPlayers = [...playerIds, ...bench];
  return POSITION_ORDER.every((position) => counts[position] === POSITION_LIMITS[position])
    && playerIds.length === STARTER_COUNT
    && bench.length === BENCH_SIZE
    && new Set(allPlayers).size === SQUAD_SIZE;
}

function formatDate(dateString, options = {}) {
  return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", ...options }).format(new Date(`${dateString}T12:00:00-04:00`));
}

function fixtureDate(event) {
  return formatDate(event.date, { weekday: "short", month: "short", day: "numeric" });
}

function renderNavigation() {
  const navMarkup = (items) => items.map((item) => `
    <a class="nav-item ${ui.route === item.id ? "active" : ""}" href="#${item.id}" ${ui.route === item.id ? 'aria-current="page"' : ""}>
      <span class="nav-icon" aria-hidden="true">${item.icon}</span>
      <span>${item.label}</span>
    </a>
  `).join("");
  document.querySelector("#desktop-nav").innerHTML = navMarkup(NAV_ITEMS);
  document.querySelector("#mobile-nav").innerHTML = navMarkup(MOBILE_NAV);
  document.querySelector("#account-link").textContent = preferences.manager ? "Account" : "Sign in";
}

function renderPage() {
  clearInterval(countdownTimer);
  renderNavigation();
  pageTitle.textContent = PAGE_TITLES[ui.route] || "Tartan Fantasy";
  teamNameLabel.textContent = preferences.teamName;
  const renders = {
    overview: renderOverview,
    "pick-team": renderPickTeam,
    transfers: renderTransfers,
    leagues: renderLeagues,
    ownership: renderOwnership,
    fixtures: renderFixtures,
    statistics: renderStatistics,
    rules: renderRules
  };
  app.innerHTML = renders[ui.route]();
  app.focus({ preventScroll: true });
  if (ui.route === "overview") startCountdown();
}

function gameweekOptions(selected) {
  return data.gameweeks.map((event) => `
    <option value="${event.gameweek}" ${event.gameweek === Number(selected) ? "selected" : ""}>
      GW${event.gameweek} · ${escapeHtml(event.opponent)}
    </option>
  `).join("");
}

function countdownMarkup(deadline) {
  const difference = Math.max(0, deadline.getTime() - Date.now());
  const days = Math.floor(difference / 86_400_000);
  const hours = Math.floor((difference / 3_600_000) % 24);
  const minutes = Math.floor((difference / 60_000) % 60);
  const units = [[days, "days"], [hours, "hours"], [minutes, "mins"]];
  return units.map(([value, label]) => `<span class="countdown-unit"><b>${String(value).padStart(2, "0")}</b><small>${label}</small></span>`).join("");
}

function startCountdown() {
  const node = document.querySelector("#live-countdown");
  if (!node) return;
  const update = () => { node.innerHTML = countdownMarkup(deadlineDate(ui.gameweek)); };
  update();
  countdownTimer = setInterval(update, 30_000);
}

function fixtureVersus(event) {
  const live = liveScoreFor(event.gameweek);
  const score = hasScore(live);
  return `
    <div class="fixture-versus">
      <div class="fixture-team">
        <span class="team-crest">CMU</span>
        <b>Tartans${score ? `<span class="team-score">${live.cmuScore}</span>` : ""}</b>
      </div>
      <span class="versus-mark ${live?.state === "live" ? "live" : ""}">${score ? liveLabel(live) : "vs"}</span>
      <div class="fixture-team">
        <span class="team-crest opponent">${initials(event.opponent)}</span>
        <b>${escapeHtml(event.opponent)}${score ? `<span class="team-score">${live.opponentScore}</span>` : ""}</b>
      </div>
    </div>
  `;
}

function coverageLinks(event, compact = false) {
  const liveStats = event.ncaaUrl || event.coverage?.find((item) => item.type === "livestats")?.url;
  const video = event.coverage?.find((item) => item.type === "video")?.url;
  const links = [];
  if (liveStats) links.push(`<a class="button secondary" href="${escapeHtml(liveStats)}" target="_blank" rel="noreferrer">${compact ? "Score" : "Live score"} ↗</a>`);
  if (video) links.push(`<a class="button secondary" href="${escapeHtml(video)}" target="_blank" rel="noreferrer">${compact ? "Watch" : "Watch"} ↗</a>`);
  if (!links.length) links.push('<a class="button secondary" href="https://athletics.cmu.edu/sports/msoc/2026-27/schedule" target="_blank" rel="noreferrer">Coverage ↗</a>');
  return links.join("");
}

function renderOverview() {
  const event = fixtureFor(ui.gameweek);
  const live = liveScoreFor(ui.gameweek);
  const team = ensureTeam(ui.gameweek);
  const squadPoints = teamPoints(ui.gameweek);
  const squadWorth = lineupCost([...team.players, ...team.bench]);
  const topPlayers = [...data.players].sort((a, b) => formScore(b) - formScore(a)).slice(0, 5);
  const totalGoals = [...data.statsById.values()].reduce((sum, stat) => sum + Number(stat.goals || 0), 0);
  return `
    <section class="hero-grid">
      <article class="deadline-card">
        <span class="gameweek-badge ${live?.state === "live" ? "is-live" : ""}">${live?.state === "live" ? "Live now" : `Gameweek ${event.gameweek}`}</span>
        <h2>${live?.state === "live" ? `${live.cmuScore ?? 0}–${live.opponentScore ?? 0} against ${escapeHtml(event.opponent)}.` : live?.state === "final" ? `Final: ${live.cmuScore ?? 0}–${live.opponentScore ?? 0}.` : event.home ? "Protect home turf." : "Take the Tartan on the road."}</h2>
        <p>${live?.state === "live" ? `NCAA live feed · ${escapeHtml(liveLabel(live))}. Provisional fantasy points refresh as the box score changes.` : live?.state === "final" ? "The NCAA box score is final; manager-reviewed bonus adjustments can still be added." : `Lock your nine-player squad before ${fixtureDate(event)} at ${event.time} ET.`}</p>
        ${live?.state === "live" || live?.state === "final" ? `<div class="live-actions">${coverageLinks(event)}</div>` : '<div class="countdown" id="live-countdown"></div>'}
      </article>
      <article class="fixture-card">
        <div class="fixture-card-head">
          <span>${live?.state === "live" ? "Live fixture" : live?.state === "final" ? "Latest result" : "Next fixture"}</span>
          <span class="home-away ${live?.state === "live" ? "live" : ""}">${live?.state === "live" ? "LIVE" : event.home ? "HOME" : "AWAY"}</span>
        </div>
        ${fixtureVersus(event)}
        <div class="fixture-detail">${fixtureDate(event)} · ${event.time}<br>${escapeHtml(event.location)}</div>
      </article>
    </section>

    <section class="stats-strip" aria-label="Season summary">
      <article class="stat-card"><span>GW points</span><b>${squadPoints}</b><small>${team.chip ? CHIP_NAMES[team.chip] : "No transfer penalties"}</small></article>
      <article class="stat-card"><span>Squad worth</span><b>$${squadWorth.toFixed(1)}</b><small>$${BUDGET.toFixed(1)} starting budget${data.reviewedThrough ? ` · prices reviewed through GW${data.reviewedThrough}` : " · base prices"}</small></article>
      <article class="stat-card"><span>2025 record</span><b>9–4–5</b><small>18 matches played</small></article>
      <article class="stat-card"><span>2025 goals</span><b>${totalGoals}</b><small>Official team total: 28</small></article>
    </section>

    <div class="section-heading">
      <div><h2>Your Tartan Squad</h2><p>Six starters · three substitutes · Gameweek ${event.gameweek}</p></div>
      <a class="text-link" href="#pick-team">Captain, bench & chips →</a>
    </div>
    <section class="overview-lower">
      <article class="panel">
        <div class="panel-header">
          <div><h3>${escapeHtml(preferences.teamName)}</h3><p>${team.players.length + team.bench.length}/${SQUAD_SIZE} selected${team.chip ? ` · ${CHIP_NAMES[team.chip]}` : ""}</p></div>
          <a class="button primary" href="#transfers">Make transfers</a>
        </div>
        <div class="mini-pitch-wrap">${renderPitch(team, ui.gameweek, true)}${renderBench(team, ui.gameweek, true)}</div>
      </article>
      <article class="panel">
        <div class="panel-header">
          <div><h3>Players to watch</h3><p>2026 form · latest three gameweeks</p></div>
          <a class="text-link" href="#statistics">Full stats</a>
        </div>
        <div class="ranking-list">
          ${topPlayers.map((player, index) => rankingRow(player, index + 1)).join("")}
        </div>
      </article>
    </section>
  `;
}

function rankingRow(player, rank) {
  const stats = currentStatsOf(player.id);
  return `
    <div class="ranking-row" role="button" tabindex="0" data-action="show-player" data-player="${player.id}">
      <span class="rank-number">${rank}</span>
      <span class="player-summary">
        <span class="mini-avatar">${escapeHtml(player.number)}</span>
        <span><b>${escapeHtml(player.name)}</b><small>${player.position} · ${stats.goals || 0}G ${stats.assists || 0}A</small></span>
      </span>
      <span class="ranking-points"><b>${formScore(player).toFixed(1)}</b><small>form</small></span>
    </div>
  `;
}

function renderPitch(team, gameweek, mini = false) {
  const byPosition = Object.fromEntries(POSITION_ORDER.map((position) => [position, []]));
  team.players.forEach((id) => {
    const player = data.playerById.get(id);
    if (player) byPosition[squadPosition(player)].push(player);
  });
  const fieldOrder = ["FWD", "MID", "DEF"];
  return `
    <div class="pitch ${mini ? "mini" : ""}">
      <span class="pitch-markings" aria-hidden="true"></span>
      <div class="formation">
        ${fieldOrder.map((position) => {
          const limit = POSITION_LIMITS[position];
          const slots = [...byPosition[position], ...Array(Math.max(0, limit - byPosition[position].length)).fill(null)];
          return `<div class="formation-line" aria-label="${SQUAD_POSITION_NAMES[position]}s">${slots.map((player) => player ? playerToken(player, team, gameweek) : emptyToken(position)).join("")}</div>`;
        }).join("")}
      </div>
    </div>
  `;
}

function playerToken(player, team, gameweek) {
  const isCaptain = team.captain === player.id;
  const isVice = team.viceCaptain === player.id;
  return `
    <button class="player-token" type="button" data-action="show-player" data-player="${player.id}" title="View ${escapeHtml(player.name)}">
      ${isCaptain ? '<span class="captain-mark">C</span>' : isVice ? '<span class="captain-mark vice">V</span>' : ""}
      <span class="shirt"><span>${escapeHtml(player.number)}</span></span>
      <span class="player-label"><b>${escapeHtml(fieldName(player))}</b><small>${playerFantasyPoints(player, gameweek, team)} pts · $${priceOf(player.id).toFixed(1)}</small></span>
    </button>
  `;
}

function emptyToken(position) {
  return `<a class="player-token" href="#transfers"><span class="empty-token">+</span><em>Add ${position === "DEF" ? "DEF/GK" : position}</em></a>`;
}

function renderBench(team, gameweek, compact = false) {
  return `
    <div class="bench-strip ${compact ? "compact" : ""}">
      <span class="bench-label">Bench${team.chip === "benchBoost" ? " · Boost active" : ""}</span>
      <div class="bench-players">
        ${team.bench.map((id) => {
          const player = data.playerById.get(id);
          return `<button type="button" data-action="show-player" data-player="${id}" title="View or substitute ${escapeHtml(player.name)}"><span class="mini-avatar">${escapeHtml(player.number)}</span><span><b>${escapeHtml(fieldName(player))}</b><small>${rawFantasyPoints(player, gameweek)} pts</small></span></button>`;
        }).join("")}
      </div>
    </div>
  `;
}

function chipUsedGameweek(chip, exceptGameweek) {
  return Object.entries(preferences.teams).find(([gameweek, team]) => Number(gameweek) !== Number(exceptGameweek) && team.chip === chip)?.[0] || null;
}

function weeklyTransferCount(gameweek) {
  if (Number(gameweek) <= 1) return 0;
  const current = ensureTeam(gameweek);
  const previous = previousTeam(gameweek);
  if (!previous) return 0;
  const currentIds = new Set([...current.players, ...current.bench]);
  return [...previous.players, ...previous.bench].filter((id) => !currentIds.has(id)).length;
}

function draftTransferCount(gameweek, players, bench) {
  if (Number(gameweek) <= 1) return 0;
  const previous = previousTeam(gameweek);
  if (!previous) return 0;
  const currentIds = new Set([...players, ...bench]);
  return [...previous.players, ...previous.bench].filter((id) => !currentIds.has(id)).length;
}

function sameSquadPlayers(players, bench, team) {
  const selected = new Set([...players, ...bench]);
  return selected.size === SQUAD_SIZE && [...team.players, ...team.bench].every((id) => selected.has(id));
}

function renderPickTeam() {
  const event = fixtureFor(ui.gameweek);
  const team = ensureTeam(ui.gameweek);
  const locked = isLocked(ui.gameweek);
  const transfersMade = weeklyTransferCount(ui.gameweek);
  const transfersRemaining = Math.max(0, FREE_TRANSFERS - transfersMade);
  const lineupPlayers = team.players.map((id) => data.playerById.get(id)).filter(Boolean);
  return `
    <div class="page-intro">
      <div><h2>Set your gameweek squad</h2><p>Six starters in a 2–2–2, three substitutes, captaincy and one optional chip. Goalkeepers share the two defensive places. Tap a player to substitute.</p></div>
      <div class="field-control">
        <label for="pick-gw">Gameweek</label>
        <select class="select" id="pick-gw" data-action="change-gameweek">${gameweekOptions(ui.gameweek)}</select>
      </div>
    </div>
    <section class="pick-layout">
      <article class="panel mini-pitch-wrap">${renderPitch(team, ui.gameweek)}</article>
      <aside class="pick-sidebar">
        <article class="panel info-panel">
          <span class="eyebrow">GW${event.gameweek} · ${event.home ? "Home" : "Away"}</span>
          <h3>vs ${escapeHtml(event.opponent)}</h3>
          <p>${escapeHtml(event.location)}</p>
          <div class="deadline-line"><i>◷</i><span><b>${locked ? "Lineup locked" : "Selection deadline"}</b><small>${fixtureDate(event)} · ${formatDeadline(event.deadline)}</small></span></div>
        </article>
        ${locked ? '<div class="lock-notice">This gameweek has passed its one-hour deadline. View your team here; edit a future gameweek instead.</div>' : ""}
        ${ui.gameweek > 1 ? `<div class="transfer-requirement complete"><b>${transfersMade > FREE_TRANSFERS ? "Grandfathered squad" : `${transfersMade}/${FREE_TRANSFERS} free transfers used`}</b><span>${transfersMade > FREE_TRANSFERS ? "This squad remains valid under the old rules. Any new player replacement must follow the two-transfer limit." : transfersRemaining ? `${transfersRemaining} transfer${transfersRemaining === 1 ? "" : "s"} remaining. Unused transfers do not carry over.` : "No free transfers remaining this gameweek."}</span></div>` : ""}
        <article class="panel info-panel">
          <h3>Substitutes</h3>
          <p>Tap a starter or substitute, then choose a same-position player to swap. Bench players score only when Bench Boost is active.</p>
          ${renderBench(team, ui.gameweek)}
        </article>
        <article class="panel info-panel">
          <h3>Leadership</h3>
          <p>C = 2× points. V takes over if your captain records no minutes.</p>
          <div class="captain-list">
            ${lineupPlayers.map((player) => `
              <div class="captain-row">
                <span class="player-summary"><span class="mini-avatar">${escapeHtml(player.number)}</span><span><b>${escapeHtml(player.name)}</b><small>${player.position}</small></span></span>
                <button class="captain-choice ${team.captain === player.id ? "active" : ""}" type="button" data-action="set-captain" data-player="${player.id}" ${locked ? "disabled" : ""} aria-label="Make ${escapeHtml(player.name)} captain">C</button>
                <button class="captain-choice vice ${team.viceCaptain === player.id ? "active" : ""}" type="button" data-action="set-vice" data-player="${player.id}" ${locked ? "disabled" : ""} aria-label="Make ${escapeHtml(player.name)} vice-captain">V</button>
              </div>
            `).join("")}
          </div>
        </article>
        <article class="panel info-panel">
          <h3>Chips</h3>
          <p>Use at most one chip per gameweek. Each is available once all season.</p>
          <div class="chip-grid">
            ${Object.entries(CHIP_NAMES).map(([chip, label]) => {
              const used = chipUsedGameweek(chip, ui.gameweek);
              return `<button class="chip-button ${team.chip === chip ? "active" : ""}" type="button" data-action="toggle-chip" data-chip="${chip}" ${locked || used ? "disabled" : ""}><b>${label}</b><small>${used ? `Used GW${used}` : chip === "tripleCaptain" ? "Captain scores 3×" : "All three subs score"}</small></button>`;
            }).join("")}
          </div>
        </article>
        <a class="button primary" href="#transfers">Edit squad</a>
      </aside>
    </section>
  `;
}

function formatDeadline(value) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short"
  }).format(new Date(value));
}

function getDraft() {
  if (ui.draftGameweek !== ui.gameweek || !ui.draftPlayers || !ui.draftBench) {
    ui.draftGameweek = ui.gameweek;
    ui.draftPlayers = [...ensureTeam(ui.gameweek).players];
    ui.draftBench = [...ensureTeam(ui.gameweek).bench];
  }
  return ui.draftPlayers;
}

function getDraftBench() {
  getDraft();
  return ui.draftBench;
}

function renderTransfers() {
  const event = fixtureFor(ui.gameweek);
  const draft = getDraft();
  const bench = getDraftBench();
  const selected = [...draft, ...bench];
  const locked = isLocked(ui.gameweek);
  const counts = lineupCounts(draft);
  const cost = lineupCost(selected);
  const spendingLimit = transferBudget(ui.gameweek);
  const transfersMade = draftTransferCount(ui.gameweek, draft, bench);
  const transfersRemaining = Math.max(0, FREE_TRANSFERS - transfersMade);
  const tooManyTransfers = transfersMade > FREE_TRANSFERS;
  const savedTeam = ensureTeam(ui.gameweek);
  const grandfatheredSquad = tooManyTransfers && sameSquadPlayers(draft, bench, savedTeam);
  const formEvents = recentFormGameweeks();
  const query = ui.marketSearch.toLowerCase();
  let players = data.players.filter((player) => (ui.marketPosition === "ALL" || squadPosition(player) === ui.marketPosition) && player.name.toLowerCase().includes(query));
  players.sort((a, b) => {
    if (ui.marketSort === "name") return a.name.localeCompare(b.name);
    if (ui.marketSort === "price") return priceOf(b.id) - priceOf(a.id) || a.name.localeCompare(b.name);
    if (ui.marketSort === "goals") return currentStatsOf(b.id).goals - currentStatsOf(a.id).goals || a.name.localeCompare(b.name);
    return formScore(b) - formScore(a) || a.name.localeCompare(b.name);
  });
  return `
    <div class="page-intro">
      <div><h2>Build for Gameweek ${event.gameweek}</h2><p>Pick six starters in a 2–2–2 plus three flexible substitutes. Goalkeepers count as defenders.</p></div>
      <div class="field-control"><label for="transfer-gw">Gameweek</label><select class="select" id="transfer-gw" data-action="change-gameweek">${gameweekOptions(ui.gameweek)}</select></div>
    </div>
    ${locked ? '<div class="lock-notice" style="margin-bottom:14px">This deadline has passed. Select a future gameweek to make changes.</div>' : ""}
    ${ui.gameweek > 1 ? `<div class="transfer-requirement ${tooManyTransfers && !grandfatheredSquad ? "warning" : "complete"} transfer-page-note"><b>${grandfatheredSquad ? "Grandfathered squad" : `${transfersMade}/${FREE_TRANSFERS} free transfers used`}</b><span>${grandfatheredSquad ? "The same nine players remain valid under the old rules. Replacing anyone now requires returning to the two-transfer limit." : tooManyTransfers ? `Put ${transfersMade - FREE_TRANSFERS} previous player${transfersMade - FREE_TRANSFERS === 1 ? "" : "s"} back before saving.` : `${transfersRemaining} remaining; unused transfers do not carry over.`}</span></div>` : ""}
    <section class="transfer-layout">
      <div>
        <div class="filter-bar">
          <div class="position-tabs">
            ${["ALL", ...POSITION_ORDER].map((position) => `<button class="filter-chip ${ui.marketPosition === position ? "active" : ""}" type="button" data-action="market-position" data-position="${position}">${position === "ALL" ? "All" : position === "DEF" ? "DEF / GK" : position}</button>`).join("")}
          </div>
          <span class="filter-spacer"></span>
          <input class="search-input" type="search" data-action="market-search" value="${escapeHtml(ui.marketSearch)}" placeholder="Search the squad…" aria-label="Search players" />
          <select class="select" data-action="market-sort" aria-label="Sort players">
            <option value="form" ${ui.marketSort === "form" ? "selected" : ""}>Form · 2026 live</option>
            <option value="goals" ${ui.marketSort === "goals" ? "selected" : ""}>Goals</option>
            <option value="price" ${ui.marketSort === "price" ? "selected" : ""}>Price</option>
            <option value="name" ${ui.marketSort === "name" ? "selected" : ""}>Name</option>
          </select>
        </div>
        <p class="market-form-note">${formEvents.length ? `Form = average fantasy points across ${formEvents.map((event) => `GW${event.gameweek}`).join(", ")}. Missed matches count as 0. Includes Impact Sub; live points are provisional.` : "Form starts when this season’s first box score is available."}</p>
        <div class="player-market">
          ${players.map((player) => marketCard(player, draft, bench, counts, cost, locked)).join("") || '<div class="empty-state"><p>No player matches that search.</p></div>'}
        </div>
      </div>
      <aside class="panel squad-builder">
        <div class="budget-block ${cost > spendingLimit ? "over-budget" : ""}">
          <small>In the bank</small><b>$${(spendingLimit - cost).toFixed(1)}</b><span>$${cost.toFixed(1)} squad worth · $${spendingLimit.toFixed(1)} available this GW · ${selected.length}/${SQUAD_SIZE} selected</span>
          <div class="budget-meter"><i style="width:${Math.min(100, (cost / spendingLimit) * 100)}%"></i></div>
        </div>
        <div class="squad-slots">
          ${POSITION_ORDER.map((position) => renderSquadGroup(position, draft)).join("")}
          ${renderDraftBench(bench)}
        </div>
        <div class="builder-actions">
          <button class="button secondary" type="button" data-action="auto-pick" ${locked ? "disabled" : ""}>Auto pick</button>
          <button class="button primary" type="button" data-action="save-transfers" ${locked || !isComplete(draft, bench) || cost > spendingLimit || (tooManyTransfers && !grandfatheredSquad) ? "disabled" : ""}>Save squad</button>
        </div>
      </aside>
    </section>
  `;
}

function marketCard(player, draft, bench, counts, cost, locked) {
  const isStarter = draft.includes(player.id);
  const isBench = bench.includes(player.id);
  const selected = isStarter || isBench;
  const position = squadPosition(player);
  const hasSpace = counts[position] < POSITION_LIMITS[position] || bench.length < BENCH_SIZE;
  const unavailable = !selected && (!hasSpace || cost + priceOf(player.id) > transferBudget(ui.gameweek));
  const stats = currentStatsOf(player.id);
  return `
    <button class="market-card ${selected ? "selected" : ""} ${unavailable ? "unavailable" : ""}" type="button" data-action="toggle-player" data-player="${player.id}" ${locked || unavailable ? "disabled" : ""}>
      <span class="market-number ${player.position}">${escapeHtml(player.number)}</span>
      <span class="market-main"><b>${escapeHtml(player.name)}</b><small>${player.position} · ${stats.appearances || 0} apps · ${stats.goals || 0}G ${stats.assists || 0}A</small></span>
      <span class="market-meta"><b>$${priceOf(player.id).toFixed(1)}</b><small>${formScore(player).toFixed(1)} form</small>${selected ? `<small>${isStarter ? "Starter ✓" : "Bench ✓"}</small>` : ""}</span>
    </button>
  `;
}

function renderSquadGroup(position, draft) {
  const players = draft.map((id) => data.playerById.get(id)).filter((player) => squadPosition(player) === position);
  const emptyCount = POSITION_LIMITS[position] - players.length;
  return `
    <div class="slot-group-label"><span>${position === "DEF" ? "Defenders / goalkeepers" : `${POSITION_NAMES[position]}s`}</span><span>${players.length}/${POSITION_LIMITS[position]}</span></div>
    ${players.map((player) => `
      <div class="selected-player"><span class="mini-avatar">${escapeHtml(player.number)}</span><b>${escapeHtml(player.name)}</b><button class="remove-player" type="button" data-action="toggle-player" data-player="${player.id}" aria-label="Remove ${escapeHtml(player.name)}">×</button></div>
    `).join("")}
    ${Array(emptyCount).fill('<div class="empty-slot-row">Open slot</div>').join("")}
  `;
}

function renderDraftBench(bench) {
  return `
    <div class="slot-group-label bench-group-label"><span>Substitutes</span><span>${bench.length}/${BENCH_SIZE}</span></div>
    ${bench.map((id) => {
      const player = data.playerById.get(id);
      return `<div class="selected-player bench-selected"><span class="mini-avatar">${escapeHtml(player.number)}</span><span><b>${escapeHtml(player.name)}</b><small>${player.position}</small></span><button class="small-text-button" type="button" data-action="promote-bench" data-player="${player.id}">Start</button><button class="remove-player" type="button" data-action="toggle-player" data-player="${player.id}" aria-label="Remove ${escapeHtml(player.name)}">×</button></div>`;
    }).join("")}
    ${Array(BENCH_SIZE - bench.length).fill('<div class="empty-slot-row">Open substitute slot</div>').join("")}
  `;
}

function renderAccountAccess() {
  if (!preferences.manager) {
    return `
      <section class="panel account-access">
        <h3>Already have a team?</h3>
        <p>On your original device, open Leagues → Enable optional sign-in. Enter that team’s private login code here.</p>
        <form class="simple-form" data-form="account-login">
          <div class="form-field"><label for="team-login-code">Team login code</label><input id="team-login-code" name="code" type="password" autocomplete="current-password" maxlength="128" required placeholder="TF-…" /></div>
          <button class="button primary" type="submit">Sign in to my team</button>
        </form>
      </section>
    `;
  }
  const enabled = preferences.manager.loginEnabled;
  return `
    <section class="panel account-access" id="account-access">
      <h3>${enabled ? "Team sign-in is enabled" : "Play on another device"}</h3>
      <p>${enabled ? "Use your private login code on another phone or computer to open this same team. Both devices can stay signed in." : "Optional: get a private login code for this team. Your squad, bank, points, and leagues will be available when you sign in on another device."}</p>
      ${accountUi.code ? `
        <div class="account-code"><label for="private-login-code">Your private team login code</label><input id="private-login-code" class="login-code-value" value="${escapeHtml(accountUi.code)}" readonly autocomplete="off" spellcheck="false" /><button class="button secondary" type="button" data-action="copy-login-code">Copy code</button></div>
        <p class="form-note">Save this code somewhere private. Anyone with it can access your team. It is shown here only until you leave or reload the page.</p>
      ` : ""}
      ${enabled ? `
        <div class="account-actions"><button class="button secondary" type="button" data-action="account-logout" ${accountUi.busy ? "disabled" : ""}>Sign out on this device</button></div>
        <details class="account-replace"><summary>Need a new login code?</summary><p>Replacing the code stops the old code from signing in. Devices already signed in stay connected.</p><button class="button secondary" type="button" data-action="replace-login-code" ${accountUi.busy ? "disabled" : ""}>Replace login code</button></details>
      ` : `<button class="button secondary" type="button" data-action="enable-login" ${accountUi.busy ? "disabled" : ""}>Enable optional sign-in</button><p class="form-note">You can keep playing on this device without enabling sign-in.</p>`}
    </section>
  `;
}

function clearManagerSession() {
  preferences.manager = null;
  preferences.activeLeagueCode = null;
  preferences.teamName = "Scotty’s Select";
  preferences.teams = {};
  syncedGameweeks = new Set();
  leagueUi = { loading: false, error: "", leagues: [], activeCode: null, standings: null };
  accountUi = { code: null, busy: false };
  ui.draftGameweek = null;
  ui.draftPlayers = null;
  ui.draftBench = null;
  savePreferences();
}

async function signInToTeam(form) {
  const values = new FormData(form);
  const response = await apiRequest("/api/auth/login", { method: "POST", body: { code: values.get("code") } });
  // Replace local drafts with the saved team before anything can sync. A
  // second device must never upload its default squad over the existing team.
  clearManagerSession();
  preferences.manager = { ...response.manager, token: response.token };
  applyManagerProfile(response);
  leagueUi.leagues = response.leagues;
  form.reset();
  await loadLeagueDashboard();
  renderPage();
  showToast(`Signed in to ${preferences.teamName}.`);
}

async function manageAccount(action) {
  if (accountUi.busy || !preferences.manager) return;
  accountUi.busy = true;
  const sessionToken = preferences.manager.token;
  renderPage();
  try {
    if (action === "account-logout") {
      await apiRequest("/api/auth/logout", { method: "POST" });
      if (preferences.manager?.token !== sessionToken) return;
      clearManagerSession();
      renderPage();
      showToast("Signed out on this device.");
      return;
    }
    const endpoint = action === "replace-login-code" ? "rotate" : "enable";
    const response = await apiRequest(`/api/auth/${endpoint}`, { method: "POST" });
    if (preferences.manager?.token !== sessionToken) return;
    preferences.manager = { ...preferences.manager, ...response.manager };
    accountUi.code = response.code;
    savePreferences();
    showToast("Save your private login code to sign in on another device.");
  } catch (error) {
    showToast(error.message);
  } finally {
    accountUi.busy = false;
    renderPage();
  }
}

function renderLeagues() {
  if (!preferences.manager) {
    return `
      <div class="page-intro">
        <div><h2>Create your fantasy team</h2><p>This creates your manager on this server. After that, you can make a league code or join someone else’s league.</p></div>
      </div>
      ${leagueUi.error ? `<div class="league-error">${escapeHtml(leagueUi.error)}</div>` : ""}
      ${renderAccountAccess()}
      <section class="panel league-setup-card">
        <form class="simple-form" data-form="manager-setup">
          <div class="form-field"><label for="manager-name">Your name</label><input id="manager-name" name="managerName" maxlength="40" required placeholder="Sudais" autocomplete="name" /></div>
          <div class="form-field"><label for="setup-team-name">Fantasy team name</label><input id="setup-team-name" name="teamName" maxlength="40" required value="${escapeHtml(preferences.teamName)}" placeholder="Scotty’s Select" /></div>
          <button class="button primary" type="submit">Create team</button>
        </form>
        <p class="form-note">No sign-in required. You can enable a private team login code later to play on other devices.</p>
      </section>
    `;
  }

  const active = leagueUi.standings?.league || leagueUi.leagues.find((league) => league.code === leagueUi.activeCode);
  const rows = leagueUi.standings?.standings || [];
  return `
    <div class="page-intro">
      <div><h2>Mini-leagues</h2><p>Create a code for the squad, or enter a code someone sends you. Rankings use the same gameweek points as your team page.</p></div>
      <button class="button secondary" type="button" data-action="refresh-league">Refresh</button>
    </div>
    <section class="manager-summary panel">
      <span class="manager-avatar">${escapeHtml(initials(preferences.manager.managerName))}</span>
      <span><small>Manager</small><b>${escapeHtml(preferences.manager.managerName)}</b></span>
      <span><small>Fantasy team</small><b>${escapeHtml(preferences.teamName)}</b></span>
    </section>
    ${leagueUi.error ? `<div class="league-error">${escapeHtml(leagueUi.error)}</div>` : ""}
    ${renderAccountAccess()}
    <section class="league-actions">
      <article class="panel league-action-card">
        <h3>Create a league</h3><p>You are added automatically and receive a shareable code.</p>
        <form class="inline-form" data-form="create-league"><input name="name" maxlength="40" required placeholder="CMU Men’s Soccer" aria-label="League name" /><button class="button primary" type="submit">Create</button></form>
      </article>
      <article class="panel league-action-card">
        <h3>Join a league</h3><p>Enter the six-character code from another manager.</p>
        <form class="inline-form" data-form="join-league"><input class="code-input" name="code" maxlength="6" required placeholder="ABC123" aria-label="League code" autocapitalize="characters" /><button class="button primary" type="submit">Join</button></form>
      </article>
    </section>
    ${leagueUi.loading ? '<div class="league-loading">Loading league…</div>' : `
      ${leagueUi.leagues.length ? `
        <div class="league-tabs" aria-label="Your leagues">
          ${leagueUi.leagues.map((league) => `<button class="filter-chip ${league.code === leagueUi.activeCode ? "active" : ""}" type="button" data-action="select-league" data-code="${league.code}">${escapeHtml(league.name)}</button>`).join("")}
        </div>
      ` : '<div class="empty-state compact"><p>You are not in a league yet. Create one or enter a code above.</p></div>'}
      ${active ? `
        <section class="panel standings-panel">
          <div class="standings-head">
            <div><span class="eyebrow">${active.isOwner ? "Your league" : "Joined league"}</span><h3>${escapeHtml(active.name)}</h3><p>${leagueUi.standings?.memberCount || 0} manager${leagueUi.standings?.memberCount === 1 ? "" : "s"} · Gameweek ${leagueUi.standings?.currentGameweek || ui.gameweek}</p></div>
            <button class="league-code" type="button" data-action="copy-code" data-code="${active.code}" title="Copy league code"><small>LEAGUE CODE</small><b>${active.code}</b></button>
          </div>
          <div class="table-scroll">
            <table class="standings-table">
              <thead><tr><th>Rank</th><th>Team</th><th>Manager</th><th>Value</th><th>GW</th><th>Total</th></tr></thead>
              <tbody>
                ${rows.map((entry) => `<tr class="${entry.managerId === preferences.manager.id ? "is-you" : ""}"><td><span class="rank-badge">${entry.rank}</span></td><td><button class="league-squad-link" type="button" data-action="view-league-squad" data-manager="${entry.managerId}"><b>${escapeHtml(entry.teamName)}</b></button></td><td><button class="league-squad-link manager-name-link" type="button" data-action="view-league-squad" data-manager="${entry.managerId}">${escapeHtml(entry.managerName)}${entry.managerId === preferences.manager.id ? " · You" : ""}</button></td><td>${entry.squadValue == null ? "—" : `$${Number(entry.squadValue).toFixed(1)}`}</td><td>${entry.gameweekPoints}</td><td><b>${entry.totalPoints}</b></td></tr>`).join("")}
              </tbody>
            </table>
          </div>
        </section>
      ` : ""}
    `}
  `;
}

function renderOwnership() {
  if (!preferences.manager) {
    return `
      <div class="page-intro"><div><h2>Player ownership</h2><p>Create your fantasy team first, then this page will show which teams in your active mini-league own each player.</p></div></div>
      <section class="panel ownership-empty"><p>Ownership is linked to your mini-leagues.</p><a class="button primary" href="#leagues">Create or join a league</a></section>
    `;
  }

  const active = leagueUi.standings?.league || leagueUi.leagues.find((league) => league.code === leagueUi.activeCode);
  const rows = leagueUi.standings?.standings || [];
  const lockedEvents = data.gameweeks.filter((event) => isLocked(event.gameweek));
  if (ui.ownershipGameweek == null) ui.ownershipGameweek = lockedEvents.at(-1)?.gameweek || data.gameweeks[0].gameweek;
  const selectedGameweek = Number(ui.ownershipGameweek);
  const selectedEvent = fixtureFor(selectedGameweek);
  const visible = isLocked(selectedGameweek);
  const pointsPeriod = ui.ownershipPointsGameweek;
  const pointsHeading = pointsPeriod === "overall" ? "Total points" : `GW${Number(pointsPeriod)} points`;

  if (leagueUi.loading) return '<div class="league-loading">Loading ownership…</div>';
  if (!active) {
    return `
      <div class="page-intro"><div><h2>Player ownership</h2><p>See every player and the fantasy teams that selected them.</p></div></div>
      ${leagueUi.error ? `<div class="league-error">${escapeHtml(leagueUi.error)}</div>` : ""}
      <section class="panel ownership-empty"><p>Join or create a mini-league to see ownership.</p><a class="button primary" href="#leagues">Go to leagues</a></section>
    `;
  }

  const ownership = new Map(data.players.map((player) => [player.id, []]));
  if (visible) {
    rows.forEach((entry) => {
      const squad = entry.squads?.[String(selectedGameweek)];
      if (!squad) return;
      [...squad.players, ...squad.bench].forEach((playerId) => ownership.get(playerId)?.push(entry));
    });
  }
  const players = [...data.players].sort((a, b) => ownership.get(b.id).length - ownership.get(a.id).length || priceOf(b.id) - priceOf(a.id) || a.name.localeCompare(b.name));

  return `
    <div class="page-intro">
      <div><h2>Player ownership</h2><p>All players and the teams that own them in ${escapeHtml(active.name)}. Selections unlock only after each deadline.</p></div>
      <div class="field-control"><label for="ownership-gw">Ownership gameweek</label><select class="select" id="ownership-gw" data-action="ownership-gameweek">${gameweekOptions(selectedGameweek)}</select></div>
    </div>
    ${leagueUi.error ? `<div class="league-error">${escapeHtml(leagueUi.error)}</div>` : ""}
    <div class="league-tabs" aria-label="Your leagues">
      ${leagueUi.leagues.map((league) => `<button class="filter-chip ${league.code === leagueUi.activeCode ? "active" : ""}" type="button" data-action="select-league" data-code="${league.code}">${escapeHtml(league.name)}</button>`).join("")}
    </div>
    <section class="ownership-review panel">
      <span><small>Starting budget</small><b>$${BUDGET.toFixed(1)}m</b></span>
      <span><small>Automated EV review</small><b>${data.reviewedThrough ? `Through GW${data.reviewedThrough}` : "After GW3"}</b></span>
      <span><small>Price movement</small><b>Up to $0.3m / review</b></span>
    </section>
    ${!visible ? `
      <div class="lock-notice">GW${selectedGameweek} ownership unlocks after the ${fixtureDate(selectedEvent)} deadline. This prevents anyone seeing rivals’ picks early.</div>
    ` : `
      <section class="panel table-panel ownership-panel">
        <div class="standings-head ownership-head"><div><span class="eyebrow">GW${selectedGameweek} · ${rows.length} managers</span><h3>${escapeHtml(active.name)}</h3><p>Current price includes each completed three-gameweek EV review. Click a team to view its GW${selectedGameweek} squad.</p></div><button class="button secondary" type="button" data-action="refresh-league">Refresh</button></div>
        <div class="ownership-points-controls">
          <div class="field-control"><label for="ownership-points-gw">Player points</label><select class="select" id="ownership-points-gw" data-action="ownership-points-gameweek"><option value="overall" ${pointsPeriod === "overall" ? "selected" : ""}>Overall · 2026 season</option>${gameweekOptions(pointsPeriod)}</select></div>
          <p>Includes Impact Sub points. Captain and chip bonuses are excluded. Live points are provisional.</p>
        </div>
        <div class="table-scroll">
          <table class="data-table ownership-table">
            <thead><tr><th>Player</th><th>${pointsHeading}</th><th>Price</th><th>Last move</th><th>3-GW points / EV</th><th>Owned</th></tr></thead>
            <tbody>
              ${players.map((player) => {
                const owners = ownership.get(player.id);
                const review = lastPriceReview(player.id);
                const percentage = rows.length ? Math.round((owners.length / rows.length) * 100) : 0;
                return `<tr>
                  <td data-action="show-player" data-player="${player.id}"><span class="table-player"><span class="mini-avatar">${escapeHtml(player.number)}</span><span><b>${escapeHtml(player.name)}</b><small>${player.position} · ${player.class}</small></span></span></td>
                  <td><b>${playerPointsForPeriod(player, pointsPeriod)}</b></td>
                  <td><b>$${priceOf(player.id).toFixed(1)}</b></td>
                  <td><span class="price-move ${review?.move > 0 ? "up" : review?.move < 0 ? "down" : ""}">${review ? priceMoveLabel(review.move) : "Pending"}</span></td>
                  <td>${review ? `<b>${review.actual}</b> / ${review.expected.toFixed(1)}` : "After GW3"}</td>
                  <td>${owners.length ? `<details class="ownership-dropdown"><summary><b>${owners.length}</b> <small>(${percentage}%)</small><span>View teams</span></summary><div class="ownership-teams">${owners.map((entry) => `<button type="button" data-action="view-league-squad" data-manager="${entry.managerId}" data-gameweek="${selectedGameweek}">${escapeHtml(entry.teamName)}</button>`).join("")}</div></details>` : `<b>0</b> <small>(0%)</small>`}</td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>
      </section>
      <p class="ownership-method">EV is each player’s preseason career projection for three matches (freshmen start at 1.5 expected points). Actual fantasy points are compared every three final gameweeks; prices move by only $0.1m–$0.3m and stay between $${MIN_PLAYER_PRICE.toFixed(1)}m and $${MAX_PLAYER_PRICE.toFixed(1)}m.</p>
    `}
  `;
}

async function loadLeagueDashboard(preferredCode = preferences.activeLeagueCode) {
  if (!preferences.manager) return;
  const sessionToken = preferences.manager.token;
  leagueUi.loading = true;
  leagueUi.error = "";
  if (["leagues", "ownership"].includes(ui.route)) renderPage();
  try {
    const profile = await apiRequest("/api/me");
    if (preferences.manager?.token !== sessionToken) return;
    applyManagerProfile(profile);
    leagueUi.leagues = profile.leagues;
    const selected = profile.leagues.find((league) => league.code === preferredCode) || profile.leagues[0] || null;
    leagueUi.activeCode = selected?.code || null;
    preferences.activeLeagueCode = leagueUi.activeCode;
    const standings = selected ? await apiRequest(`/api/leagues/${selected.code}`) : null;
    if (preferences.manager?.token !== sessionToken) return;
    leagueUi.standings = standings;
    savePreferences();
  } catch (error) {
    if (preferences.manager?.token !== sessionToken) return;
    if (error.status === 401) {
      clearManagerSession();
      leagueUi.error = "Your session has expired. Sign in with your team login code, or create a team if you have not played before.";
    } else {
      leagueUi.error = error.message;
    }
  } finally {
    leagueUi.loading = false;
    if (["leagues", "ownership"].includes(ui.route)) renderPage();
  }
}

async function createManager(form) {
  const values = new FormData(form);
  const response = await apiRequest("/api/managers", {
    method: "POST",
    body: { managerName: values.get("managerName"), teamName: values.get("teamName") }
  });
  preferences.manager = { ...response.manager, token: response.token };
  preferences.teamName = response.manager.teamName;
  savePreferences();
  ensureTeam(ui.gameweek);
  const failures = await syncExistingSquads();
  await loadLeagueDashboard();
  showToast(failures ? "Team created; one or more old lineups could not sync." : "Fantasy team created.");
}

async function createLeague(form) {
  const name = new FormData(form).get("name");
  const response = await apiRequest("/api/leagues", { method: "POST", body: { name } });
  await loadLeagueDashboard(response.league.code);
  showToast(`League created: ${response.league.code}`);
}

async function joinLeague(form) {
  const code = new FormData(form).get("code");
  const response = await apiRequest("/api/leagues/join", { method: "POST", body: { code } });
  await loadLeagueDashboard(response.league.code);
  showToast(`Joined ${response.league.name}.`);
}

function renderFixtures() {
  const current = findLiveGameweek();
  return `
    <div class="page-intro">
      <div><h2>The road to November</h2><p>Every regular-season fixture is a fantasy gameweek. Home/away status, Eastern times, and venue details follow the published 2026 schedule.</p></div>
      <a class="button secondary" href="https://athletics.cmu.edu/sports/msoc/2026-27/schedule" target="_blank" rel="noreferrer">Official schedule ↗</a>
    </div>
    <section class="fixtures-list">
      ${data.gameweeks.map((event) => `
        ${(() => {
          const live = liveScoreFor(event.gameweek);
          const score = hasScore(live);
          return `<article class="fixture-row ${event.gameweek === current ? "next" : ""} ${live?.state === "live" ? "is-live" : ""}">
          <span class="gw-square"><span>GAMEWEEK<b>${event.gameweek}</b></span></span>
          <span class="status-badge ${live?.state === "live" ? "live" : event.home ? "" : "away"}">${live?.state === "live" ? "LIVE" : event.home ? "HOME" : "AWAY"}</span>
          <span class="fixture-opponent"><b>CMU ${score ? `${live.cmuScore}–${live.opponentScore}` : event.home ? "vs" : "at"} ${escapeHtml(event.opponent)}</b><small>${live?.state === "final" ? "Final · " : live?.state === "live" ? `${escapeHtml(liveLabel(live))} · ` : ""}${event.conference ? "UAA · " : "Non-conference · "}${escapeHtml(event.location)}</small></span>
          <span class="fixture-date"><b>${fixtureDate(event)}</b><small>${event.time} ET · deadline ${formatDeadline(event.deadline)}</small></span>
          <span class="fixture-links">${coverageLinks(event, true)}</span>
        </article>`;
        })()}
      `).join("")}
    </section>
  `;
}

function renderStatistics() {
  const query = ui.statsSearch.toLowerCase();
  let players = data.players.filter((player) => (ui.statsPosition === "ALL" || player.position === ui.statsPosition) && player.name.toLowerCase().includes(query));
  players.sort((a, b) => {
    const aStats = ui.statsSeason === "2026" ? currentStatsOf(a.id) : statsOf(a.id);
    const bStats = ui.statsSeason === "2026" ? currentStatsOf(b.id) : statsOf(b.id);
    if (ui.statsSort === "name") return a.name.localeCompare(b.name);
    if (ui.statsSort === "apps") return (bStats.appearances || 0) - (aStats.appearances || 0) || a.name.localeCompare(b.name);
    if (ui.statsSort === "assists") return (bStats.assists || 0) - (aStats.assists || 0) || a.name.localeCompare(b.name);
    if (ui.statsSort === "form") return ui.statsSeason === "2026" ? bStats.fantasyPoints - aStats.fantasyPoints || a.name.localeCompare(b.name) : historicalFormScore(b) - historicalFormScore(a) || a.name.localeCompare(b.name);
    return (bStats.goals || 0) - (aStats.goals || 0) || (bStats.assists || 0) - (aStats.assists || 0);
  });
  return `
    <div class="page-intro">
      <div><h2>Player database</h2><p>${ui.statsSeason === "2026" ? "Current-season totals from NCAA and CMU game box scores. Live-match figures are provisional until the game is final." : "Official 2025 cumulative production for returning players. New players correctly show no prior CMU line."}</p></div>
      <div class="field-control"><label for="stats-season">Season</label><select class="select" id="stats-season" data-action="stats-season"><option value="2026" ${ui.statsSeason === "2026" ? "selected" : ""}>2026 live</option><option value="2025" ${ui.statsSeason === "2025" ? "selected" : ""}>2025 reference</option></select></div>
    </div>
    <div class="filter-bar">
      <div class="position-tabs">${["ALL", ...PLAYER_POSITION_ORDER].map((position) => `<button class="filter-chip ${ui.statsPosition === position ? "active" : ""}" type="button" data-action="stats-position" data-position="${position}">${position === "ALL" ? "All" : position}</button>`).join("")}</div>
      <span class="filter-spacer"></span>
      <input class="search-input" type="search" data-action="stats-search" value="${escapeHtml(ui.statsSearch)}" placeholder="Find a player…" aria-label="Search player database" />
      <select class="select" data-action="stats-sort" aria-label="Sort player database">
        <option value="goals" ${ui.statsSort === "goals" ? "selected" : ""}>Goals</option>
        <option value="assists" ${ui.statsSort === "assists" ? "selected" : ""}>Assists</option>
        <option value="apps" ${ui.statsSort === "apps" ? "selected" : ""}>Appearances</option>
        <option value="form" ${ui.statsSort === "form" ? "selected" : ""}>${ui.statsSeason === "2026" ? "Fantasy points" : "Form index"}</option>
        <option value="name" ${ui.statsSort === "name" ? "selected" : ""}>Name</option>
      </select>
    </div>
    <section class="panel table-panel">
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th>Player</th><th>Price</th><th>GP</th><th>GS</th><th>MIN</th><th>G</th><th>A</th><th>PTS</th><th>SH</th><th>SOG</th><th>PS</th><th>YC</th><th>RC</th><th>${ui.statsSeason === "2026" ? "CS" : "Form"}</th></tr></thead>
          <tbody>
            ${players.map((player) => {
              const stats = ui.statsSeason === "2026" ? currentStatsOf(player.id) : statsOf(player.id);
              const points = ui.statsSeason === "2026" ? stats.fantasyPoints : stats.ncaaPoints;
              return `<tr data-action="show-player" data-player="${player.id}">
                <td><span class="table-player"><span class="mini-avatar">${escapeHtml(player.number)}</span><span><b>${escapeHtml(player.name)}</b><small>${player.position} · ${player.class}</small></span></span></td>
                <td>$${priceOf(player.id).toFixed(1)}</td><td>${stats.appearances || 0}</td><td>${stats.starts || 0}</td><td>${stats.minutes ?? "—"}</td><td>${stats.goals || 0}</td><td>${stats.assists || 0}</td><td>${points || 0}</td><td>${stats.shots || 0}</td><td>${stats.shotsOnGoal || 0}</td><td>${stats.penaltiesSaved || 0}</td><td>${stats.yellowCards || 0}</td><td>${stats.redCards || 0}</td><td><b>${ui.statsSeason === "2026" ? stats.shutouts : historicalFormScore(player)}</b></td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    </section>
    <p style="color:var(--ink-soft);font-size:.62rem;line-height:1.5;margin:12px 4px 0">${ui.statsSeason === "2026" ? "NCAA is the primary live score and box-score feed; CMU/PrestoSports is the official post-match fallback. FPL points exclude captain multipliers in this table." : "MIN is shown where CMU’s cumulative source publishes it (goalkeepers)."}</p>
  `;
}

function renderRules() {
  return `
    <div class="page-intro"><div><h2>Simple enough to play. Serious enough to win.</h2><p>The scoring borrows FPL’s familiar logic and adapts it to a compact, single-squad college season.</p></div><span class="gameweek-badge">2026 season</span></div>
    <section class="rules-grid">
      <article class="rules-card wide">
        <h3>Start playing in three steps</h3><p>Play without signing in, or enable a private team login code in Leagues to use the same team on other devices.</p>
        <div class="how-to-steps">
          <a href="#leagues"><b>1</b><span><strong>Create your team</strong><small>Enter your name, then create or join a league code.</small></span></a>
          <a href="#transfers"><b>2</b><span><strong>Build your squad</strong><small>Select nine players within $${BUDGET.toFixed(1)}m and save them before the deadline.</small></span></a>
          <a href="#pick-team"><b>3</b><span><strong>Set the gameweek</strong><small>Choose your six starters, captain, vice-captain and optional chip.</small></span></a>
        </div>
      </article>
      <article class="rules-card">
        <h3>Your squad</h3><p>Start a fixed 2–2–2 and select three additional substitutes. Goalkeepers compete with defenders instead of occupying a mandatory place.</p>
        <div class="rules-list">
          <div class="rule-row"><span>Defenders / goalkeepers</span><b>2 combined</b></div>
          <div class="rule-row"><span>Midfielders</span><b>2</b></div>
          <div class="rule-row"><span>Forwards</span><b>2</b></div>
          <div class="rule-row"><span>Substitutes</span><b>3 flexible</b></div>
          <div class="rule-row"><span>Budget</span><b>$${BUDGET.toFixed(1)}m</b></div>
          <div class="rule-row"><span>Dynamic price range</span><b>$${MIN_PLAYER_PRICE.toFixed(1)}m–$${MAX_PLAYER_PRICE.toFixed(1)}m</b></div>
          <div class="rule-row"><span>$10.0m+ premiums affordable</span><b>Maximum 2</b></div>
        </div>
      </article>
      <article class="rules-card">
        <h3>Core points</h3><p>Points are calculated per gameweek from the stat record in <code>data/gameweek-stats.json</code>.</p>
        <div class="rules-list">
          <div class="rule-row"><span>Plays 1–39 / 40+ minutes</span><b>1 / 2</b></div>
          <div class="rule-row"><span>Goal — GK/DEF · MID · FWD</span><b>6 · 5 · 4</b></div>
          <div class="rule-row"><span>Assist</span><b>3</b></div>
          <div class="rule-row"><span>Clean sheet after 40 min — GK/DEF · MID</span><b>4 · 1</b></div>
          <div class="rule-row"><span>Every 3 goalkeeper saves</span><b>1</b></div>
          <div class="rule-row"><span>Goalkeeper penalty save</span><b>5</b></div>
          <div class="rule-row"><span>Fantasy starter who enters as a real substitute for 20+ min</span><b>1.25×, rounded up</b></div>
        </div>
      </article>
      <article class="rules-card">
        <h3>Leadership & chips</h3><p>Each chip can be used once during the season, with at most one active per gameweek.</p>
        <div class="rules-list">
          <div class="rule-row"><span>Captain</span><b>2×</b></div>
          <div class="rule-row"><span>Vice-captain</span><b>Captain backup</b></div>
          <div class="rule-row"><span>Triple Captain</span><b>Captain 3×</b></div>
          <div class="rule-row"><span>Bench Boost</span><b>All subs score</b></div>
          <div class="rule-row"><span>Yellow / red card</span><b>−1 / −3</b></div>
          <div class="rule-row"><span>Own goal / penalty miss</span><b>−2 / −2</b></div>
          <div class="rule-row"><span>Manual bonus</span><b>0–3</b></div>
        </div>
      </article>
      <article class="rules-card">
        <h3>Deadlines & transfers</h3><p>Each squad locks one hour before kickoff. After the opening squad, every manager receives two free transfers per gameweek.</p>
        <div class="rules-list">
          <div class="rule-row"><span>Gameweeks</span><b>18</b></div>
          <div class="rule-row"><span>Deadline</span><b>−60 min</b></div>
          <div class="rule-row"><span>Free transfers</span><b>2 per week</b></div>
          <div class="rule-row"><span>Unused transfers</span><b>Do not roll over</b></div>
          <div class="rule-row"><span>Transfer penalties</span><b>None</b></div>
          <div class="rule-row"><span>League squads visible</span><b>After deadline</b></div>
          <div class="rule-row"><span>Current 2026 points</span><b>0 preseason</b></div>
        </div>
      </article>
      <article class="rules-card">
        <h3>Automated price reviews</h3><p>After every three final gameweeks, actual fantasy points are compared with a preseason three-match expected value. The calculation is deterministic and published on the Ownership page.</p>
        <div class="rules-list">
          <div class="rule-row"><span>Review cycle</span><b>Every 3 GWs</b></div>
          <div class="rule-row"><span>Freshman starting EV</span><b>1.5 points</b></div>
          <div class="rule-row"><span>Change per review</span><b>±$0.1m–$0.3m</b></div>
          <div class="rule-row"><span>Starting budget</span><b>$${BUDGET.toFixed(1)}m</b></div>
          <div class="rule-row"><span>Bank after a price change</span><b>Cash stays unchanged</b></div>
          <div class="rule-row"><span>Gameweek spending limit</span><b>Squad value + bank</b></div>
        </div>
      </article>
      <article class="rules-card wide">
        <h3>Official data trail</h3><p>The site separates public source data from your manual fantasy decisions. Run <code>make sync</code> to refresh the roster and 2023–2025 career tables; your price CSV is deliberately never overwritten.</p>
        <div class="source-stack">
          <a class="source-card" href="https://athletics.cmu.edu/sports/msoc/2026-27/roster" target="_blank" rel="noreferrer"><b>2026 CMU roster ↗</b><small>Names, numbers, classes, roles, height and hometown.</small></a>
          <a class="source-card" href="https://athletics.cmu.edu/sports/msoc/2026-27/schedule" target="_blank" rel="noreferrer"><b>2026 CMU schedule ↗</b><small>Dates, kickoff times, home/away and live coverage links.</small></a>
          <a class="source-card" href="https://athletics.cmu.edu/sports/msoc/2025-26/teams/carnegiemellon" target="_blank" rel="noreferrer"><b>2023–2025 CMU career stats ↗</b><small>Three official archived seasons feed the reproducible pricing model.</small></a>
          <a class="source-card" href="https://www.ncaa.com/scoreboard/soccer-men/d3" target="_blank" rel="noreferrer"><b>NCAA Division III scores ↗</b><small>ESPN-style game state, score and individual box-score cross-check.</small></a>
          <a class="source-card" href="https://www.flofc.com/teams/11194390-carnegie-mellon-mens-soccer" target="_blank" rel="noreferrer"><b>FloCollege video ↗</b><small>Published CMU match streams and commentary; access may require a subscription.</small></a>
        </div>
      </article>
    </section>
  `;
}

function showPlayer(playerId) {
  const player = data.playerById.get(playerId);
  if (!player) return;
  const stats = statsOf(player.id);
  const priceReview = lastPriceReview(player.id);
  const team = ensureTeam(ui.gameweek);
  const isStarter = team.players.includes(player.id);
  const isSubstitute = team.bench.includes(player.id);
  const canChangeLineup = ["overview", "pick-team"].includes(ui.route) && (isStarter || isSubstitute);
  const playerSquadPosition = squadPosition(player);
  const swapOptions = isStarter
    ? team.bench.map((id) => data.playerById.get(id)).filter((candidate) => squadPosition(candidate) === playerSquadPosition)
    : isSubstitute
      ? team.players.map((id) => data.playerById.get(id)).filter((candidate) => squadPosition(candidate) === playerSquadPosition)
      : [];
  const substitutionMarkup = canChangeLineup ? `
    <section class="dialog-substitution">
      <div class="dialog-section-heading">
        <span class="eyebrow">Gameweek ${ui.gameweek} lineup</span>
        <h3>${isStarter ? `Move ${escapeHtml(fieldName(player))} to the bench` : `Bring ${escapeHtml(fieldName(player))} into the lineup`}</h3>
        <p>Formation stays 2–2–2, so substitutions are made within the same squad group${playerSquadPosition === "DEF" ? " (defender or goalkeeper)" : ""}.</p>
      </div>
      ${isLocked(ui.gameweek)
        ? '<div class="lineup-action-note">This gameweek is locked.</div>'
        : swapOptions.length
          ? `<div class="substitution-options">${swapOptions.map((candidate) => `
              <button class="substitution-option" type="button" data-action="swap-lineup" data-starter="${isStarter ? player.id : candidate.id}" data-bench="${isStarter ? candidate.id : player.id}">
                <span class="mini-avatar">${escapeHtml(candidate.number)}</span>
                <span><b>${isStarter ? `Bring on ${escapeHtml(fieldName(candidate))}` : `Replace ${escapeHtml(fieldName(candidate))}`}</b><small>${escapeHtml(candidate.name)} · ${candidate.position}</small></span>
                <strong>SUB</strong>
              </button>
            `).join("")}</div>`
          : `<div class="lineup-action-note">There is no compatible ${SQUAD_POSITION_NAMES[playerSquadPosition].toLowerCase()} on the ${isStarter ? "bench" : "field"} to swap with. Use Transfers to change the nine-player squad.</div>`}
    </section>
  ` : "";
  dialogContent.innerHTML = `
    <div class="dialog-hero">
      <span class="dialog-number">${escapeHtml(player.number)}</span>
      <div class="dialog-name"><h2>${escapeHtml(player.name)}</h2><p>${POSITION_NAMES[player.position]} · ${player.class} · $${priceOf(player.id).toFixed(1)}m</p></div>
    </div>
    <div class="dialog-body">
      <div class="dialog-stats">
        <div class="dialog-stat"><b>${stats.appearances || 0}</b><small>2025 apps</small></div>
        <div class="dialog-stat"><b>${stats.goals || 0}</b><small>Goals</small></div>
        <div class="dialog-stat"><b>${stats.assists || 0}</b><small>Assists</small></div>
        <div class="dialog-stat"><b>${formScore(player).toFixed(1)}</b><small>2026 form</small></div>
      </div>
      <div class="bio-list">
        <div class="bio-line"><span>Position</span><b>${POSITION_NAMES[player.position]}</b></div>
        <div class="bio-line"><span>Height</span><b>${escapeHtml(player.height)}</b></div>
        <div class="bio-line"><span>From</span><b>${escapeHtml(player.hometown)}</b></div>
        <div class="bio-line"><span>Discipline</span><b>${stats.yellowCards || 0} yellow · ${stats.redCards || 0} red</b></div>
        <div class="bio-line"><span>Last EV review</span><b>${priceReview ? `${priceReview.actual} pts vs ${priceReview.expected.toFixed(1)} EV · ${priceMoveLabel(priceReview.move)}` : "Pending after GW3"}</b></div>
      </div>
      ${substitutionMarkup}
      <a class="button secondary" href="${escapeHtml(player.rosterUrl)}" target="_blank" rel="noreferrer">Official player bio ↗</a>
    </div>
  `;
  if (!dialog.open) dialog.showModal();
}

function showLeagueSquad(managerId, requestedGameweek = null) {
  const entry = leagueUi.standings?.standings?.find((candidate) => candidate.managerId === managerId);
  if (!entry) return;
  const isOwnTeam = managerId === preferences.manager?.id;
  const viewableGameweeks = isOwnTeam
    ? data.gameweeks.map((event) => event.gameweek)
    : Object.keys(entry.squads || {}).map(Number).sort((a, b) => a - b);
  if (!viewableGameweeks.length) {
    const current = leagueUi.standings.currentGameweek;
    const event = fixtureFor(current);
    showToast(`${entry.teamName} has no unlocked squad yet. Gameweek ${current} unlocks ${formatDeadline(event.deadline)}.`);
    return;
  }
  const current = leagueUi.standings.currentGameweek;
  const requested = Number(requestedGameweek);
  const gameweek = viewableGameweeks.includes(requested)
    ? requested
    : viewableGameweeks.includes(current) ? current : viewableGameweeks.at(-1);
  const team = entry.squads?.[String(gameweek)] || (isOwnTeam ? ensureTeam(gameweek) : null);
  if (!team) {
    showToast(`${entry.teamName} has not saved a squad for Gameweek ${gameweek}.`);
    return;
  }
  const points = entry.weeklyPoints?.[String(gameweek)] || 0;
  const transfers = entry.transfersByGameweek?.[String(gameweek)] || 0;
  dialogContent.innerHTML = `
    <div class="dialog-hero league-squad-hero">
      <span class="dialog-number">${entry.rank}</span>
      <div class="dialog-name"><h2>${escapeHtml(entry.teamName)}</h2><p>${escapeHtml(entry.managerName)} · Gameweek ${gameweek} · ${points} points</p></div>
    </div>
    <div class="dialog-body league-squad-dialog-body">
      <div class="league-squad-toolbar">
        <p class="league-squad-note">Read-only lineup${team.chip ? ` · ${CHIP_NAMES[team.chip]}` : ""}${gameweek > 1 ? ` · ${transfers}/${FREE_TRANSFERS} transfers used` : ""}. Tap a player for details.</p>
        <label>Gameweek<select class="select" data-action="league-squad-gameweek" data-manager="${managerId}">${viewableGameweeks.map((value) => `<option value="${value}" ${value === gameweek ? "selected" : ""}>GW${value}</option>`).join("")}</select></label>
      </div>
      ${renderPitch(team, gameweek, true)}
      ${renderBench(team, gameweek, true)}
    </div>
  `;
  if (!dialog.open) dialog.showModal();
}

function showToast(message) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.add("show");
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
}

function togglePlayer(playerId) {
  if (isLocked(ui.gameweek)) return showToast("That gameweek is already locked.");
  const draft = getDraft();
  const bench = getDraftBench();
  const starterIndex = draft.indexOf(playerId);
  const benchIndex = bench.indexOf(playerId);
  if (starterIndex >= 0 || benchIndex >= 0) {
    if (starterIndex >= 0) draft.splice(starterIndex, 1);
    if (benchIndex >= 0) bench.splice(benchIndex, 1);
    renderPage();
    return;
  }
  const player = data.playerById.get(playerId);
  const counts = lineupCounts(draft);
  if (lineupCost([...draft, ...bench]) + priceOf(playerId) > transferBudget(ui.gameweek)) {
    showToast("That move would take you over budget.");
    return;
  }
  const position = squadPosition(player);
  if (counts[position] < POSITION_LIMITS[position]) {
    draft.push(playerId);
  } else if (bench.length < BENCH_SIZE) {
    bench.push(playerId);
  } else {
    showToast("The starters and bench are full. Remove someone first.");
    return;
  }
  renderPage();
}

function promoteBench(playerId) {
  if (isLocked(ui.gameweek)) return;
  const draft = getDraft();
  const bench = getDraftBench();
  const player = data.playerById.get(playerId);
  const benchIndex = bench.indexOf(playerId);
  if (benchIndex < 0) return;
  const position = squadPosition(player);
  if (lineupCounts(draft)[position] >= POSITION_LIMITS[position]) {
    showToast(`Remove a starting ${SQUAD_POSITION_NAMES[position].toLowerCase()} first.`);
    return;
  }
  bench.splice(benchIndex, 1);
  draft.push(playerId);
  renderPage();
}

async function swapLineup(starterId, benchId) {
  if (isLocked(ui.gameweek)) return showToast("That gameweek is already locked.");
  const team = ensureTeam(ui.gameweek);
  const starterIndex = team.players.indexOf(starterId);
  const benchIndex = team.bench.indexOf(benchId);
  const starter = data.playerById.get(starterId);
  const substitute = data.playerById.get(benchId);
  if (starterIndex < 0 || benchIndex < 0 || !starter || !substitute) return;
  if (squadPosition(starter) !== squadPosition(substitute)) {
    return showToast("Choose a substitute in the same squad group.");
  }

  team.players[starterIndex] = benchId;
  team.bench[benchIndex] = starterId;
  const previousCaptain = team.captain;
  const previousViceCaptain = team.viceCaptain;
  if (team.captain === starterId) team.captain = benchId;
  if (team.viceCaptain === starterId) team.viceCaptain = benchId;
  savePreferences();
  dialog.close();
  renderPage();
  try {
    await syncSquad(ui.gameweek);
    showToast(`${fieldName(substitute)} is on; ${fieldName(starter)} moves to the bench.`);
  } catch (error) {
    team.players[starterIndex] = starterId;
    team.bench[benchIndex] = benchId;
    team.captain = previousCaptain;
    team.viceCaptain = previousViceCaptain;
    savePreferences();
    renderPage();
    showToast(`Lineup not saved: ${error.message}`);
  }
}

function autoPick() {
  const selection = affordableSquadSelection(transferBudget(ui.gameweek));
  if (!selection) return showToast("No nine-player squad fits the current budget and prices.");
  ui.draftPlayers = selection.players;
  ui.draftBench = selection.bench;
  renderPage();
  showToast(`Best-value squad picked for $${lineupCost([...selection.players, ...selection.bench]).toFixed(1)}m.`);
}

async function saveTransfers() {
  const draft = getDraft();
  const bench = getDraftBench();
  if (!isComplete(draft, bench)) return showToast("Fill all six starter and three bench places before saving.");
  const existing = ensureTeam(ui.gameweek);
  const spendingLimit = transferBudget(ui.gameweek);
  if (lineupCost([...draft, ...bench]) > spendingLimit + 1e-9) return showToast(`Your squad is over the $${spendingLimit.toFixed(1)}m gameweek budget.`);
  const transfersMade = draftTransferCount(ui.gameweek, draft, bench);
  const grandfatheredSquad = transfersMade > FREE_TRANSFERS && sameSquadPlayers(draft, bench, existing);
  if (transfersMade > FREE_TRANSFERS && !grandfatheredSquad) return showToast(`You can make at most ${FREE_TRANSFERS} transfers this gameweek.`);
  const previousSelection = {
    players: [...existing.players],
    bench: [...existing.bench],
    captain: existing.captain,
    viceCaptain: existing.viceCaptain,
    chip: existing.chip || null,
    bank: existing.bank
  };
  const captain = draft.includes(existing.captain) ? existing.captain : [...draft].sort((a, b) => formScore(data.playerById.get(b)) - formScore(data.playerById.get(a)))[0];
  const viceCaptain = draft.includes(existing.viceCaptain) && existing.viceCaptain !== captain ? existing.viceCaptain : draft.find((id) => id !== captain);
  preferences.teams[String(ui.gameweek)] = { players: [...draft], bench: [...bench], captain, viceCaptain, chip: existing.chip || null, bank: money(spendingLimit - lineupCost([...draft, ...bench])) };
  savePreferences();
  try {
    await syncSquad(ui.gameweek);
    showToast(grandfatheredSquad ? `Gameweek ${ui.gameweek} grandfathered squad saved.` : `Gameweek ${ui.gameweek} squad saved · ${transfersMade}/${FREE_TRANSFERS} free transfers used.`);
  } catch (error) {
    preferences.teams[String(ui.gameweek)] = previousSelection;
    savePreferences();
    showToast(`Squad not saved: ${error.message}`);
    return;
  }
  location.hash = "pick-team";
}

async function setChip(chip) {
  const team = ensureTeam(ui.gameweek);
  if (isLocked(ui.gameweek)) return;
  const usedGameweek = chipUsedGameweek(chip, ui.gameweek);
  if (usedGameweek) return showToast(`${CHIP_NAMES[chip]} was already used in Gameweek ${usedGameweek}.`);
  const previousChip = team.chip;
  team.chip = team.chip === chip ? null : chip;
  savePreferences();
  renderPage();
  try {
    await syncSquad(ui.gameweek);
    showToast(team.chip ? `${CHIP_NAMES[team.chip]} active for Gameweek ${ui.gameweek}.` : "Chip removed.");
  } catch (error) {
    team.chip = previousChip;
    savePreferences();
    renderPage();
    showToast(`Chip was not saved: ${error.message}`);
  }
}

async function setLeadership(playerId, role) {
  const team = ensureTeam(ui.gameweek);
  if (!team.players.includes(playerId) || isLocked(ui.gameweek)) return;
  const previousCaptain = team.captain;
  const previousViceCaptain = team.viceCaptain;
  if (role === "captain") {
    if (team.viceCaptain === playerId) team.viceCaptain = team.captain;
    team.captain = playerId;
  } else {
    if (team.captain === playerId) {
      const replacement = team.viceCaptain && team.viceCaptain !== playerId
        ? team.viceCaptain
        : team.players.find((id) => id !== playerId);
      team.captain = replacement;
    }
    team.viceCaptain = playerId;
  }
  savePreferences();
  renderPage();
  try {
    await syncSquad(ui.gameweek);
  } catch (error) {
    team.captain = previousCaptain;
    team.viceCaptain = previousViceCaptain;
    savePreferences();
    renderPage();
    showToast(`Captain not saved: ${error.message}`);
  }
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (action === "show-player") showPlayer(target.dataset.player);
  if (action === "view-league-squad") showLeagueSquad(target.dataset.manager, target.dataset.gameweek ? Number(target.dataset.gameweek) : undefined);
  if (action === "close-dialog") dialog.close();
  if (action === "toggle-player") togglePlayer(target.dataset.player);
  if (action === "promote-bench") promoteBench(target.dataset.player);
  if (action === "swap-lineup") swapLineup(target.dataset.starter, target.dataset.bench);
  if (action === "market-position") { ui.marketPosition = target.dataset.position; renderPage(); }
  if (action === "stats-position") { ui.statsPosition = target.dataset.position; renderPage(); }
  if (action === "auto-pick") autoPick();
  if (action === "save-transfers") saveTransfers();
  if (action === "set-captain") setLeadership(target.dataset.player, "captain");
  if (action === "set-vice") setLeadership(target.dataset.player, "vice");
  if (action === "toggle-chip") setChip(target.dataset.chip);
  if (action === "select-league") loadLeagueDashboard(target.dataset.code);
  if (action === "refresh-league") loadLeagueDashboard(leagueUi.activeCode);
  if (["enable-login", "replace-login-code", "account-logout"].includes(action)) manageAccount(action);
  if (action === "copy-login-code" && accountUi.code) {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(accountUi.code).then(() => showToast("Login code copied. Keep it private.")).catch(() => showToast("Select the code and copy it manually."));
    } else {
      showToast("Select the code and copy it manually.");
    }
  }
  if (action === "copy-code") {
    navigator.clipboard?.writeText(target.dataset.code)
      .then(() => showToast(`League code ${target.dataset.code} copied.`))
      .catch(() => showToast(`League code: ${target.dataset.code}`));
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-form]");
  if (!form) return;
  event.preventDefault();
  const button = form.querySelector('button[type="submit"]');
  if (button) button.disabled = true;
  leagueUi.error = "";
  try {
    if (form.dataset.form === "account-login") await signInToTeam(form);
    if (form.dataset.form === "manager-setup") await createManager(form);
    if (form.dataset.form === "create-league") await createLeague(form);
    if (form.dataset.form === "join-league") await joinLeague(form);
  } catch (error) {
    leagueUi.error = error.message;
    showToast(error.message);
    if (ui.route === "leagues") renderPage();
  } finally {
    if (button?.isConnected) button.disabled = false;
  }
});

document.addEventListener("change", (event) => {
  const action = event.target.dataset.action;
  if (action === "change-gameweek") {
    ui.gameweek = Number(event.target.value);
    ensureTeam(ui.gameweek);
    ui.draftGameweek = null;
    ui.draftPlayers = null;
    ui.draftBench = null;
    renderPage();
  }
  if (action === "ownership-gameweek") { ui.ownershipGameweek = Number(event.target.value); renderPage(); }
  if (action === "ownership-points-gameweek") { ui.ownershipPointsGameweek = event.target.value; renderPage(); }
  if (action === "league-squad-gameweek") showLeagueSquad(event.target.dataset.manager, Number(event.target.value));
  if (action === "market-sort") { ui.marketSort = event.target.value; renderPage(); }
  if (action === "stats-sort") { ui.statsSort = event.target.value; renderPage(); }
  if (action === "stats-season") { ui.statsSeason = event.target.value; renderPage(); }
});

document.addEventListener("input", (event) => {
  const action = event.target.dataset.action;
  if (action === "market-search") { ui.marketSearch = event.target.value; renderPage(); document.querySelector('[data-action="market-search"]')?.focus(); }
  if (action === "stats-search") { ui.statsSearch = event.target.value; renderPage(); document.querySelector('[data-action="stats-search"]')?.focus(); }
});

window.addEventListener("hashchange", () => {
  accountUi.code = null;
  ui.route = validRoute(location.hash.slice(1)) || "overview";
  ui.draftGameweek = null;
  ui.draftPlayers = null;
  ui.draftBench = null;
  renderPage();
  if (["leagues", "ownership"].includes(ui.route) && preferences.manager) loadLeagueDashboard();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

document.querySelector("#rename-team").addEventListener("click", async () => {
  const nextName = prompt("Name your fantasy team", preferences.teamName)?.trim();
  if (!nextName) return;
  preferences.teamName = nextName.slice(0, 28);
  savePreferences();
  renderPage();
  if (preferences.manager) {
    try {
      const response = await apiRequest("/api/me", {
        method: "PUT",
        body: { managerName: preferences.manager.managerName, teamName: preferences.teamName }
      });
      preferences.manager = { ...preferences.manager, ...response.manager };
      savePreferences();
      showToast("Team name updated.");
    } catch (error) {
      showToast(`Name changed locally; league update failed: ${error.message}`);
    }
  } else {
    showToast("Team name updated.");
  }
});

document.querySelector("#theme-button").addEventListener("click", () => {
  preferences.theme = document.documentElement.classList.toggle("dark") ? "dark" : "light";
  savePreferences();
});

dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});

async function initialize() {
  try {
    const [players, gameweeks, stats, priceText, pricingReportText, gameweekStats, liveScores] = await Promise.all([
      fetch("data/players.json").then((response) => response.json()),
      fetch("data/gameweeks.json").then((response) => response.json()),
      fetch("data/stats-2025.json").then((response) => response.json()),
      fetch("data/player-prices.csv").then((response) => response.text()),
      fetch("data/pricing-report.csv").then((response) => response.text()),
      fetch("data/gameweek-stats.json").then((response) => response.json()),
      fetch("data/live-scores.json").then((response) => response.json())
    ]);
    const prices = parseCsv(priceText);
    const pricingReport = parseCsv(pricingReportText);
    data = {
      players,
      gameweeks,
      stats,
      gameweekStats,
      liveScores,
      pricingReport,
      playerById: new Map(players.map((player) => [player.id, player])),
      statsById: new Map(stats.map((player) => [player.id, player])),
      basePriceById: new Map(prices.map((row) => [row.player_id, Number(row.price)])),
      priceById: new Map(prices.map((row) => [row.player_id, Number(row.price)])),
      priceReviewsById: new Map(),
      reviewedThrough: 0
    };
    recalculatePrices();
    ui.gameweek = findLiveGameweek();
    document.documentElement.classList.toggle("dark", preferences.theme === "dark");
    if (preferences.manager) {
      try {
        const profile = await apiRequest("/api/me");
        applyManagerProfile(profile);
        leagueUi.leagues = profile.leagues;
      } catch (error) {
        if (error.status === 401) {
          clearManagerSession();
        } else {
          syncedGameweeks = new Set(Object.keys(preferences.teams).map(Number));
          console.debug("Manager profile refresh unavailable", error);
        }
      }
    }
    ensureTeam(ui.gameweek);
    renderPage();
    if (["leagues", "ownership"].includes(ui.route) && preferences.manager) loadLeagueDashboard();
    liveRefreshTimer = setInterval(refreshLiveData, 30_000);
  } catch (error) {
    console.error(error);
    app.innerHTML = `<div class="error-state"><div><h2>We couldn’t load the squad.</h2><p>Run this site through <code>make dev</code>, then refresh.</p></div></div>`;
  }
}

async function refreshLiveData() {
  if (!data) return;
  try {
    const [nextLiveScores, nextGameweekStats] = await Promise.all([
      fetch("data/live-scores.json", { cache: "no-store" }).then((response) => response.json()),
      fetch("data/gameweek-stats.json", { cache: "no-store" }).then((response) => response.json())
    ]);
    const changed = JSON.stringify(nextLiveScores) !== JSON.stringify(data.liveScores) || JSON.stringify(nextGameweekStats) !== JSON.stringify(data.gameweekStats);
    if (!changed) return;
    data.liveScores = nextLiveScores;
    data.gameweekStats = nextGameweekStats;
    recalculatePrices();
    const activeGameweek = findLiveGameweek();
    if (liveScoreFor(activeGameweek)?.state === "live") ui.gameweek = activeGameweek;
    renderPage();
    if (["leagues", "ownership"].includes(ui.route) && preferences.manager) loadLeagueDashboard(leagueUi.activeCode);
  } catch (error) {
    console.debug("Live refresh unavailable", error);
  }
}

initialize();
