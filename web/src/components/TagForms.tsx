import { type FormEvent, type ReactNode, useState } from "react";
import { toast } from "sonner";
import type { Tag } from "@/api/client";
import { useAddTag, useChangeTag, useDeleteTag } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// The Taxonomy page's forms (D28): add a Tag, edit its description or path, delete an unused one.

/** A new Tag under `parent` (top level without). The path starts as "parent/" so only the name is typed. */
export function NewTagForm({ parent, onDone }: { parent?: string; onDone?: () => void }) {
  const prefix = parent ? `${parent}/` : "";
  const add = useAddTag();
  const [path, setPath] = useState(prefix);
  const [description, setDescription] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate(
      { path: path.trim(), description: description.trim() },
      {
        onSuccess: (tag) => {
          toast(`Added ${tag.path}. Items get it on their next capture or re-tag.`);
          setPath(prefix);
          setDescription("");
          onDone?.();
        },
      },
    );
  };

  return (
    <Form onSubmit={submit} error={add.error?.message} label={parent ? `New sub-tag of ${parent}` : "New tag"}>
      <div className="flex flex-wrap gap-2">
        <Input
          aria-label="Path"
          placeholder={parent ? undefined : "New top-level tag, e.g. science"}
          required
          autoFocus={!!parent}
          value={path}
          onChange={(event) => setPath(event.target.value)}
          className="w-56 flex-none"
        />
        <Input
          aria-label="Description"
          placeholder="Description (optional; the tagger reads it)"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          className="min-w-48 flex-1"
        />
        <Button type="submit" disabled={add.isPending}>
          {parent ? "Add sub-tag" : "Add tag"}
        </Button>
        {onDone && (
          <Button type="button" variant="outline" onClick={onDone}>
            Cancel
          </Button>
        )}
      </div>
    </Form>
  );
}

/** The Tag's description and path. A new path renames it: fixing spelling or moving it with its sub-tags,
 * in every Item and Version. */
export function EditTagForm({ tag, onDone }: { tag: Tag; onDone: () => void }) {
  const change = useChangeTag(tag.path);
  const [path, setPath] = useState(tag.path);
  const [description, setDescription] = useState(tag.description ?? "");
  const renaming = path.trim() !== tag.path;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const edit = {
      ...(renaming && { path: path.trim() }),
      ...(description.trim() !== (tag.description ?? "") && { description: description.trim() }),
    };
    if (!Object.keys(edit).length) return onDone();
    change.mutate(edit, {
      onSuccess: (changed) => {
        toast(renaming ? `Renamed to ${changed.path} everywhere.` : `Saved the description of ${changed.path}.`);
        onDone();
      },
    });
  };

  return (
    <Form onSubmit={submit} error={change.error?.message} label={`Edit ${tag.path}`}>
      <div className="flex flex-wrap gap-2">
        <Input aria-label="Path" required value={path} onChange={(event) => setPath(event.target.value)} className="w-56 flex-none" />
        <Input
          aria-label="Description"
          placeholder="Description (optional; the tagger reads it)"
          autoFocus
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          className="min-w-48 flex-1"
        />
        <Button type="submit" disabled={change.isPending}>
          {renaming ? "Rename" : "Save"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {renaming && (
        <p className="text-[0.78rem] text-muted-foreground">
          Renames {tag.path}, with its sub-tags, in every item and version. For a new meaning, add a new tag instead.
        </p>
      )}
    </Form>
  );
}

/** Asks before deleting; only offered for a Tag nothing uses and without sub-tags. */
export function DeleteTagConfirm({ tag, onDone }: { tag: Tag; onDone: () => void }) {
  const remove = useDeleteTag(tag.path);
  return (
    <div role="alert" className="grid gap-2 rounded-lg border border-destructive bg-destructive-soft px-3.5 py-3">
      <p>
        Delete the tag <b>{tag.path}</b>? No item uses it.
      </p>
      {remove.isError && <p className="text-sm text-destructive">Could not delete it: {remove.error.message}</p>}
      <div className="flex gap-2">
        <Button
          variant="destructive"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(undefined, {
              onSuccess: () => {
                toast(`Deleted ${tag.path}.`);
                onDone();
              },
            })
          }
        >
          Delete tag
        </Button>
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function Form({
  label,
  error,
  onSubmit,
  children,
}: {
  label: string;
  error?: string;
  onSubmit: (event: FormEvent) => void;
  children: ReactNode;
}) {
  return (
    <form aria-label={label} onSubmit={onSubmit} className="grid gap-1.5">
      {children}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}
