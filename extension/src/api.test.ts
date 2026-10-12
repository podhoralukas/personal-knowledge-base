import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { ApiError, capture, checkConnection, getTags, normaliseServer } from "./api.ts";

const SETTINGS = { server: "http://localhost:8000", token: "secret" };
const PAGE = { url: "https://example.com/a", title: "A", html: "<h1>A</h1>", readable: true };
const realFetch = globalThis.fetch;
let calls: { url: string; init: RequestInit }[] = [];

function respond(status: number, body: unknown): void {
  calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init! });
    return new Response(JSON.stringify(body), { status });
  };
}

afterEach(() => {
  globalThis.fetch = realFetch;
});

test("capture posts the page with the token and returns the Item's UI page", async () => {
  respond(202, { item_id: "abc", version_id: "abc:t" });
  const itemUrl = await capture(SETTINGS, PAGE, ["ai/rag"], "for the RAG talk", new Date("2026-10-05T10:00:00Z"));
  assert.equal(itemUrl, "http://localhost:8000/ui/items/abc");
  assert.equal(calls[0].url, "http://localhost:8000/capture");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(calls[0].init.headers, { Authorization: "Bearer secret", "Content-Type": "application/json" });
  assert.deepEqual(JSON.parse(calls[0].init.body as string), {
    url: "https://example.com/a",
    content: "<h1>A</h1>",
    captured_at: "2026-10-05T10:00:00.000Z",
    channel: "extension",
    tags: ["ai/rag"],
    note: "for the RAG talk",
  });
});

test("tags come in tree order", async () => {
  const paths = ["ai-safety", "ai/rag", "news", "ai"];
  respond(200, { tags: paths.map((path) => ({ path })), version: 4 });
  assert.deepEqual(await getTags(SETTINGS), ["ai", "ai/rag", "ai-safety", "news"]);
  assert.equal(calls[0].url, "http://localhost:8000/taxonomy");
});

test("a wrong token points at the options", async () => {
  respond(401, { detail: "invalid or missing bearer token" });
  await assert.rejects(capture(SETTINGS, PAGE), new ApiError("The server rejected the token. Check it in the extension options."));
});

test("server errors show FastAPI's detail", async () => {
  respond(422, { detail: [{ msg: "invalid URL" }] });
  await assert.rejects(capture(SETTINGS, PAGE), new ApiError("Failed: invalid URL"));
  respond(502, { detail: "fetch failed: boom" });
  await assert.rejects(checkConnection(SETTINGS), new ApiError("Failed: fetch failed: boom"));
});

test("an unreachable server says so", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  await assert.rejects(capture(SETTINGS, PAGE), new ApiError("Can't reach http://localhost:8000. Is the app running?"));
});

test("server URLs are trimmed to origin and path", () => {
  assert.equal(normaliseServer(" http://localhost:8000/ "), "http://localhost:8000");
  assert.equal(normaliseServer("https://kb.example.com/base//"), "https://kb.example.com/base");
  assert.throws(() => normaliseServer("ftp://x"), ApiError);
  assert.throws(() => normaliseServer("not a url"), TypeError);
});
