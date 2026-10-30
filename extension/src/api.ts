import type { Extracted } from "./extract.ts";

export interface Settings {
  server: string;
  token: string;
}

export class ApiError extends Error {}

/** Send the page to POST /capture; returns the link that opens the Item. Picked `tags` replace the automatic tagging;
 * the `note` goes below the Item's Note. */
export async function capture(
  settings: Settings,
  page: Extracted,
  tags: string[] = [],
  note = "",
  now = new Date(),
): Promise<string> {
  const body = { url: page.url, content: page.html, captured_at: now.toISOString(), channel: "extension", tags, note };
  const response = await request(settings, "/capture", { method: "POST", body: JSON.stringify(body) });
  const { item_id } = (await response.json()) as { item_id: string };
  return `${settings.server}/open/items/${item_id}`;
}

/** Tag paths in tree order (parents before their children). */
export async function getTags(settings: Settings): Promise<string[]> {
  const response = await request(settings, "/taxonomy", { method: "GET" });
  const { tags } = (await response.json()) as { tags: { path: string }[] };
  const paths = tags.map((t) => t.path);
  return paths.sort((a, b) => compareSegments(a.split("/"), b.split("/")));
}

function compareSegments(a: string[], b: string[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  }
  return a.length - b.length;
}

/** Cheapest authenticated call, used by the options page. */
export async function checkConnection(settings: Settings): Promise<void> {
  await request(settings, "/taxonomy", { method: "GET" });
}

async function request(settings: Settings, path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${settings.server}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${settings.token}`, "Content-Type": "application/json" },
    });
  } catch {
    throw new ApiError(`Can't reach ${settings.server}. Is the app running?`);
  }
  if (response.status === 401) {
    throw new ApiError("The server rejected the token. Check it in the extension options.");
  }
  if (!response.ok) {
    throw new ApiError(`Failed: ${await detail(response)}`);
  }
  return response;
}

async function detail(response: Response): Promise<string> {
  try {
    const { detail } = (await response.json()) as { detail?: unknown };
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch {
    // not JSON
  }
  return `HTTP ${response.status}`;
}

export function normaliseServer(server: string): string {
  const url = new URL(server.trim());
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ApiError("The server URL must start with http:// or https://");
  }
  return url.origin + url.pathname.replace(/\/+$/, "");
}
