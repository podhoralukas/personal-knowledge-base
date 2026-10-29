import { type FormEvent, useId, useRef, useState } from "react";
import { toast } from "sonner";
import type { Accepted } from "@/api/client";
import { type ThoughtDraft, useAdd, useTaxonomy } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TagPicks, ThoughtFields } from "./ThoughtFields";

type Tab = "url" | "thought";

const NO_THOUGHT: ThoughtDraft = { title: "", text: "", tags: [] };

/** "+ Add" (D36): capture a URL or write a Thought, one tab each. What was typed survives closing the dialog;
 * saving clears it and opens the new Item through `onAdded`. */
export function AddDialog({
  open,
  onOpenChange,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("url");
  const [url, setUrl] = useState("");
  const [thought, setThought] = useState(NO_THOUGHT);
  // Fixed once the draft is first sent, so sending it again (say, after a lost response) stores one Thought.
  const writtenAt = useRef<string | null>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const paths = (useTaxonomy().data?.tags ?? []).map((t) => t.path);
  const add = useAdd();
  const id = useId();
  const sending = tab === "url" ? add.capture : add.write;

  const added = (accepted: Accepted, message: string) => {
    onOpenChange(false);
    onAdded(accepted.item_id);
    toast(message);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (tab === "url") {
      add.capture.mutate(url.trim(), {
        onSuccess: (accepted) => {
          setUrl("");
          added(accepted, "Captured. The summary and Tags follow in a moment.");
        },
      });
    } else {
      writtenAt.current ??= new Date().toISOString();
      add.write.mutate(
        { ...thought, written_at: writtenAt.current },
        {
          onSuccess: (accepted) => {
            setThought(NO_THOUGHT);
            writtenAt.current = null;
            added(accepted, "Thought saved. Its Tags follow in a moment.");
          },
        },
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="gap-0 p-0 sm:max-w-[34rem]"
        aria-describedby={undefined}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          (tab === "url" ? urlRef : textRef).current?.focus();
        }}
      >
        <form onSubmit={submit} className="grid gap-4 p-5">
          <DialogTitle className="text-lg">Add to the knowledge base</DialogTitle>
          <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)} className="gap-4">
            <TabsList variant="line" className="w-full justify-start border-b">
              <TabsTrigger value="url" className="flex-none px-3 data-active:after:bg-primary">
                Capture a URL
              </TabsTrigger>
              <TabsTrigger value="thought" className="flex-none px-3 data-active:after:bg-primary">
                Write a Thought
              </TabsTrigger>
            </TabsList>
            <TabsContent value="url" className="grid gap-1.5">
              <Label htmlFor={`${id}-url`}>Page URL</Label>
              <Input
                id={`${id}-url`}
                ref={urlRef}
                type="url"
                required
                placeholder="https://…"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
              />
              <p className="text-[0.78rem] text-muted-foreground">
                The server fetches the page. For pages behind a login or a consent wall, use the browser extension
                (Alt+Shift+K).
              </p>
            </TabsContent>
            <TabsContent value="thought" className="grid gap-3">
              <ThoughtFields value={thought} onChange={(change) => setThought({ ...thought, ...change })} textRef={textRef} />
              {paths.length > 0 && (
                <TagPicks
                  tags={paths}
                  picked={thought.tags}
                  onChange={(tags) => setThought({ ...thought, tags })}
                />
              )}
            </TabsContent>
          </Tabs>
          {sending.isError && (
            <p role="alert" className="text-sm text-destructive">
              {tab === "url" ? "Could not capture it: " : "Could not save it: "}
              {sending.error.message}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={sending.isPending}>
              {tab === "url" ? (add.capture.isPending ? "Capturing…" : "Capture") : "Save Thought"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
