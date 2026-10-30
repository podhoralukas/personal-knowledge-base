// The API filters by whole UTC days, so dates here are UTC too.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A UTC day as the date fields hold it: "2026-10-27". */
export function daysAgo(days: number, now = new Date()): string {
  const day = new Date(now);
  day.setUTCDate(day.getUTCDate() - days);
  return day.toISOString().slice(0, 10);
}

/** The quick ranges only fill in From/To, which are the date filter's whole state (D36). */
export const RANGES = [
  { label: "Any time", days: null },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
] as const;

/** The From/To of a quick range: the last `days` days, today included. */
export function rangeDates(days: number | null, now = new Date()): { from: string | undefined; to: string | undefined } {
  return days === null ? { from: undefined, to: undefined } : { from: daysAgo(days - 1, now), to: daysAgo(0, now) };
}

/** "27 Oct", or "27 Oct 2026" with the year. */
export function day(iso: string, withYear = false): string {
  const d = new Date(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}${withYear ? ` ${d.getUTCFullYear()}` : ""}`;
}

/** "27 Oct 2026, 08:37 UTC" */
export function stamp(iso: string): string {
  const d = new Date(iso);
  const time = `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
  return `${day(iso, true)}, ${time} UTC`;
}

export function domain(url: string): string {
  return new URL(url).hostname.replace(/^www\./, "");
}
