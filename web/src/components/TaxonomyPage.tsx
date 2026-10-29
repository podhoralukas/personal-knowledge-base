import { ChevronDownIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { Tag } from "@/api/client";
import { useStats, useTaxonomy } from "@/api/queries";
import { splitPath, type TagNode, tagTree } from "@/lib/tags";
import { cn } from "@/lib/utils";
import { AppLink, Empty, Panel } from "./bits";
import { Header } from "./Header";
import { RetagPanel } from "./RetagPanel";
import { DeleteTagConfirm, EditTagForm, NewTagForm } from "./TagForms";

/** One form open at a time, under the Tag it belongs to. */
type Open = { path: string; form: "sub" | "edit" | "delete" } | null;

/** The Taxonomy editor (D28): the Tag tree with counts and descriptions, each Tag's actions inline, a new
 * top-level Tag, and the re-tag panel beside it (below it on a narrow window). */
export function TaxonomyPage() {
  return (
    <div className="flex h-svh flex-col overflow-hidden px-4">
      <Header page="taxonomy" />
      <div className="grid min-h-0 flex-1 auto-rows-min gap-3 overflow-y-auto pb-3 lg:auto-rows-auto lg:grid-cols-[minmax(0,1fr)_24rem] lg:overflow-hidden">
        <Panel label="Tags">
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            <TaxonomyTree />
          </div>
        </Panel>
        <Panel label="Re-tag panel">
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            <RetagPanel />
          </div>
        </Panel>
      </div>
    </div>
  );
}

function TaxonomyTree() {
  const taxonomy = useTaxonomy();
  const stats = useStats();
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const [open, setOpen] = useState<Open>(null);
  const tree = tagTree(taxonomy.data?.tags ?? []);
  const counts = stats.data?.counts ?? {};
  const deletable = stats.data?.deletable ?? [];
  const untagged = stats.data?.untagged ?? 0;

  const toggle = (path: string) =>
    setClosed((before) => {
      const after = new Set(before);
      if (!after.delete(path)) after.add(path);
      return after;
    });
  const opened = (tag: Tag): ReactNode => {
    if (open?.path !== tag.path) return null;
    const done = () => setOpen(null);
    if (open.form === "sub") return <NewTagForm parent={tag.path} onDone={done} />;
    if (open.form === "edit") return <EditTagForm tag={tag} onDone={done} />;
    return <DeleteTagConfirm tag={tag} onDone={done} />;
  };

  const node = ({ tag, children }: TagNode): ReactNode => {
    const expanded = !closed.has(tag.path);
    const form = opened(tag);
    return (
      <li key={tag.path}>
        <div className="flex flex-wrap items-center gap-x-2 rounded-md py-0.5 pr-1 hover:bg-muted">
          <button
            type="button"
            aria-label={`${expanded ? "Collapse" : "Expand"} ${tag.path}`}
            aria-expanded={expanded}
            tabIndex={children.length ? undefined : -1}
            onClick={() => toggle(tag.path)}
            className={cn("grid h-7 w-5 shrink-0 place-items-center text-muted-foreground", !children.length && "invisible")}
          >
            <ChevronDownIcon className={cn("size-3.5 transition-transform", !expanded && "-rotate-90")} />
          </button>
          <AppLink
            href={`/app/?tag=${encodeURIComponent(tag.path)}`}
            title={`Items under ${tag.path}`}
            className="font-medium hover:text-primary hover:underline"
          >
            {splitPath(tag.path)[1]}
          </AppLink>
          <span title="Items under this tag, sub-tags included" className="text-[0.8rem] text-muted-foreground tabular-nums">
            {counts[tag.path] ?? 0}
          </span>
          <span className="min-w-0 flex-1 truncate text-[0.88rem] text-muted-foreground">{tag.description}</span>
          <span className="flex gap-3 text-[0.82rem]">
            <Action label={`Add a sub-tag to ${tag.path}`} onClick={() => setOpen({ path: tag.path, form: "sub" })}>
              + sub-tag
            </Action>
            <Action label={`Edit ${tag.path}`} onClick={() => setOpen({ path: tag.path, form: "edit" })}>
              edit
            </Action>
            {deletable.includes(tag.path) && (
              <Action label={`Delete ${tag.path}`} danger onClick={() => setOpen({ path: tag.path, form: "delete" })}>
                delete
              </Action>
            )}
          </span>
        </div>
        {form && <div className="my-2 ml-6">{form}</div>}
        {children.length > 0 && expanded && <ul className="ml-[0.55rem] border-l pl-[0.9rem]">{children.map(node)}</ul>}
      </li>
    );
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1 className="text-xl font-semibold tracking-tight">
          Taxonomy{" "}
          {taxonomy.data && <span className="text-base font-normal text-muted-foreground">version {taxonomy.data.version}</span>}
        </h1>
        <AppLink href="/app/?untagged=1" className="text-[0.88rem] text-primary hover:underline">
          {untagged} untagged item{untagged === 1 ? "" : "s"}
        </AppLink>
      </div>
      {tree.length ? (
        <ul aria-label="Tag tree">{tree.map(node)}</ul>
      ) : (
        taxonomy.isSuccess && <Empty>No tags yet. Add the first one below.</Empty>
      )}
      <div className="grid gap-1.5 border-t pt-4">
        <NewTagForm />
        <p className="text-[0.78rem] text-muted-foreground">
          Lowercase words joined by "/"; the parent must exist. A tag can be deleted only while no item uses it and it
          has no sub-tags.
        </p>
      </div>
    </div>
  );
}

function Action({
  label,
  danger,
  onClick,
  children,
}: {
  label: string;
  danger?: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className={cn("hover:underline", danger ? "text-destructive" : "text-primary")}
    >
      {children}
    </button>
  );
}
