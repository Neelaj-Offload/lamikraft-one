/**
 * DecimalStr handling (docs/architecture/api-conventions.md §4).
 *
 * Money and quantities travel as strings matching `^-?\d{1,14}(\.\d{1,6})?$`. The client
 * validates and normalises what people type, and formats what the server sends, but never
 * turns either into a JavaScript number: `parseFloat`/`Number()` would lose precision beyond
 * 15-17 significant digits and invite client-side arithmetic.
 */

export const DECIMAL_STR_PATTERN = /^-?\d{1,14}(\.\d{1,6})?$/;

export function isDecimalStr(value: unknown): value is string {
  return typeof value === "string" && DECIMAL_STR_PATTERN.test(value);
}

/**
 * The same value without trailing fraction zeros ("240.000000" -> "240", "12.500" -> "12.5"): the
 * server keeps the column's scale, people edit the plain value. String work only, no arithmetic.
 */
export function trimDecimalStr(value: string): string {
  if (!value.includes(".")) return value;
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "-0" ? "0" : trimmed;
}

export interface DecimalInputRules {
  /** Fraction digits accepted (money entry: 4; integer UOMs: 0). At most 6. */
  maxFractionDigits?: number;
  allowNegative?: boolean;
}

export type DecimalInputResult =
  | { ok: true; value: string }
  | { ok: true; value: null }
  | { ok: false; reason: "invalid" | "too_many_integer_digits" | "too_many_fraction_digits" | "negative" };

/**
 * Normalises typed input into a DecimalStr: trims, removes digit-group separators
 * (`,`, spaces, the Indian `1,23,456` style), drops a leading `+`, strips redundant leading
 * zeros and a trailing bare `.`. An empty field is `null` (no value), not zero.
 */
export function normaliseDecimalInput(raw: string, rules: DecimalInputRules = {}): DecimalInputResult {
  const maxFraction = Math.min(Math.max(rules.maxFractionDigits ?? 6, 0), 6);
  let text = raw.trim().replace(/[\s,  ']/g, "");
  if (text === "") return { ok: true, value: null };
  if (text.startsWith("+")) text = text.slice(1);
  const negative = text.startsWith("-");
  if (negative) text = text.slice(1);
  if (text.endsWith(".")) text = text.slice(0, -1);
  if (text.startsWith(".")) text = `0${text}`;
  if (!/^\d+(\.\d+)?$/.test(text)) return { ok: false, reason: "invalid" };

  const [rawInteger = "", fraction = ""] = text.split(".");
  const integer = rawInteger.replace(/^0+(?=\d)/, "");
  if (integer.length > 14) return { ok: false, reason: "too_many_integer_digits" };
  if (fraction.length > maxFraction) return { ok: false, reason: "too_many_fraction_digits" };

  const isZero = /^0*$/.test(integer) && /^0*$/.test(fraction);
  if (negative && !isZero && !rules.allowNegative) return { ok: false, reason: "negative" };
  const sign = negative && !isZero ? "-" : "";
  return { ok: true, value: `${sign}${integer}${fraction ? `.${fraction}` : ""}` };
}

/** Compares two DecimalStr values by sign, length and digits; no float conversion. */
export function compareDecimalStr(a: string, b: string): -1 | 0 | 1 {
  if (!isDecimalStr(a) || !isDecimalStr(b)) throw new TypeError("compareDecimalStr needs DecimalStr values");
  const parse = (value: string) => {
    const negative = value.startsWith("-");
    const [integer = "0", fraction = ""] = (negative ? value.slice(1) : value).split(".");
    const int = integer.replace(/^0+(?=\d)/, "");
    const frac = fraction.replace(/0+$/, "");
    const zero = /^0*$/.test(int) && frac === "";
    return { negative: negative && !zero, int, frac };
  };
  const x = parse(a);
  const y = parse(b);
  if (x.negative !== y.negative) return x.negative ? -1 : 1;
  const flip = x.negative ? -1 : 1;
  if (x.int.length !== y.int.length) return (x.int.length > y.int.length ? flip : -flip) as -1 | 1;
  if (x.int !== y.int) return (x.int > y.int ? flip : -flip) as -1 | 1;
  const width = Math.max(x.frac.length, y.frac.length);
  const fx = x.frac.padEnd(width, "0");
  const fy = y.frac.padEnd(width, "0");
  if (fx === fy) return 0;
  return (fx > fy ? flip : -flip) as -1 | 1;
}
