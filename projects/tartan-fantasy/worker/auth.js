const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const SESSION_SECONDS = 90 * 24 * 60 * 60;
const RATE_WINDOW_SECONDS = 15 * 60;
const MAX_LOGIN_ATTEMPTS = 100;

export class AuthError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export async function secretHash(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function newSessionToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export async function findSessionManager(token, env) {
  if (!token || token.length > 128) return null;
  const legacy = await env.DB.prepare(`
    SELECT m.*, CASE WHEN l.manager_id IS NULL THEN 0 ELSE 1 END AS login_enabled
    FROM managers m LEFT JOIN manager_logins l ON l.manager_id = m.id WHERE m.token = ?
  `).bind(token).first();
  if (legacy) return legacy;
  return env.DB.prepare(`
    SELECT m.*, CASE WHEN l.manager_id IS NULL THEN 0 ELSE 1 END AS login_enabled
    FROM manager_sessions s JOIN managers m ON m.id = s.manager_id
    LEFT JOIN manager_logins l ON l.manager_id = m.id
    WHERE s.token_hash = ? AND s.expires_at > ?
  `).bind(await secretHash(token), Math.floor(Date.now() / 1000)).first();
}

export async function createLoginCode(manager, env, replace = false) {
  // 32 independent base32 characters provide 160 bits of entropy. This is a
  // generated secret, never a user-chosen password; only its hash is stored.
  const code = [...crypto.getRandomValues(new Uint8Array(32))]
    .map((byte) => CODE_ALPHABET[byte & 31]).join("");
  const codeHash = await secretHash(code);
  if (replace) {
    const result = await env.DB.prepare("UPDATE manager_logins SET code_hash = ?, created_at = ? WHERE manager_id = ?")
      .bind(codeHash, new Date().toISOString(), manager.id).run();
    if (!result.meta.changes) throw new AuthError(409, "Enable optional sign-in for this team first.");
  } else {
    const result = await env.DB.prepare("INSERT OR IGNORE INTO manager_logins (manager_id, code_hash, created_at) VALUES (?, ?, ?)")
      .bind(manager.id, codeHash, new Date().toISOString()).run();
    if (!result.meta.changes) throw new AuthError(409, "Sign-in is already enabled. Use Replace login code if you need a new code.");
  }
  return `TF-${code.match(/.{8}/g).join("-")}`;
}

async function limitLoginAttempts(request, env) {
  const now = Math.floor(Date.now() / 1000);
  const window = Math.floor(now / RATE_WINDOW_SECONDS) * RATE_WINDOW_SECONDS;
  const bucket = await secretHash(`login:${request.headers.get("CF-Connecting-IP") || "local"}`);
  const row = await env.DB.prepare(`
    INSERT INTO login_attempts (bucket, window_start, attempts) VALUES (?, ?, 1)
    ON CONFLICT(bucket) DO UPDATE SET
      attempts = CASE WHEN window_start = excluded.window_start THEN attempts + 1 ELSE 1 END,
      window_start = excluded.window_start
    RETURNING attempts
  `).bind(bucket, window).first();
  await env.DB.prepare("DELETE FROM login_attempts WHERE window_start < ?").bind(window - RATE_WINDOW_SECONDS).run();
  if (row.attempts > MAX_LOGIN_ATTEMPTS) throw new AuthError(429, "Too many sign-in attempts. Try again in 15 minutes.");
}

export async function loginWithCode(value, request, env) {
  await limitLoginAttempts(request, env);
  if (typeof value !== "string" || value.length > 128) throw new AuthError(401, "That login code is not valid.");
  let code = value.toUpperCase().replace(/[\s-]/g, "");
  if (code.length === 34 && code.startsWith("TF")) code = code.slice(2);
  if (code.length !== 32 || [...code].some((char) => !CODE_ALPHABET.includes(char))) {
    throw new AuthError(401, "That login code is not valid.");
  }
  const manager = await env.DB.prepare(`
    SELECT m.*, 1 AS login_enabled FROM manager_logins l
    JOIN managers m ON m.id = l.manager_id WHERE l.code_hash = ?
  `).bind(await secretHash(code)).first();
  if (!manager) throw new AuthError(401, "That login code is not valid.");
  const token = newSessionToken();
  const now = Math.floor(Date.now() / 1000);
  await env.DB.batch([
    env.DB.prepare("DELETE FROM manager_sessions WHERE expires_at <= ?").bind(now),
    env.DB.prepare("INSERT INTO manager_sessions (token_hash, manager_id, expires_at) VALUES (?, ?, ?)")
      .bind(await secretHash(token), manager.id, now + SESSION_SECONDS)
  ]);
  return { manager, token };
}

export async function logoutSession(manager, token, env) {
  // Revoke only this device. Original guest sessions remain supported, and
  // rotating one legacy token does not revoke independently signed-in devices.
  await env.DB.batch([
    env.DB.prepare("DELETE FROM manager_sessions WHERE token_hash = ? AND manager_id = ?")
      .bind(await secretHash(token), manager.id),
    env.DB.prepare("UPDATE managers SET token = ? WHERE id = ? AND token = ?")
      .bind(newSessionToken(), manager.id, token)
  ]);
}
