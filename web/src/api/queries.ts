import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";
import type { Filters } from "@/lib/filters";
import { api, type Item, SESSION_KEY, unwrap } from "./client";

const keys = {
  stats: SESSION_KEY,
  taxonomy: ["taxonomy"],
  items: ["items"],
  item: (id: string) => ["item", id],
  versions: (id: string) => ["versions", id],
};

/** While a Capture or a Thought is being enriched, its Item and Versions are polled. */
const PENDING_POLL_MS = 2000;

/** Counts for the Tag tree and the re-tag panel; polled every `pollMs` while a re-tag runs. */
export function useStats(pollMs: number | false = false) {
  return useQuery({
    queryKey: keys.stats,
    queryFn: async () => unwrap(await api.GET("/taxonomy/stats")),
    refetchInterval: pollMs,
  });
}

export function useTaxonomy() {
  return useQuery({ queryKey: keys.taxonomy, queryFn: async () => unwrap(await api.GET("/taxonomy")) });
}

/** After a Taxonomy change everything is read again: a rename rewrites Tags on Items and Versions. */
function useTaxonomyChanged() {
  const client = useQueryClient();
  return useCallback(() => void client.invalidateQueries(), [client]);
}

export type NewTag = { path: string; description: string };

/** Adds a Tag; its parent must exist. Items get it on their next Capture or re-tag. */
export function useAddTag() {
  return useMutation({
    mutationFn: async (tag: NewTag) => unwrap(await api.POST("/taxonomy/tags", { body: tag })),
    onSuccess: useTaxonomyChanged(),
    meta: { inlineError: true },
  });
}

/** A new description and/or path for the Tag at `path`; a new path renames it everywhere (spelling, not meaning). */
export function useChangeTag(path: string) {
  return useMutation({
    mutationFn: async (change: { path?: string; description?: string }) =>
      unwrap(await api.PATCH("/taxonomy/tags/{path}", { params: { path: { path } }, body: change })),
    onSuccess: useTaxonomyChanged(),
    meta: { inlineError: true },
  });
}

/** Deletes a Tag nothing uses and without sub-tags. */
export function useDeleteTag(path: string) {
  return useMutation({
    mutationFn: async () => unwrap(await api.DELETE("/taxonomy/tags/{path}", { params: { path: { path } } })),
    onSuccess: useTaxonomyChanged(),
    meta: { inlineError: true },
  });
}

/** Re-tags the candidates, or every Item with `all`, in the background; one LLM call per Item. */
export function useRetag() {
  return useMutation({
    mutationFn: async (all: boolean) => unwrap(await api.POST("/taxonomy/retag", { params: { query: { all } } })),
    onSuccess: useTaxonomyChanged(),
  });
}

export type ItemList = {
  items: Item[];
  /** Best match first (a search), not newest first. */
  ranked: boolean;
  /** False when a search matched keywords only, because the query could not be embedded. */
  semantic: boolean;
};

/** The Items the filters select; with a query, the search's best matches. */
export function useItemList(filters: Filters, q: string) {
  const { tag, untagged, kind, from, to } = filters;
  return useQuery({
    queryKey: [...keys.items, { tag, untagged, kind, from, to, q }],
    queryFn: async (): Promise<ItemList> => {
      const dates = { kind, from, to };
      if (q) {
        const found = unwrap(await api.GET("/search", { params: { query: { q, tag, ...dates } } }));
        // Search has no untagged filter; the few results are filtered here.
        const items = untagged ? found.items.filter((i) => !i.tags?.length) : found.items;
        return { items, ranked: true, semantic: found.semantic };
      }
      const items = untagged
        ? unwrap(await api.GET("/items/untagged", { params: { query: dates } }))
        : unwrap(await api.GET("/items", { params: { query: { tag, ...dates } } }));
      return { items, ranked: false, semantic: true };
    },
    placeholderData: keepPreviousData,
  });
}

export function useItem(id: string, pending: boolean) {
  return useQuery({
    queryKey: keys.item(id),
    queryFn: async () => unwrap(await api.GET("/items/{item_id}", { params: { path: { item_id: id } } })),
    refetchInterval: pending ? PENDING_POLL_MS : false,
    retry: false,
  });
}

export function useVersions(id: string) {
  return useQuery({
    queryKey: keys.versions(id),
    queryFn: async () => unwrap(await api.GET("/items/{item_id}/versions", { params: { path: { item_id: id } } })),
    refetchInterval: (query) =>
      query.state.data?.some((v) => v.status === "pending") ? PENDING_POLL_MS : false,
  });
}

/** Once the Item's pending Version is done, the Item is read again (its polling stops, and the last poll may
 * predate the end) and so are the lists, which a new Capture joins only now. */
