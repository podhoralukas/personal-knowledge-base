import type { Kind } from "@/api/client";
import { RANGES, rangeDates } from "@/lib/dates";
import type { Filters } from "@/lib/filters";
import { AppLink, SectionLabel } from "./bits";
import { Segmented } from "./Segmented";
import { TagTree } from "./TagTree";

const KINDS: { value: Kind | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "article", label: "Articles" },
  { value: "thought", label: "Thoughts" },
];

/** Kind, saved-date and Tag filters. `onTagPicked` closes the sidebar where it is a drawer. */
export function Sidebar({
  filters,
  onChange,
  onTagPicked,
}: {
  filters: Filters;
  onChange: (change: Partial<Filters>) => void;
  onTagPicked?: () => void;
}) {
  const range = RANGES.find((r) => {
    const dates = rangeDates(r.days);
    return dates.from === filters.from && dates.to === filters.to;
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 pt-3.5 pb-5">
      <section>
        <SectionLabel>Kind</SectionLabel>
        <Segmented
          label="Kind"
          options={KINDS}
          value={filters.kind ?? "all"}
          onChange={(kind) => onChange({ kind: kind === "all" ? undefined : kind })}
        />
      </section>
      <section>
        <SectionLabel>Saved</SectionLabel>
        <Segmented
          label="Saved"
          options={RANGES.map((r) => ({ value: r.label, label: r.label }))}
          value={range?.label ?? null}
          onChange={(label) => onChange(rangeDates(RANGES.find((r) => r.label === label)!.days))}
        />
        <div className="mt-2 grid grid-cols-2 gap-1.5">
          {(
            [
              ["from", "From"],
              ["to", "To"],
            ] as const
          ).map(([end, label]) => (
            <label key={end} className="grid gap-0.5 text-[0.75rem] text-muted-foreground">
              {label}
              <input
                type="date"
                value={filters[end] ?? ""}
                onChange={(event) => onChange({ [end]: event.target.value || undefined })}
                className="w-full min-w-0 rounded-md border bg-card px-1.5 py-1 text-[0.82rem] text-foreground"
              />
            </label>
          ))}
        </div>
      </section>
      <section>
        <SectionLabel>Tags</SectionLabel>
        <TagTree
          filters={filters}
          onPick={(change) => {
            onChange(change);
            onTagPicked?.();
          }}
        />
      </section>
      <p className="px-1.5 text-[0.8rem] text-muted-foreground">
        Edit tags on the{" "}
        <AppLink href="/app/taxonomy" className="text-primary hover:underline">
          Taxonomy
        </AppLink>{" "}
        page.
      </p>
    </div>
  );
}
