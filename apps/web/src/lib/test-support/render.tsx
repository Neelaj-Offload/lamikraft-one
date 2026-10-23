/**
 * Server-render helper for component tests. Vitest runs in the node environment (no DOM
 * library is installed), so component tests assert on the HTML React produces: semantics,
 * accessible names, labels, ARIA state and which controls exist. Interaction tests belong to
 * Playwright (run by the integrator).
 */

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
