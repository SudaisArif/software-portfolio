import { money, restoreBanks, spendingLimit } from "../squad-finances.js";
import { AuthError, findSessionManager, createLoginCode, loginWithCode, logoutSession } from "./auth.js";

const BUDGET = 60;
const POSITION_LIMITS = { DEF: 2, MID: 2, FWD: 2 };
const BENCH_SIZE = 3;
const FREE_TRANSFERS = 2;
const IMPACT_SUB_MULTIPLIER = 1.25;
const IMPACT_SUB_MINUTES = 20;
const FULL_APPEARANCE_MINUTES = 40;
const PRICE_REVIEW_GAMEWEEKS = 3;
const FRESHMAN_BLOCK_EV = 1.5;
const MIN_PLAYER_PRICE = 3.5;
const MAX_PLAYER_PRICE = 12.5;
const CHIPS = new Set(["tripleCaptain", "benchBoost"]);
const LEAGUE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const NCAA_API = "https://ncaa-api.henrygd.me";
const NCAA_SCHOOL = "carnegie-mellon";
const RUNTIME_DATA = new Set(["live-scores.json", "gameweek-stats.json"]);

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function jsonResponse(value, status = 200) {
  return Response.json(value, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff"
    }
  });
}

function cleanText(value, label, minimum = 2, maximum = 40) {
  const cleaned = String(value ?? "").replace(/\s+/g, " ").trim();
  if (cleaned.length < minimum || cleaned.length > maximum) {
    throw new ApiError(400, `${label} must be ${minimum}–${maximum} characters.`);
  }
  return cleaned;
}

function publicManager(row) {
  return {
    id: row.id,
    managerName: row.manager_name,
    teamName: row.team_name,
    loginEnabled: Boolean(row.login_enabled)
  };
}

function publicSquad(row) {
  return {
    players: JSON.parse(row.players_json),
    bench: JSON.parse(row.bench_json || "[]"),
    captain: row.captain,
    viceCaptain: row.vice_captain,
    chip: row.chip || null,
    bank: row.bank ?? null
  };
}

async function managerSquads(env, managerId, requestUrl) {
  const { results } = await env.DB.prepare(
    "SELECT * FROM squads WHERE manager_id = ? ORDER BY gameweek"
  ).bind(managerId).all();
  const teams = restoreBanks(results.map((row) => ({ ...publicSquad(row), gameweek: row.gameweek })),
    await loadPriceState(env, requestUrl));
  return Object.fromEntries(teams.map(({ gameweek, ...team }) => [String(gameweek), team]));
}

function leagueSummary(row, managerId) {
  return {
    code: row.code,
    name: row.name,
    isOwner: row.owner_manager_id === managerId
  };
}

function bearerToken(request) {
  const value = request.headers.get("Authorization") || "";
  return value.startsWith("Bearer ") ? value.slice(7).trim() : "";
}

async function requestJson(request) {
  const declaredLength = Number(request.headers.get("Content-Length") || 0);
  if (declaredLength > 100_000) throw new ApiError(413, "Request is too large.");
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > 100_000) {
    throw new ApiError(413, "Request is too large.");
  }
  try {
    const payload = text ? JSON.parse(text) : {};
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("Object required");
    return payload;
  } catch {
    throw new ApiError(400, "Request body must be valid JSON.");
  }
}

async function managerFromRequest(request, env) {
  const token = bearerToken(request);
  if (!token) throw new ApiError(401, "Create your manager first.");
  const manager = await findSessionManager(token, env);
  if (!manager) throw new ApiError(401, "This manager session is no longer valid.");
  return manager;
}

async function managerLeagues(env, managerId) {
  const { results } = await env.DB.prepare(`
    SELECT l.* FROM leagues l
    JOIN league_members lm ON lm.league_id = l.id
    WHERE lm.manager_id = ?
    ORDER BY l.created_at, l.name
  `).bind(managerId).all();
  return results.map((row) => leagueSummary(row, managerId));
}

function generateCode() {
  const random = new Uint8Array(6);
  crypto.getRandomValues(random);
  return Array.from(random, (value) => LEAGUE_ALPHABET[value % LEAGUE_ALPHABET.length]).join("");
}

