import type { UseQueryResult } from "@tanstack/react-query";
import { SearchIcon, XIcon } from "lucide-react";
import type { Ref } from "react";
import type { Item } from "@/api/client";
import type { ItemList as Listed } from "@/api/queries";
import { day } from "@/lib/dates";
import type { Filters } from "@/lib/filters";
import { mostSpecific } from "@/lib/tags";
import { cn } from "@/lib/utils";
import { Dot, Empty, pill, Source, TagLabel } from "./bits";

type Props = {
  filters: Filters;
  onChange: (change: Partial<Filters>) => void;
  list: UseQueryResult<Listed>;
  /** The open Item, highlighted when the reading pane or drawer shows it. */
  selected?: string;
  onSelect: (id: string) => void;
  searchRef: Ref<HTMLInputElement>;
};

/** Search on top of the Item list: best match first while a query is typed, newest first otherwise (D36). */
export function ItemList({ filters, onChange, list, selected, onSelect, searchRef }: Props) {
  const filter = filters.untagged ? "Untagged" : filters.tag;
  const items = list.data?.items ?? [];

  return (
    <>
      <div className="grid gap-2 border-b p-3">
        <div className="relative">
          <SearchIcon className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            ref={searchRef}
            type="search"
            aria-label="Search items"
            placeholder="Search by words or meaning"
            autoComplete="off"
            value={filters.q}
            onChange={(event) => onChange({ q: event.target.value })}
            onKeyDown={(event) => {
              if (event.key === "Escape" && filters.q) onChange({ q: "" });
            }}
            className="w-full rounded-lg border bg-background py-2 pr-8 pl-8 outline-none focus:border-primary focus:ring-3 focus:ring-selected"
          />
          <kbd className="absolute top-1/2 right-2 -translate-y-1/2 rounded border border-b-2 bg-card px-1 font-mono text-[0.72rem] text-muted-foreground">
            /
          </kbd>
        </div>
        <div className="flex items-center justify-between gap-2 text-[0.82rem] text-muted-foreground" aria-live="polite">
          {list.isError ? (
            <span className="text-destructive">{list.error.message}</span>
          ) : (
            <span>
              {list.data ? `${items.length} item${items.length === 1 ? "" : "s"}` : ""}
              {filter && (
                <>
                  {" in "}
                  <span className="inline-flex items-center gap-1 rounded-full bg-selected py-0.5 pr-1 pl-2 font-medium text-primary">
                    {filter}
                    <button
                      type="button"
                      aria-label="Clear tag filter"
                      onClick={() => onChange({ tag: undefined, untagged: false })}
                    >
                      <XIcon className="size-3.5" />
                    </button>
                  </span>
                </>
              )}
            </span>
          )}
          <span>
            {list.data?.ranked ? "best match first" : "newest first"}
            {list.data && !list.data.semantic && " · keywords only"}
          </span>
        </div>
      </div>
      <div className={cn("min-h-0 flex-1 overflow-y-auto", list.isPlaceholderData && "opacity-60")}>
        {list.isPending ? (
          <Empty>Loading…</Empty>
        ) : items.length === 0 ? (
          <Empty>
            {filters.q
              ? `Nothing matches “${filters.q}”${filter ? ` in ${filter}` : ""}.`
              : "No items match these filters."}
          </Empty>
        ) : (
          <ul aria-label="Items" className="grid gap-0.5 p-1.5">
            {items.map((item) => (
              <ItemRow
                key={item.id}
                item={item}
                selected={item.id === selected}
                onSelect={onSelect}
                onTag={(tag) => onChange({ tag })}
              />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function ItemRow({
  item,
  selected,
  onSelect,
  onTag,
}: {
  item: Item;
  selected: boolean;
  onSelect: (id: string) => void;
  onTag: (tag: string) => void;
}) {
  const tags = mostSpecific(item.tags ?? []);
  return (
    <li
      data-id={item.id}
      tabIndex={0}
      aria-current={selected || undefined}
      onClick={() => onSelect(item.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) onSelect(item.id);
      }}
      className={cn(
        "grid cursor-pointer gap-1.5 rounded-lg border border-transparent px-3 py-2.5",
        selected ? "border-primary/35 bg-selected" : "hover:bg-muted",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted-foreground">
        <Source item={item} />
        <Dot />
        <span>saved {day(item.first_captured_at)}</span>
        {item.annotations?.notes && (
          <>
            <Dot />
            <span title="Has a note">✎ note</span>
          </>
        )}
      </div>
      <h3 className="line-clamp-2 text-[0.97rem] leading-snug font-semibold text-pretty">{item.title}</h3>
      {tags.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <li key={tag}>
              <button
                type="button"
                title={`Show ${tag}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onTag(tag);
                }}
                className={cn(pill, "px-2 py-0.5 text-[0.8rem] hover:ring-1 hover:ring-tag-foreground hover:ring-inset")}
              >
                <TagLabel path={tag} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="line-clamp-2 text-[0.86rem] text-muted-foreground">
        {item.media_type === "thought" ? item.text : item.summary}
      </p>
    </li>
  );
}
