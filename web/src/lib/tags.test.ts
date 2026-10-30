import { expect, test } from "vitest";
import { tag } from "@/test/fakeApi";
import { mostSpecific, splitPath, tagTree } from "./tags";

test("lists leave out an ancestor of another Tag on the Item", () => {
  expect(mostSpecific(["news", "news/sport", "news/sport/formula1", "ai"])).toEqual(["news/sport/formula1", "ai"]);
  expect(mostSpecific(["news", "newsletters"])).toEqual(["news", "newsletters"]);
});

test("a path splits into its faded parent and its name", () => {
  expect(splitPath("news/sport/formula1")).toEqual(["news/sport/", "formula1"]);
  expect(splitPath("ai")).toEqual(["", "ai"]);
});

test("the tree nests sub-tags under their parents in path order", () => {
  const tree = tagTree([tag("news/sport"), tag("ai"), tag("news"), tag("ai/agents")]);
  const shape = (nodes: ReturnType<typeof tagTree>): unknown =>
    nodes.map((n) => (n.children.length ? [n.tag.path, shape(n.children)] : n.tag.path));
  expect(shape(tree)).toEqual([
    ["ai", ["ai/agents"]],
    ["news", ["news/sport"]],
  ]);
});
