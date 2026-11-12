"use client";

import {
  Button as RacButton,
  ComboBox as RacComboBox,
  Input,
  ListBox,
  ListBoxItem,
  Popover,
  Select as RacSelect,
  SelectValue,
  Text,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { FieldLabel, FieldMessage, hasError, inputClass, type FieldChromeProps, type FieldSize } from "./field";
import { Icon, type IconName } from "./icon";

export interface SelectOption {
  value: string;
  label: string;
  /** A second, quieter line: a business key, a short explanation. */
  description?: string;
  icon?: IconName;
  isDisabled?: boolean;
}

export interface SelectProps extends FieldChromeProps {
  options: readonly SelectOption[];
  /** Controlled value; null shows the placeholder. Leave undefined (with `defaultValue`) for an uncontrolled field. */
  value?: string | null;
  defaultValue?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  size?: FieldSize;
  glass?: boolean;
  /** Submits the chosen value with a native form. */
  name?: string;
  className?: string;
}

function OptionBody({ label, description, icon }: { label: string; description?: string; icon?: IconName }) {
  return (
    <>
      {icon ? <Icon name={icon} size={16} /> : null}
      <span className="lk-option-text">
        <Text slot="label" className="lk-option-label">
          {label}
        </Text>
        {description ? (
          <Text slot="description" className="lk-option-desc">
            {description}
          </Text>
        ) : null}
      </span>
      {/* The tick marks the chosen option, so selection does not rest on weight or colour alone. */}
      <Icon name="check" size={16} className="lk-option-check" />
    </>
  );
}

/**
 * Choose one of a known, short list. A button opens a listbox in a popover: arrow keys move,
 * typing jumps to a match, Enter chooses, Escape closes.
 */
export function Select({
  label,
  optional,
  hideLabel,
  help,
  error,
  options,
  value,
  defaultValue,
  onChange,
  placeholder = "Select",
  isRequired,
  isDisabled,
  size = "md",
  glass,
  name,
  className,
}: SelectProps) {
  const invalid = hasError(error);
  return (
    <RacSelect
      value={value}
      defaultValue={defaultValue}
      onChange={(key) => {
        if (key !== null) onChange?.(String(key));
      }}
      placeholder={placeholder}
      isInvalid={invalid || undefined}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={isDisabled}
      name={name}
      className={cx("lk-field", className)}
    >
      <FieldLabel optional={optional} hidden={hideLabel}>
        {label}
      </FieldLabel>
      <RacButton className={cx(inputClass({ size, glass, invalid, disabled: isDisabled }), "lk-select")}>
        <SelectValue className="lk-select-value">
          {({ isPlaceholder, selectedText }) => (isPlaceholder ? placeholder : selectedText)}
        </SelectValue>
        <Icon name="chevronDown" />
      </RacButton>
      <FieldMessage help={help} error={error} />
      <Popover className="lk-picker-popover" offset={6}>
        <ListBox className="lk-listbox">
          {options.map((option) => (
            <ListBoxItem
              key={option.value}
              id={option.value}
              textValue={option.label}
              isDisabled={option.isDisabled}
              className="lk-option"
            >
              <OptionBody label={option.label} description={option.description} icon={option.icon} />
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </RacSelect>
  );
}

export interface ComboBoxItem {
  id: string;
  label: string;
  description?: string;
}

export interface ComboBoxProps extends FieldChromeProps {
  /** The matches for the current text, already filtered by the server. */
  items: readonly ComboBoxItem[];
  inputValue: string;
  onInputChange: (text: string) => void;
  selectedKey: string | null;
  onSelectionChange: (id: string | null) => void;
  /** A search is in flight: shows a busy mark, and a "Searching" row while there are no matches yet. */
  isLoading?: boolean;
  /** Shown when a search returned nothing. */
  emptyText?: string;
  placeholder?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  size?: FieldSize;
  glass?: boolean;
  name?: string;
  className?: string;
}

/**
 * A search picker for long or remote lists (customers, products). The caller owns the text and
 * the matches: fetch on `onInputChange`, pass the results as `items`.
 */
export function ComboBox({
  label,
  optional,
  hideLabel,
  help,
  error,
  items,
  inputValue,
  onInputChange,
  selectedKey,
  onSelectionChange,
  isLoading = false,
  emptyText = "No matches. Try a different spelling or fewer words.",
  placeholder,
  isRequired,
  isDisabled,
  size = "md",
  glass,
  name,
  className,
}: ComboBoxProps) {
  const invalid = hasError(error);
  const idle = inputValue.trim() === "";
  return (
    <RacComboBox<ComboBoxItem>
      items={items}
      inputValue={inputValue}
      onInputChange={onInputChange}
      selectedKey={selectedKey}
      onSelectionChange={(key) => onSelectionChange(key === null ? null : String(key))}
      allowsEmptyCollection
      menuTrigger="focus"
      isInvalid={invalid || undefined}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={isDisabled}
      name={name}
      className={cx("lk-field", className)}
    >
      <FieldLabel optional={optional} hidden={hideLabel}>
        {label}
      </FieldLabel>
      <div className={cx(inputClass({ size, glass, invalid, disabled: isDisabled }), "lk-combo")} aria-busy={isLoading || undefined}>
        <Input placeholder={placeholder} />
        <RacButton className="lk-combo-btn">
          {isLoading ? <span className="lk-input-spinner" aria-hidden="true" /> : <Icon name="chevronDown" />}
        </RacButton>
      </div>
      <FieldMessage help={help} error={error} />
      <Popover className="lk-picker-popover" offset={6}>
        <ListBox<ComboBoxItem>
          className="lk-listbox"
          renderEmptyState={() => (
            <div className="lk-option-status" role="status">
              {isLoading ? (
                <>
                  <span className="lk-input-spinner" aria-hidden="true" />
                  Searching
                </>
              ) : idle ? (
                "Type to search"
              ) : (
                emptyText
              )}
            </div>
          )}
        >
          {(item) => (
            <ListBoxItem id={item.id} textValue={item.label} className="lk-option">
              <OptionBody label={item.label} description={item.description} />
            </ListBoxItem>
          )}
        </ListBox>
      </Popover>
    </RacComboBox>
  );
}
