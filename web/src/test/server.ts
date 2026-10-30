import { setupServer } from "msw/node";

/** The mocked API; each test installs the handlers it needs with `server.use`. */
export const server = setupServer();