function generateToken() {
  const random = new Uint8Array(32);
  crypto.getRandomValues(random);
  return btoa(String.fromCharCode(...random)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

async function loadText(env, requestUrl, name) {
  const url = new URL(`/data/${name}`, requestUrl);
  const response = await env.ASSETS.fetch(url);
  if (!response.ok) throw new Error(`Could not load ${name}.`);
  return response.text();
}

async function loadJson(env, requestUrl, name) {
  const baseline = JSON.parse(await loadText(env, requestUrl, name));
  if (!RUNTIME_DATA.has(name)) return baseline;
  const stored = await env.DB.prepare("SELECT value FROM runtime_data WHERE key = ?").bind(name).first();
  if (!stored) return baseline;
  const runtime = JSON.parse(stored.value);
  if (name === "live-scores.json") return { ...baseline, ...runtime };

  const merged = { ...baseline };
  for (const [gameweek, players] of Object.entries(runtime)) {
    merged[gameweek] ||= {};
    for (const [playerId, stats] of Object.entries(players)) {
      const manual = merged[gameweek][playerId] || {};
      merged[gameweek][playerId] = mergeStatRecord(manual, stats);
    }
  }
  return merged;
}

function mergeStatRecord(manual, stats) {
  const manualOverrides = manual.manualOverrides ?? stats.manualOverrides ?? null;
  const merged = {
    ...manual,
    ...stats,
    bonus: manual.bonus ?? stats.bonus ?? 0,
    ownGoals: manual.ownGoals ?? stats.ownGoals ?? 0,
    penaltiesMissed: manual.penaltiesMissed ?? stats.penaltiesMissed ?? 0,
    penaltiesSaved: manual.penaltiesSaved ?? stats.penaltiesSaved ?? 0
  };
  if (manualOverrides && typeof manualOverrides === "object") {
    Object.assign(merged, manualOverrides);
    merged.manualOverrides = manualOverrides;
  }
  return merged;
}

async function loadPrices(env, requestUrl) {
  const rows = (await loadText(env, requestUrl, "player-prices.csv")).trim().split(/\r?\n/).slice(1);
  return Object.fromEntries(rows.filter(Boolean).map((row) => {
    const [playerId, , price] = row.split(",");
    return [playerId, Number(price)];
  }));
}

function parseCsvRows(text) {
  const [header, ...lines] = text.trim().split(/\r?\n/);
  const keys = header.split(",");
  return lines.filter(Boolean).map((line) => Object.fromEntries(line.split(",").map((value, index) => [keys[index], value])));
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

function calculatePriceReviews(playerList, basePrices, pricingReport, gameweekStats, liveScores, gameweeks) {
  const prices = { ...basePrices };
  const reportById = Object.fromEntries(pricingReport.map((row) => [row.player_id, row]));
  const reviewsById = Object.fromEntries(playerList.map((player) => [player.id, []]));
  const sortedEvents = [...gameweeks].sort((a, b) => a.gameweek - b.gameweek);
  const completedBlocks = [];

  for (let start = 0; start + PRICE_REVIEW_GAMEWEEKS <= sortedEvents.length; start += PRICE_REVIEW_GAMEWEEKS) {
    const events = sortedEvents.slice(start, start + PRICE_REVIEW_GAMEWEEKS);
    const ready = events.every((event) => liveScores[String(event.gameweek)]?.state === "final"
      && Object.hasOwn(gameweekStats, String(event.gameweek)));
    if (!ready) break;
    completedBlocks.push(events);
  }

  completedBlocks.forEach((events, blockIndex) => {
    for (const player of playerList) {
      const careerRating = Number(reportById[player.id]?.career_rating || 0);
      const expected = Math.max(FRESHMAN_BLOCK_EV, careerRating / 6);
      const actual = events.reduce((total, event) => {
        const stats = gameweekStats[String(event.gameweek)]?.[player.id] || {};
        return total + impactSubPoints(rawPoints(player.position, stats), stats);
      }, 0);
      const previousPrice = prices[player.id] ?? 5;
      const nextPrice = Math.min(MAX_PLAYER_PRICE, Math.max(
        MIN_PLAYER_PRICE,
        Math.round((previousPrice + priceReviewMove(actual, expected)) * 10) / 10
      ));
      prices[player.id] = nextPrice;
      reviewsById[player.id].push({
        block: blockIndex + 1,
        fromGameweek: events[0].gameweek,
        throughGameweek: events.at(-1).gameweek,
        actual,
        expected: Math.round(expected * 10) / 10,
        move: Math.round((nextPrice - previousPrice) * 10) / 10,
        price: nextPrice
      });
    }
  });

  return {
    prices,
    reviewsById,
    reviewedThrough: completedBlocks.at(-1)?.at(-1)?.gameweek || 0
  };
}

async function loadPriceState(env, requestUrl, inputs = {}) {
  const [playerList, basePrices, pricingReportText, gameweekStats, liveScores, gameweeks] = await Promise.all([
    inputs.playerList || loadJson(env, requestUrl, "players.json"),
    inputs.basePrices || loadPrices(env, requestUrl),
    inputs.pricingReportText || loadText(env, requestUrl, "pricing-report.csv"),
    inputs.gameweekStats || loadJson(env, requestUrl, "gameweek-stats.json"),
    inputs.liveScores || loadJson(env, requestUrl, "live-scores.json"),
    inputs.gameweeks || loadJson(env, requestUrl, "gameweeks.json")
  ]);
  return calculatePriceReviews(playerList, basePrices, parseCsvRows(pricingReportText), gameweekStats, liveScores, gameweeks);
}

function easternDate() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date());
}

async function currentGameweek(env, requestUrl, gameweeks = null, liveScores = null) {
  const events = gameweeks || await loadJson(env, requestUrl, "gameweeks.json");
  const live = liveScores || await loadJson(env, requestUrl, "live-scores.json");
  const liveEvent = events.find((event) => live[String(event.gameweek)]?.state === "live");
  if (liveEvent) return liveEvent.gameweek;
  const today = easternDate();
  const todayEvent = events.find((event) => event.date === today);
  if (todayEvent) return todayEvent.gameweek;
  const upcoming = events.find((event) => new Date(event.deadline).getTime() > Date.now());
  return (upcoming || events.at(-1)).gameweek;
}

async function validateSquad(gameweek, payload, env, requestUrl) {
  const [events, playerList] = await Promise.all([
    loadJson(env, requestUrl, "gameweeks.json"),
    loadJson(env, requestUrl, "players.json")
  ]);
  const priceState = await loadPriceState(env, requestUrl, { playerList, gameweeks: events });
  const event = events.find((candidate) => candidate.gameweek === gameweek);
  if (!event) throw new ApiError(404, "Unknown gameweek.");
  if (env.ALLOW_LOCKED_WRITES !== "1" && Date.now() >= new Date(event.deadline).getTime()) {
    throw new ApiError(409, "That gameweek is locked.");
  }

  const players = payload.players;
  const bench = payload.bench;
  const captain = payload.captain;
  const viceCaptain = payload.viceCaptain;
  const chip = payload.chip || null;
  if (!Array.isArray(players) || players.length !== 6 || new Set(players).size !== 6) {
    throw new ApiError(400, "The starting lineup must contain six different players.");
  }
  if (!Array.isArray(bench) || bench.length !== BENCH_SIZE || new Set(bench).size !== BENCH_SIZE) {
    throw new ApiError(400, "The bench must contain three different players.");
  }
  const squadIds = [...players, ...bench];
  if (new Set(squadIds).size !== 6 + BENCH_SIZE) {
    throw new ApiError(400, "A player cannot be both a starter and a substitute.");
  }
  const playerPool = Object.fromEntries(playerList.map((player) => [player.id, player]));
  if (squadIds.some((playerId) => !playerPool[playerId])) {
    throw new ApiError(400, "The squad contains an unknown player.");
  }
  const counts = { DEF: 0, MID: 0, FWD: 0 };
  for (const playerId of players) {
    const playerPosition = playerPool[playerId].position;
    counts[playerPosition === "GK" ? "DEF" : playerPosition] += 1;
  }
  if (Object.keys(POSITION_LIMITS).some((position) => counts[position] !== POSITION_LIMITS[position])) {
    throw new ApiError(400, "Use the 2–2–2 formation; goalkeepers count as defenders.");
  }
  if (!players.includes(captain) || !players.includes(viceCaptain) || captain === viceCaptain) {
    throw new ApiError(400, "Captain and vice-captain must be different selected players.");
  }
  if (chip !== null && !CHIPS.has(chip)) throw new ApiError(400, "Unknown chip selection.");
  const squadCost = squadIds.reduce((total, playerId) => total + priceState.prices[playerId], 0);
  return { players, bench, captain, viceCaptain, chip, squadCost, prices: priceState.prices, priceState };
}

function rawPoints(position, stats) {
  const minutes = Math.trunc(Number(stats.minutes || 0));
  let points = minutes >= FULL_APPEARANCE_MINUTES ? 2 : minutes > 0 ? 1 : 0;
  points += Math.trunc(Number(stats.goals || 0)) * ({ GK: 6, DEF: 6, MID: 5, FWD: 4 }[position] || 4);
  points += Math.trunc(Number(stats.assists || 0)) * 3;
  if (earnedCleanSheet(stats, minutes)) points += ({ GK: 4, DEF: 4, MID: 1, FWD: 0 }[position] || 0);
  if (position === "GK") {
    points += Math.floor(Number(stats.saves || 0) / 3);
    points += Math.trunc(Number(stats.penaltiesSaved || 0)) * 5;
  }
  points -= Math.trunc(Number(stats.yellowCards || 0));
  points -= Math.trunc(Number(stats.redCards || 0)) * 3;
  points -= Math.trunc(Number(stats.ownGoals || 0)) * 2;
  points -= Math.trunc(Number(stats.penaltiesMissed || 0)) * 2;
  points += Math.trunc(Number(stats.bonus || 0));
  return points;
}

function earnedCleanSheet(stats, minutes = Math.trunc(Number(stats?.minutes || 0))) {
  const shutout = stats?.cleanSheet === true || stats?.opponentScore === 0 || stats?.opponentScore === "0";
  return shutout && minutes >= FULL_APPEARANCE_MINUTES;
}

function impactSubPoints(points, stats) {
  const minutes = Math.trunc(Number(stats.minutes || 0));
  return stats.started === false && minutes >= IMPACT_SUB_MINUTES && points > 0
    ? Math.ceil(points * IMPACT_SUB_MULTIPLIER)
    : points;
}

function squadPoints(squad, gameweek, positions, gameweekStats) {
  const records = gameweekStats[String(gameweek)] || {};
  const captainStats = records[squad.captain] || {};
  const effectiveCaptain = Number(captainStats.minutes || 0) > 0 ? squad.captain : squad.vice_captain;
  const chip = Number(squad.gameweek) === gameweek ? squad.chip : null;
  const starters = JSON.parse(squad.players_json);
  const bench = JSON.parse(squad.bench_json || "[]");
  const scoringPlayers = chip === "benchBoost" ? [...starters, ...bench] : starters;
  const captainMultiplier = chip === "tripleCaptain" ? 3 : 2;
  return scoringPlayers.reduce((total, playerId) => {
    const playerStats = records[playerId] || {};
    let points = rawPoints(positions[playerId], playerStats);
    if (starters.includes(playerId)) points = impactSubPoints(points, playerStats);
    return total + points * (playerId === effectiveCaptain ? captainMultiplier : 1);
  }, 0);
}

function squadPlayerIds(squad) {
  return new Set([...JSON.parse(squad.players_json), ...JSON.parse(squad.bench_json || "[]")]);
}

function transferCount(currentSquad, previousSquad) {
  const currentIds = squadPlayerIds(currentSquad);
  return [...squadPlayerIds(previousSquad)].filter((playerId) => !currentIds.has(playerId)).length;
}

function scoreValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
}

