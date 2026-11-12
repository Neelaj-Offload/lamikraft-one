import type { Route } from "next";
import NextLink from "next/link";
import type { AnchorHTMLAttributes, ReactNode, Ref } from "react";
import { cx } from "@/lib/cx";
import { Icon } from "./icon";

type AnchorRest = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "className" | "children">;

export interface TextLinkProps extends AnchorRest {
  href: Route;
  className?: string;
  children: ReactNode;
  ref?: Ref<HTMLAnchorElement>;
}

/** An in-app link in running text or a table cell: gold, underlined on hover. */
export function TextLink({ href, className, children, ...rest }: TextLinkProps) {
  return (
    <NextLink {...rest} href={href} className={cx("lk-link", className)}>
      {children}
    </NextLink>
  );
}

export interface ExternalLinkProps extends Omit<AnchorRest, "target"> {
  href: string;
  className?: string;
  children: ReactNode;
  ref?: Ref<HTMLAnchorElement>;
}

/** A link that leaves the app: opens a new tab and says so, to the eye and to a screen reader. */
export function ExternalLink({ href, className, children, rel = "noopener noreferrer", ...rest }: ExternalLinkProps) {
  return (
    <a {...rest} href={href} target="_blank" rel={rel} className={cx("lk-link lk-link-external", className)}>
      {children}
      <Icon name="external" size={14} />
      <span className="lk-sr-only"> (opens in a new tab)</span>
    </a>
  );
}
