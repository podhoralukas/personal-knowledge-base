import { ChevronDownIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useStats, useTaxonomy } from "@/api/queries";
import type { Filters } from "@/lib/filters";
import { splitPath, type TagNode, tagTree } from "@/lib/tags";
import { cn } from "@/lib/utils";

/** Browsing by Tag: click to filter, with Item counts (sub-tags included). Editing is on the Taxonomy page. */
export function TagTree({ filters, onPick }: { filters: Filters; onPick: (change: Partial<Filters>) => void }) {
  const stats = useStats();
  const taxonomy = useTaxonomy();
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const counts = stats.data?.counts ?? {};

  const toggle = (path: string) =>
    setClosed((before) => {
      const after = new Set(before);
      if (!after.delete(path)) after.add(path);
      return after;
    });

  const node = ({ tag, children }: TagNode): ReactNode => {
    const open = !closed.has(tag.path);
    const twisty = (
      <button
        type="button"
        aria-label={`${open ? "Collapse" : "Expand"} ${tag.path}`}
        aria-expanded={open}
        tabIndex={children.length ? undefined : -1}
        onClick={() => toggle(tag.path)}
        className={cn("grid h-7 w-5 shrink-0 place-items-center text-muted-foreground", !children.length && "invisible")}
      >
        <ChevronDownIcon className={cn("size-3.5 transition-transform", !open && "-rotate-90")} />
      </button>
    );
    return (
      <li key={tag.path}>
        <Row
          name={splitPath(tag.path)[1]}
          title={tag.description || tag.path}
          count={counts[tag.path]}
          on={filters.tag === tag.path}
          onPick={() => onPick({ tag: tag.path })}
          twisty={twisty}
        />
        {children.length > 0 && open && (
          <ul className="ml-[0.55rem] border-l pl-[0.9rem]">{children.map(node)}</ul>
        )}
      </li>
    );
  };

  return (
    <ul aria-label="Tags">
      <li>
        <Row
          name="All items"
          count={stats.data?.items}
          on={!filters.tag && !filters.untagged}
          onPick={() => onPick({ tag: undefined, untagged: false })}
        />
      </li>
      <li>
        <Row name="Untagged" count={stats.data?.untagged} on={filters.untagged} onPick={() => onPick({ untagged: true })} />
      </li>
      {tagTree(taxonomy.data?.tags ?? []).map(node)}
    </ul>
  );
}

function Row({
  name,
  title,
  count,
  on,
  onPick,
  twisty,
}: {
  name: string;
  title?: string;
  count?: number;
  on: boolean;
  onPick: () => void;
  twisty?: ReactNode;
}) {
  return (
    <div className={cn("flex items-center gap-0.5 rounded-md", on ? "bg-selected" : "hover:bg-muted", !twisty && "pl-1.5")}>
      {twisty}
      <button
        type="button"
        title={title}
        aria-current={on || undefined}
        onClick={onPick}
        className="flex min-w-0 flex-1 justify-between gap-2 py-1 pr-2 pl-0.5 text-left"
      >
        <span className={cn("truncate", on && "font-semibold text-primary")}>{name}</span>
        <span className="text-[0.8rem] text-muted-foreground tabular-nums">{count ?? ""}</span>
      </button>
    </div>
  );
}