function truthy(value) {
  return value === true || ["1", "true", "yes", "y"].includes(String(value ?? "").trim().toLowerCase());
}

function slugify(value) {
  return String(value)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function findCmuGame(scoreboard) {
  for (const wrapper of scoreboard.games || []) {
    const game = wrapper.game || {};
    const away = game.away?.names?.seo;
    const home = game.home?.names?.seo;
    if ([away, home].includes(NCAA_SCHOOL)) return game;
  }
  return null;
}

function liveRecord(game, event) {
  const cmuIsHome = game.home?.names?.seo === NCAA_SCHOOL;
  const cmu = game[cmuIsHome ? "home" : "away"] || {};
  const opponent = game[cmuIsHome ? "away" : "home"] || {};
  return {
    gameweek: event.gameweek,
    gameId: String(game.gameID || ""),
    state: game.gameState || "pre",
    cmuScore: scoreValue(cmu.score),
    opponentScore: scoreValue(opponent.score),
    opponent: event.opponent,
    period: game.currentPeriod || game.finalMessage || "",
    clock: game.contestClock || "",
    startTime: game.startTime || `${event.time} ET`,
    updatedAt: new Date().toISOString(),
    sourceUrl: `https://www.ncaa.com/game/${game.gameID}`
  };
}

function parseNcaaBoxscore(document, game, currentIds) {
  const cmuIsHome = game.home?.names?.seo === NCAA_SCHOOL;
  const cmuSide = game[cmuIsHome ? "home" : "away"] || {};
  const opponentSide = game[cmuIsHome ? "away" : "home"] || {};
  const teams = Object.fromEntries((document.teams || []).map((team) => [String(team.teamId), team]));
  const cmuTeamId = Object.keys(teams).find((teamId) => teams[teamId].seoname === NCAA_SCHOOL);
  const teamBoxscore = (document.teamBoxscore || []).find((team) => String(team.teamId) === cmuTeamId);
  if (!cmuTeamId || !teamBoxscore) return {};

  const output = {};
  for (const player of teamBoxscore.playerStats || []) {
    if (!player.participated) continue;
    const playerId = slugify(`${player.firstName || ""} ${player.lastName || ""}`);
    if (!currentIds.has(playerId)) continue;
    const penalties = player.penalties || {};
    const minutes = scoreValue(player.minutesPlayed) || 0;
    output[playerId] = {
      minutes,
      started: truthy(player.starter),
      goals: scoreValue(player.goals) || 0,
      assists: scoreValue(player.assists) || 0,
      shots: scoreValue(player.shots) || 0,
      shotsOnGoal: scoreValue(player.shotsOnGoal) || 0,
      yellowCards: scoreValue(penalties.yellowCards) || 0,
      redCards: scoreValue(penalties.redCards) || 0,
      saves: scoreValue(player.goalie?.saves) ?? scoreValue(player.saves) ?? 0,
      cleanSheet: game.gameState === "final" && scoreValue(opponentSide.score) === 0 && minutes >= FULL_APPEARANCE_MINUTES,
      ownGoals: 0,
      penaltiesMissed: Math.max(0, (scoreValue(player.penaltyShotAttempts) || 0) - (scoreValue(player.penaltyShotGoals) || 0)),
      penaltiesSaved: 0,
      bonus: 0,
      source: "NCAA",
      provisional: game.gameState !== "final",
      teamScore: scoreValue(cmuSide.score),
      opponentScore: scoreValue(opponentSide.score)
    };
  }
  return output;
}

async function storeRuntimeData(env, key, value) {
  await env.DB.prepare(`
    INSERT INTO runtime_data (key, value, updated_at) VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
  `).bind(key, JSON.stringify(value), new Date().toISOString()).run();
}

async function syncLiveData(env) {
  const assetUrl = "https://static-assets.local";
  const [gameweeks, players] = await Promise.all([
    loadJson(env, assetUrl, "gameweeks.json"),
    loadJson(env, assetUrl, "players.json")
  ]);
  const event = gameweeks.find((candidate) => candidate.date === easternDate());
  if (!event) return;

  const datePath = event.date.replaceAll("-", "/");
  const scoreboardResponse = await fetch(`${NCAA_API}/scoreboard/soccer-men/d3/${datePath}`);
  if (!scoreboardResponse.ok) throw new Error(`NCAA scoreboard returned ${scoreboardResponse.status}.`);
  const game = findCmuGame(await scoreboardResponse.json());
  if (!game) return;

  const liveScores = await loadJson(env, assetUrl, "live-scores.json");
  liveScores[String(event.gameweek)] = liveRecord(game, event);
  await storeRuntimeData(env, "live-scores.json", liveScores);

  if (!["live", "final"].includes(game.gameState)) return;
  const boxscoreResponse = await fetch(`${NCAA_API}/game/${game.gameID}/boxscore`);
  if (!boxscoreResponse.ok) throw new Error(`NCAA box score returned ${boxscoreResponse.status}.`);
  const parsed = parseNcaaBoxscore(await boxscoreResponse.json(), game, new Set(players.map((player) => player.id)));
  if (!Object.keys(parsed).length) return;
  const gameweekStats = await loadJson(env, assetUrl, "gameweek-stats.json");
  const existingWeek = gameweekStats[String(event.gameweek)] || {};
  gameweekStats[String(event.gameweek)] = { ...existingWeek };
  for (const [playerId, stats] of Object.entries(parsed)) {
    const prior = existingWeek[playerId] || {};
    gameweekStats[String(event.gameweek)][playerId] = mergeStatRecord(prior, stats);
  }
  await storeRuntimeData(env, "gameweek-stats.json", gameweekStats);
}

async function leagueStandings(code, managerId, env, requestUrl) {
  const league = await env.DB.prepare("SELECT * FROM leagues WHERE code = ?").bind(code).first();
  if (!league) throw new ApiError(404, "League code not found.");
  const membership = await env.DB.prepare(
    "SELECT 1 AS member FROM league_members WHERE league_id = ? AND manager_id = ?"
  ).bind(league.id, managerId).first();
  if (!membership) throw new ApiError(403, "Join this league before viewing it.");

  const [memberRows, squadRows, playerList, stats, liveScores, gameweeks] = await Promise.all([
    env.DB.prepare(`
      SELECT m.* FROM managers m
      JOIN league_members lm ON lm.manager_id = m.id
      WHERE lm.league_id = ?
    `).bind(league.id).all(),
    env.DB.prepare(`
      SELECT * FROM squads
      WHERE manager_id IN (SELECT manager_id FROM league_members WHERE league_id = ?)
    `).bind(league.id).all(),
    loadJson(env, requestUrl, "players.json"),
    loadJson(env, requestUrl, "gameweek-stats.json"),
    loadJson(env, requestUrl, "live-scores.json"),
    loadJson(env, requestUrl, "gameweeks.json")
  ]);
  const activeGameweek = await currentGameweek(env, requestUrl, gameweeks, liveScores);
  const priceState = await loadPriceState(env, requestUrl, {
    playerList,
    gameweekStats: stats,
    liveScores,
    gameweeks
  });
  const activeEvent = gameweeks.find((event) => event.gameweek === activeGameweek);
  const otherSquadsVisible = Date.now() >= new Date(activeEvent.deadline).getTime();
  const positions = Object.fromEntries(playerList.map((player) => [player.id, player.position]));
  const gameweekNumbers = gameweeks.map((event) => event.gameweek).sort((a, b) => a - b);
  const squadsByManager = {};
  for (const squad of squadRows.results) {
    (squadsByManager[squad.manager_id] ||= {})[Number(squad.gameweek)] = squad;
  }

  const standings = memberRows.results.map((member) => {
    const memberSquads = squadsByManager[member.id] || {};
    const weekly = {};
    const transfers = {};
    let activeSquad = null;
    let previousSquad = null;
    const squadHistory = {};
    for (const gameweek of gameweekNumbers) {
      activeSquad = memberSquads[gameweek] || activeSquad;
      const event = gameweeks.find((candidate) => candidate.gameweek === gameweek);
      const canViewGameweek = member.id === managerId || Date.now() >= new Date(event.deadline).getTime();
      if (activeSquad && canViewGameweek) {
        squadHistory[String(gameweek)] = publicSquad(activeSquad);
        if (Number(activeSquad.gameweek) !== gameweek) squadHistory[String(gameweek)].chip = null;
      }
      const scored = Object.hasOwn(stats, String(gameweek)) || ["live", "final"].includes(liveScores[String(gameweek)]?.state);
      if (activeSquad && scored) {
        const made = gameweek > 1 && previousSquad ? transferCount(activeSquad, previousSquad) : 0;
        transfers[gameweek] = made;
        weekly[gameweek] = squadPoints(activeSquad, gameweek, positions, stats);
      }
      if (activeSquad) previousSquad = activeSquad;
    }
    const canViewSquad = member.id === managerId || otherSquadsVisible;
    const latestVisibleGameweek = Object.keys(squadHistory).map(Number).sort((a, b) => b - a)[0];
    const latestVisibleSquad = latestVisibleGameweek ? squadHistory[String(latestVisibleGameweek)] : null;
    const squadValue = latestVisibleSquad
      ? [...latestVisibleSquad.players, ...latestVisibleSquad.bench]
        .reduce((total, playerId) => total + priceState.prices[playerId], 0)
      : null;
    return {
      managerId: member.id,
      managerName: member.manager_name,
      teamName: member.team_name,
      totalPoints: Object.values(weekly).reduce((total, points) => total + points, 0),
      gameweekPoints: weekly[activeGameweek] || 0,
      transfersMade: transfers[activeGameweek] || 0,
      squadValue: squadValue === null ? null : Math.round(squadValue * 10) / 10,
      canViewSquad,
      squad: squadHistory[String(activeGameweek)] || null,
      squads: squadHistory,
      weeklyPoints: weekly,
      transfersByGameweek: transfers
    };
  });
  standings.sort((a, b) => b.totalPoints - a.totalPoints || a.teamName.localeCompare(b.teamName) || a.managerName.localeCompare(b.managerName));
  let previousPoints = null;
  let previousRank = 0;
  standings.forEach((entry, index) => {
    if (entry.totalPoints !== previousPoints) previousRank = index + 1;
    entry.rank = previousRank;
    previousPoints = entry.totalPoints;
  });
  return {
    league: leagueSummary(league, managerId),
    memberCount: standings.length,
    currentGameweek: activeGameweek,
    freeTransfers: FREE_TRANSFERS,
    standings
  };
}

async function managerProfile(manager, env, requestUrl) {
  return {
    manager: publicManager(manager),
    leagues: await managerLeagues(env, manager.id),
    squads: await managerSquads(env, manager.id, requestUrl)
  };
}

async function handleGet(request, env, path) {
  if (path === "/api/health") return jsonResponse({ ok: true });
  const manager = await managerFromRequest(request, env);
  if (path === "/api/me") {
    return jsonResponse(await managerProfile(manager, env, request.url));
  }
  const match = path.match(/^\/api\/leagues\/([A-Za-z0-9]+)$/);
  if (match) return jsonResponse(await leagueStandings(match[1].toUpperCase(), manager.id, env, request.url));
  throw new ApiError(404, "API route not found.");
}

async function handlePost(request, env, path) {
  const payload = await requestJson(request);
  if (path === "/api/auth/login") {
    const { manager, token } = await loginWithCode(payload.code, request, env);
    return jsonResponse({ ...await managerProfile(manager, env, request.url), token });
  }
  if (path === "/api/managers") {
    const managerName = cleanText(payload.managerName, "Your name");
    const teamName = cleanText(payload.teamName, "Team name");
    const id = crypto.randomUUID();
    const token = generateToken();
    await env.DB.prepare("INSERT INTO managers VALUES (?, ?, ?, ?, ?)")
      .bind(id, token, managerName, teamName, new Date().toISOString()).run();
    return jsonResponse({ manager: { id, managerName, teamName }, token }, 201);
  }

  const manager = await managerFromRequest(request, env);
  if (path === "/api/auth/enable" || path === "/api/auth/rotate") {
    const code = await createLoginCode(manager, env, path === "/api/auth/rotate");
    return jsonResponse({ code, manager: { ...publicManager(manager), loginEnabled: true } });
  }
  if (path === "/api/auth/logout") {
    await logoutSession(manager, bearerToken(request), env);
    return jsonResponse({ ok: true });
  }
  if (path === "/api/leagues") {
    const name = cleanText(payload.name, "League name");
    const leagueId = crypto.randomUUID();
    let code = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const candidate = generateCode();
      try {
        await env.DB.batch([
          env.DB.prepare("INSERT INTO leagues VALUES (?, ?, ?, ?, ?)")
            .bind(leagueId, candidate, name, manager.id, new Date().toISOString()),
          env.DB.prepare("INSERT INTO league_members VALUES (?, ?, ?)")
            .bind(leagueId, manager.id, new Date().toISOString())
        ]);
        code = candidate;
        break;
      } catch (error) {
        if (!String(error).toLowerCase().includes("unique")) throw error;
      }
    }
    if (!code) throw new ApiError(500, "Could not generate a league code.");
    return jsonResponse({ league: { code, name, isOwner: true } }, 201);
  }

  if (path === "/api/leagues/join") {
    const code = String(payload.code || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (code.length !== 6) throw new ApiError(400, "Enter the six-character league code.");
    const league = await env.DB.prepare("SELECT * FROM leagues WHERE code = ?").bind(code).first();
    if (!league) throw new ApiError(404, "League code not found.");
    await env.DB.prepare("INSERT OR IGNORE INTO league_members VALUES (?, ?, ?)")
      .bind(league.id, manager.id, new Date().toISOString()).run();
    return jsonResponse({ league: leagueSummary(league, manager.id) });
  }
  throw new ApiError(404, "API route not found.");
}

async function handlePut(request, env, path) {
  const manager = await managerFromRequest(request, env);
  const payload = await requestJson(request);
  if (path === "/api/me") {
    const managerName = cleanText(payload.managerName ?? manager.manager_name, "Your name");
    const teamName = cleanText(payload.teamName ?? manager.team_name, "Team name");
    await env.DB.prepare("UPDATE managers SET manager_name = ?, team_name = ? WHERE id = ?")
      .bind(managerName, teamName, manager.id).run();
    return jsonResponse({ manager: { id: manager.id, managerName, teamName } });
  }

  const match = path.match(/^\/api\/squads\/(\d+)$/);
  if (match) {
    const gameweek = Number(match[1]);
    const squad = await validateSquad(gameweek, payload, env, request.url);
    if (squad.chip) {
      const used = await env.DB.prepare(
        "SELECT gameweek FROM squads WHERE manager_id = ? AND chip = ? AND gameweek != ?"
      ).bind(manager.id, squad.chip, gameweek).first();
      if (used) throw new ApiError(409, `That chip was already used in Gameweek ${used.gameweek}.`);
    }
    const [previousSquad, existingSquad, nextSquad] = await Promise.all([
      env.DB.prepare(`
        SELECT * FROM squads WHERE manager_id = ? AND gameweek < ? ORDER BY gameweek DESC LIMIT 1
      `).bind(manager.id, gameweek).first(),
      env.DB.prepare("SELECT * FROM squads WHERE manager_id = ? AND gameweek = ?")
        .bind(manager.id, gameweek).first(),
      env.DB.prepare(`
        SELECT * FROM squads WHERE manager_id = ? AND gameweek > ? ORDER BY gameweek LIMIT 1
      `).bind(manager.id, gameweek).first()
    ]);
    const candidate = {
      players_json: JSON.stringify(squad.players),
      bench_json: JSON.stringify(squad.bench)
    };
    const { results: history } = await env.DB.prepare(
      "SELECT * FROM squads WHERE manager_id = ? AND gameweek <= ? ORDER BY gameweek"
    ).bind(manager.id, gameweek).all();
    const teams = restoreBanks(history.map((row) => ({ ...publicSquad(row), gameweek: row.gameweek })), squad.priceState);
    const available = spendingLimit(teams.at(-1), squad.prices, BUDGET);
    if (squad.squadCost > available + 1e-9) {
      throw new ApiError(400, `The squad is over this gameweek's $${available.toFixed(1)}m budget.`);
    }
    const bank = money(available - squad.squadCost);
    const keepsGrandfatheredSquad = previousSquad
      && existingSquad
      && transferCount(existingSquad, previousSquad) > FREE_TRANSFERS
      && transferCount(candidate, existingSquad) === 0;
    if (previousSquad && transferCount(candidate, previousSquad) > FREE_TRANSFERS && !keepsGrandfatheredSquad) {
      throw new ApiError(400, `You can make at most ${FREE_TRANSFERS} transfers per gameweek.`);
    }
    if (nextSquad && transferCount(nextSquad, candidate) > FREE_TRANSFERS) {
      throw new ApiError(400, `This change would leave Gameweek ${nextSquad.gameweek} over its ${FREE_TRANSFERS}-transfer limit.`);
    }
    if (nextSquad && (!existingSquad || transferCount(candidate, existingSquad) !== 0)) {
      throw new ApiError(409, "Make transfers in your latest saved gameweek so later squads keep the correct bank.");
    }
    await env.DB.prepare(`
      INSERT INTO squads (
        manager_id, gameweek, players_json, bench_json,
        captain, vice_captain, chip, updated_at, bank
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(manager_id, gameweek) DO UPDATE SET
        players_json = excluded.players_json,
        bench_json = excluded.bench_json,
        captain = excluded.captain,
        vice_captain = excluded.vice_captain,
        chip = excluded.chip,
        updated_at = excluded.updated_at,
        bank = excluded.bank
    `).bind(
      manager.id,
      gameweek,
      JSON.stringify(squad.players),
      JSON.stringify(squad.bench),
      squad.captain,
      squad.viceCaptain,
      squad.chip,
      new Date().toISOString(),
      bank
    ).run();
    return jsonResponse({ ok: true, gameweek, bank });
  }
  throw new ApiError(404, "API route not found.");
}

async function handleApi(request, env, path) {
  if (request.method === "GET") return handleGet(request, env, path);
  if (request.method === "POST") return handlePost(request, env, path);
  if (request.method === "PUT") return handlePut(request, env, path);
  throw new ApiError(405, "Method not allowed.");
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    try {
      if (path.startsWith("/api/")) return await handleApi(request, env, path);
      if (request.method === "GET" && ["/data/live-scores.json", "/data/gameweek-stats.json"].includes(path)) {
        return jsonResponse(await loadJson(env, request.url, path.slice("/data/".length)));
      }
      return env.ASSETS.fetch(request);
    } catch (error) {
      if (error instanceof ApiError || error instanceof AuthError) return jsonResponse({ error: error.message }, error.status);
      console.error("API error", error);
      return jsonResponse({ error: "The league server hit an unexpected error." }, 500);
    }
  },

  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(syncLiveData(env).catch((error) => console.error("Live sync error", error)));
  }
};

export const testing = {
  rawPoints,
  impactSubPoints,
  priceReviewMove,
  calculatePriceReviews,
  mergeStatRecord,
  transferCount,
  findCmuGame,
  parseNcaaBoxscore
};
