import { useState } from "react";
import { toast } from "sonner";
import type { Item } from "@/api/client";
import type { useItemEdits } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { ThoughtFields } from "./ThoughtFields";

/** Edits a Thought in place of its text; saving adds a Version. `title` is the current Version's own title,
 * empty when the Item's title comes from the first line. Mounted for one edit, so it starts from what is shown. */
export function ThoughtEdit({
  item,
  title,
  edits,
  onDone,
}: {
  item: Item;
  title: string;
  edits: ReturnType<typeof useItemEdits>;
  onDone: () => void;
}) {
  const [draft, setDraft] = useState({ title, text: item.text ?? "" });
  const saving = edits.editThought;
  const done = () => {
    saving.reset();
    onDone();
  };

  return (
    <form
      aria-label="Edit Thought"
      className="grid gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        saving.mutate(draft, {
          onSuccess: () => {
            done();
            toast("Saved as a new version. Its Tags follow in a moment.");
          },
        });
      }}
    >
      <ThoughtFields value={draft} onChange={(change) => setDraft({ ...draft, ...change })} />
      {saving.isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not save it: {saving.error.message}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving.isPending}>
          Save as new version
        </Button>
        <Button type="button" variant="outline" onClick={done}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
