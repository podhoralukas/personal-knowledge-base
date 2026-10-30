import { useSyncExternalStore } from "react";

/** The app's pages: the Items (three panes) at `/app/`, the Taxonomy editor at `/app/taxonomy`. */
export type Page = "items" | "taxonomy";

export function pageOf(pathname: string): Page {
  return /\/app\/taxonomy\/?$/.test(pathname) ? "taxonomy" : "items";
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

export function usePage(): Page {
  return pageOf(useSyncExternalStore(subscribe, () => window.location.pathname));
}

/** Goes to `to` (a path with an optional query) inside the app, a step Back can undo. Announced as a popstate,
 * which the page and the filters already listen to. */
export function navigate(to: string) {
  window.history.pushState(null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
