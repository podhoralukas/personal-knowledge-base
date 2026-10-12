import { ApiError, capture, getTags, type Settings } from "./api.ts";
import type { Extracted } from "./extract.ts";
import { loadSettings } from "./settings.ts";

const title = document.getElementById("title")!;
const button = document.getElementById("capture") as HTMLButtonElement;
const status = document.getElementById("status")!;
const tagPicker = document.getElementById("tags")!;
const tagList = document.getElementById("tag-list")!;
const openKb = document.getElementById("open-kb")!;
const note = document.getElementById("note") as HTMLTextAreaElement;

async function init(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  title.textContent = tab?.title ?? "";
  const settings = await loadSettings();
  linkTo(openKb, `${settings.server}/ui`);
  if (!settings.token) {
    show("Set the server and token in the options first.", "error");
    button.textContent = "Open options";
    button.onclick = () => chrome.runtime.openOptionsPage();
    return;
  }
  button.onclick = () => run(tab.id!);
  note.onkeydown = (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !button.disabled) run(tab.id!);
  };
  button.focus();
  showTags(settings);
}

/** Without the Taxonomy the popup still captures; the server then tags automatically. */
async function showTags(settings: Settings): Promise<void> {
  let paths: string[];
  try {
    paths = await getTags(settings);
  } catch {
    return;
  }
  for (const path of paths) {
    const label = tagList.appendChild(document.createElement("label"));
    label.style.setProperty("--depth", String(path.split("/").length - 1));
    label.title = path;
    const box = label.appendChild(document.createElement("input"));
    box.type = "checkbox";
    box.value = path;
    label.append(path.split("/").pop()!);
  }
  tagPicker.hidden = paths.length === 0;
}

function pickedTags(): string[] {
  return [...tagList.querySelectorAll<HTMLInputElement>("input:checked")].map((box) => box.value);
}

async function run(tabId: number): Promise<void> {
  button.disabled = true;
  show("Capturing…");
  try {
    const page = await extractFrom(tabId);
    const itemUrl = await capture(await loadSettings(), page, pickedTags(), note.value.trim());
    show(page.readable ? "Captured." : "Captured the whole page (no article found).", "ok");
    const link = status.appendChild(document.createElement("a"));
    link.textContent = " Open in Knowledge Base";
    linkTo(link, itemUrl);
  } catch (error) {
    show(error instanceof ApiError ? error.message : `Can't read this page: ${error}`, "error");
    button.disabled = false;
  }
}

async function extractFrom(tabId: number): Promise<Extracted> {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["page.js"] });
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => (globalThis as unknown as { kbExtract: () => Extracted }).kbExtract(),
  });
  return result.result as Extracted;
}

/** Opens in a new tab next to the current one and closes the popup. */
function linkTo(link: HTMLElement, url: string): void {
  link.setAttribute("href", url);
  link.onclick = (event) => {
    event.preventDefault();
    chrome.tabs.create({ url }).then(() => window.close());
  };
}

function show(message: string, kind: "ok" | "error" | "" = ""): void {
  status.textContent = message;
  status.className = kind;
}

init();
