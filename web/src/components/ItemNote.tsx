import { useState } from "react";
import { toast } from "sonner";
import type { Item } from "@/api/client";
import type { useItemEdits } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { SectionLabel } from "./bits";

const NOTE_MAX_CHARS = 20_000; // kb/config.py

/** The Owner's Note on an article; never shown to the pipeline. */
export function ItemNote({ item, edits }: { item: Item; edits: ReturnType<typeof useItemEdits> }) {
  const notes = item.annotations?.notes ?? "";
  const [draft, setDraft] = useState<string | null>(null);

  return (
    <section className="grid gap-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>Note</SectionLabel>
        {draft === null && (
          <button type="button" className="text-[0.85rem] text-primary hover:underline" onClick={() => setDraft(notes)}>
            {notes ? "Edit" : "Add a note"}
          </button>
        )}
      </div>
      {draft === null ? (
        <p
          className={cn(
            "rounded-r-lg border-l-[3px] bg-muted px-3.5 py-2.5 whitespace-pre-wrap [overflow-wrap:anywhere]",
            notes ? "border-primary" : "border-border text-muted-foreground italic",
          )}
        >
          {notes || "No note yet. Only you see it; the pipeline never reads it."}
        </p>
      ) : (
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            edits.note.mutate(draft.trim(), {
              onSuccess: () => {
                setDraft(null);
                toast("Note saved.");
              },
            });
          }}
        >
          <Textarea
            aria-label="Note"
            rows={4}
            maxLength={NOTE_MAX_CHARS}
            value={draft}
            autoFocus
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="flex gap-2">
            <Button type="submit" disabled={edits.note.isPending}>
              Save note
            </Button>
            <Button type="button" variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
