// Console output helpers for scripts/dev.mjs.

const useColor = Boolean(process.stdout.isTTY) && !('NO_COLOR' in process.env);

const paint = (code) => (text) => (useColor ? `\x1b[${code}m${text}\x1b[0m` : String(text));
export const bold = paint('1');
export const dim = paint('2');
export const red = paint('31');
export const green = paint('32');
export const yellow = paint('33');
export const cyan = paint('36');
export const colorsEnabled = useColor;

export function info(message) {
  process.stdout.write(`${cyan('[dev]')} ${message}\n`);
}

export function warn(message) {
  process.stderr.write(`${yellow('[dev] warning:')} ${message}\n`);
}

export function fail(message) {
  process.stderr.write(`${red('[dev] error:')} ${message}\n`);
}

export function heading(title) {
  const line = '-'.repeat(Math.max(8, 72 - title.length - 4));
  process.stdout.write(`\n${bold(`-- ${title} ${line}`)}\n`);
}

export function seconds(ms) {
  return `${(ms / 1000).toFixed(1)}s`;
}

const STATUS_COLORS = { PASS: green, FAIL: red, MISSING: yellow, SKIPPED: dim };

/** Render rows of {name, status, ms, note} as an aligned summary table. */
export function summaryTable(title, rows) {
  const nameWidth = Math.max(4, ...rows.map((row) => row.name.length));
  const out = [`\n${bold(title)}`];
  out.push(`  ${'step'.padEnd(nameWidth)}  ${'status'.padEnd(7)}  ${'time'.padStart(7)}  note`);
  for (const row of rows) {
    const color = STATUS_COLORS[row.status] ?? ((text) => text);
    const time = row.ms === undefined ? '' : seconds(row.ms);
    out.push(`  ${row.name.padEnd(nameWidth)}  ${color(row.status.padEnd(7))}  ${time.padStart(7)}  ${row.note ?? ''}`);
  }
  process.stdout.write(`${out.join('\n')}\n`);
}
