// Route scaffold for the rebuild.
//   node scripts/stubs.mjs            create a stub page for every route of apps/web that apps/one lacks
//   node scripts/stubs.mjs --check    list routes that still render the stub (exit 1 if any)
// The URL set is identical to apps/web so deep links, the route manifest and the API's links keep working.
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const oldApp = join(root, "..", "web", "src", "app");
const newApp = join(root, "src", "app");
const MARK = "LK-STUB";

function pages(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) pages(full, out);
    else if (name === "page.tsx") out.push(full);
  }
  return out;
}

/** apps/web groups its auth pages as (auth)/(centered)/x; apps/one has one (auth) layout. */
function mapSegments(rel) {
  return rel.split(sep).filter((segment) => segment !== "(centered)");
}

function urlOf(segments) {
  const parts = segments.slice(0, -1).filter((segment) => !(segment.startsWith("(") && segment.endsWith(")")));
  return "/" + parts.join("/");
}

if (process.argv.includes("--check")) {
  const left = pages(newApp).filter((file) => readFileSync(file, "utf8").includes(MARK));
  for (const file of left) console.log(urlOf(relative(newApp, file).split(sep)));
  console.log(left.length === 0 ? "No stub routes remain." : `${left.length} stub route(s) remain.`);
  process.exit(left.length === 0 ? 0 : 1);
}

let created = 0;
for (const file of pages(oldApp)) {
  const segments = mapSegments(relative(oldApp, file));
  const target = join(newApp, ...segments);
  if (existsSync(target)) continue;
  const url = urlOf(segments);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(
    target,
    `import { RouteStub } from "~/shell/route-stub";\n\n// ${MARK}: replace with the real screen.\nexport default function Page() {\n  return <RouteStub path="${url}" />;\n}\n`,
  );
  created += 1;
}
console.log(`created ${created} stub page(s)`);
