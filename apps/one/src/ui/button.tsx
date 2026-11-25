"use client";

import type { Route } from "next";
import NextLink from "next/link";
import type { AnchorHTMLAttributes, ReactNode, Ref } from "react";
import { Button as RacButton, type ButtonProps as RacButtonProps } from "react-aria-components";
import { cx } from "@/lib/cx";
import { Icon, type IconName } from "./icon";
import { Tooltip, type TooltipProps } from "./tooltip";

export type ButtonVariant = "primary" | "inverse" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonLook {
  /** primary is the one gold action on a screen; inverse the ink pill; secondary is glass. */
  variant?: ButtonVariant;
  size?: ButtonSize;
  iconLeft?: IconName;
  iconRight?: IconName;
  className?: string;
  children?: ReactNode;
}

function buttonClass(variant: ButtonVariant, size: ButtonSize, loading: boolean, className?: string): string {
  return cx("lk-btn", `lk-btn-${variant}`, size !== "md" && `lk-btn-${size}`, loading && "lk-btn-loading", className);
}

function ButtonContent({ iconLeft, iconRight, children }: Pick<ButtonLook, "iconLeft" | "iconRight" | "children">) {
  return (
    <>
      {iconLeft ? <Icon name={iconLeft} className="lk-btn-icon" /> : null}
      {children}
      {iconRight ? <Icon name={iconRight} className="lk-btn-icon" /> : null}
    </>
  );
}

export interface ButtonProps
  extends Omit<RacButtonProps, "className" | "style" | "children" | "isPending" | "render">,
    ButtonLook {
  /**
   * Shows the spinner in place of the label, keeps the width, sets aria-busy and ignores presses
   * (the button stays focusable so focus is not lost while the request runs).
   */
  loading?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

/** A pill button. `type="submit"` submits its form; everything else acts through `onPress`. */
export function Button({
  variant = "primary",
  size = "md",
  iconLeft,
  iconRight,
  loading = false,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <RacButton
      {...rest}
      isPending={loading}
      className={buttonClass(variant, size, loading, className)}
      render={(domProps) => <button {...domProps} aria-busy={loading || undefined} />}
    >
      <ButtonContent iconLeft={iconLeft} iconRight={iconRight}>
        {children}
      </ButtonContent>
      {loading ? <span className="lk-sr-only">, in progress</span> : null}
    </RacButton>
  );
}

type AnchorRest = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "className" | "children">;

export type ButtonLinkProps = ButtonLook &
  AnchorRest & { ref?: Ref<HTMLAnchorElement> } & (
    | { /** An in-app route, navigated by the Next router. */ href: Route; external?: false }
    | { /** An absolute or download URL, rendered as a plain anchor. */ href: string; external: true }
  );

/** A navigation that looks like a button ("Open quotation", "Download PDF"). */
export function ButtonLink(props: ButtonLinkProps) {
  const { variant = "primary", size = "md", iconLeft, iconRight, className, children, external, href, ...rest } = props;
  const classes = buttonClass(variant, size, false, className);
  const content = (
    <ButtonContent iconLeft={iconLeft} iconRight={iconRight}>
      {children}
    </ButtonContent>
  );
  if (external) {
    const rel = rest.target === "_blank" ? (rest.rel ?? "noopener noreferrer") : rest.rel;
    return (
      <a {...rest} href={href} rel={rel} className={classes}>
        {content}
      </a>
    );
  }
  return (
    <NextLink {...rest} href={href as Route} className={classes}>
      {content}
    </NextLink>
  );
}

export type IconButtonVariant = "glass" | "ghost" | "inverse" | "primary";

interface IconButtonLook {
  icon: IconName;
  /** The accessible name, also shown as the tooltip. Required: the control has no visible text. */
  label: string;
  variant?: IconButtonVariant;
  size?: ButtonSize;
  /** A gold dot for "something new here". Say what in `label` ("Notifications, 3 unread"). */
  badge?: boolean;
  tooltipPlacement?: TooltipProps["placement"];
  className?: string;
}

function iconButtonClass(variant: IconButtonVariant, size: ButtonSize, className?: string): string {
  return cx("lk-iconbtn", variant !== "glass" && `lk-iconbtn-${variant}`, size !== "md" && `lk-iconbtn-${size}`, className);
}

function IconButtonContent({ icon, badge }: { icon: IconName; badge: boolean }) {
  return (
    <>
      <Icon name={icon} />
      {badge ? <span className="lk-iconbtn-badge" /> : null}
    </>
  );
}

export interface IconButtonProps
  extends Omit<RacButtonProps, "className" | "style" | "children" | "render" | "aria-label">,
    IconButtonLook {
  ref?: Ref<HTMLButtonElement>;
}

/** A round icon-only button with a required name and a tooltip showing it. */
export function IconButton({
  icon,
  label,
  variant = "glass",
  size = "md",
  badge = false,
  tooltipPlacement,
  className,
  ...rest
}: IconButtonProps) {
  return (
    <Tooltip text={label} placement={tooltipPlacement}>
      <RacButton {...rest} aria-label={label} className={iconButtonClass(variant, size, className)}>
        <IconButtonContent icon={icon} badge={badge} />
      </RacButton>
    </Tooltip>
  );
}

export interface IconButtonLinkProps extends Omit<AnchorRest, "aria-label">, IconButtonLook {
  href: Route;
  ref?: Ref<HTMLAnchorElement>;
}

/** The icon button as an in-app link. */
export function IconButtonLink({
  icon,
  label,
  variant = "glass",
  size = "md",
  badge = false,
  tooltipPlacement,
  className,
  href,
  ...rest
}: IconButtonLinkProps) {
  return (
    <Tooltip text={label} placement={tooltipPlacement} focusable>
      <NextLink {...rest} href={href} aria-label={label} className={iconButtonClass(variant, size, className)}>
        <IconButtonContent icon={icon} badge={badge} />
      </NextLink>
    </Tooltip>
  );
}
