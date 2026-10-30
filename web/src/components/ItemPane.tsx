import { EllipsisIcon, XIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { useItem, useItemEdits, useVersions, useWhenProcessed } from "@/api/queries";
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
import { ThoughtEdit } from "./ThoughtEdit";

type Props = {
  id?: string;
  /** Shows another Item: the one a "Capture again" landed on when the page redirected. */
  onOpen: (id: string) => void;
  /** Closes the drawer the pane is shown in; absent in the three-pane layout. */
  onClose?: () => void;
  onDeleted: () => void;
};

/** The selected Item: what it is, its Tags, its text, the Note and the Versions (D36). */
export function ItemPane({ id, onOpen, onClose, onDeleted }: Props) {
  return (
    // Keyed by the Item, so a newly selected one starts at the top with no open menu, confirm or draft.
    <div key={id} className="min-h-0 flex-1 overflow-y-auto px-[clamp(1.25rem,3vw,2.75rem)] pt-7 pb-12">
      {id ? (
        <ItemView id={id} onOpen={onOpen} onClose={onClose} onDeleted={onDeleted} />
      ) : (
        <Empty>Pick an item from the list.</Empty>
      )}
    </div>
  );
}

function ItemView({ id, onOpen, onClose, onDeleted }: Props & { id: string }) {
  const versions = useVersions(id);
  const pending = versions.data?.some((v) => v.status === "pending") ?? false;
  const latest = versions.data?.[0];
  const item = useItem(id, pending);
  const edits = useItemEdits(id);
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState(false);
  useWhenProcessed(id, pending);

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
        <Empty>
          {!gone
            ? item.error.message
            : pending
              ? "Being captured…"
              : latest?.status === "failed"
                ? `Capturing failed: ${latest.error ?? "unknown error"}`
                : "This item no longer exists."}
        </Empty>
      </>
    );
  }

  const it = item.data;
  const thought = it.media_type === "thought";
  const captureAgain = () =>
    edits.captureAgain.mutate(it.original_url!, {
      onSuccess: (accepted) => {
        toast("Capturing again. The new version shows here when it's processed.");
        if (accepted.item_id !== id) onOpen(accepted.item_id);
      },
    });
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
              <DropdownMenuItem onSelect={() => copyLink(id)}>
                Copy link
              </DropdownMenuItem>
              {thought ? (
                <DropdownMenuItem disabled={editing} onSelect={() => setEditing(true)}>
                  Edit Thought
                </DropdownMenuItem>
              ) : (
                it.original_url && (
                  <DropdownMenuItem disabled={pending || edits.captureAgain.isPending} onSelect={captureAgain}>
                    Capture again
                  </DropdownMenuItem>
                )
              )}
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

      {pending ? (
        <Notice>Processing the new version. This updates by itself.</Notice>
      ) : (
        latest?.status === "failed" &&
        (thought && latest.id === it.current_version_id ? (
          <Notice>
            Not enriched: its Tags and search by meaning still reflect an earlier version.{" "}
            <button
              type="button"
              className="text-primary hover:underline"
              disabled={edits.retry.isPending}
              onClick={() => edits.retry.mutate()}
            >
              Retry
            </button>
          </Notice>
        ) : (
          !thought && <Notice>The latest capture failed, so this shows an earlier version.</Notice>
        ))
      )}

      {thought ? (
        editing ? (
          <ThoughtEdit
            item={it}
            title={versions.data?.find((v) => v.id === it.current_version_id)?.title ?? ""}
            edits={edits}
            onDone={() => setEditing(false)}
          />
        ) : (
          <p className="font-serif text-[1.02rem] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">
            {it.text}
          </p>
        )
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

/** `navigator.clipboard` is missing outside a secure context (plain HTTP on a LAN address), and writing to it
 * can be refused. */
async function copyLink(id: string) {
  const link = `${window.location.origin}${window.location.pathname}?item=${encodeURIComponent(id)}`;
  try {
    await navigator.clipboard.writeText(link);
    toast("Link copied.");
  } catch {
    toast.error("Couldn't copy the link.");
  }
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <div role="status" className="rounded-lg bg-muted px-3.5 py-2.5 text-[0.9rem] text-muted-foreground">
      {children}
    </div>
  );
}

function Kbd({ children }: { children: string }) {
  return <kbd className="rounded border border-b-2 bg-card px-1 font-mono text-[0.72rem]">{children}</kbd>;
}
