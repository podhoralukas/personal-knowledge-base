import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import createClient from "openapi-fetch";
import { toast } from "sonner";
import type { components, paths } from "./schema";

type Schemas = components["schemas"];
export type Accepted = Schemas["Accepted"];
export type Item = Schemas["ItemView"];
export type Kind = Schemas["Kind"];
export type Tag = Schemas["Tag"];
export type Version = Schemas["Version"];

/** The JSON API, on the same origin as the app. The browser sends the login cookie along; the API accepts it
 * only together with this header, which another site cannot add without a CORS preflight the API refuses. */
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  headers: { "X-KB-CSRF": "1" },
  // Looked up per call, so a fetch replaced after this module loads (MSW in tests) is the one used.
  fetch: (request) => fetch(request),
});

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** The response's data, or an ApiError with the API's `detail`. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(result.response.status, detail(result.error) ?? `request failed (${result.response.status})`);
  }
  return result.data as T;
}

function detail(error: unknown): string | undefined {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg; // FastAPI's 422
  return undefined;
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** The query whose 401 shows the login form. */
export const SESSION_KEY = ["stats"];

declare module "@tanstack/react-query" {
  interface Register {
    /** `inlineError`: the form that made the change shows its error, so no toast. */
    mutationMeta: { inlineError?: boolean };
  }
}

/** A failed read is retried once, a 401 never: it needs a login, not another try. A 401 anywhere refreshes
 * the session query, so an expired login shows the login form; any other failed change is a toast, unless
 * its form shows the error itself. */
export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (isUnauthorized(error) && query.queryKey[0] !== SESSION_KEY[0]) loggedOut();
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (isUnauthorized(error)) loggedOut();
        else if (!mutation.meta?.inlineError) toast.error(error.message);
      },
    }),
    defaultOptions: { queries: { retry: (failures, error) => !isUnauthorized(error) && failures < 1 } },
  });
  const loggedOut = () => client.invalidateQueries({ queryKey: SESSION_KEY });
  return client;
}
