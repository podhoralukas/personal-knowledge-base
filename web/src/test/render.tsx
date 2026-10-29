import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createQueryClient } from "@/api/client";
import { App } from "@/App";

/** The whole app at `url`, with a fresh cache. */
export function renderApp(url = "/app/") {
  window.history.replaceState(null, "", url);
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <App />
    </QueryClientProvider>,
  );
}
