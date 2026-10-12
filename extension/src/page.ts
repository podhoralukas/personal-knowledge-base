// Injected into the tab on capture; the popup then calls kbExtract() in the same isolated world.
import { extract } from "./extract.ts";

(globalThis as { kbExtract?: () => ReturnType<typeof extract> }).kbExtract = () => extract(document, location.href);
