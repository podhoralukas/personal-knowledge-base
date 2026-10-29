import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { fakeApi, item, tag, version } from "@/test/fakeApi";
import { renderApp } from "@/test/render";

const TAGS = [tag("ai"), tag("ai/agents"), tag("cooking")];
const ARTICLE = item({
  id: "a1",
  title: "Agents in practice",
  summary: "How teams use coding agents.",
  key_points: ["Harnesses matter more than models."],
  tags: ["ai", "ai/agents"],
  annotations: { notes: "", owner_tags: [], rejected_tags: ["cooking"] },
});

const pane = () => within(screen.getByRole("region", { name: "Selected item" }));

async function open(url = "/app/?item=a1") {
  renderApp(url);
  await screen.findByRole("region", { name: "Selected item" });
  return pane().findByRole("heading", { level: 1 });
}

test("shows the article's summary, key points, every Tag and the source", async () => {
  fakeApi({ items: [ARTICLE], tags: TAGS });
  await open();

  expect(pane().getByText("How teams use coding agents.")).toBeInTheDocument();
  expect(pane().getByText("Harnesses matter more than models.")).toBeInTheDocument();
  expect(pane().getByRole("button", { name: "Untag ai" })).toBeInTheDocument(); // ancestors too, unlike lists
  expect(pane().getByRole("button", { name: "Untag ai/agents" })).toBeInTheDocument();
  expect(pane().getByRole("link", { name: "Open original ↗" })).toHaveAttribute("href", "https://www.example.com/a1");
});

test("untag, allow again and add a Tag", async () => {
  const api = fakeApi({ items: [ARTICLE], tags: TAGS });
  await open();

  await userEvent.click(pane().getByRole("button", { name: "Untag ai/agents" }));
  expect(await pane().findByRole("button", { name: "Allow ai/agents again" })).toBeInTheDocument();
  expect(api.items[0].tags).toEqual(["ai"]);

  await userEvent.click(pane().getByRole("button", { name: "Allow cooking again" }));
  await waitFor(() => expect(pane().queryByRole("button", { name: "Allow cooking again" })).not.toBeInTheDocument());

  await userEvent.click(pane().getByRole("button", { name: "+ tag" }));
  await userEvent.click(await screen.findByRole("option", { name: "cooking" }));
  expect(await pane().findByRole("button", { name: "Untag cooking" })).toBeInTheDocument();
  expect(api.items[0].annotations?.owner_tags).toEqual(["cooking"]);
});

test("write and save a Note", async () => {
  const api = fakeApi({ items: [ARTICLE], tags: TAGS });
  await open();

  await userEvent.click(pane().getByRole("button", { name: "Add a note" }));
  await userEvent.type(pane().getByRole("textbox", { name: "Note" }), "  for the talk ");
  await userEvent.click(pane().getByRole("button", { name: "Save note" }));

  expect(await pane().findByText("for the talk")).toBeInTheDocument();
  expect(api.items[0].annotations?.notes).toBe("for the talk");
  expect(pane().getByRole("button", { name: "Edit" })).toBeInTheDocument();
});

test("a Thought shows its text and has no Note", async () => {
  const thought = item({ id: "t1", media_type: "thought", original_url: null, title: "Soup", text: "Lentils\nand more" });
  fakeApi({ items: [thought], tags: TAGS });
  await open("/app/?item=t1");

  expect(pane().getByText(/Lentils\s+and more/)).toBeInTheDocument();
  expect(pane().queryByText("Note")).not.toBeInTheDocument();
  expect(pane().queryByRole("link", { name: "Open original ↗" })).not.toBeInTheDocument();
});

test("deleting asks first, then removes the Item and opens the next", async () => {
  const other = item({ id: "a2", title: "Older item", first_captured_at: "2026-10-01T10:00:00.000Z" });
  const api = fakeApi({ items: [ARTICLE, other], tags: TAGS });
  await open();

  await userEvent.click(pane().getByRole("button", { name: "More actions" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Delete item…" }));
  const confirm = await pane().findByRole("alert");
  expect(confirm).toHaveTextContent("Delete Agents in practice and its whole history?");
  expect(api.items).toHaveLength(2);

  await userEvent.click(within(confirm).getByRole("button", { name: "Delete item" }));
  expect(await pane().findByRole("heading", { name: "Older item", level: 1 })).toBeInTheDocument();
  expect(api.items.map((i) => i.id)).toEqual(["a2"]);
});

test("Versions: details, and deleting one but never the last", async () => {
  const older = version(ARTICLE, { id: "a1:v0", captured_at: "2026-10-01T08:00:00.000Z", channel: "manual" });
  const api = fakeApi({ items: [ARTICLE], tags: TAGS, versions: [version(ARTICLE), older] });
  await open();

  await userEvent.click(pane().getByText("Versions · 2"));
  const rows = () => pane().getAllByRole("row").slice(1);
  expect(rows()[0]).toHaveTextContent("enriched · current");

  await userEvent.click(within(rows()[1]).getByRole("button", { name: "delete" }));
  await userEvent.click(within(rows()[1]).getByRole("button", { name: "Delete this version" }));
  expect(await pane().findByText("Versions · 1")).toBeInTheDocument();
  expect(api.versions.map((v) => v.id)).toEqual(["a1:v1"]);
  expect(pane().queryByRole("button", { name: "delete" })).not.toBeInTheDocument();
});

test("an Item that is gone says so", async () => {
  fakeApi({ items: [], tags: TAGS });
  await open("/app/?item=nope").catch(() => {});
  expect(await pane().findByText("This item no longer exists.")).toBeInTheDocument();
});
