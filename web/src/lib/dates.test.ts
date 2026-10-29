import { expect, test } from "vitest";
import { day, rangeDates, stamp } from "./dates";

const NOW = new Date("2026-10-27T23:30:00Z");

test("a quick range fills From/To with the last days, today included", () => {
  expect(rangeDates(7, NOW)).toEqual({ from: "2026-10-21", to: "2026-10-27" });
  expect(rangeDates(null, NOW)).toEqual({ from: undefined, to: undefined });
});

test("dates are shown as UTC days", () => {
  expect(day("2026-10-27T23:30:00Z")).toBe("27 Oct");
  expect(day("2026-10-27T23:30:00Z", true)).toBe("27 Oct 2026");
  expect(stamp("2026-10-27T08:07:00Z")).toBe("27 Oct 2026, 08:07 UTC");
});
