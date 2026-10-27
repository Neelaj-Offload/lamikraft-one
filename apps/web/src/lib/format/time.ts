/**
 * Dates and times in the user's zone (frontend_verification §5 "Time"; api-conventions §14).
 *
 * Timestamps arrive as RFC 3339 UTC instants and are shown in the session's IANA `time_zone`,
 * never the browser's, so server and client render the same text and tests are deterministic.
 * Business dates (`YYYY-MM-DD`) are already local to the documented zone and are formatted as
 * calendar dates without any zone conversion. "Now" is passed in (from bootstrap `server_now`),
 * never read from the browser clock during render.
 */

export const DEFAULT_TIME_ZONE = "Asia/Kolkata";

export interface ZoneOptions {
  timeZone: string;
  locale: string;
}

const dtfCache = new Map<string, Intl.DateTimeFormat>();

function dtf(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let cached = dtfCache.get(key);
  if (!cached) {
    cached = new Intl.DateTimeFormat(locale, options);
    dtfCache.set(key, cached);
  }
  return cached;
}

/** Parses an RFC 3339 instant; null for anything else (never guesses a zone). */
export function parseInstant(iso: string | null | undefined): Date | null {
  if (typeof iso !== "string") return null;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.test(iso)) return null;
  const time = Date.parse(iso);
  return Number.isNaN(time) ? null : new Date(time);
}

/** Parses a business date `YYYY-MM-DD` into a UTC-midnight Date used only for formatting. */
export function parseBusinessDate(value: string | null | undefined): Date | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value ? null : date;
}

/** The calendar date (YYYY-MM-DD) of an instant in a zone. */
export function zonedDateKey(instant: Date, timeZone: string): string {
  const parts = dtf("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(instant);
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Whole calendar days from `now` to `instant` in the zone (0 today, 1 tomorrow, -1 yesterday). */
export function calendarDaysFrom(instant: Date, now: Date, timeZone: string): number {
  const a = Date.parse(`${zonedDateKey(instant, timeZone)}T00:00:00Z`);
  const b = Date.parse(`${zonedDateKey(now, timeZone)}T00:00:00Z`);
  return Math.round((a - b) / 86_400_000);
}

export function formatTime(instant: Date, { timeZone, locale }: ZoneOptions): string {
  return dtf(locale, { timeZone, hour: "numeric", minute: "2-digit" }).format(instant);
}

function capitalise(text: string, locale: string): string {
  return text.charAt(0).toLocaleUpperCase(locale) + text.slice(1);
}

/**
 * "Today, 5:00 PM", "Tomorrow, 10:00 AM", "Yesterday, 4:12 PM", "Mon 12 Oct, 8:15 AM",
 * or with the year when it differs from now's year.
 */
export function formatDayTime(iso: string, now: Date, zone: ZoneOptions): string | null {
  const instant = parseInstant(iso);
  if (!instant) return null;
  const days = calendarDaysFrom(instant, now, zone.timeZone);
  const time = formatTime(instant, zone);
  if (days >= -1 && days <= 1) {
    const word = new Intl.RelativeTimeFormat(zone.locale, { numeric: "auto" }).format(days, "day");
    return `${capitalise(word, zone.locale)}, ${time}`;
  }
  const sameYear = zonedDateKey(instant, zone.timeZone).slice(0, 4) === zonedDateKey(now, zone.timeZone).slice(0, 4);
  const date = dtf(zone.locale, {
    timeZone: zone.timeZone,
    weekday: sameYear ? "short" : undefined,
    day: "numeric",
    month: "short",
    year: sameYear ? undefined : "numeric",
  }).format(instant);
  return `${date}, ${time}`;
}

/** "Monday, 12 October" for an instant in the zone (greeting meta line). */
export function formatLongDate(instant: Date, zone: ZoneOptions): string {
  return dtf(zone.locale, { timeZone: zone.timeZone, weekday: "long", day: "numeric", month: "long" }).format(instant);
}

/** "12 Oct 2026" for an instant in the zone. */
export function formatDate(iso: string, zone: ZoneOptions): string | null {
  const instant = parseInstant(iso);
  if (!instant) return null;
  return dtf(zone.locale, { timeZone: zone.timeZone, day: "numeric", month: "short", year: "numeric" }).format(instant);
}

/** Business date `2026-10-12` → "12 Oct 2026" (or "Monday, 12 October" with `long`); no zone shift. */
export function formatBusinessDate(value: string, locale: string, style: "medium" | "long" = "medium"): string | null {
  const date = parseBusinessDate(value);
  if (!date) return null;
  const options: Intl.DateTimeFormatOptions =
    style === "long"
      ? { timeZone: "UTC", weekday: "long", day: "numeric", month: "long" }
      : { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" };
  return dtf(locale, options).format(date);
}

const RELATIVE_STEPS: ReadonlyArray<[Intl.RelativeTimeFormatUnit, number, number]> = [
  // unit, seconds per unit, use while |diff| is below this many seconds
  ["second", 1, 45],
  ["minute", 60, 45 * 60],
  ["hour", 3600, 22 * 3600],
  ["day", 86_400, 26 * 86_400],
  ["month", 2_592_000, 320 * 86_400],
  ["year", 31_536_000, Number.POSITIVE_INFINITY],
];

/** "5 minutes ago", "in 2 hours", "now"; for freshness labels, not for deadlines. */
export function formatRelative(iso: string, now: Date, locale: string): string | null {
  const instant = parseInstant(iso);
  if (!instant) return null;
  const seconds = (instant.getTime() - now.getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size, limit] of RELATIVE_STEPS) {
    if (Math.abs(seconds) < limit) {
      const value = unit === "second" ? 0 : Math.round(seconds / size);
      return rtf.format(value, unit);
    }
  }
  return null;
}
