"use client";

import type { ReactNode } from "react";
import {
  FieldError,
  Input,
  Label,
  Text,
  TextArea as RacTextArea,
  TextField as RacTextField,
  type TextFieldProps as RacTextFieldProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { descriptionClasses, fieldErrorClasses, inputClasses, labelClasses } from "./styles";

export interface FieldChromeProps {
  /** Visible label; every field has one (placeholders are not labels). */
  label: string;
  description?: ReactNode;
  /** Shown when the field is invalid: a server 422 message or a client rule. */
  errorMessage?: string;
}

export type TextFieldProps = Omit<RacTextFieldProps, "className" | "children"> &
  FieldChromeProps & {
    placeholder?: string;
    className?: string;
    inputClassName?: string;
  };

export function TextField({ label, description, errorMessage, placeholder, className, inputClassName, ...props }: TextFieldProps) {
  return (
    <RacTextField {...props} className={cx("flex flex-col gap-1.5", className)}>
      <Label className={labelClasses}>{label}</Label>
      <Input placeholder={placeholder} className={cx(inputClasses, inputClassName)} />
      {description ? (
        <Text slot="description" className={descriptionClasses}>
          {description}
        </Text>
      ) : null}
      <FieldError className={fieldErrorClasses}>{errorMessage}</FieldError>
    </RacTextField>
  );
}

export type TextAreaProps = Omit<RacTextFieldProps, "className" | "children" | "type"> &
  FieldChromeProps & {
    placeholder?: string;
    rows?: number;
    className?: string;
  };

export function TextArea({ label, description, errorMessage, placeholder, rows = 3, className, ...props }: TextAreaProps) {
  return (
    <RacTextField {...props} className={cx("flex flex-col gap-1.5", className)}>
      <Label className={labelClasses}>{label}</Label>
      <RacTextArea placeholder={placeholder} rows={rows} className={cx(inputClasses, "py-2 leading-normal")} />
      {description ? (
        <Text slot="description" className={descriptionClasses}>
          {description}
        </Text>
      ) : null}
      <FieldError className={fieldErrorClasses}>{errorMessage}</FieldError>
    </RacTextField>
  );
}
