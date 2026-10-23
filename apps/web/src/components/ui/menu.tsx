"use client";

import type { ReactNode } from "react";
import {
  Header,
  Menu as RacMenu,
  MenuItem as RacMenuItem,
  MenuSection as RacMenuSection,
  MenuTrigger,
  Popover as RacPopover,
  Separator,
  type MenuItemProps as RacMenuItemProps,
  type MenuProps as RacMenuProps,
  type PopoverProps as RacPopoverProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { CheckIcon } from "./icons";
import { listItemClasses, popoverClasses, sectionLabelClasses } from "./styles";

export { MenuTrigger };

export type PopoverProps = Omit<RacPopoverProps, "className"> & { className?: string };

export function Popover({ className, offset = 4, ...props }: PopoverProps) {
  return <RacPopover {...props} offset={offset} className={cx(popoverClasses, className)} />;
}

export type MenuProps<T extends object> = Omit<RacMenuProps<T>, "className"> & { className?: string };

/** A menu of actions; place inside `<MenuTrigger>` after its trigger button. */
export function Menu<T extends object>({ className, ...props }: MenuProps<T>) {
  return (
    <Popover placement="bottom end" className="min-w-52">
      <RacMenu {...props} className={cx("max-h-[70dvh] outline-none", className)} />
    </Popover>
  );
}

export type MenuItemProps = Omit<RacMenuItemProps, "className" | "children"> & {
  children: ReactNode;
  icon?: ReactNode;
  /** Secondary text such as a keyboard shortcut or a count. */
  detail?: ReactNode;
  tone?: "default" | "danger";
};

export function MenuItem({ children, icon, detail, tone = "default", ...props }: MenuItemProps) {
  const textValue = props.textValue ?? (typeof children === "string" ? children : undefined);
  return (
    <RacMenuItem {...props} textValue={textValue} className={cx(listItemClasses, tone === "danger" && "text-danger")}>
      {({ isSelected, selectionMode }) => (
        <>
          {selectionMode !== "none" ? (
            <span className="flex w-4 shrink-0 justify-center" aria-hidden="true">
              {isSelected ? <CheckIcon size={16} /> : null}
            </span>
          ) : null}
          {icon ? (
            <span className="shrink-0 text-ink-muted" aria-hidden="true">
              {icon}
            </span>
          ) : null}
          <span className="flex-1 truncate">{children}</span>
          {detail ? <span className="ms-4 text-sm text-ink-muted">{detail}</span> : null}
        </>
      )}
    </RacMenuItem>
  );
}

export function MenuSection({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <RacMenuSection>
      {title ? <Header className={cx(sectionLabelClasses, "px-3 pt-2 pb-1")}>{title}</Header> : null}
      {children}
    </RacMenuSection>
  );
}

export function MenuSeparator() {
  return <Separator className="mx-2 my-1 border-t" />;
}
