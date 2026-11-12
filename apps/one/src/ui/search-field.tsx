"use client";

import { useEffect, useRef } from "react";
import { Button as RacButton, Input, Label, SearchField as RacSearchField } from "react-aria-components";
import { cx } from "@/lib/cx";
import { focusFieldControl, type FieldSize } from "./field";
import { Icon } from "./icon";

export interface SearchFieldProps {
  /** Names the field for screen readers; it is not shown. */
  label: string;
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  /** Enter was pressed. */
  onSubmit?: (value: string) => void;
  placeholder?: string;
  /**
   * A single key that moves focus here from anywhere on the page (usually `"/"`), shown as a hint
   * while the field is empty. Off by default: give it to one search field per page.
   */
  shortcut?: string | false;
  glass?: boolean;
  size?: FieldSize;
  /** Results are loading: the magnifier becomes a busy mark. */
  isPending?: boolean;
  isDisabled?: boolean;
  name?: string;
  autoFocus?: boolean;
  className?: string;
}

/** The pill search input: magnifier, a clear button once there is text (Escape clears too), optional shortcut. */
export function SearchField({
  label,
  placeholder = "Search",
  shortcut = false,
  glass = true,
  size = "md",
  isPending = false,
  className,
  ...field
}: SearchFieldProps) {
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!shortcut) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.key !== shortcut || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      event.preventDefault();
      input.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [shortcut]);

  return (
    <RacSearchField {...field} className={cx("lk-search-field", className)}>
      <Label className="sr-only">{label}</Label>
      <div
        className={cx("lk-input lk-search", size !== "md" && `lk-input-${size}`, glass && "lk-input-glass")}
        onMouseDown={focusFieldControl}
        aria-busy={isPending || undefined}
      >
        {isPending ? <span className="lk-input-spinner" aria-hidden="true" /> : <Icon name="search" />}
        <Input ref={input} placeholder={placeholder} aria-keyshortcuts={shortcut || undefined} />
        <RacButton className="lk-search-clear">
          <Icon name="x" size={14} />
        </RacButton>
        {shortcut ? (
          <kbd className="lk-search-kbd" aria-hidden="true">
            {shortcut}
          </kbd>
        ) : null}
      </div>
    </RacSearchField>
  );
}
