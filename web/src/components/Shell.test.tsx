import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import { rangeDates } from "@/lib/dates";
import { fakeApi, item, lastListQuery, tag } from "@/test/fakeApi";
import { renderApp } from "@/test/render";
import { setViewport } from "@/test/viewport";

const TAGS = [tag("news", "General news"), tag("news/sport"), tag("news/sport/formula1"), tag("ai")];
const ITEMS = [
  item({
    id: "f1",
    title: "Verstappen wins in Singapore",
    summary: "A first win at Marina Bay.",
    tags: ["news", "news/sport", "news/sport/formula1"],
    first_captured_at: "2026-10-12T09:00:00.000Z",
    annotations: { notes: "for the quiz", owner_tags: [], rejected_tags: [] },
  }),
  item({
    id: "thought:1",
    media_type: "thought",
    original_url: null,
    title: "Soup ideas",
    text: "Lentils, then more lentils.",
    first_captured_at: "2026-10-27T10:00:00.000Z",
  }),
  item({ id: "ai1", title: "Agents in practice", summary: "Tools.", tags: ["ai"], first_captured_at: "2026-10-20T10:00:00.000Z" }),
];

const list = () => within(screen.getByRole("list", { name: "Items" }));
const titles = () => list().getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
const pane = () => within(screen.getByRole("region", { name: "Selected item" }));
/** The three panes, once the app has loaded. */
const shown = () => screen.findByRole("region", { name: "Selected item" });

describe("the Item list", () => {
  test("shows every Item newest first, with the first one open", async () => {
    fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();

    await shown();
    await waitFor(() => expect(titles()).toEqual(["Soup ideas", "Agents in practice", "Verstappen wins in Singapore"]));
    expect(screen.getByText("3 items")).toBeInTheDocument();
    expect(screen.getByText("newest first")).toBeInTheDocument();
    expect(await pane().findByRole("heading", { name: "Soup ideas", level: 1 })).toBeInTheDocument();
    expect(window.location.search).toBe("?item=thought%3A1");
  });

  test("a row shows the site, the note mark and only the most specific Tags", async () => {
    fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    const row = within((await screen.findByRole("heading", { name: "Verstappen wins in Singapore", level: 3 })).closest("li")!);

    expect(row.getByText("example.com")).toBeInTheDocument();
    expect(row.getByText("✎ note")).toBeInTheDocument();
    expect(row.getAllByRole("button").map((b) => b.textContent)).toEqual(["news/sport/formula1"]);
  });

  test("a Tag in the tree filters the list, sub-tags included, until cleared", async () => {
    const api = fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    const tree = within(await screen.findByRole("list", { name: "Tags" }));

    await userEvent.click(await tree.findByRole("button", { name: /^news\s*1$/ }));
    await waitFor(() => expect(titles()).toEqual(["Verstappen wins in Singapore"]));
    expect(lastListQuery(api.requests)?.get("tag")).toBe("news");
    expect(window.location.search).toContain("tag=news");

    await userEvent.click(screen.getByRole("button", { name: "Clear tag filter" }));
    await waitFor(() => expect(titles()).toHaveLength(3));
  });

  test("a Tag pill on a row filters by that Tag", async () => {
    fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    await screen.findByText("3 items");
    await userEvent.click(list().getByRole("button", { name: "ai" }));
    await waitFor(() => expect(titles()).toEqual(["Agents in practice"]));
  });

  test("Untagged lists the Items without Tags", async () => {
    fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: /^Untagged/ }));
    await waitFor(() => expect(titles()).toEqual(["Soup ideas"]));
  });

  test("Kind and the quick date ranges filter through the API", async () => {
    const api = fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    await screen.findByText("3 items");

    await userEvent.click(screen.getByRole("button", { name: "Thoughts" }));
    await waitFor(() => expect(titles()).toEqual(["Soup ideas"]));
    expect(lastListQuery(api.requests)?.get("kind")).toBe("thought");

    await userEvent.click(screen.getByRole("button", { name: "7 days" }));
    const { from, to } = rangeDates(7);
    await waitFor(() => expect(lastListQuery(api.requests)?.get("from")).toBe(from));
    expect(screen.getByLabelText("From")).toHaveValue(from);
    expect(screen.getByLabelText("To")).toHaveValue(to);
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(screen.getByRole("button", { name: "Any time" }));
    await waitFor(() => expect(lastListQuery(api.requests)?.has("from")).toBe(false));
  });

  test("typing a query searches, best match first; Escape clears it", async () => {
    const api = fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    await screen.findByText("3 items");

    await userEvent.type(screen.getByRole("searchbox", { name: "Search items" }), "lentils");
    await waitFor(() => expect(titles()).toEqual(["Soup ideas"]));
    expect(screen.getByText("best match first")).toBeInTheDocument();
    expect(api.requests.filter((u) => u.pathname === "/search")).toHaveLength(1); // once typing paused

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(titles()).toHaveLength(3));
  });

  test("filters and the open Item come back from the URL", async () => {
    fakeApi({ items: ITEMS, tags: TAGS });
    renderApp("/app/?tag=news&item=f1");
    await shown();
    expect(await pane().findByRole("heading", { name: "Verstappen wins in Singapore", level: 1 })).toBeInTheDocument();
    expect(titles()).toEqual(["Verstappen wins in Singapore"]);
  });
});

describe("keyboard", () => {
  test("j and k open the next and previous Item, / goes to search", async () => {
    fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    await shown();
    await pane().findByRole("heading", { name: "Soup ideas", level: 1 });

    await userEvent.keyboard("j");
    expect(await pane().findByRole("heading", { name: "Agents in practice", level: 1 })).toBeInTheDocument();
    await userEvent.keyboard("k");
    expect(await pane().findByRole("heading", { name: "Soup ideas", level: 1 })).toBeInTheDocument();

    await userEvent.keyboard("/");
    expect(screen.getByRole("searchbox", { name: "Search items" })).toHaveFocus();
  });
});

describe("narrower windows", () => {
  test("the Item opens in a drawer that Escape closes", async () => {
    setViewport(1000);
    fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    expect(screen.queryByRole("region", { name: "Selected item" })).not.toBeInTheDocument();

    await userEvent.click(await screen.findByRole("heading", { name: "Agents in practice", level: 3 }));
    const drawer = await screen.findByRole("dialog", { name: "Selected item" });
    expect(await within(drawer).findByRole("heading", { name: "Agents in practice", level: 1 })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  test("the sidebar is a drawer behind the menu button", async () => {
    setViewport(600);
    fakeApi({ items: ITEMS, tags: TAGS });
    renderApp();
    await screen.findByText("3 items");
    expect(screen.queryByRole("list", { name: "Tags" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show tags and filters" }));
    const drawer = await screen.findByRole("dialog", { name: "Tags and filters" });
    await userEvent.click(await within(drawer).findByRole("button", { name: /^ai\s*1$/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(titles()).toEqual(["Agents in practice"]));
  });
});
