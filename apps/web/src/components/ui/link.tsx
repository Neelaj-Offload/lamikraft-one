"use client";

import type { ReactNode } from "react";
import { Link as RacLink, type LinkProps as RacLinkProps } from "react-aria-components";
import { cx } from "@/lib/cx";
import { buttonClasses, linkClasses, type ButtonSize, type ButtonVariant } from "./styles";

/**
 * In-app links go through React Aria's RouterProvider (set up in app/providers.tsx), so they
 * navigate with the Next router while rendering a real <a href> that works without JavaScript.
 */
export type LinkProps = Omit<RacLinkProps, "className" | "href" | "children"> & {
  href: string;
  className?: string;
  children: ReactNode;
};

export function Link({ className, ...props }: LinkProps) {
  return <RacLink {...props} className={cx(linkClasses, className)} />;
}

export type LinkButtonProps = LinkProps & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
};

/** A navigation that looks like a button (primary controls that open a record, "Review quote"). */
export function LinkButton({ variant = "secondary", size = "md", icon, className, children, ...props }: LinkButtonProps) {
  return (
    <RacLink {...props} className={buttonClasses(variant, size, cx("no-underline", className))}>
      {icon}
      <span>{children}</span>
    </RacLink>
  );
}
