import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { fakeApi, item, tag } from "@/test/fakeApi";
import { renderApp } from "@/test/render";
import { setViewport } from "@/test/viewport";

const TAGS = [tag("ai"), tag("cooking")];
const OLD = item({ id: "a1", title: "An older article", first_captured_at: "2026-10-01T10:00:00.000Z" });

const pane = () => within(screen.getByRole("region", { name: "Selected item" }));
const list = () => within(screen.getByRole("list", { name: "Items" }));

async function openDialog() {
  renderApp();
  await screen.findByRole("heading", { name: "An older article", level: 1 });
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  return within(await screen.findByRole("dialog", { name: "Add to the knowledge base" }));
}

test("capturing a URL keeps the new Item open while it is processed, then lists it", async () => {
  const api = fakeApi({ items: [OLD], tags: TAGS });
  const dialog = await openDialog();

  await userEvent.type(dialog.getByRole("textbox", { name: "Page URL" }), "https://example.com/new");
  await userEvent.click(dialog.getByRole("button", { name: "Capture" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(api.bodies).toEqual([
    { method: "POST", path: "/capture", body: { url: "https://example.com/new", channel: "manual", note: "" } },
  ]);
  // Not in the list yet, and still open rather than replaced by the first listed Item.
  expect(await pane().findByText("Being captured…")).toBeInTheDocument();
  expect(window.location.search).toBe("?item=captured%3Ahttps%3A%2F%2Fexample.com%2Fnew");

  // The pipeline finishes: the next poll shows the Item, and the list picks it up.
  const id = "captured:https://example.com/new";
  api.items.push(item({ id, title: "The new article", original_url: "https://example.com/new" }));
  api.versions.find((v) => v.item_id === id)!.status = "enriched";
  expect(await pane().findByRole("heading", { name: "The new article", level: 1 }, { timeout: 4000 })).toBeInTheDocument();
  expect(await list().findByRole("heading", { name: "The new article", level: 3 })).toBeInTheDocument();
});

test("a failed capture says why in the dialog, without a toast, and keeps the URL", async () => {
  const api = fakeApi({ items: [OLD], tags: TAGS });
  const dialog = await openDialog();

  await userEvent.type(dialog.getByRole("textbox", { name: "Page URL" }), "https://unreachable.example/");
  await userEvent.click(dialog.getByRole("button", { name: "Capture" }));

  expect(await dialog.findByRole("alert")).toHaveTextContent("Could not capture it: fetch failed: timed out");
  expect(screen.getAllByText(/fetch failed/)).toHaveLength(1);
  expect(dialog.getByRole("textbox", { name: "Page URL" })).toHaveValue("https://unreachable.example/");
  expect(api.versions).toEqual([]);
});

test("writing a Thought with a picked Tag opens it", async () => {
  const api = fakeApi({ items: [OLD], tags: TAGS });
  const dialog = await openDialog();

  await userEvent.click(dialog.getByRole("tab", { name: "Write a Thought" }));
  await userEvent.type(dialog.getByRole("textbox", { name: "Text" }), "Lentil soup{Enter}with cumin");
  await userEvent.click(dialog.getByRole("checkbox", { name: "cooking" }));
  await userEvent.click(dialog.getByRole("button", { name: "Save Thought" }));

  expect(await pane().findByRole("heading", { name: "Lentil soup", level: 1 })).toBeInTheDocument();
  expect(pane().getByText(/Lentil soup\s+with cumin/)).toBeInTheDocument();
  expect(await list().findByRole("heading", { name: "Lentil soup", level: 3 })).toBeInTheDocument();
  const { body } = api.bodies[0] as { body: Record<string, unknown> };
  expect(body).toMatchObject({ title: "", text: "Lentil soup\nwith cumin", tags: ["cooking"] });
  expect(body.written_at).toEqual(expect.any(String));
});

test("what was typed survives closing the dialog", async () => {
  fakeApi({ items: [OLD], tags: TAGS });
  let dialog = await openDialog();

  await userEvent.click(dialog.getByRole("tab", { name: "Write a Thought" }));
  await userEvent.type(dialog.getByRole("textbox", { name: "Text" }), "Half a thought");
  await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  dialog = within(await screen.findByRole("dialog"));
  expect(dialog.getByRole("textbox", { name: "Text" })).toHaveValue("Half a thought");
});

test("on a narrow window the Add button keeps its name and the new Item opens in the drawer", async () => {
  setViewport(700);
  fakeApi({ items: [OLD], tags: TAGS });
  renderApp();
  await screen.findByRole("heading", { name: "An older article", level: 3 });

  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  const dialog = within(await screen.findByRole("dialog"));
  await userEvent.click(dialog.getByRole("tab", { name: "Write a Thought" }));
  await userEvent.type(dialog.getByRole("textbox", { name: "Title (optional)" }), "Groceries");
  await userEvent.type(dialog.getByRole("textbox", { name: "Text" }), "Lentils");
  await userEvent.click(dialog.getByRole("button", { name: "Save Thought" }));

  expect(await screen.findByRole("heading", { name: "Groceries", level: 1 })).toBeInTheDocument();
});
