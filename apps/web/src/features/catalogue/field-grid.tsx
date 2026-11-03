"use client";

import { TextArea, TextField } from "@/components/ui/text-field";
import { cx } from "@/lib/cx";
import type { FieldDef, FormValues } from "./form-model";

/**
 * A two-column grid of text inputs for a form section. Server field errors arrive keyed by dotted path; `errorPrefix`
 * maps a field to its path (``packaging.`` for the packaging section of a create form).
 */
export function FieldGrid({
  fields,
  values,
  onChange,
  errors,
  errorPrefix = "",
  valuePrefix = "",
  isDisabled = false,
}: {
  fields: readonly FieldDef[];
  values: FormValues;
  onChange: (name: string, value: string) => void;
  errors: Record<string, string>;
  errorPrefix?: string;
  valuePrefix?: string;
  isDisabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {fields.map((field) => {
        const key = `${valuePrefix}${field.name}`;
        const error = errors[`${errorPrefix}${field.name}`];
        const common = {
          label: field.label,
          description: field.description,
          value: values[key] ?? "",
          onChange: (v: string) => onChange(key, v),
          isInvalid: Boolean(error),
          errorMessage: error,
          isDisabled,
          name: key,
        };
        return field.kind === "textarea" ? (
          <TextArea key={key} {...common} className={cx(field.wide && "md:col-span-2")} />
        ) : (
          <TextField
            key={key}
            {...common}
            inputMode={field.kind === "integer" ? "numeric" : undefined}
            className={cx(field.wide && "md:col-span-2")}
          />
        );
      })}
    </div>
  );
}

/** Read-only key facts of a section (dash for blanks). */
export function FieldValues({ fields, values }: { fields: readonly FieldDef[]; values: FormValues }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 md:grid-cols-2">
      {fields.map((field) => (
        <div key={field.name} className={cx("flex flex-col gap-0.5", field.wide && "md:col-span-2")}>
          <dt className="text-xs font-semibold text-ink-muted">{field.label}</dt>
          <dd className="text-sm text-ink">{values[field.name]?.trim() ? values[field.name] : <span className="text-ink-muted">—</span>}</dd>
        </div>
      ))}
    </dl>
  );
}
