import { http, HttpResponse } from "msw";
import type { Item, Tag, Version } from "@/api/client";
import { splitPath, under } from "@/lib/tags";
import { server } from "./server";

export function item(fields: Partial<Item> & Pick<Item, "id" | "title">): Item {
  const saved = fields.first_captured_at ?? "2026-10-20T10:00:00.000Z";
  return {
    media_type: "article",
    original_url: `https://www.example.com/${fields.id}`,
    first_captured_at: saved,
    captured_at: saved,
    current_version_id: `${fields.id}:v1`,
    summary: "",
    key_points: [],
    tags: [],
    taxonomy_version: 1,
    annotations: { notes: "", owner_tags: [], rejected_tags: [] },
    ...fields,
  };
}

export function tag(path: string, description = ""): Tag {
  return { path, description, created_at: "2026-10-01T00:00:00.000Z", created_in_taxonomy_version: 1 };
}

export function version(of: Item, fields: Partial<Version> = {}): Version {
  return {
    id: of.current_version_id,
    item_id: of.id,
    captured_at: of.captured_at,
    channel: "extension",
    kind: of.media_type,
    title: "",
    content_hash: "h",
    status: "enriched",
    note: "",
    enrichment: { title: of.title, summary: of.summary, tags: of.tags, taxonomy_version: 1, embedding_model: "e" },
    ...fields,
  };
}

/** The JSON API over in-memory Items and Tags. Like the real one it wants the login cookie (here: `loggedIn`)
 * with the CSRF header; `requests` records every URL asked for, `bodies` every JSON body sent.
 * A Capture of a URL containing "unreachable" fails like a failed fetch. A new Capture stores only a pending
 * Version, as the real one does until enrichment, which a test does by hand. `retagCandidates` is what stats
 * report until a re-tag runs; Tags are checked like the real Taxonomy (lowercase path, existing parent). */
