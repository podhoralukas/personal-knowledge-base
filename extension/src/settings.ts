import type { Settings } from "./api.ts";

const DEFAULT_SERVER = "http://localhost:8000";

export async function loadSettings(): Promise<Settings> {
  const stored = await chrome.storage.local.get(["server", "token"]);
  return { server: (stored.server as string) || DEFAULT_SERVER, token: (stored.token as string) || "" };
}

export async function saveSettings(settings: Settings): Promise<void> {
  await chrome.storage.local.set(settings);
}
