"use client";

import { useState, type ReactNode } from "react";
import {
  Button as RacButton,
  Group,
  Input,
  NumberField as RacNumberField,
  TextField as RacTextField,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { normaliseDecimalInput, type DecimalInputResult } from "@/lib/format/decimal";
import { FieldLabel, FieldMessage, focusFieldControl, hasError, inputClass, type FieldChromeProps, type FieldSize } from "./field";
import { Icon } from "./icon";

type DecimalProblem = Exclude<DecimalInputResult, { ok: true }>["reason"];

function decimalProblemText(reason: DecimalProblem, maxFractionDigits: number): string {
  switch (reason) {
    case "invalid":
      return "This is not a number. Enter digits only, for example 240 or 24.50.";
    case "too_many_integer_digits":
      return "This number is too large. Use at most 14 digits before the decimal point.";
    case "too_many_fraction_digits":
      return maxFractionDigits === 0
        ? "Decimals are not allowed here. Enter a whole number."
        : `Too many decimal places. Use at most ${maxFractionDigits}.`;
    case "negative":
      return "Negative values are not allowed here. Enter zero or more.";
  }
}

export interface DecimalFieldProps extends FieldChromeProps {
  /** A decimal string exactly as the API sends it (`"5760.00"`); `""` when empty. Never a JavaScript number. */
  value: string;
  /** Called with the normalised decimal string while the entry is valid, and `""` when cleared. */
  onChange: (value: string) => void;
  /** Money entry allows 4 places; whole-unit quantities (pcs, sheets) allow 0. At most 6. */
  maxFractionDigits?: number;
  allowNegative?: boolean;
  /** Quiet text before the value, usually the currency. */
  prefix?: ReactNode;
  /** Quiet text after the value, usually the unit. */
  suffix?: ReactNode;
  placeholder?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  isReadOnly?: boolean;
  size?: FieldSize;
  glass?: boolean;
  name?: string;
  className?: string;
}

/**
 * Decimal entry for money and quantities. The value stays a string end to end: what is typed is
 * validated and normalised with `normaliseDecimalInput`, never parsed to a float. Grouping
 * separators are accepted while typing and removed when the field loses focus.
 */
export function DecimalField({
  label,
  optional,
  hideLabel,
  help,
  error,
  value,
  onChange,
  maxFractionDigits = 4,
  allowNegative = false,
  prefix,
  suffix,
  placeholder,
  isRequired,
  isDisabled,
  isReadOnly,
  size = "md",
  glass,
  name,
  className,
}: DecimalFieldProps) {
  const [draft, setDraft] = useState(value);
  const [synced, setSynced] = useState(value);
  const [problem, setProblem] = useState<string | null>(null);

  if (value !== synced) {
    // The parent set a value this field did not type (a reset, a server recalculation): show it.
    setSynced(value);
    setDraft(value);
    setProblem(null);
  }

  const rules = { maxFractionDigits, allowNegative };

  const edit = (text: string) => {
    setDraft(text);
    const result = normaliseDecimalInput(text, rules);
    if (!result.ok) return;
    setProblem(null);
    const next = result.value ?? "";
    if (next !== value) {
      setSynced(next);
      onChange(next);
    }
  };

  const commit = () => {
    const result = normaliseDecimalInput(draft, rules);
    if (!result.ok) {
      setProblem(decimalProblemText(result.reason, maxFractionDigits));
      return;
    }
    setProblem(null);
    setDraft(result.value ?? "");
  };

  const message = problem ?? error;
  const invalid = hasError(message);

  return (
    <RacTextField
      value={draft}
      onChange={edit}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
      // The phone decimal keypad has no minus key, so signed fields get the full keyboard.
      inputMode={allowNegative ? "text" : maxFractionDigits === 0 ? "numeric" : "decimal"}
      autoComplete="off"
      isInvalid={invalid || undefined}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={isDisabled}
      isReadOnly={isReadOnly}
      name={name}
      className={cx("lk-field", className)}
    >
      <FieldLabel optional={optional} hidden={hideLabel}>
        {label}
      </FieldLabel>
      <div
        className={cx(inputClass({ size, glass, invalid, disabled: isDisabled, readOnly: isReadOnly }), "lk-input-num")}
        onMouseDown={focusFieldControl}
      >
        {prefix ? <span className="lk-input-affix">{prefix}</span> : null}
        <Input placeholder={placeholder} spellCheck={false} />
        {suffix ? <span className="lk-input-affix">{suffix}</span> : null}
      </div>
      <FieldMessage help={help} error={message} />
    </RacTextField>
  );
}

export interface IntegerFieldProps extends FieldChromeProps {
  /** A whole number, or null when empty. For counts and steps only, never money or measured quantities. */
  value: number | null;
  onChange: (value: number | null) => void;
  minValue?: number;
  maxValue?: number;
  step?: number;
  isRequired?: boolean;
  isDisabled?: boolean;
  isReadOnly?: boolean;
  size?: FieldSize;
  glass?: boolean;
  name?: string;
  className?: string;
}

const WHOLE_NUMBERS: Intl.NumberFormatOptions = { maximumFractionDigits: 0 };

/** Whole-number entry with minus and plus steppers (copies, cartons, days). Arrow keys step too. */
export function IntegerField({
  label,
  optional,
  hideLabel,
  help,
  error,
  value,
  onChange,
  minValue,
  maxValue,
  step = 1,
  isRequired,
  isDisabled,
  isReadOnly,
  size = "md",
  glass,
  name,
  className,
}: IntegerFieldProps) {
  const invalid = hasError(error);
  return (
    <RacNumberField
      value={value ?? Number.NaN}
      onChange={(next) => onChange(Number.isNaN(next) ? null : next)}
      minValue={minValue}
      maxValue={maxValue}
      step={step}
      formatOptions={WHOLE_NUMBERS}
      isInvalid={invalid || undefined}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={isDisabled}
      isReadOnly={isReadOnly}
      name={name}
      className={cx("lk-field", className)}
    >
      <FieldLabel optional={optional} hidden={hideLabel}>
        {label}
      </FieldLabel>
      <Group className={cx(inputClass({ size, glass, invalid, disabled: isDisabled, readOnly: isReadOnly }), "lk-stepper")}>
        <RacButton slot="decrement" className="lk-stepper-btn">
          <Icon name="minus" size={16} />
        </RacButton>
        <Input />
        <RacButton slot="increment" className="lk-stepper-btn">
          <Icon name="plus" size={16} />
        </RacButton>
      </Group>
      <FieldMessage help={help} error={error} />
    </RacNumberField>
  );
}
