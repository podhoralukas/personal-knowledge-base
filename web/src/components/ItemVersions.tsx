import type { UseQueryResult } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import type { Item, Version } from "@/api/client";
import type { useItemEdits } from "@/api/queries";
import { stamp } from "@/lib/dates";
import { cn } from "@/lib/utils";
import { pill, TagLabel } from "./bits";

const STATUS_COLOR = { enriched: "text-primary", pending: "text-muted-foreground", failed: "text-destructive" };

/** The Item's Versions, newest first, collapsed: details of each, and deleting any but the last. */
export function ItemVersions({
  item,
  versions,
  edits,
}: {
  item: Item;
  versions: UseQueryResult<Version[]>;
  edits: ReturnType<typeof useItemEdits>;
}) {
  const [shown, setShown] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const list = versions.data ?? [];
  const action = "text-[0.85rem] text-primary hover:underline";

  return (
    <details>
      <summary className="cursor-pointer text-[0.72rem] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
        Versions · {list.length}
      </summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-[0.85rem]">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">Captured</th>
              <th className="py-1.5 pr-3 font-medium">Channel</th>
              <th className="py-1.5 pr-3 font-medium">Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((v) => (
              <Fragment key={v.id}>
                <tr className="border-b whitespace-nowrap">
                  <td className="py-1.5 pr-3">{stamp(v.captured_at)}</td>
                  <td className="py-1.5 pr-3">{v.channel}</td>
                  <td className={cn("py-1.5 pr-3", STATUS_COLOR[v.status ?? "pending"])}>
                    {v.status}
                    {v.id === item.current_version_id && " · current"}
                  </td>
                  <td className="space-x-3 py-1.5 text-right">
                    <button type="button" className={action} onClick={() => setShown(shown === v.id ? null : v.id)}>
                      {shown === v.id ? "hide" : "details"}
                    </button>
                    {list.length > 1 &&
                      (deleting === v.id ? (
                        <>
                          <button
                            type="button"
                            className="text-[0.85rem] font-medium text-destructive hover:underline"
                            onClick={() => edits.removeVersion.mutate(v.id, { onSettled: () => setDeleting(null) })}
                          >
                            Delete this version
                          </button>
                          <button type="button" className={action} onClick={() => setDeleting(null)}>
                            keep
                          </button>
                        </>
                      ) : (
                        <button type="button" className={action} onClick={() => setDeleting(v.id)}>
                          delete
                        </button>
                      ))}
                  </td>
                </tr>
                {shown === v.id && (
                  <tr className="border-b">
                    <td colSpan={4} className="py-2">
                      <VersionDetails version={v} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function VersionDetails({ version }: { version: Version }) {
  const e = version.enrichment;
  return (
    <div className="grid gap-1.5 text-[0.85rem]">
      <p className="font-medium">{e?.title || version.title || "(no title)"}</p>
      <p className="whitespace-pre-wrap text-muted-foreground">{version.text ?? e?.summary}</p>
      {version.error && <p className="text-destructive">{version.error}</p>}
      {e?.tags && e.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {e.tags.map((tag) => (
            <span key={tag} className={cn(pill, "px-2 py-0.5 text-[0.75rem]")}>
              <TagLabel path={tag} />
            </span>
          ))}
        </div>
      )}
      {e?.model && (
        <p className="text-[0.75rem] text-muted-foreground">
          {e.model} · prompt {e.prompt_version} · taxonomy v{e.taxonomy_version}
        </p>
      )}
    </div>
  );
}
