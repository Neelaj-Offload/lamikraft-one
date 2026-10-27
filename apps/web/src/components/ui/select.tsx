"use client";

import type { Key } from "react-aria-components";
import {
  Button as RacButton,
  ComboBox as RacComboBox,
  FieldError,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Select as RacSelect,
  SelectValue,
  Text,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { ChevronDownIcon } from "./icons";
import {
  descriptionClasses,
  fieldErrorClasses,
  inputClasses,
  labelClasses,
  listItemClasses,
  popoverClasses,
} from "./styles";
import type { FieldChromeProps } from "./text-field";

export interface Option {
  id: string;
  label: string;
  /** Secondary text, e.g. a business key. */
  detail?: string;
  isDisabled?: boolean;
}

function OptionItem({ option }: { option: Option }) {
  return (
    <ListBoxItem id={option.id} textValue={option.label} isDisabled={option.isDisabled} className={listItemClasses}>
      <span className="truncate">{option.label}</span>
      {option.detail ? <span className="ms-auto font-mono text-xs text-ink-muted">{option.detail}</span> : null}
    </ListBoxItem>
  );
}

export interface SelectProps extends FieldChromeProps {
  options: readonly Option[];
  value: string | null;
  onChange: (value: string | null) => void;
  placeholder?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  isInvalid?: boolean;
  name?: string;
  className?: string;
}

export function Select({
  label,
  description,
  errorMessage,
  options,
  value,
  onChange,
  placeholder = "Choose…",
  className,
  ...props
}: SelectProps) {
  return (
    <RacSelect
      {...props}
      value={value}
      onChange={(key: Key | null) => onChange(key === null ? null : String(key))}
      placeholder={placeholder}
      isInvalid={props.isInvalid ?? Boolean(errorMessage)}
      className={cx("flex flex-col gap-1.5", className)}
    >
      <Label className={labelClasses}>{label}</Label>
      <RacButton className={cx(inputClasses, "flex items-center justify-between gap-2 text-start")}>
        <SelectValue className="truncate placeholder-shown:text-ink-muted" />
        <ChevronDownIcon size={18} className="shrink-0 text-ink-muted" />
      </RacButton>
      {description ? (
        <Text slot="description" className={descriptionClasses}>
          {description}
        </Text>
      ) : null}
      <FieldError className={fieldErrorClasses}>{errorMessage}</FieldError>
      <Popover className={popoverClasses} offset={4}>
        <ListBox className="max-h-72 outline-hidden" items={options}>
          {(option) => <OptionItem option={option} />}
        </ListBox>
      </Popover>
    </RacSelect>
  );
}

export interface ComboBoxProps extends FieldChromeProps {
  options: readonly Option[];
  value: string | null;
  onChange: (value: string | null) => void;
  /** Controlled text for server-side filtering; omit to filter `options` locally. */
  inputValue?: string;
  onInputChange?: (text: string) => void;
  placeholder?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  /** Message rendered inside the popover when nothing matches. */
  emptyText?: string;
  name?: string;
  className?: string;
}

export function ComboBox({
  label,
  description,
  errorMessage,
  options,
  value,
  onChange,
  inputValue,
  onInputChange,
  placeholder,
  emptyText = "No matches",
  className,
  ...props
}: ComboBoxProps) {
  return (
    <RacComboBox
      {...props}
      value={value}
      onChange={(key: Key | null) => onChange(key === null ? null : String(key))}
      {...(inputValue !== undefined ? { inputValue, onInputChange } : {})}
      {...(inputValue !== undefined ? { items: options } : { defaultItems: options })}
      isInvalid={Boolean(errorMessage)}
      allowsEmptyCollection
      className={cx("flex flex-col gap-1.5", className)}
    >
      <Label className={labelClasses}>{label}</Label>
      <div className="relative">
        <Input placeholder={placeholder} className={cx(inputClasses, "pe-11")} />
        <RacButton
          aria-label={`Show ${label} options`}
          className="absolute inset-y-0 end-0 flex w-11 items-center justify-center rounded-e-md text-ink-muted hover:text-ink"
        >
          <ChevronDownIcon size={18} />
        </RacButton>
      </div>
      {description ? (
        <Text slot="description" className={descriptionClasses}>
          {description}
        </Text>
      ) : null}
      <FieldError className={fieldErrorClasses}>{errorMessage}</FieldError>
      <Popover className={popoverClasses} offset={4}>
        <ListBox
          className="max-h-72 outline-hidden"
          renderEmptyState={() => <p className="px-3 py-2 text-sm text-ink-muted">{emptyText}</p>}
        >
          {(option: Option) => <OptionItem option={option} />}
        </ListBox>
      </Popover>
    </RacComboBox>
  );
}
