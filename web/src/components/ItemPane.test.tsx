import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { expect, test, vi } from "vitest";
import { fakeApi, item, tag, version } from "@/test/fakeApi";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

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

test("Copy link copies the Item's link", async () => {
  fakeApi({ items: [ARTICLE], tags: TAGS });
  await open();
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

  try {
    await userEvent.click(pane().getByRole("button", { name: "More actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Copy link" }));
    expect(await screen.findByText("Link copied.")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/app/?item=a1`);
  } finally {
    delete (navigator as { clipboard?: Clipboard }).clipboard;
  }
});

test("Copy link says so when there is no clipboard (plain HTTP, like jsdom)", async () => {
  fakeApi({ items: [ARTICLE], tags: TAGS });
  await open();

  await userEvent.click(pane().getByRole("button", { name: "More actions" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Copy link" }));
  expect(await screen.findByText("Couldn't copy the link.")).toBeInTheDocument();
});

test("a Capture not processed yet never says it no longer exists while its Versions load", async () => {
  const id = "captured:https://example.com/new";
  fakeApi({ tags: TAGS, versions: [version(item({ id, title: "" }), { status: "pending", enrichment: null })] });
  let release = () => {};
  const versionsHeld = new Promise<void>((resolve) => (release = resolve));
  // Answered by the fake API once released: the Item's 404 comes first.
  server.use(http.get("/items/:id/versions", () => versionsHeld));
  renderApp(`/app/?item=${encodeURIComponent(id)}`);

  await expect(screen.findByText("This item no longer exists.", {}, { timeout: 500 })).rejects.toThrow();
  release();
  expect(await pane().findByText("Being captured…")).toBeInTheDocument();
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

const THOUGHT = item({
  id: "t1",
  media_type: "thought",
  original_url: null,
  title: "Soup plan",
  text: "Lentils on Monday",
});

test("Edit Thought starts from what is shown and saves a new version", async () => {
  const api = fakeApi({ items: [THOUGHT], tags: TAGS, versions: [version(THOUGHT, { title: "Soup plan", text: "Lentils on Monday" })] });
  await open("/app/?item=t1");

  await userEvent.click(pane().getByRole("button", { name: "More actions" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Edit Thought" }));
  const form = within(pane().getByRole("form", { name: "Edit Thought" }));
  expect(form.getByRole("textbox", { name: "Title (optional)" })).toHaveValue("Soup plan");
  const text = form.getByRole("textbox", { name: "Text" });
  expect(text).toHaveValue("Lentils on Monday");

  await userEvent.clear(text);
  await userEvent.type(text, "Lentils on Tuesday");
  await userEvent.click(form.getByRole("button", { name: "Save as new version" }));

  expect(await pane().findByText("Lentils on Tuesday")).toBeInTheDocument();
  expect(pane().queryByRole("form", { name: "Edit Thought" })).not.toBeInTheDocument();
  expect(pane().getByRole("status")).toHaveTextContent("Processing the new version.");
  expect(api.bodies).toEqual([
    { method: "PUT", path: "/thoughts/t1", body: { title: "Soup plan", text: "Lentils on Tuesday" } },
  ]);
});

test("a rejected Thought edit says why in the form", async () => {
  fakeApi({ items: [THOUGHT], tags: TAGS });
  await open("/app/?item=t1");

  await userEvent.click(pane().getByRole("button", { name: "More actions" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Edit Thought" }));
  const form = within(pane().getByRole("form", { name: "Edit Thought" }));
  await userEvent.clear(form.getByRole("textbox", { name: "Text" }));
  await userEvent.type(form.getByRole("textbox", { name: "Text" }), "   ");
  await userEvent.click(form.getByRole("button", { name: "Save as new version" }));

  expect(await form.findByRole("alert")).toHaveTextContent("Could not save it: a Thought needs some text");
});

test("Capture again fetches the article's page as a new version", async () => {
  const api = fakeApi({ items: [ARTICLE], tags: TAGS });
  await open();

  await userEvent.click(pane().getByRole("button", { name: "More actions" }));
  expect(screen.queryByRole("menuitem", { name: "Edit Thought" })).not.toBeInTheDocument();
  await userEvent.click(await screen.findByRole("menuitem", { name: "Capture again" }));

  expect(await pane().findByRole("status")).toHaveTextContent("Processing the new version.");
  expect(api.bodies).toEqual([
    { method: "POST", path: "/capture", body: { url: "https://www.example.com/a1", channel: "manual", note: "" } },
  ]);
});

test("a Thought whose current version failed offers Retry", async () => {
  const api = fakeApi({ items: [THOUGHT], tags: TAGS, versions: [version(THOUGHT, { status: "failed", error: "timeout" })] });
  await open("/app/?item=t1");

  expect(pane().getByRole("status")).toHaveTextContent("Not enriched");
  await userEvent.click(pane().getByRole("button", { name: "Retry" }));

  await waitFor(() => expect(pane().getByRole("status")).toHaveTextContent("Processing the new version."));
  expect(api.versions[0].status).toBe("pending");
});

test("a new Capture whose processing failed says so", async () => {
  const gone = item({ id: "c1", title: "" });
  fakeApi({ items: [], tags: TAGS, versions: [version(gone, { status: "failed", error: "no text in the page" })] });
  await open("/app/?item=c1").catch(() => {});

  expect(await pane().findByText("Capturing failed: no text in the page")).toBeInTheDocument();
});
