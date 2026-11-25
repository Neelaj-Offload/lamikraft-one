"use client";

import { useLayoutEffect, useRef, type ReactNode, type Ref } from "react";
import {
  Input,
  TextArea as RacTextArea,
  TextField as RacTextField,
  type TextFieldProps as RacTextFieldProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { FieldLabel, FieldMessage, focusFieldControl, hasError, inputClass, type FieldChromeProps, type FieldSize } from "./field";
import { Icon, type IconName } from "./icon";

type SharedFieldProps = Pick<
  RacTextFieldProps,
  | "value"
  | "defaultValue"
  | "onChange"
  | "name"
  | "isRequired"
  | "isDisabled"
  | "isReadOnly"
  | "autoComplete"
  | "inputMode"
  | "maxLength"
  | "minLength"
  | "autoFocus"
  | "onBlur"
  | "onFocus"
  | "onKeyDown"
  | "id"
>;

export interface TextFieldProps extends FieldChromeProps, SharedFieldProps, Pick<RacTextFieldProps, "type" | "pattern"> {
  placeholder?: string;
  iconLeft?: IconName;
  /** Quiet text before the value: a currency code, a URL scheme. */
  prefix?: ReactNode;
  /** Quiet text or a small control after the value: a unit, a reveal button. */
  suffix?: ReactNode;
  size?: FieldSize;
  /** Frosted variant for fields that sit directly on the page ground or a hero. */
  glass?: boolean;
  className?: string;
  ref?: Ref<HTMLInputElement>;
}

/** A single-line text input with its label, optional affixes, help text and error. */
export function TextField({
  label,
  optional,
  hideLabel,
  help,
  error,
  placeholder,
  iconLeft,
  prefix,
  suffix,
  size = "md",
  glass,
  className,
  ref,
  ...field
}: TextFieldProps) {
  const invalid = hasError(error);
  return (
    <RacTextField {...field} isInvalid={invalid || undefined} validationBehavior="aria" className={cx("lk-field", className)}>
      <FieldLabel optional={optional} hidden={hideLabel}>
        {label}
      </FieldLabel>
      <div
        className={inputClass({ size, glass, invalid, disabled: field.isDisabled, readOnly: field.isReadOnly })}
        onMouseDown={focusFieldControl}
      >
        {iconLeft ? <Icon name={iconLeft} /> : null}
        {prefix ? <span className="lk-input-affix">{prefix}</span> : null}
        <Input ref={ref} placeholder={placeholder} />
        {suffix ? <span className="lk-input-affix">{suffix}</span> : null}
      </div>
      <FieldMessage help={help} error={error} />
    </RacTextField>
  );
}

export interface TextareaProps extends FieldChromeProps, SharedFieldProps {
  placeholder?: string;
  /** Rows shown when empty; the box then grows with its content up to 12 rows and scrolls after that. */
  rows?: number;
  glass?: boolean;
  className?: string;
}

const MAX_ROWS = 12;

function fitToContent(element: HTMLTextAreaElement) {
  const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight) || 22;
  const limit = lineHeight * MAX_ROWS;
  element.style.height = "auto";
  const wanted = element.scrollHeight;
  element.style.height = `${Math.min(wanted, limit)}px`;
  element.style.overflowY = wanted > limit ? "auto" : "hidden";
}

/** A multi-line text input that grows with what is typed, up to 12 rows. */
export function Textarea({
  label,
  optional,
  hideLabel,
  help,
  error,
  placeholder,
  rows = 3,
  glass,
  className,
  ...field
}: TextareaProps) {
  const invalid = hasError(error);
  const area = useRef<HTMLTextAreaElement>(null);
  const { value } = field;

  // Typing is handled by onInput; this covers the first paint and values set from outside.
  useLayoutEffect(() => {
    if (area.current) fitToContent(area.current);
  }, [value, rows]);

  return (
    <RacTextField {...field} isInvalid={invalid || undefined} validationBehavior="aria" className={cx("lk-field", className)}>
      <FieldLabel optional={optional} hidden={hideLabel}>
        {label}
      </FieldLabel>
      <div
        className={cx(
          inputClass({ glass, invalid, disabled: field.isDisabled, readOnly: field.isReadOnly }),
          "lk-textarea lk-textarea-auto",
        )}
        onMouseDown={focusFieldControl}
      >
        <RacTextArea
          ref={area}
          rows={rows}
          placeholder={placeholder}
          onInput={(event) => fitToContent(event.currentTarget)}
        />
      </div>
      <FieldMessage help={help} error={error} />
    </RacTextField>
  );
}
