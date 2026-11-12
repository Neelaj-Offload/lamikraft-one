// Screenshots of the running app, for visual review.
//
//   node scripts/shots.mjs --only /sales            every route under /sales, desktop + phone
//   node scripts/shots.mjs --only /sales/quotes,/sales/quotes/[quoteId] --out shots/quotes
//   node scripts/shots.mjs --url "/sales/parties?status=prospect" --widths 390
//   node scripts/shots.mjs --all --theme dark
//
// Options: --user SAHIL (demo person) · --widths 1440,390 · --theme light|dark · --out <dir>
//          --base http://127.0.0.1:3200 · --max-height 4200 · --public (include signed-out screens)
//
// Needs the web app on --base and the API behind it. Only one run at a time on this machine (a lock
// in ~/.lamikraft-dev), because each run starts a browser. Dynamic routes ([id]) are resolved by
// opening the nearest list screen and following the first matching link; anything it cannot
// resolve is listed in report.json so you can pass it with --url.
import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const flag = (name, fallback = null) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : fallback;
};
const BASE = String(flag("base", "http://127.0.0.1:3200")).replace(/\/+$/, "");
const USER = String(flag("user", "SAHIL"));
const WIDTHS = String(flag("widths", "1440,390")).split(",").map(Number).filter(Boolean);
const THEME = String(flag("theme", "light"));
const OUT = join(root, String(flag("out", "shots/latest")));
const MAX_H = Number(flag("max-height", 4200));
// Git Bash rewrites arguments that start with "/" into Windows paths ("/sales" becomes
// "C:/Program Files/Git/sales"). Undo that, and accept paths written without the leading slash.
const appPath = (value) => {
  const mangled = /^[A-Za-z]:[\\/].*?[\\/]Git[\\/](.*)$/.exec(value);
  const path = (mangled ? mangled[1] : value).replace(/\\/g, "/");
  return path.startsWith("/") ? path : `/${path}`;
};
const ONLY = flag("only") ? String(flag("only")).split(",").map((s) => s.trim()).filter(Boolean).map(appPath) : null;
const URLS = args.flatMap((a, i) => (a === "--url" && args[i + 1] ? [appPath(args[i + 1])] : []));
const BACKEND = process.env.LK_BACKEND_DIR ?? "D:/Lamikraft ERP/backend";

// ---- one run at a time ----
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
      else if (Date.now() - started > 30 * 60_000) throw new Error("another screenshot run has held the lock for 30 minutes");
      else await new Promise((r) => setTimeout(r, 4000));
    }
  }
}
const unlock = () => rmSync(lockDir, { recursive: true, force: true });