export function fakeApi(
  init: { items?: Item[]; tags?: Tag[]; versions?: Version[]; loggedIn?: boolean; retagCandidates?: number } = {},
) {
  const state = {
    items: structuredClone(init.items ?? []),
    tags: structuredClone(init.tags ?? []),
    retagCandidates: init.retagCandidates ?? 0,
    versions: structuredClone(init.versions ?? []),
    loggedIn: init.loggedIn ?? true,
    requests: [] as URL[],
    bodies: [] as { method: string; path: string; body: unknown }[],
  };
  const authed = (request: Request) => state.loggedIn && request.headers.has("X-KB-CSRF");
  const denied = () => HttpResponse.json({ detail: "invalid or missing token" }, { status: 401 });
  const missing = () => HttpResponse.json({ detail: "no such item" }, { status: 404 });
  const invalid = (detail: string) => HttpResponse.json({ detail }, { status: 422 });
  const conflict = (detail: string) => HttpResponse.json({ detail }, { status: 409 });
  const find = (id: string) => state.items.find((i) => i.id === id);
  const listed = (url: URL, keep: (i: Item) => boolean) => {
    const [kind, from, to] = ["kind", "from", "to"].map((k) => url.searchParams.get(k));
    return state.items
      .filter((i) => keep(i) && (!kind || i.media_type === kind))
      .filter((i) => (!from || i.first_captured_at >= from) && (!to || i.first_captured_at.slice(0, 10) <= to))
      .sort((a, b) => b.first_captured_at.localeCompare(a.first_captured_at));
  };
  const hasTag = (url: URL) => (i: Item) => {
    const tag = url.searchParams.get("tag");
    return !tag || (i.tags ?? []).some((t) => under(t, tag));
  };
  /** The Item behind an `/items/{id}/…` path, changed by `edit`. */
  const editing = (request: Request, pattern: RegExp, edit: (i: Item, path: string) => void) => {
    if (!authed(request)) return denied();
    const [, id, path] = new URL(request.url).pathname.match(pattern)!;
    const it = find(decodeURIComponent(id));
    if (!it) return missing();
    edit(it, decodeURIComponent(path ?? ""));
    return HttpResponse.json(it);
  };
  const annotations = (i: Item) => (i.annotations ??= { notes: "", owner_tags: [], rejected_tags: [] });
  /** The request's JSON body, recorded in `bodies`. */
  const sent = async <T,>(request: Request): Promise<T> => {
    const body = (await request.json()) as T;
    state.bodies.push({ method: request.method, path: new URL(request.url).pathname, body });
    return body;
  };
  /** A pending Version of `itemId`, captured or written now. */
  const pending = (itemId: string, fields: Partial<Version> = {}) => {
    const at = new Date().toISOString();
    const v: Version = {
      ...version(item({ id: itemId, title: "" }), { status: "pending", enrichment: null }),
      id: `${itemId}:${at}`,
      captured_at: at,
      ...fields,
    };
    state.versions.push(v);
    return HttpResponse.json({ item_id: itemId, version_id: v.id }, { status: 202 });
  };

  server.use(
    http.all("*", ({ request }) => {
      state.requests.push(new URL(request.url));
    }),
    http.post("/auth/login", async ({ request }) => {
      const { token } = (await request.json()) as { token: string };
      if (token !== "secret") return HttpResponse.json({ detail: "wrong token" }, { status: 401 });
      state.loggedIn = true;
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("/auth/logout", () => {
      state.loggedIn = false;
      return new HttpResponse(null, { status: 204 });
    }),
    http.get("/taxonomy", ({ request }) =>
      authed(request) ? HttpResponse.json({ tags: state.tags, version: 1 }) : denied(),
    ),
    http.get("/taxonomy/stats", ({ request }) => {
      if (!authed(request)) return denied();
      const counts = Object.fromEntries(
        state.tags.map((t) => [t.path, state.items.filter((i) => (i.tags ?? []).some((p) => under(p, t.path))).length]),
      );
      const untagged = state.items.filter((i) => !i.tags?.length).length;
      const deletable = state.tags
        .map((t) => t.path)
        .filter((path) => !counts[path] && !state.tags.some((t) => t.path.startsWith(`${path}/`)));
      return HttpResponse.json({
        items: state.items.length,
        untagged,
        counts,
        deletable,
        retag_candidates: state.retagCandidates,
      });
    }),
    http.post("/taxonomy/tags", async ({ request }) => {
      if (!authed(request)) return denied();
      const { path, description } = await sent<{ path: string; description: string }>(request);
      const parent = splitPath(path)[0].slice(0, -1);
      if (!/^[a-z0-9-]+(\/[a-z0-9-]+)*$/.test(path)) return invalid(`invalid tag path ${path}`);
      if (state.tags.some((t) => t.path === path)) return conflict(`tag '${path}' already exists`);
      if (parent && !state.tags.some((t) => t.path === parent)) return invalid(`parent tag '${parent}' does not exist`);
      const created = tag(path, description);
      state.tags.push(created);
      return HttpResponse.json(created, { status: 201 });
    }),
    http.patch(/\/taxonomy\/tags\/(.+)$/, async ({ request }) => {
      if (!authed(request)) return denied();
      const path = decodeURIComponent(new URL(request.url).pathname.match(/\/taxonomy\/tags\/(.+)$/)![1]);
      const change = await sent<{ path?: string; description?: string }>(request);
      const own = state.tags.find((t) => t.path === path);
      if (!own) return missing();
      if (change.path && state.tags.some((t) => t.path === change.path)) return conflict(`tag '${change.path}' already exists`);
      if (change.description !== undefined) own.description = change.description;
      if (change.path) {
        const moved = (p: string) => (under(p, path) ? change.path + p.slice(path.length) : p);
        for (const t of state.tags) t.path = moved(t.path);
        for (const i of state.items) i.tags = (i.tags ?? []).map(moved);
      }
      return HttpResponse.json(own);
    }),
    http.delete(/\/taxonomy\/tags\/(.+)$/, ({ request }) => {
      if (!authed(request)) return denied();
      const path = decodeURIComponent(new URL(request.url).pathname.match(/\/taxonomy\/tags\/(.+)$/)![1]);
      state.tags = state.tags.filter((t) => t.path !== path);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("/taxonomy/retag", ({ request }) => {
      if (!authed(request)) return denied();
      const all = new URL(request.url).searchParams.get("all") === "true";
      const item_count = all ? state.items.length : state.retagCandidates;
      state.bodies.push({ method: "POST", path: `/taxonomy/retag${all ? "?all=true" : ""}`, body: null });
      state.retagCandidates = 0;
      return HttpResponse.json({ taxonomy_version: 1, item_count }, { status: 202 });
    }),
    http.get("/items/untagged", ({ request }) =>
      authed(request) ? HttpResponse.json(listed(new URL(request.url), (i) => !i.tags?.length)) : denied(),
    ),
    http.get("/items", ({ request }) => {
      const url = new URL(request.url);
      return authed(request) ? HttpResponse.json(listed(url, hasTag(url))) : denied();
    }),
    http.get("/search", ({ request }) => {
      if (!authed(request)) return denied();
      const url = new URL(request.url);
      const words = url.searchParams.get("q")!.toLowerCase().split(/\s+/);
      const found = listed(url, hasTag(url)).filter((i) =>
        words.some((w) => `${i.title} ${i.summary} ${i.text ?? ""}`.toLowerCase().includes(w)),
      );
      return HttpResponse.json({ items: found.reverse().map((i) => ({ ...i, score: 1 })), semantic: true });
    }),
    http.get("/items/:id", ({ request, params }) => {
      if (!authed(request)) return denied();
      const it = find(String(params.id));
      return it ? HttpResponse.json(it) : missing();
    }),
    http.get("/items/:id/versions", ({ request, params }) => {
      if (!authed(request)) return denied();
      const it = find(String(params.id));
      const own = state.versions
        .filter((v) => v.item_id === params.id)
        .sort((a, b) => b.captured_at.localeCompare(a.captured_at)); // newest first, as stored
      return HttpResponse.json(own.length || !it ? own : [version(it)]);
    }),
    http.post("/items/:id/tags", async ({ request, params }) => {
      if (!authed(request)) return denied();
      const it = find(String(params.id));
      if (!it) return missing();
      const { path } = (await request.json()) as { path: string };
      const a = annotations(it);
      it.tags = [...(it.tags ?? []), path].sort();
      a.owner_tags = [...(a.owner_tags ?? []), path];
      a.rejected_tags = (a.rejected_tags ?? []).filter((t) => t !== path);
      return HttpResponse.json(it);
    }),
    http.delete(/\/items\/([^/]+)\/tags\/(.+)$/, ({ request }) =>
      editing(request, /\/items\/([^/]+)\/tags\/(.+)$/, (it, path) => {
        const a = annotations(it);
        it.tags = (it.tags ?? []).filter((t) => t !== path);
        a.owner_tags = (a.owner_tags ?? []).filter((t) => t !== path);
        a.rejected_tags = [...(a.rejected_tags ?? []), path];
      }),
    ),
    http.delete(/\/items\/([^/]+)\/rejected-tags\/(.+)$/, ({ request }) =>
      editing(request, /\/items\/([^/]+)\/rejected-tags\/(.+)$/, (it, path) => {
        const a = annotations(it);
        a.rejected_tags = (a.rejected_tags ?? []).filter((t) => t !== path);
      }),
    ),
    http.put("/items/:id/notes", async ({ request, params }) => {
      if (!authed(request)) return denied();
      const it = find(String(params.id));
      if (!it) return missing();
      annotations(it).notes = ((await request.json()) as { notes: string }).notes;
      return HttpResponse.json(it);
    }),
    http.delete("/items/:id", ({ request, params }) => {
      if (!authed(request)) return denied();
      if (!find(String(params.id))) return missing();
      state.items = state.items.filter((i) => i.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("/capture", async ({ request }) => {
      if (!authed(request)) return denied();
      const { url } = await sent<{ url: string }>(request);
      if (url.includes("unreachable")) return HttpResponse.json({ detail: "fetch failed: timed out" }, { status: 502 });
      const known = state.items.find((i) => i.original_url === url);
      return pending(known?.id ?? `captured:${url}`, { channel: "manual", original_url: url });
    }),
    http.post("/thoughts", async ({ request }) => {
      if (!authed(request)) return denied();
      const t = await sent<{ title: string; text: string; tags: string[]; written_at: string }>(request);
      const id = `thought:${t.written_at}`;
      if (!find(id)) {
        const title = t.title || t.text.split("\n")[0];
        state.items.push(
          item({ id, media_type: "thought", original_url: null, title, text: t.text, tags: t.tags, first_captured_at: t.written_at }),
        );
      }
      return pending(id, { channel: "written", kind: "thought", title: t.title, text: t.text });
    }),
    http.put("/thoughts/:id", async ({ request, params }) => {
      if (!authed(request)) return denied();
      const it = find(String(params.id));
      if (!it) return missing();
      const t = await sent<{ title: string; text: string }>(request);
      if (!t.text.trim()) return HttpResponse.json({ detail: [{ msg: "Value error, a Thought needs some text" }] }, { status: 422 });
      Object.assign(it, { title: t.title || t.text.split("\n")[0], text: t.text });
      const response = pending(it.id, { channel: "written", kind: "thought", title: t.title, text: t.text });
      it.current_version_id = state.versions.at(-1)!.id;
      return response;
    }),
    http.post("/thoughts/:id/retry", ({ request, params }) => {
      if (!authed(request)) return denied();
      const it = find(String(params.id));
      const current = state.versions.find((v) => v.id === it?.current_version_id);
      if (!current || current.status !== "failed") return HttpResponse.json({ detail: "nothing to retry" }, { status: 409 });
      current.status = "pending";
      return HttpResponse.json({ item_id: current.item_id, version_id: current.id }, { status: 202 });
    }),
    http.delete("/versions/:id", ({ request, params }) => {
      if (!authed(request)) return denied();
      state.versions = state.versions.filter((v) => v.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return state;
}

/** The query of the last Item list or search request. */
export function lastListQuery(requests: URL[]): URLSearchParams | undefined {
  return requests.filter((u) => ["/items", "/items/untagged", "/search"].includes(u.pathname)).at(-1)?.searchParams;
}
