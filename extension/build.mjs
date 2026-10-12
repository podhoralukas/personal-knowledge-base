import { cp } from "node:fs/promises";
import * as esbuild from "esbuild";

const options = {
  entryPoints: ["src/popup.ts", "src/options.ts", "src/page.ts"],
  bundle: true,
  format: "iife",
  target: ["chrome120", "firefox128"],
  outdir: "dist",
  logLevel: "info",
};

await cp("static", "dist", { recursive: true });
if (process.argv.includes("--watch")) {
  await (await esbuild.context(options)).watch();
} else {
  await esbuild.build(options);
}
