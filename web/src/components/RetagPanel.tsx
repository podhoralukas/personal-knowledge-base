import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useRetag, useStats } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { SectionLabel } from "./bits";

/** While a re-tag runs the counts are polled, for about as long as it takes: a few seconds per Item. The API
 * does not report when the background job ends. */
const RETAG_POLL_MS = 3000;
const RETAG_MS_PER_ITEM = 5000;
const RETAG_MIN_MS = 30_000;

type Running = { count: number; until: number };

/** Re-tag (D25): the Items a newly added Tag could change, or every Item. Re-tags only add Tags. */
export function RetagPanel() {
  const [running, setRunning] = useState<Running | null>(null);
  const [confirming, setConfirming] = useState<"candidates" | "all" | null>(null);
  const stats = useStats(running ? RETAG_POLL_MS : false);
  const retag = useRetag();
  const client = useQueryClient();
  const candidates = stats.data?.retag_candidates ?? 0;
  const total = stats.data?.items ?? 0;

  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => {
      setRunning(null);
      void client.invalidateQueries(); // the Items' Tags, not only the counts
    }, running.until - Date.now());
    return () => clearTimeout(timer);
  }, [running, client]);

  const start = (all: boolean) =>
    retag.mutate(all, {
      onSuccess: ({ item_count }) => {
        setConfirming(null);
        setRunning({ count: item_count, until: Date.now() + Math.max(RETAG_MIN_MS, item_count * RETAG_MS_PER_ITEM) });
      },
    });
  const count = confirming === "all" ? total : candidates;

  return (
    <section aria-label="Re-tag" className="grid gap-3">
      <SectionLabel>Re-tag</SectionLabel>
      <p className="text-[0.9rem] text-muted-foreground">
        A re-tag only adds tags; it never removes one. Each item is one LLM call.
      </p>
      <p>
        {candidates
          ? `${plural(candidates, "item")} could get one of the newest tags: untagged items, and items tagged with a parent of a new tag.`
          : "No item is waiting for the newest tags."}
      </p>
      {running && (
        <p role="status" className="rounded-lg bg-muted px-3.5 py-2.5 text-[0.9rem] text-muted-foreground">
          Re-tagging {plural(running.count, "item")} in the background. The counts update as it goes.
        </p>
      )}
      {confirming ? (
        <div role="alert" className="grid gap-2 rounded-lg border px-3.5 py-3">
          <p>
            Re-tag {confirming === "all" ? "all " : ""}
            {plural(count, "item")}? That is one LLM call each.
          </p>
          <div className="flex gap-2">
            <Button disabled={retag.isPending} onClick={() => start(confirming === "all")}>
              Re-tag {count}
            </Button>
            <Button variant="outline" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {candidates > 0 && <Button onClick={() => setConfirming("candidates")}>Re-tag {candidates}</Button>}
          {total > 0 && (
            <Button variant="outline" onClick={() => setConfirming("all")}>
              Re-tag all {total}
            </Button>
          )}
        </div>
      )}
    </section>
  );
}

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}
