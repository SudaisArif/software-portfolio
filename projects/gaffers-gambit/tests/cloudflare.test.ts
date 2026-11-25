import test from "node:test";
import assert from "node:assert/strict";
import { forward, upstreamOrigin } from "../deploy/cloudflare/worker.ts";

test("the branded address forwards only to the fixed game host and carries its player cookie", async () => {
  const cookie = "gg_player=" + "a".repeat(64);
  const req = new Request(
    "https://football.example/api/game?next=https://evil.invalid",
    {
      method: "POST",
      headers: {
        Origin: "https://football.example",
        Cookie: "unrelated=secret; " + cookie,
        "Content-Type": "application/json",
        Authorization: "must-not-forward",
      },
      body: JSON.stringify({ action: "start", mode: "practice" }),
    },
  );
  const result = await forward(req, (async (url, init) => {
    assert.equal(new URL(String(url)).origin, upstreamOrigin);
    assert.equal(new URL(String(url)).pathname, "/api/game");
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("Origin"), upstreamOrigin);
    assert.equal(headers.get("Cookie"), cookie);
    assert.equal(headers.get("Authorization"), null);
    assert.equal(init?.redirect, "manual");
    return Response.json(
      { game: { mode: "practice" } },
      {
        headers: {
          "Set-Cookie": cookie + "; HttpOnly; Secure; SameSite=Lax; Path=/",
        },
      },
    );
  }) as typeof fetch);
  assert.equal(result.status, 200);
  assert.equal(result.headers.get("Cache-Control"), "no-store");
  assert.ok(result.headers.get("Set-Cookie")?.includes("HttpOnly"));
});

test("new visitors receive independent anonymous identities behind the proxy", async () => {
  const identities: string[] = [];
  for (let n = 0; n < 2; n++) {
    await forward(new Request("https://football.example/api/game", {
      method: "POST", headers: { Origin: "https://football.example" }, body: "{}",
    }), (async (_url, init) => {
      identities.push(new Headers(init?.headers).get("Cookie")!);
      return Response.json({});
    }) as typeof fetch);
  }
  assert.match(identities[0], /^gg_player=[a-f0-9]{64}$/);
  assert.notEqual(identities[0], identities[1]);
});

test("a cross-origin submission cannot be laundered through the branded address", async () => {
  let contacted = false;
  const result = await forward(
    new Request("https://football.example/api/game", {
      method: "POST",
      headers: { Origin: "https://evil.invalid" },
      body: "{}",
    }),
    (async () => {
      contacted = true;
      return new Response();
    }) as typeof fetch,
  );
  assert.equal(result.status, 403);
  assert.equal(contacted, false);
});

test("game redirects stay on the public address and unsafe methods are rejected", async () => {
  const result = await forward(
    new Request("https://football.example/"),
    (async () =>
      new Response(null, {
        status: 302,
        headers: { Location: upstreamOrigin + "/?play=1" },
      })) as typeof fetch,
  );
  assert.equal(
    result.headers.get("Location"),
    "https://football.example/?play=1",
  );
  assert.equal(
    (
      await forward(
        new Request("https://football.example/", { method: "DELETE" }),
      )
    ).status,
    405,
  );
});
