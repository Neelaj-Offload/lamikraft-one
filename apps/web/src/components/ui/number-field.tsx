"use client";

import { useState, type ReactNode } from "react";
import { FieldError, Input, Label, Text, TextField as RacTextField } from "react-aria-components";
import { cx } from "@/lib/cx";
import { normaliseDecimalInput, type DecimalInputResult } from "@/lib/format/decimal";
import { formatMoney, formatQuantity } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { descriptionClasses, fieldErrorClasses, inputClasses, labelClasses } from "./styles";

export const DECIMAL_ERROR_TEXT: Record<Exclude<DecimalInputResult, { ok: true }>["reason"], string> = {
  invalid: "Enter a number, for example 240 or 24.50.",
  too_many_integer_digits: "This number is too large.",
  too_many_fraction_digits: "This has too many decimal places.",
  negative: "Enter a value of zero or more.",
};

export interface NumberFieldProps {
  label: string;
  /** The DecimalStr value (`"5760.00"`), or null when empty. Never a JavaScript number. */
  value: string | null;
  onChange: (value: string | null) => void;
  /** Money entry allows 4 places; integer UOMs (pcs, sheets, cartons) allow 0. */
  maxFractionDigits?: number;
  allowNegative?: boolean;
  /** Shows the formatted amount under the field. */
  currency?: string;
  /** Shows the formatted quantity under the field. */
  uom?: string;
  description?: ReactNode;
  /** A server-side message (422) for this field. */
  errorMessage?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  name?: string;
  className?: string;
}

/**
 * Decimal input for money and quantities (frontend_verification §11): a text input with
 * `inputMode="decimal"`, validated and normalised as a DecimalStr on blur. The React Aria
 * NumberField is deliberately not used here because it parses to a float.
 */
export function NumberField({
  label,
  value,
  onChange,
  maxFractionDigits = 4,
  allowNegative = false,
  currency,
  uom,
  description,
  errorMessage,
  isRequired,
  isDisabled,
  name,
  className,
}: NumberFieldProps) {
  const zone = useZone();
  const [draft, setDraft] = useState(value ?? "");
  const [syncedValue, setSyncedValue] = useState(value);
  const [localError, setLocalError] = useState<string | null>(null);

  if (value !== syncedValue) {
    // The parent changed the value (reset, server recalculation): show it.
    setSyncedValue(value);
    setDraft(value ?? "");
    setLocalError(null);
  }

  const commit = () => {
    const result = normaliseDecimalInput(draft, { maxFractionDigits, allowNegative });
    if (!result.ok) {
      setLocalError(DECIMAL_ERROR_TEXT[result.reason]);
      return;
    }
    if (result.value === null && isRequired) {
      setLocalError("Enter a value.");
      return;
    }
    setLocalError(null);
    setDraft(result.value ?? "");
    setSyncedValue(result.value);
    if (result.value !== value) onChange(result.value);
  };

  const preview =
    value === null
      ? null
      : currency
        ? formatMoney({ amount: value, currency }, { locale: zone.locale, maxFractionDigits })
        : uom
          ? formatQuantity({ value, uom }, { locale: zone.locale })
          : null;

  const message = localError ?? errorMessage;

  return (
    <RacTextField
      value={draft}
      onChange={setDraft}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
      inputMode={maxFractionDigits === 0 ? "numeric" : "decimal"}
      isInvalid={Boolean(message)}
      isRequired={isRequired}
      isDisabled={isDisabled}
      name={name}
      validationBehavior="aria"
      className={cx("flex flex-col gap-1.5", className)}
    >
      <Label className={labelClasses}>{label}</Label>
      <Input autoComplete="off" spellCheck={false} className={cx(inputClasses, "tabular text-end")} />
      {description || preview ? (
        <Text slot="description" className={descriptionClasses}>
          {description}
          {description && preview ? " · " : null}
          {preview ? <span className="tabular">{preview}</span> : null}
        </Text>
      ) : null}
      <FieldError className={fieldErrorClasses}>{message}</FieldError>
    </RacTextField>
  );
}
