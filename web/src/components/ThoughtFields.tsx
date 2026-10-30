import { type Ref, useId } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { TagLabel } from "./bits";

const THOUGHT_TITLE_MAX_CHARS = 200; // kb/config.py
const THOUGHT_MAX_CHARS = 20_000; // kb/config.py

type Text = { title: string; text: string };

/** A Thought's title (optional: the first line otherwise) and text, for writing one or editing it. */
export function ThoughtFields({
  value,
  onChange,
  textRef,
}: {
  value: Text;
  onChange: (change: Partial<Text>) => void;
  textRef?: Ref<HTMLTextAreaElement>;
}) {
  const id = useId();
  return (
    <>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-title`}>
          Title <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <Input
          id={`${id}-title`}
          placeholder="The first line otherwise"
          maxLength={THOUGHT_TITLE_MAX_CHARS}
          value={value.title}
          onChange={(event) => onChange({ title: event.target.value })}
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-text`}>Text</Label>
        <Textarea
          id={`${id}-text`}
          ref={textRef}
          rows={7}
          required
          placeholder="What's on your mind…"
          maxLength={THOUGHT_MAX_CHARS}
          value={value.text}
          onChange={(event) => onChange({ text: event.target.value })}
        />
      </div>
    </>
  );
}

/** Tags to put on a new Thought as toggles; none picked and the pipeline tags it. */
export function TagPicks({
  tags,
  picked,
  onChange,
}: {
  tags: string[];
  picked: string[];
  onChange: (picked: string[]) => void;
}) {
  return (
    <fieldset className="grid gap-1.5">
      <legend className="mb-1.5 text-sm font-medium">
        Tags <span className="font-normal text-muted-foreground">(optional; none and the pipeline picks them)</span>
      </legend>
      <div className="flex flex-wrap gap-1.5">
        {tags.map((path) => (
          <label key={path} className="cursor-pointer">
            <input
              type="checkbox"
              className="peer sr-only"
              checked={picked.includes(path)}
              onChange={(event) =>
                onChange(event.target.checked ? [...picked, path] : picked.filter((p) => p !== path))
              }
            />
            <span className="inline-block rounded-full border px-2.5 py-0.5 text-[0.82rem] text-muted-foreground peer-checked:border-tag-foreground peer-checked:bg-tag peer-checked:text-tag-foreground peer-focus-visible:outline-2 peer-focus-visible:outline-ring">
              <TagLabel path={path} />
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
