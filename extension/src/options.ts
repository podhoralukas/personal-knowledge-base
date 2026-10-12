import { ApiError, checkConnection, normaliseServer } from "./api.ts";
import { loadSettings, saveSettings } from "./settings.ts";

const form = document.getElementById("options") as HTMLFormElement;
const server = document.getElementById("server") as HTMLInputElement;
const token = document.getElementById("token") as HTMLInputElement;
const status = document.getElementById("status")!;

async function init(): Promise<void> {
  const settings = await loadSettings();
  server.value = settings.server;
  token.value = settings.token;
}

form.onsubmit = async (event) => {
  event.preventDefault();
  let settings;
  try {
    settings = { server: normaliseServer(server.value), token: token.value.trim() };
  } catch (error) {
    show(error instanceof ApiError ? error.message : "That is not a valid server URL.", "error");
    return;
  }
  await saveSettings(settings);
  server.value = settings.server;
  try {
    await checkConnection(settings);
    show("Saved. Connected to the Knowledge Base.", "ok");
  } catch (error) {
    show(`Saved, but: ${error instanceof ApiError ? error.message : error}`, "error");
  }
};

function show(message: string, kind: "ok" | "error"): void {
  status.textContent = message;
  status.className = kind;
}

init();
