"use client";

import type { ReactNode } from "react";
import {
  Checkbox as RacCheckbox,
  FieldError,
  Label,
  Radio,
  RadioGroup as RacRadioGroup,
  Switch as RacSwitch,
  Text,
  type CheckboxProps as RacCheckboxProps,
  type SwitchProps as RacSwitchProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { CheckIcon, MinusIcon } from "./icons";
import { descriptionClasses, fieldErrorClasses, labelClasses } from "./styles";

const boxClasses =
  "flex size-5 shrink-0 items-center justify-center rounded-xs border-2 border-border-strong bg-surface text-on-forest " +
  "transition-colors duration-150";

export type CheckboxProps = Omit<RacCheckboxProps, "className" | "children"> & {
  children?: ReactNode;
  className?: string;
};

/** 44 px hit area on touch; a label (visible children or aria-label) is required by usage. */
export function Checkbox({ children, className, ...props }: CheckboxProps) {
  return (
    <RacCheckbox
      {...props}
      className={cx("group inline-flex min-h-11 cursor-default items-center gap-3 text-[15px] text-ink pointer-fine:min-h-8", className)}
    >
      {({ isSelected, isIndeterminate }) => (
        <>
          <span
            aria-hidden="true"
            className={cx(
              boxClasses,
              (isSelected || isIndeterminate) && "border-forest bg-forest",
              "group-data-[focus-visible]:outline-2 group-data-[focus-visible]:outline-offset-2 group-data-[focus-visible]:outline-focus",
              "group-data-[invalid]:border-danger",
            )}
          >
            {isIndeterminate ? <MinusIcon size={14} strokeWidth={3} /> : isSelected ? <CheckIcon size={14} strokeWidth={3} /> : null}
          </span>
          {children}
        </>
      )}
    </RacCheckbox>
  );
}

export type SwitchProps = Omit<RacSwitchProps, "className" | "children"> & { children: ReactNode; className?: string };

export function Switch({ children, className, ...props }: SwitchProps) {
  return (
    <RacSwitch
      {...props}
      className={cx("group inline-flex min-h-11 cursor-default items-center gap-3 text-[15px] text-ink pointer-fine:min-h-8", className)}
    >
      <span
        aria-hidden="true"
        className={cx(
          "flex h-6 w-10 shrink-0 items-center rounded-full border-2 border-border-strong bg-surface-sunken px-0.5 transition-colors duration-150",
          "group-data-[selected]:border-forest group-data-[selected]:bg-forest",
          "group-data-[focus-visible]:outline-2 group-data-[focus-visible]:outline-offset-2 group-data-[focus-visible]:outline-focus",
          "group-data-[disabled]:opacity-55",
        )}
      >
        <span className="size-4 rounded-full bg-ink-muted transition-transform duration-150 group-data-[selected]:translate-x-4 group-data-[selected]:bg-on-forest rtl:group-data-[selected]:-translate-x-4" />
      </span>
      {children}
    </RacSwitch>
  );
}

export interface RadioOption {
  value: string;
  label: string;
  description?: string;
  isDisabled?: boolean;
}

export interface RadioGroupProps {
  label: string;
  options: readonly RadioOption[];
  value: string | null;
  onChange: (value: string) => void;
  description?: ReactNode;
  errorMessage?: string;
  orientation?: "vertical" | "horizontal";
  isRequired?: boolean;
  isDisabled?: boolean;
  name?: string;
  className?: string;
}

export function RadioGroup({
  label,
  options,
  value,
  onChange,
  description,
  errorMessage,
  orientation = "vertical",
  className,
  ...props
}: RadioGroupProps) {
  return (
    <RacRadioGroup
      {...props}
      value={value}
      onChange={onChange}
      orientation={orientation}
      isInvalid={Boolean(errorMessage)}
      className={cx("flex flex-col gap-1.5", className)}
    >
      <Label className={labelClasses}>{label}</Label>
      <div className={cx("flex gap-x-6", orientation === "vertical" ? "flex-col" : "flex-wrap")}>
        {options.map((option) => (
          <Radio
            key={option.value}
            value={option.value}
            isDisabled={option.isDisabled}
            className="group flex min-h-11 cursor-default items-start gap-3 py-2 text-[15px] text-ink pointer-fine:min-h-8"
          >
            <span
              aria-hidden="true"
              className={cx(
                "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border-2 border-border-strong bg-surface transition-colors duration-150",
                "group-data-[selected]:border-forest",
                "group-data-[focus-visible]:outline-2 group-data-[focus-visible]:outline-offset-2 group-data-[focus-visible]:outline-focus",
                "group-data-[disabled]:opacity-55",
              )}
            >
              <span className="size-2.5 scale-0 rounded-full bg-forest transition-transform duration-150 group-data-[selected]:scale-100" />
            </span>
            <span className="flex flex-col">
              <span>{option.label}</span>
              {option.description ? <span className={descriptionClasses}>{option.description}</span> : null}
            </span>
          </Radio>
        ))}
      </div>
      {description ? (
        <Text slot="description" className={descriptionClasses}>
          {description}
        </Text>
      ) : null}
      <FieldError className={fieldErrorClasses}>{errorMessage}</FieldError>
    </RacRadioGroup>
  );
}
