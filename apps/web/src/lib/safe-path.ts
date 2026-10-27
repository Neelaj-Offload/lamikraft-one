/**
 * In-app link checks for every URL that comes from outside the bundle: server-supplied hrefs
 * (briefing sources and actions, Inbox items, search hits, Explain sources, action receipts)
 * and the `next` parameter of the sign-in page.
 *
 * A string that merely starts with "/" is not enough: browsers treat "/\host" (and
 * "/\t/host") like "//host", so `<a href="/\evil.example">` leaves the site. The check
 * resolves the value against a fixed origin and keeps it only if the origin is unchanged.
 */

const BASE = "http://lamikraft.invalid";

/**
 * Same-origin absolute path (`/sales/quotes/q1?tab=history#notes`), normalised by the URL
 * parser; null for anything else: absolute or protocol-relative URLs, "/\host", relative
 * paths, control characters, other schemes.
 */
export function safeAppPath(raw: unknown): string | null {
  if (typeof raw !== "string" || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return null;
  if (/[\u0000-\u001f\u007f]/.test(raw)) return null;
  let url: URL;
  try {
    url = new URL(raw, BASE);
  } catch {
    return null;
  }
  if (url.origin !== BASE) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * The `next` parameter for sign-in: an in-app path that is not the sign-in page itself, so a
 * crafted link cannot bounce the user to another site (or loop) after signing in.
 */
export function safeNextPath(raw: string | null | undefined): string | null {
  const path = safeAppPath(raw);
  if (path === null) return null;
  const pathname = path.split(/[?#]/, 1)[0]!;
  if (pathname === "/login" || pathname.startsWith("/login/")) return null;
  return path;
}
