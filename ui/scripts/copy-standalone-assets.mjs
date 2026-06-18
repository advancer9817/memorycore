// Copy static assets into .next/standalone so `node .next/standalone/server.js` serves everything.
// Next.js standalone build omits .next/static and public/ — they must be copied manually.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

const standaloneDir = join(root, ".next", "standalone");
if (!existsSync(standaloneDir)) {
  console.error("[postbuild] .next/standalone not found — was `output: 'standalone'` set in next.config?");
  process.exit(1);
}

// .next/static -> .next/standalone/.next/static
const staticSrc = join(root, ".next", "static");
const staticDst = join(standaloneDir, ".next", "static");
if (existsSync(staticSrc)) {
  mkdirSync(dirname(staticDst), { recursive: true });
  cpSync(staticSrc, staticDst, { recursive: true });
  console.log("[postbuild] copied .next/static -> .next/standalone/.next/static");
}

// public -> .next/standalone/public
const publicSrc = join(root, "public");
const publicDst = join(standaloneDir, "public");
if (existsSync(publicSrc)) {
  cpSync(publicSrc, publicDst, { recursive: true });
  console.log("[postbuild] copied public -> .next/standalone/public");
}

console.log("[postbuild] standalone assets ready.");
