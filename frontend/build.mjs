// Production build: bundles src/ into dist/assets with esbuild.
//   npm run build          (one-off)
//   npm run dev            (watch mode; run the backend separately on :8000)
import { build, context } from "esbuild";
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const watch = process.argv.includes("--watch");
const out = "dist";
rmSync(out, { recursive: true, force: true });
mkdirSync(path.join(out, "assets"), { recursive: true });
copyFileSync("index.html", path.join(out, "index.html"));
// The server compares this with its own version and warns when an old interface build is being served.
const { version } = JSON.parse(readFileSync("package.json", "utf8"));
writeFileSync(path.join(out, "version.json"), JSON.stringify({ version }) + "\n");

// Allow building against a shared node_modules (EHMS_NODE_PATH) when packages are not installed locally.
const nodePaths = process.env.EHMS_NODE_PATH ? process.env.EHMS_NODE_PATH.split(path.delimiter) : [];
if (!existsSync("node_modules") && !nodePaths.length) console.warn("node_modules not found — run `npm install` first.");

const options = {
  entryPoints: { main: "src/main.tsx" },
  bundle: true,
  outdir: path.join(out, "assets"),
  format: "esm",
  target: ["es2020"],
  jsx: "automatic",
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production"), __APP_VERSION__: JSON.stringify(version) },
  nodePaths,
  logLevel: "info",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
} else {
  await build(options);
}
