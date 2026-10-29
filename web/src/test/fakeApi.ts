import { http, HttpResponse } from "msw";
import type { Item, Tag, Version } from "@/api/client";
import { under } from "@/lib/tags";
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
 * with the CSRF header; `requests` records every URL asked for. */
export function fakeApi(init: { items?: Item[]; tags?: Tag[]; versions?: Version[]; loggedIn?: boolean } = {}) {
  const state = {
    items: structuredClone(init.items ?? []),
    tags: init.tags ?? [],
    versions: structuredClone(init.versions ?? []),
    loggedIn: init.loggedIn ?? true,
    requests: [] as URL[],
  };
  const authed = (request: Request) => state.loggedIn && request.headers.has("X-KB-CSRF");
  const denied = () => HttpResponse.json({ detail: "invalid or missing token" }, { status: 401 });
  const missing = () => HttpResponse.json({ detail: "no such item" }, { status: 404 });
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
      return HttpResponse.json({ items: state.items.length, untagged, counts, deletable: [] });
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
      const own = state.versions.filter((v) => v.item_id === params.id);
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
