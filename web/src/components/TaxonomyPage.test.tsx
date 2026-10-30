import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { fakeApi, item, tag } from "@/test/fakeApi";
import { renderApp } from "@/test/render";

const TAGS = [tag("news", "General news"), tag("news/sport"), tag("news/sport/formula1"), tag("cooking")];
const ITEMS = [
  item({ id: "f1", title: "Verstappen wins", tags: ["news", "news/sport", "news/sport/formula1"] }),
  item({ id: "u1", title: "Untagged one", first_captured_at: "2026-10-01T10:00:00.000Z" }),
];

const nav = () => within(screen.getByRole("navigation", { name: "Main" }));
const tree = () => within(screen.getByRole("list", { name: "Tag tree" }));
/** The tree row of `path`: its name links to the Items under it. */
const row = (path: string) => within(tree().getByRole("link", { name: path.split("/").at(-1) }).parentElement!);

async function openPage() {
  renderApp("/app/taxonomy");
  await screen.findByRole("heading", { name: /Taxonomy/, level: 1 });
  await within(await screen.findByRole("list", { name: "Tag tree" })).findByRole("link", { name: "formula1" });
}

test("the header switches between Items and Taxonomy without a reload", async () => {
  fakeApi({ items: ITEMS, tags: TAGS });
  renderApp();
  await screen.findByRole("heading", { name: "Verstappen wins", level: 1 });

  await userEvent.click(nav().getByRole("link", { name: "Taxonomy" }));
  expect(await screen.findByRole("heading", { name: /Taxonomy/, level: 1 })).toBeInTheDocument();
  expect(window.location.pathname).toBe("/app/taxonomy");
  expect(nav().getByRole("link", { name: "Taxonomy" })).toHaveAttribute("aria-current", "page");

  await userEvent.click(nav().getByRole("link", { name: "Items" }));
  expect(await screen.findByRole("heading", { name: "Verstappen wins", level: 1 })).toBeInTheDocument();
});

test("the tree shows counts and descriptions; a Tag's name opens its Items", async () => {
  fakeApi({ items: ITEMS, tags: TAGS });
  await openPage();

  expect(row("news").getByText("1")).toBeInTheDocument();
  expect(row("news").getByText("General news")).toBeInTheDocument();
  expect(row("cooking").getByText("0")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "1 untagged item" })).toHaveAttribute("href", "/app/?untagged=1");

  await userEvent.click(row("news/sport/formula1").getByRole("link", { name: "formula1" }));
  expect(await screen.findByRole("heading", { name: "Verstappen wins", level: 3 })).toBeInTheDocument();
  expect(window.location.search).toContain("tag=news%2Fsport%2Fformula1");
});

test("add a top-level Tag and a sub-tag; a missing parent is explained in the form", async () => {
  const api = fakeApi({ items: ITEMS, tags: TAGS });
  await openPage();

  const top = within(screen.getByRole("form", { name: "New tag" }));
  await userEvent.type(top.getByRole("textbox", { name: "Path" }), "science/physics");
  await userEvent.click(top.getByRole("button", { name: "Add tag" }));
  expect(await top.findByRole("alert")).toHaveTextContent("parent tag 'science' does not exist");

  await userEvent.clear(top.getByRole("textbox", { name: "Path" }));
  await userEvent.type(top.getByRole("textbox", { name: "Path" }), "science");
  await userEvent.type(top.getByRole("textbox", { name: "Description" }), "Research and discoveries");
  await userEvent.click(top.getByRole("button", { name: "Add tag" }));
  expect(await tree().findByRole("link", { name: "science" })).toBeInTheDocument();
  expect(top.queryByRole("alert")).not.toBeInTheDocument();

  await userEvent.click(row("science").getByRole("button", { name: "Add a sub-tag to science" }));
  const sub = within(screen.getByRole("form", { name: "New sub-tag of science" }));
  expect(sub.getByRole("textbox", { name: "Path" })).toHaveValue("science/");
  await userEvent.type(sub.getByRole("textbox", { name: "Path" }), "physics");
  await userEvent.click(sub.getByRole("button", { name: "Add sub-tag" }));

  expect(await tree().findByRole("link", { name: "physics" })).toBeInTheDocument();
  expect(api.tags.map((t) => [t.path, t.description])).toContainEqual(["science", "Research and discoveries"]);
  expect(api.tags.map((t) => t.path)).toContain("science/physics");
});

