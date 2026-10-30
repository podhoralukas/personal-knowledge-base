import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { Kind } from "@/api/client";

/** What the Item list shows and which Item is open. Kept in the URL, so a reload or a link brings it back. */
export type Filters = {
  tag?: string;
  untagged: boolean;
  kind?: Kind;
  from?: string;
  to?: string;
  q: string;
  item?: string;
};

const KINDS: Kind[] = ["article", "thought"];

export function readFilters(search: string): Filters {
  const params = new URLSearchParams(search);
  const kind = params.get("kind") as Kind | null;
  return {
    tag: params.get("tag") || undefined,
    untagged: params.has("untagged"),
    kind: kind && KINDS.includes(kind) ? kind : undefined,
    from: params.get("from") || undefined,
    to: params.get("to") || undefined,
    q: params.get("q") ?? "",
    item: params.get("item") || undefined,
  };
}

export function writeFilters(filters: Filters): string {
  const params = new URLSearchParams();
  for (const key of ["tag", "kind", "from", "to", "q", "item"] as const) {
    if (filters[key]) params.set(key, filters[key]);
  }
  if (filters.untagged) params.set("untagged", "1");
  const search = params.toString();
  return search ? `?${search}` : "";
}

const CHANGED = "kb:filters";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(CHANGED, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(CHANGED, onChange);
  };
}

/** The filters and a function that changes some of them. A Tag filter and "Untagged" exclude each other. */
export function useFilters(): [Filters, (change: Partial<Filters>) => void] {
  const search = useSyncExternalStore(subscribe, () => window.location.search);
  const filters = useMemo(() => readFilters(search), [search]);
  const change = useCallback((change: Partial<Filters>) => {
    const next = { ...readFilters(window.location.search), ...change };
    if (change.tag) next.untagged = false;
    if (change.untagged) next.tag = undefined;
    window.history.replaceState(null, "", `${window.location.pathname}${writeFilters(next)}`);
    window.dispatchEvent(new Event(CHANGED));
  }, []);
  return [filters, change];
}
