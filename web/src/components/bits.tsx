// Small pieces the panes share.
import type { ReactNode } from "react";
import type { Item } from "@/api/client";
import { domain } from "@/lib/dates";
import { splitPath } from "@/lib/tags";
import { cn } from "@/lib/utils";

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-1.5 ml-1.5 text-[0.72rem] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
      {children}
    </h2>
  );
}

/** A Tag path with its parent path faded: "news/sport/" formula1. */
export function TagLabel({ path }: { path: string }) {
  const [parent, name] = splitPath(path);
  return (
    <>
      {parent && <span className="font-normal opacity-60">{parent}</span>}
      <span>{name}</span>
    </>
  );
}

export const pill = "inline-flex items-center rounded-full bg-tag text-tag-foreground font-medium whitespace-nowrap";

export function KindBadge({ item }: { item: Item }) {
  const thought = item.media_type === "thought";
  return (
    <span
      className={cn(
        "rounded border px-1.5 font-mono text-[0.7rem] font-medium tracking-wide uppercase",
        thought ? "border-primary text-primary" : "text-muted-foreground",
      )}
    >
      {thought ? "Thought" : "Article"}
    </span>
  );
}

/** Where an Item came from: the article's site, or the Thought badge. */
export function Source({ item }: { item: Item }) {
  return item.media_type === "thought" || !item.original_url ? (
    <KindBadge item={item} />
  ) : (
    <span>{domain(item.original_url)}</span>
  );
}

export function Dot() {
  return <span aria-hidden>·</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-6 py-10 text-center text-muted-foreground">{children}</div>;
}