// ---- routes from the shared manifest ----
function manifest() {
  const src = readFileSync(join(root, "..", "web", "src", "lib", "routes.ts"), "utf8");
  const re = /path:\s*"([^"]+)",\s*label:\s*"([^"]+)",\s*area:\s*"([^"]+)"/g;
  const out = [];
  let m;
  while ((m = re.exec(src))) out.push({ path: m[1], label: m[2], area: m[3] });
  return out;
}
const patternToRegex = (pattern) => new RegExp("^" + pattern.replace(/\[[^\]]+\]/g, "[^/?#]+") + "$");
const slug = (url) => url.replace(/^\//, "").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "") || "home";

async function signIn(context) {
  const stateFile = join(root, "shots", `.auth-${USER}.json`);
  if (existsSync(stateFile)) {
    await context.addCookies(JSON.parse(readFileSync(stateFile, "utf8")).cookies ?? []);
    const ok = await context.request.get(`${BASE}/api/v1/session/bootstrap`);
    if (ok.status() === 200) return;
    await context.clearCookies();
  }
  const printed = execFileSync("uv", ["run", "--locked", "python", "-m", "app.cli", "demo", "sign-in-link", USER], {
    cwd: BACKEND,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  const token = /#t=([^\s"']+)/.exec(printed)?.[1];
  if (!token) throw new Error(`no sign-in link for ${USER}: ${printed.slice(0, 300)}`);
  const response = await context.request.post(`${BASE}/api/v1/identity/demo-sign-in`, {
    data: { token: decodeURIComponent(token) },
    headers: { Origin: BASE, "Content-Type": "application/json" },
  });
  if (!response.ok()) throw new Error(`demo sign-in failed: ${response.status()} ${await response.text()}`);
  mkdirSync(dirname(stateFile), { recursive: true });
  writeFileSync(stateFile, JSON.stringify(await context.storageState()));
}

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
  await page.waitForTimeout(900); // entrances are at most 480ms plus an 8 x 40ms stagger
}

async function resolveDynamic(page, pattern, cache) {
  const regex = patternToRegex(pattern);
  const staticPaths = cache.staticPaths;
  // Candidate list screens: the pattern's static prefix, then each shorter prefix that is a route.
  const prefix = pattern.slice(0, pattern.indexOf("[")).replace(/\/$/, "");
  const candidates = [];
  for (let p = prefix; p.length > 0; p = p.slice(0, p.lastIndexOf("/"))) if (staticPaths.has(p)) candidates.push(p);
  for (const candidate of candidates) {
    if (!cache.links.has(candidate)) {
      await page.goto(BASE + candidate, { waitUntil: "domcontentloaded" }).catch(() => {});
      await settle(page);
      const hrefs = await page.$$eval("a[href]", (as) => as.map((a) => a.getAttribute("href")));
      cache.links.set(candidate, hrefs.filter(Boolean).map((h) => h.split("#")[0]));
    }
    const hit = cache.links.get(candidate).find((href) => regex.test(href.split("?")[0]));
    if (hit) return hit;
  }
  return null;
}

async function main() {
  await lock();
  const report = { base: BASE, user: USER, theme: THEME, shots: [], unresolved: [], problems: [] };
  const browser = await chromium.launch();
  try {
    const all = manifest();
    const staticPaths = new Set(all.filter((r) => !r.path.includes("[")).map((r) => r.path));
    let wanted = all.filter((r) => (flag("public") ? true : r.area !== "auth")).filter((r) => r.path !== "/" && !r.path.startsWith("/r/"));
    if (ONLY) wanted = all.filter((r) => ONLY.some((o) => r.path === o || (!o.includes("[") && (r.path === o || r.path.startsWith(o + "/")))));
    if (!ONLY && !flag("all") && URLS.length > 0) wanted = [];
    if (!ONLY && !flag("all") && URLS.length === 0) throw new Error("pass --only <paths>, --url <url> or --all");

    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: THEME === "dark" ? "dark" : "light", reducedMotion: flag("reduced") ? "reduce" : "no-preference" });
    const needsAuth = wanted.some((r) => r.area !== "auth") || URLS.length > 0;
    if (needsAuth) await signIn(context);

    const finder = await context.newPage();
    const cache = { staticPaths, links: new Map() };
    const targets = [];
    for (const route of wanted) {
      if (!route.path.includes("[")) targets.push({ url: route.path, pattern: route.path });
      else {
        const url = await resolveDynamic(finder, route.path, cache);
        if (url) targets.push({ url, pattern: route.path });
        else report.unresolved.push(route.path);
      }
    }
    for (const url of URLS) targets.push({ url, pattern: url });
    await finder.close();

    mkdirSync(OUT, { recursive: true });
    for (const width of WIDTHS) {
      const page = await context.newPage();
      await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
      const noise = [];
      page.on("console", (msg) => msg.type() === "error" && noise.push(`console: ${msg.text().slice(0, 240)}`));
      page.on("pageerror", (err) => noise.push(`pageerror: ${String(err).slice(0, 240)}`));
      page.on("response", (res) => res.status() >= 400 && res.url().includes("/api/") && noise.push(`${res.status()} ${res.url().replace(BASE, "")}`));
      for (const target of targets) {
        noise.length = 0;
        const file = `${slug(target.pattern)}--${width}${THEME === "dark" ? "-dark" : ""}.png`;
        try {
          const response = await page.goto(BASE + target.url, { waitUntil: "domcontentloaded" });
          await settle(page);
          const full = await page.evaluate(() => document.documentElement.scrollHeight);
          const height = Math.min(full, MAX_H);
          if (flag("slice")) {
            // Tall pages as consecutive 1500px slices (…--1440-p1.png, -p2.png) so details stay legible.
            const step = 1500;
            for (let y = 0, n = 1; y < Math.min(full, 15000); y += step, n += 1) {
              await page.screenshot({ path: join(OUT, file.replace(/\.png$/, `-p${n}.png`)), clip: { x: 0, y, width, height: Math.min(step, full - y) }, fullPage: true, animations: "disabled" });
            }
          } else {
            await page.screenshot({ path: join(OUT, file), clip: { x: 0, y: 0, width, height }, fullPage: true, animations: "disabled" });
          }
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
          report.shots.push({ url: target.url, pattern: target.pattern, width, file, status: response?.status() ?? null, horizontalOverflowPx: Math.max(0, overflow) });
          if (noise.length > 0 || overflow > 1) report.problems.push({ url: target.url, width, overflowPx: Math.max(0, overflow), noise: [...new Set(noise)].slice(0, 8) });
        } catch (error) {
          report.problems.push({ url: target.url, width, noise: [`navigation failed: ${String(error).slice(0, 200)}`] });
        }
      }
      await page.close();
    }
    writeFileSync(join(OUT, "report.json"), JSON.stringify(report, null, 2));
    console.log(`${report.shots.length} screenshot(s) in ${OUT}`);
    if (report.unresolved.length) console.log(`unresolved dynamic routes (${report.unresolved.length}):\n  ${report.unresolved.join("\n  ")}`);
    if (report.problems.length) {
      console.log(`problems (${report.problems.length}):`);
      for (const p of report.problems) console.log(`  ${p.url} @${p.width}${p.overflowPx > 1 ? ` overflow ${p.overflowPx}px` : ""}${p.noise.length ? `\n    ${p.noise.join("\n    ")}` : ""}`);
    }
  } finally {
    await browser.close();
    unlock();
  }
}

main().catch((error) => {
  unlock();
  console.error(String(error?.stack ?? error));
  process.exit(1);
});
