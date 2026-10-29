import { RotateCcwIcon, XIcon } from "lucide-react";
import { useState } from "react";
import type { Item } from "@/api/client";
import { type useItemEdits, useTaxonomy } from "@/api/queries";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { pill, TagLabel } from "./bits";

/** Every Tag on the Item (D36: no ancestors hidden here); untag, allow a rejected one again, add one. */
export function ItemTags({ item, edits }: { item: Item; edits: ReturnType<typeof useItemEdits> }) {
  const taxonomy = useTaxonomy();
  const tags = item.tags ?? [];
  const owner = item.annotations?.owner_tags ?? [];
  const rejected = item.annotations?.rejected_tags ?? [];
  const addable = (taxonomy.data?.tags ?? [])
    .map((t) => t.path)
    .filter((path) => !tags.includes(path) && !rejected.includes(path));

  return (
    <section aria-label="Tags" className="grid gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag}
            className={cn(pill, "pl-2.5 text-[0.85rem]", owner.includes(tag) && "ring-[1.5px] ring-tag-foreground ring-inset")}
          >
            <TagLabel path={tag} />
            <button
              type="button"
              aria-label={`Untag ${tag}`}
              title="Untag"
              onClick={() => edits.untag.mutate(tag)}
              className="rounded-full py-1 pr-2 pl-1 opacity-55 hover:text-destructive hover:opacity-100"
            >
              <XIcon className="size-3" />
            </button>
          </span>
        ))}
        {rejected.map((tag) => (
          <span key={tag} className={cn(pill, "bg-transparent pl-2.5 text-[0.85rem] text-muted-foreground ring-1 ring-border ring-inset")}>
            <span className="line-through">{tag}</span>
            <button
              type="button"
              aria-label={`Allow ${tag} again`}
              title="Allow again"
              onClick={() => edits.allow.mutate(tag)}
              className="rounded-full py-1 pr-2 pl-1 opacity-55 hover:text-primary hover:opacity-100"
            >
              <RotateCcwIcon className="size-3" />
            </button>
          </span>
        ))}
        <AddTag addable={addable} onAdd={(path) => edits.tag.mutate(path)} />
      </div>
      {(owner.length > 0 || rejected.length > 0) && (
        <p className="text-[0.78rem] text-muted-foreground">
          Outlined: added by you. Struck through: taken off by you, never suggested again.
        </p>
      )}
    </section>
  );
}

function AddTag({ addable, onAdd }: { addable: string[]; onAdd: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="rounded-full border border-dashed px-2 py-0.5 text-[0.85rem] text-muted-foreground hover:text-foreground"
        >
          + tag
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-0">
        <Command>
          <CommandInput placeholder="Find a tag…" />
          <CommandList>
            <CommandEmpty>No tag to add.</CommandEmpty>
            {addable.map((path) => (
              <CommandItem
                key={path}
                value={path}
                onSelect={() => {
                  setOpen(false);
                  onAdd(path);
                }}
              >
                <span>
                  <TagLabel path={path} />
                </span>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
