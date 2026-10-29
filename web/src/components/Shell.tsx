import { useCallback, useEffect, useRef, useState } from "react";
import { useItemList } from "@/api/queries";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useFilters } from "@/lib/filters";
import { useDebounced, useMediaQuery } from "@/lib/hooks";
import { AddDialog } from "./AddDialog";
import { Panel } from "./bits";
import { Header } from "./Header";
import { ItemList } from "./ItemList";
import { ItemPane } from "./ItemPane";
import { Sidebar } from "./Sidebar";

/** Each search embeds the query (one paid call), so it waits until typing pauses. */
const SEARCH_DELAY_MS = 300;

/** The three panes (D36): Tag tree, Item list, selected Item. Narrower, the Item opens in a drawer; narrowest,
 * the sidebar does too. Keys: `/` search, `j`/`k` next/previous, `Esc` close. */
export function Shell() {
  const wide = useMediaQuery("(min-width: 1181px)");
  const narrow = useMediaQuery("(max-width: 760px)");
  const [filters, change] = useFilters();
  const q = useDebounced(filters.q.trim(), SEARCH_DELAY_MS);
  const list = useItemList(filters, q);
  const [drawer, setDrawer] = useState(false);
  const [sidebar, setSidebar] = useState(false);
  const [adding, setAdding] = useState(false);
  // A new Capture joins the list only once it is enriched; until then it stays open anyway.
  const [added, setAdded] = useState<string>();
  const searchRef = useRef<HTMLInputElement>(null);
  const items = list.data?.items;

  const select = useCallback(
    (id: string) => {
      change({ item: id });
      if (!wide) setDrawer(true);
    },
    [change, wide],
  );
  const opened = (id: string) => {
    setAdded(id);
    select(id);
  };

  // Three panes always show an Item: the first one when the selected one is not in the list.
  useEffect(() => {
    if (
      wide &&
      items?.length &&
      !list.isPlaceholderData &&
      (!added || filters.item !== added) &&
      !items.some((i) => i.id === filters.item)
    ) {
      change({ item: items[0].id });
    }
  }, [wide, items, list.isPlaceholderData, filters.item, added, change]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
      if (target.closest("input, textarea, select, [contenteditable], [role=menu], [cmdk-root]")) return;
      if (event.key === "/") {
        event.preventDefault();
        searchRef.current?.focus();
      } else if ((event.key === "j" || event.key === "k") && items?.length) {
        const at = items.findIndex((i) => i.id === filters.item);
        const next = items[Math.max(0, Math.min(items.length - 1, at + (event.key === "j" ? 1 : -1)))];
        if (wide || drawer) change({ item: next.id });
        else document.querySelector<HTMLElement>(`[data-id="${CSS.escape(next.id)}"]`)?.focus();
        document.querySelector(`[data-id="${CSS.escape(next.id)}"]`)?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "Escape") {
        setDrawer(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, filters.item, wide, drawer, change]);

  const deleted = () => {
    change({ item: undefined });
    setDrawer(false);
  };
  const sidebarContent = <Sidebar filters={filters} onChange={change} onTagPicked={() => setSidebar(false)} />;

  return (
    <div className="flex h-svh flex-col overflow-hidden px-4">
      <Header page="items" onFilters={narrow ? () => setSidebar(true) : undefined} onAdd={() => setAdding(true)} />
      <div
        className={
          wide
            ? "grid min-h-0 flex-1 grid-cols-[15.5rem_minmax(20rem,27rem)_minmax(0,1fr)] gap-3 pb-3"
            : narrow
              ? "grid min-h-0 flex-1 grid-cols-1 gap-3 pb-3"
              : "grid min-h-0 flex-1 grid-cols-[14.5rem_minmax(0,1fr)] gap-3 pb-3"
        }
      >
        {!narrow && <Panel label="Tags and filters">{sidebarContent}</Panel>}
        <Panel label="Item list">
          <ItemList
            filters={filters}
            onChange={change}
            list={list}
            selected={wide || drawer ? filters.item : undefined}
            onSelect={select}
            searchRef={searchRef}
          />
        </Panel>
        {wide && (
          <Panel label="Selected item">
            <ItemPane id={filters.item} onOpen={opened} onDeleted={deleted} />
          </Panel>
        )}
      </div>

      {!wide && (
        <Sheet open={drawer && !!filters.item} onOpenChange={setDrawer}>
          <SheetContent side="right" showCloseButton={false} aria-describedby={undefined} className="w-full gap-0 p-0 sm:max-w-[46rem]">
            <SheetTitle className="sr-only">Selected item</SheetTitle>
            <ItemPane id={filters.item} onOpen={opened} onClose={() => setDrawer(false)} onDeleted={deleted} />
          </SheetContent>
        </Sheet>
      )}
      <AddDialog open={adding} onOpenChange={setAdding} onAdded={opened} />
      {narrow && (
        <Sheet open={sidebar} onOpenChange={setSidebar}>
          <SheetContent side="left" aria-describedby={undefined} className="w-[min(18rem,86%)] gap-0 p-0 pt-8">
            <SheetTitle className="sr-only">Tags and filters</SheetTitle>
            {sidebarContent}
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}
