// Type-check and lint, reporting only the paths you own.
//
//   node scripts/check.mjs src/screens/sales "src/app/(app)/sales"
//   node scripts/check.mjs --all
//
// Runs `tsc --noEmit` for the whole app (incremental) and eslint on the given paths, then prints
// only the TypeScript errors under those paths plus a count of errors elsewhere. It takes the same
// machine-wide lock as scripts/shots.mjs, so heavy jobs never overlap (this machine is short on RAM).
import { spawnSync } from "node:child_process";
import { mkdirSync, rmSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(root, "..", "..");
const args = process.argv.slice(2);
const all = args.includes("--all");
const owned = args.filter((a) => !a.startsWith("--")).map((p) => p.replace(/\\/g, "/").replace(/^apps\/one\//, "").replace(/\/$/, ""));
if (!all && owned.length === 0) {
  console.error("usage: node scripts/check.mjs <path> [<path>…]   (paths relative to apps/one), or --all");
  process.exit(2);
}

const lockDir = join(homedir(), ".lamikraft-dev", "one-shots.lock");
async function lock() {
  mkdirSync(dirname(lockDir), { recursive: true });
  const started = Date.now();
  for (;;) {
    try {
      mkdirSync(lockDir);
      return;
    } catch {
      const age = Date.now() - statSync(lockDir).mtimeMs;
      if (age > 20 * 60_000) rmSync(lockDir, { recursive: true, force: true });
      else if (Date.now() - started > 30 * 60_000) throw new Error("another check or screenshot run has held the lock for 30 minutes");
      else await new Promise((r) => setTimeout(r, 3000));
    }
  }
}

const node = process.execPath;
await lock();
let failed = false;
try {
  const tsc = spawnSync(node, [join(repo, "node_modules", "typescript", "bin", "tsc"), "--noEmit", "-p", join(root, "tsconfig.json"), "--pretty", "false"], {
    cwd: root,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  const lines = `${tsc.stdout ?? ""}${tsc.stderr ?? ""}`.split(/\r?\n/).filter((line) => /error TS\d+/.test(line));
  const mine = all ? lines : lines.filter((line) => owned.some((p) => line.replace(/\\/g, "/").startsWith(p + "/") || line.replace(/\\/g, "/").startsWith(p + "(")));
  const elsewhere = lines.length - mine.length;
  console.log(`TypeScript: ${mine.length} error(s) in your paths${all ? "" : `, ${elsewhere} elsewhere (not yours)`}`);
  for (const line of mine.slice(0, 80)) console.log("  " + line);
  if (mine.length > 80) console.log(`  … ${mine.length - 80} more`);
  if (mine.length > 0) failed = true;

  const targets = all ? ["src"] : owned;
  const eslint = spawnSync(node, [join(repo, "node_modules", "eslint", "bin", "eslint.js"), ...targets, "--no-warn-ignored"], {
    cwd: root,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  const lintOut = `${eslint.stdout ?? ""}${eslint.stderr ?? ""}`.trim();
  console.log(`ESLint: ${eslint.status === 0 ? "clean" : "problems"}`);
  if (eslint.status !== 0) {
    console.log(lintOut.split(/\r?\n/).slice(0, 80).join("\n"));
    failed = true;
  }
} finally {
  rmSync(lockDir, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
