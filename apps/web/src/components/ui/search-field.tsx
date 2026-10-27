"use client";

import {
  Button as RacButton,
  Input,
  Label,
  SearchField as RacSearchField,
  type SearchFieldProps as RacSearchFieldProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { CloseIcon, SearchIcon } from "./icons";
import { inputClasses, labelClasses } from "./styles";

export type SearchFieldProps = Omit<RacSearchFieldProps, "className" | "children"> & {
  label: string;
  /** Keep the label for screen readers only (the field's purpose is obvious from context). */
  hideLabel?: boolean;
  placeholder?: string;
  className?: string;
};

export function SearchField({ label, hideLabel = false, placeholder, className, ...props }: SearchFieldProps) {
  return (
    <RacSearchField {...props} className={cx("group flex flex-col gap-1.5", className)}>
      <Label className={cx(labelClasses, hideLabel && "sr-only")}>{label}</Label>
      <div className="relative">
        <SearchIcon size={18} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-ink-muted" />
        <Input
          placeholder={placeholder}
          className={cx(inputClasses, "ps-10 pe-11 [&::-webkit-search-cancel-button]:hidden")}
        />
        <RacButton
          aria-label="Clear search"
          className="absolute inset-y-0 end-0 flex w-11 items-center justify-center rounded-e-md text-ink-muted hover:text-ink group-data-[empty]:hidden"
        >
          <CloseIcon size={16} />
        </RacButton>
      </div>
    </RacSearchField>
  );
}
