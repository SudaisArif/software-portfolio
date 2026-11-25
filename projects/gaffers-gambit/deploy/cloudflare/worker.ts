// The public address serves the existing game and database, preserving the
// daily pack and leaderboard. It is a fixed-origin proxy, never an open proxy.
export const upstreamOrigin =
  "https://gaffers-gambit.awake-wave-4408.chatgpt.site";

export async function forward(
  request: Request,
  fetchOrigin: typeof fetch = fetch,
): Promise<Response> {
  const publicUrl = new URL(request.url);
  if (!["GET", "HEAD", "POST"].includes(request.method)) {
    return new Response("Method not allowed", {
      status: 405,
      headers: { Allow: "GET, HEAD, POST" },
    });
  }
  const origin = request.headers.get("Origin");
  if (request.method === "POST" && origin && origin !== publicUrl.origin) {
    return Response.json(
      { error: "Please play from the game website." },
      { status: 403 },
    );
  }
  const upstream = new URL(upstreamOrigin);
  upstream.pathname = publicUrl.pathname;
  upstream.search = publicUrl.search;
  const headers = new Headers();
  for (const name of [
    "Accept",
    "Content-Type",
    "User-Agent",
    "If-None-Match",
    "If-Modified-Since",
    "Range",
  ])
    if (request.headers.has(name))
      headers.set(name, request.headers.get(name)!);
  let player = request.headers
    .get("Cookie")
    ?.match(/(?:^|;\s*)(gg_player=[a-f0-9]{64})(?:;|$)/)?.[1];
  // Cross-zone Worker traffic shares a Cloudflare network address. Establish
  // the normal anonymous identity before the first POST so new players don't
  // share one network rate-limit bucket. The game persists it via HttpOnly cookie.
  if (!player && request.method === "POST")
    player =
      "gg_player=" +
      (crypto.randomUUID() + crypto.randomUUID()).replaceAll("-", "");
  if (player) headers.set("Cookie", player);
  if (origin) headers.set("Origin", upstreamOrigin);
  const response = await fetchOrigin(upstream, {
    method: request.method,
    headers,
    body: request.method === "POST" ? request.body : undefined,
    redirect: "manual",
  });
  const result = new Response(response.body, response);
  const redirect = result.headers.get("Location");
  if (redirect) {
    const target = new URL(redirect, upstream);
    if (target.origin === upstreamOrigin) {
      target.protocol = publicUrl.protocol;
      target.host = publicUrl.host;
      result.headers.set("Location", target.href);
    }
  }
  result.headers.set("X-Content-Type-Options", "nosniff");
  result.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  if (
    (publicUrl.pathname.startsWith("/api/") &&
      publicUrl.pathname !== "/api/leaderboard") ||
    result.headers.has("Set-Cookie")
  ) {
    result.headers.set("Cache-Control", "no-store");
  }
  return result;
}

export default {
  async fetch(request: Request): Promise<Response> {
    try {
      return await forward(request);
    } catch {
      return new Response(
        "The match is warming up. Please try again shortly.",
        {
          status: 502,
          headers: {
            "Cache-Control": "no-store",
            "Content-Type": "text/plain; charset=utf-8",
          },
        },
      );
    }
  },
};
