"use client";

import type { Route } from "next";
import type { ReactElement, ReactNode } from "react";
import {
  Dialog as RacDialog,
  DialogTrigger,
  Header,
  Menu as RacMenu,
  MenuItem as RacMenuItem,
  MenuSection as RacMenuSection,
  MenuTrigger,
  Popover as RacPopover,
  Separator,
  Text,
  type PopoverProps as RacPopoverProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { Icon, type IconName } from "./icon";

export type MenuAction = {
  id: string;
  label: string;
  icon?: IconName;
  /** Makes the item a link, navigated by the Next router. */
  href?: Route;
  onAction?: () => void;
  /** danger: ember text, for the destructive item (keep it last, after a separator). */
  tone?: "danger";
  isDisabled?: boolean;
  /** A second, quieter line. */
  description?: string;
};

export type MenuItem = MenuAction | { separator: true; id: string } | { section: string; id: string; items: MenuItem[] };

type Placement = RacPopoverProps["placement"];

function renderItem(item: MenuItem): ReactNode {
  if ("separator" in item) return <Separator key={item.id} className="lk-menu-sep" />;
  if ("section" in item) {
    return (
      <RacMenuSection key={item.id} id={item.id}>
        <Header className="lk-menu-header">{item.section}</Header>
        {item.items.map(renderItem)}
      </RacMenuSection>
    );
  }
  return (
    <RacMenuItem
      key={item.id}
      id={item.id}
      href={item.href}
      onAction={item.onAction}
      isDisabled={item.isDisabled}
      textValue={item.label}
      className={cx("lk-menu-item", item.tone === "danger" && "lk-menu-item-danger")}
    >
      {item.icon ? <Icon name={item.icon} /> : null}
      <span className="lk-menu-item-text">
        <Text slot="label">{item.label}</Text>
        {item.description ? (
          <Text slot="description" className="lk-menu-item-desc">
            {item.description}
          </Text>
        ) : null}
      </span>
    </RacMenuItem>
  );
}

export interface MenuProps {
  /** The control that opens the menu: a `Button` or `IconButton` from this library. */
  trigger: ReactElement;
  /** Names the menu for assistive technology ("Quotation actions"). */
  label: string;
  items: MenuItem[];
  placement?: Placement;
  className?: string;
}

/**
 * A menu of actions on a glass popover. Opens on press, Enter, Space or the arrow keys; arrows
 * and type-ahead move through the items; Escape closes and returns focus to the trigger.
 */
export function Menu({ trigger, label, items, placement = "bottom end", className }: MenuProps) {
  return (
    <MenuTrigger>
      {trigger}
      <RacPopover placement={placement} offset={6} className="lk-popover">
        <RacMenu aria-label={label} className={cx("lk-menu", className)}>
          {items.map(renderItem)}
        </RacMenu>
      </RacPopover>
    </MenuTrigger>
  );
}

export interface PopoverProps {
  /** The control that opens the popover: a `Button` or `IconButton` from this library. */
  trigger: ReactElement;
  /** Names the popover for assistive technology. */
  label: string;
  placement?: Placement;
  className?: string;
  /** The content, or a function that receives `close`. */
  children: ReactNode | ((close: () => void) => ReactNode);
}

/** The same glass surface for custom content (a filter form, a short explanation). */
export function Popover({ trigger, label, placement = "bottom start", className, children }: PopoverProps) {
  return (
    <DialogTrigger>
      {trigger}
      <RacPopover placement={placement} offset={6} className="lk-popover">
        <RacDialog aria-label={label} className={cx("lk-popover-dialog", className)}>
          {({ close }) => (typeof children === "function" ? children(close) : children)}
        </RacDialog>
      </RacPopover>
    </DialogTrigger>
  );
}
