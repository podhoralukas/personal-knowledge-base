import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useStats() {
  return useQuery({ queryKey: keys.stats, queryFn: async () => unwrap(await api.GET("/taxonomy/stats")) });
}

export function useTaxonomy() {
  return useQuery({ queryKey: keys.taxonomy, queryFn: async () => unwrap(await api.GET("/taxonomy")) });
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

/** Changes to one Item: its Tags, its Note, deleting it or one of its Versions. */
export function useItemEdits(id: string) {
  const client = useQueryClient();
  const listsChanged = () => {
    void client.invalidateQueries({ queryKey: keys.items });
    void client.invalidateQueries({ queryKey: keys.stats });
  };
  const edited = (item: Item) => {
    client.setQueryData(keys.item(id), item);
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
