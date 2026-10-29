import { EllipsisIcon, XIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { useItem, useItemEdits, useVersions } from "@/api/queries";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { day, domain } from "@/lib/dates";
import { Dot, Empty, KindBadge, SectionLabel } from "./bits";
import { ItemNote } from "./ItemNote";
import { ItemTags } from "./ItemTags";
import { ItemVersions } from "./ItemVersions";

type Props = {
  id?: string;
  /** Closes the drawer the pane is shown in; absent in the three-pane layout. */
  onClose?: () => void;
  onDeleted: () => void;
};

/** The selected Item: what it is, its Tags, its text, the Note and the Versions (D36). */
export function ItemPane({ id, onClose, onDeleted }: Props) {
  return (
    // Keyed by the Item, so a newly selected one starts at the top with no open menu, confirm or draft.
    <div key={id} className="min-h-0 flex-1 overflow-y-auto px-[clamp(1.25rem,3vw,2.75rem)] pt-7 pb-12">
      {id ? (
        <ItemView id={id} onClose={onClose} onDeleted={onDeleted} />
      ) : (
        <Empty>Pick an item from the list.</Empty>
      )}
    </div>
  );
}

function ItemView({ id, onClose, onDeleted }: Props & { id: string }) {
  const versions = useVersions(id);
  const pending = versions.data?.some((v) => v.status === "pending") ?? false;
  const item = useItem(id, pending);
  const edits = useItemEdits(id);
  const [confirming, setConfirming] = useState(false);

  const close = onClose && (
    <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose}>
      <XIcon />
    </Button>
  );

  if (item.isPending) return <Empty>Loading…</Empty>;
  if (item.isError) {
    const gone = item.error instanceof ApiError && item.error.status === 404;
    return (
      <>
        <div className="flex justify-end">{close}</div>
        <Empty>{gone ? (pending ? "Being captured…" : "This item no longer exists.") : item.error.message}</Empty>
      </>
    );
  }

  const it = item.data;
  const thought = it.media_type === "thought";
  return (
    <article className="mx-auto grid max-w-[44rem] gap-[1.4rem]">
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.85rem] text-muted-foreground">
          <KindBadge item={it} />
          {it.original_url && <span>{domain(it.original_url)}</span>}
          <Dot />
          <span>saved {day(it.first_captured_at, true)}</span>
          {it.original_url && (
            <>
              <Dot />
              <a href={it.original_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                Open original ↗
              </a>
            </>
          )}
        </div>
        <div className="flex gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="More actions">
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onSelect={() =>
                  navigator.clipboard
                    .writeText(`${window.location.origin}${window.location.pathname}?item=${encodeURIComponent(id)}`)
                    .then(() => toast("Link copied."))
                }
              >
                Copy link
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={() => setConfirming(true)}>
                Delete item…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          {close}
        </div>
      </div>

      {confirming && (
        <div role="alert" className="grid gap-2.5 rounded-lg border border-destructive bg-destructive-soft px-3.5 py-3">
          <p>
            Delete <b>{it.title}</b> and its whole history? This can't be undone.
          </p>
          <div className="flex gap-2">
            <Button
              variant="destructive"
              disabled={edits.remove.isPending}
              onClick={() =>
                edits.remove.mutate(undefined, {
                  onSuccess: () => {
                    toast("Item deleted.");
                    onDeleted();
                  },
                })
              }
            >
              Delete item
            </Button>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      <h1 className="font-serif text-[clamp(1.45rem,2.2vw,1.95rem)] leading-tight font-semibold tracking-tight text-balance">
        {it.title}
      </h1>
      <ItemTags item={it} edits={edits} />

      {thought ? (
        <p className="font-serif text-[1.02rem] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{it.text}</p>
      ) : (
        <>
          <p className="font-serif text-[1.08rem] leading-[1.65]">{it.summary}</p>
          {(it.key_points?.length ?? 0) > 0 && (
            <section>
              <SectionLabel>Key points</SectionLabel>
              <ul className="grid list-disc gap-1.5 pl-5 font-serif leading-normal marker:text-primary">
                {it.key_points!.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </section>
          )}
          <ItemNote item={it} edits={edits} />
        </>
      )}

      <ItemVersions item={it} versions={versions} edits={edits} />

      <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 border-t pt-4 text-[0.78rem] text-muted-foreground">
        <span>
          <Kbd>j</Kbd> <Kbd>k</Kbd> next / previous
        </span>
        <span>
          <Kbd>/</Kbd> search
        </span>
        <span>
          <Kbd>Esc</Kbd> close
        </span>
      </div>
    </article>
  );
}

function Kbd({ children }: { children: string }) {
  return <kbd className="rounded border border-b-2 bg-card px-1 font-mono text-[0.72rem]">{children}</kbd>;
}