export function useWhenProcessed(id: string, pending: boolean) {
  const client = useQueryClient();
  const listsChanged = useListsChanged();
  const was = useRef(pending);
  useEffect(() => {
    if (was.current && !pending) {
      void client.invalidateQueries({ queryKey: keys.item(id) });
      listsChanged();
    }
    was.current = pending;
  }, [id, pending, client, listsChanged]);
}

/** Refreshes the Item lists and the sidebar's counts after an Item was added, changed or deleted. */
export function useListsChanged() {
  const client = useQueryClient();
  return useCallback(() => {
    void client.invalidateQueries({ queryKey: keys.items });
    void client.invalidateQueries({ queryKey: keys.stats });
  }, [client]);
}

/** What the Owner typed for a Thought; no Tags picked means the pipeline tags it. */
export type ThoughtDraft = { title: string; text: string; tags: string[] };

/** The "+ Add" dialog's two ways in. Both return at once; the Item is enriched in the background. */
export function useAdd() {
  const listsChanged = useListsChanged();
  return {
    /** The server fetches the page. */
    capture: useMutation({
      mutationFn: async (url: string) =>
        unwrap(await api.POST("/capture", { body: { url, channel: "manual", note: "" } })),
      onSuccess: listsChanged,
      meta: { inlineError: true },
    }),
    /** `written_at` is fixed per draft, so sending it twice stores one Thought. */
    write: useMutation({
      mutationFn: async (thought: ThoughtDraft & { written_at: string }) =>
        unwrap(await api.POST("/thoughts", { body: thought })),
      onSuccess: listsChanged,
      meta: { inlineError: true },
    }),
  };
}

/** Changes to one Item: its Tags, its Note, a new Version, deleting it or one of its Versions. */
export function useItemEdits(id: string) {
  const client = useQueryClient();
  const listsChanged = useListsChanged();
  const edited = (item: Item) => {
    client.setQueryData(keys.item(id), item);
    listsChanged();
  };
  /** A new or retried Version is pending: the Item and its Versions are read again, and polled while pending. */
  const processing = () => {
    void client.invalidateQueries({ queryKey: keys.item(id) });
    void client.invalidateQueries({ queryKey: keys.versions(id) });
    listsChanged();
  };
  const item_id = id;

  return {
    tag: useMutation({
      mutationFn: async (path: string) =>
        unwrap(await api.POST("/items/{item_id}/tags", { params: { path: { item_id } }, body: { path } })),
      onSuccess: edited,
    }),
    untag: useMutation({
      mutationFn: async (path: string) =>
        unwrap(await api.DELETE("/items/{item_id}/tags/{path}", { params: { path: { item_id, path } } })),
      onSuccess: edited,
    }),
    allow: useMutation({
      mutationFn: async (path: string) =>
        unwrap(
          await api.DELETE("/items/{item_id}/rejected-tags/{path}", { params: { path: { item_id, path } } }),
        ),
      onSuccess: edited,
    }),
    note: useMutation({
      mutationFn: async (notes: string) =>
        unwrap(await api.PUT("/items/{item_id}/notes", { params: { path: { item_id } }, body: { notes } })),
      onSuccess: edited,
    }),
    /** A new Version of a Thought; its Tags follow from the pipeline, as the Item's own Tags are kept. */
    editThought: useMutation({
      mutationFn: async (thought: { title: string; text: string }) =>
        unwrap(await api.PUT("/thoughts/{item_id}", { params: { path: { item_id } }, body: thought })),
      onSuccess: processing,
      meta: { inlineError: true },
    }),
    /** Fetches the article's page again, as a new Version. The Accepted Item can differ when the page redirects. */
    captureAgain: useMutation({
      mutationFn: async (url: string) =>
        unwrap(await api.POST("/capture", { body: { url, channel: "manual", note: "" } })),
      onSuccess: processing,
    }),
    /** Enriches a Thought's failed current Version again. */
    retry: useMutation({
      mutationFn: async () =>
        unwrap(await api.POST("/thoughts/{item_id}/retry", { params: { path: { item_id } } })),
      onSuccess: processing,
    }),
    remove: useMutation({
      mutationFn: async () => unwrap(await api.DELETE("/items/{item_id}", { params: { path: { item_id } } })),
      onSuccess: () => {
        client.removeQueries({ queryKey: keys.item(id) });
        client.removeQueries({ queryKey: keys.versions(id) });
        listsChanged();
      },
    }),
    removeVersion: useMutation({
      mutationFn: async (version_id: string) =>
        unwrap(await api.DELETE("/versions/{version_id}", { params: { path: { version_id } } })),
      onSuccess: () => {
        void client.invalidateQueries({ queryKey: keys.item(id) });
        void client.invalidateQueries({ queryKey: keys.versions(id) });
        listsChanged();
      },
    }),
  };
}
