/**
 * Server-render helper for component tests. Vitest runs in the node environment (no DOM
 * library is installed), so component tests assert on the HTML React produces: semantics,
 * accessible names, labels, ARIA state and which controls exist. Interaction tests belong to
 * Playwright (run by the integrator).
 */

import { QueryClient, QueryClientProvider, type QueryKey } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SessionProvider } from "@/lib/session/context";
import type { SessionBootstrap } from "@/lib/session/types";
import { testBootstrap } from "./session";

export function render(element: ReactElement): string {
  return renderToStaticMarkup(element);
}

export function renderInSession(element: ReactNode, bootstrap: SessionBootstrap = testBootstrap()): string {
  return renderToStaticMarkup(<SessionProvider bootstrap={bootstrap}>{element}</SessionProvider>);
}

/**
 * A query client for server-render tests: nothing fetches, and a seeded error is shown as is
 * (no optimistic refetch on mount), the way a page looks once a request has failed.
 */
export function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false, staleTime: Number.POSITIVE_INFINITY } } });
}

/** Puts a failed request into the cache (data already in it stays, as after a failed refresh). */
export function seedQueryError(client: QueryClient, queryKey: QueryKey, error: unknown): void {
  const query = client.getQueryCache().build(client, { queryKey });
  query.setState({ status: "error", error: error as Error, errorUpdatedAt: Date.now(), fetchStatus: "idle" });
}

/** Renders a page component inside a session and a seeded query client. */
export function renderWithQueries(
  element: ReactNode,
  seed: (client: QueryClient) => void,
  bootstrap: SessionBootstrap = testBootstrap(),
): string {
  const client = testQueryClient();
  seed(client);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <SessionProvider bootstrap={bootstrap}>{element}</SessionProvider>
    </QueryClientProvider>,
  );
}

const FOCUSABLE_TAG = /<(?:a|button|input|textarea|select)\b[^>]*>|<[a-z]+\b[^>]*\brole="(?:tab|tabpanel|menuitem|menuitemradio|menuitemcheckbox|option|gridcell|button|link|switch|checkbox|radio)"[^>]*>/g;

/**
 * Controls in rendered HTML that hide the browser's focus outline (`outline-hidden` or
 * `outline-none`) without putting a ring back (`focus-ring`, `focus-ring-inset`). Tailwind's
 * utilities layer outranks the global `:focus-visible` rule, so such a control would show no
 * focus at all. An empty list means keyboard focus stays visible.
 */
export function controlsWithoutVisibleFocus(html: string): string[] {
  const out: string[] = [];
  for (const [tag] of html.matchAll(FOCUSABLE_TAG)) {
    if (/\btype="hidden"/.test(tag)) continue;
    const classes = /\bclass="([^"]*)"/.exec(tag)?.[1] ?? "";
    if (/(^|\s)outline-(hidden|none)(\s|$)/.test(classes) && !/focus-ring/.test(classes)) out.push(tag);
  }
  return out;
}

/** Text content without tags or repeated whitespace, for readable assertions. */
export function textOf(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Interactive elements nested inside an <a> or <button> (invalid HTML that breaks hydration).
 * Returns the offending opening tags; an empty list means the markup is valid in this respect.
 */
export function nestedInteractive(html: string): string[] {
  const out: string[] = [];
  const stack: string[] = [];
  for (const match of html.matchAll(/<(\/?)(a|button)(\s[^>]*)?>/g)) {
    const [, closing, tag] = match;
    if (closing) {
      stack.pop();
      continue;
    }
    if (stack.length > 0) out.push(`<${tag}> inside <${stack[stack.length - 1]}>`);
    stack.push(tag!);
  }
  return out;
}

/** Counts elements matching a tag name, optionally with an attribute fragment such as `type="submit"`. */
export function countTags(html: string, tag: string, attributeFragment = ""): number {
  const pattern = new RegExp(`<${tag}(\\s[^>]*)?>`, "g");
  return [...html.matchAll(pattern)].filter((match) => match[0].includes(attributeFragment)).length;
}
