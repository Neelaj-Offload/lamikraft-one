"use client";

import type { Route } from "next";
import NextLink from "next/link";
import type { AnchorHTMLAttributes, ReactNode, Ref } from "react";
import { ToggleButton, type ToggleButtonProps } from "react-aria-components";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { Icon, type IconName } from "./icon";

export interface ChipProps
  extends Omit<ToggleButtonProps, "className" | "style" | "children" | "render" | "isSelected" | "defaultSelected" | "onChange" | "id"> {
  /** Controlled state. Leave out (with `defaultSelected`) to let the chip keep its own. */
  selected?: boolean;
  defaultSelected?: boolean;
  onChange?: (next: boolean) => void;
  /** gold: a soft gold selected state for the one highlighted option; default is the ink pill. */
  tone?: "gold";
  icon?: IconName;
  /** A leading status dot in the chip's own colour. */
  dot?: boolean;
  className?: string;
  children: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

/** A toggle: on or off, announced as a pressed button. For filters that live in the URL use `ChipLink`. */
export function Chip({ selected, defaultSelected, onChange, tone, icon, dot = false, className, children, ...rest }: ChipProps) {
  return (
    <ToggleButton
      {...rest}
      isSelected={selected}
      defaultSelected={defaultSelected}
      onChange={onChange}
      className={cx("lk-chip", tone === "gold" && "lk-chip-gold", className)}
    >
      {dot ? <span className="lk-chip-dot" /> : null}
      {icon ? <Icon name={icon} size={14} /> : null}
      {children}
    </ToggleButton>
  );
}

export interface ChipLinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "className" | "children"> {
  href: Route;
  selected?: boolean;
  /** How many records the filter holds; a real count from the server, left out when unknown. */
  count?: number;
  icon?: IconName;
  /** Passed to the Next router: false keeps the scroll position when only the filter changes. */
  scroll?: boolean;
  className?: string;
  children: ReactNode;
  ref?: Ref<HTMLAnchorElement>;
}

/** A filter chip that is a link, so the filtered view is a URL: shareable and back-button safe. */
export function ChipLink({ href, selected = false, count, icon, className, children, ...rest }: ChipLinkProps) {
  return (
    <NextLink
      {...rest}
      href={href}
      aria-current={selected ? "true" : undefined}
      className={cx("lk-chip", selected && "lk-chip-selected", className)}
    >
      {icon ? <Icon name={icon} size={14} /> : null}
      {children}
      {count === undefined ? null : <span className="lk-chip-count">{formatCount(count)}</span>}
    </NextLink>
  );
}

export interface ChipGroupProps {
  /** Names the set for assistive technology ("Filter by status"). */
  label: string;
  className?: string;
  children: ReactNode;
}

/** A labelled row of chips: wraps on wide screens, scrolls sideways on phones. */
export function ChipGroup({ label, className, children }: ChipGroupProps) {
  return (
    <div role="group" aria-label={label} className={cx("lk-chip-group", className)}>
      {children}
    </div>
  );
}
