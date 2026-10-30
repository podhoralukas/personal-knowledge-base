import { expect, test } from "vitest";
import { readFilters, writeFilters } from "./filters";

test("filters survive the round trip through the URL", () => {
  const filters = { tag: "news/sport", untagged: false, kind: "thought" as const, from: "2026-10-01", to: "2026-10-27", q: "soup", item: "thought:1" };
  expect(readFilters(writeFilters(filters))).toEqual(filters);
  expect(writeFilters({ untagged: true, q: "" })).toBe("?untagged=1");
});

test("an unknown Kind is ignored", () => {
  expect(readFilters("?kind=video").kind).toBeUndefined();
});