test("edit a description, and rename a Tag with its sub-tags everywhere", async () => {
  const api = fakeApi({ items: ITEMS, tags: TAGS });
  await openPage();

  await userEvent.click(row("cooking").getByRole("button", { name: "Edit cooking" }));
  let form = within(screen.getByRole("form", { name: "Edit cooking" }));
  await userEvent.type(form.getByRole("textbox", { name: "Description" }), "Recipes");
  await userEvent.click(form.getByRole("button", { name: "Save" }));
  expect(await row("cooking").findByText("Recipes")).toBeInTheDocument();
  expect(api.bodies.at(-1)).toEqual({ method: "PATCH", path: "/taxonomy/tags/cooking", body: { description: "Recipes" } });

  await userEvent.click(row("news/sport").getByRole("button", { name: "Edit news/sport" }));
  form = within(screen.getByRole("form", { name: "Edit news/sport" }));
  const path = form.getByRole("textbox", { name: "Path" });
  await userEvent.clear(path);
  await userEvent.type(path, "news/sports");
  expect(form.getByText(/Renames news\/sport, with its sub-tags, in every item and version/)).toBeInTheDocument();
  await userEvent.click(form.getByRole("button", { name: "Rename" }));

  expect(await tree().findByRole("link", { name: "sports" })).toBeInTheDocument();
  expect(api.items[0].tags).toEqual(["news", "news/sports", "news/sports/formula1"]);
});

test("only an unused Tag without sub-tags offers delete, and it asks first", async () => {
  const api = fakeApi({ items: ITEMS, tags: TAGS });
  await openPage();

  expect(row("news").queryByRole("button", { name: "Delete news" })).not.toBeInTheDocument();
  expect(row("news/sport/formula1").queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
  await userEvent.click(row("cooking").getByRole("button", { name: "Delete cooking" }));
  const confirm = await screen.findByRole("alert");
  expect(confirm).toHaveTextContent("Delete the tag cooking?");
  expect(api.tags).toHaveLength(4);

  await userEvent.click(within(confirm).getByRole("button", { name: "Delete tag" }));
  await waitFor(() => expect(tree().queryByRole("link", { name: "cooking" })).not.toBeInTheDocument());
  expect(api.tags.map((t) => t.path)).not.toContain("cooking");
});

test("re-tag the candidates after a confirm, then see it running", async () => {
  const api = fakeApi({ items: ITEMS, tags: TAGS, retagCandidates: 1 });
  await openPage();
  const panel = within(screen.getByRole("region", { name: "Re-tag" }));

  expect(panel.getByText(/1 item could get one of the newest tags/)).toBeInTheDocument();
  await userEvent.click(panel.getByRole("button", { name: "Re-tag 1" }));
  expect(panel.getByRole("alert")).toHaveTextContent("Re-tag 1 item? That is one LLM call each.");
  expect(api.bodies).toEqual([]);

  await userEvent.click(within(panel.getByRole("alert")).getByRole("button", { name: "Re-tag 1" }));
  expect(await panel.findByRole("status")).toHaveTextContent("Re-tagging 1 item in the background.");
  expect(api.bodies).toEqual([{ method: "POST", path: "/taxonomy/retag", body: null }]);
  expect(await panel.findByText("No item is waiting for the newest tags.")).toBeInTheDocument();
});

test("re-tag all asks with the total", async () => {
  const api = fakeApi({ items: ITEMS, tags: TAGS });
  await openPage();
  const panel = within(screen.getByRole("region", { name: "Re-tag" }));

  expect(panel.queryByRole("button", { name: /^Re-tag \d/ })).not.toBeInTheDocument();
  await userEvent.click(panel.getByRole("button", { name: "Re-tag all 2" }));
  expect(panel.getByRole("alert")).toHaveTextContent("Re-tag all 2 items?");
  await userEvent.click(within(panel.getByRole("alert")).getByRole("button", { name: "Re-tag 2" }));

  expect(await panel.findByRole("status")).toHaveTextContent("Re-tagging 2 items in the background.");
  expect(api.bodies).toEqual([{ method: "POST", path: "/taxonomy/retag?all=true", body: null }]);
});
