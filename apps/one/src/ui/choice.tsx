"use client";

import type { ReactNode } from "react";
import {
  Checkbox as RacCheckbox,
  CheckboxGroup as RacCheckboxGroup,
  Label,
  Radio,
  RadioGroup as RacRadioGroup,
  Slider as RacSlider,
  SliderOutput,
  SliderThumb,
  SliderTrack,
  Switch as RacSwitch,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { FieldLabel, FieldMessage, hasError } from "./field";
import { Icon, type IconName } from "./icon";

function ChoiceText({ label, description }: { label: ReactNode; description?: ReactNode }) {
  if (!label && !description) return null;
  return (
    <span className="lk-check-text">
      <span>{label}</span>
      {description ? <span className="lk-check-desc">{description}</span> : null}
    </span>
  );
}

export interface CheckboxProps {
  label: ReactNode;
  description?: ReactNode;
  isSelected?: boolean;
  defaultSelected?: boolean;
  onChange?: (selected: boolean) => void;
  /** Some but not all of a set are selected: shows a dash and reports "mixed". */
  isIndeterminate?: boolean;
  isDisabled?: boolean;
  isInvalid?: boolean;
  name?: string;
  value?: string;
  /** Names the box when `label` is left empty (a row selector in a table). */
  "aria-label"?: string;
  className?: string;
}

export function Checkbox({ label, description, className, ...props }: CheckboxProps) {
  return (
    <RacCheckbox {...props} className={cx("lk-check", className)}>
      {({ isIndeterminate }) => (
        <>
          <span className="lk-check-box" aria-hidden="true">
            <Icon name={isIndeterminate ? "minus" : "check"} size={12} strokeWidth={2.5} />
          </span>
          <ChoiceText label={label} description={description} />
        </>
      )}
    </RacCheckbox>
  );
}

export interface ChoiceOption {
  value: string;
  label: ReactNode;
  description?: ReactNode;
  isDisabled?: boolean;
}

interface ChoiceGroupChrome {
  label: string;
  /** Keeps the group label for screen readers only. */
  hideLabel?: boolean;
  options: readonly ChoiceOption[];
  orientation?: "vertical" | "horizontal";
  help?: ReactNode;
  error?: ReactNode;
  isRequired?: boolean;
  isDisabled?: boolean;
  name?: string;
  className?: string;
}

export interface CheckboxGroupProps extends ChoiceGroupChrome {
  value?: string[];
  defaultValue?: string[];
  onChange?: (value: string[]) => void;
}

/** Choose any number of a few options. */
export function CheckboxGroup({
  label,
  hideLabel,
  options,
  orientation = "vertical",
  help,
  error,
  className,
  ...group
}: CheckboxGroupProps) {
  return (
    <RacCheckboxGroup {...group} isInvalid={hasError(error) || undefined} validationBehavior="aria" className={cx("lk-choice-group", className)}>
      <FieldLabel hidden={hideLabel}>{label}</FieldLabel>
      <div className="lk-choice-list" data-orientation={orientation}>
        {options.map((option) => (
          <Checkbox
            key={option.value}
            value={option.value}
            label={option.label}
            description={option.description}
            isDisabled={option.isDisabled}
          />
        ))}
      </div>
      <FieldMessage help={help} error={error} />
    </RacCheckboxGroup>
  );
}

export interface RadioGroupProps extends ChoiceGroupChrome {
  value?: string | null;
  defaultValue?: string;
  onChange?: (value: string) => void;
}

/** Choose exactly one of a few options. Arrow keys move the choice. */
export function RadioGroup({
  label,
  hideLabel,
  options,
  orientation = "vertical",
  help,
  error,
  className,
  ...group
}: RadioGroupProps) {
  return (
    <RacRadioGroup
      {...group}
      orientation={orientation}
      isInvalid={hasError(error) || undefined}
      validationBehavior="aria"
      className={cx("lk-choice-group", className)}
    >
      <FieldLabel hidden={hideLabel}>{label}</FieldLabel>
      <div className="lk-choice-list" data-orientation={orientation}>
        {options.map((option) => (
          <Radio key={option.value} value={option.value} isDisabled={option.isDisabled} className="lk-check lk-check-radio">
            <span className="lk-check-box" aria-hidden="true" />
            <ChoiceText label={option.label} description={option.description} />
          </Radio>
        ))}
      </div>
      <FieldMessage help={help} error={error} />
    </RacRadioGroup>
  );
}

export interface RadioCardOption extends ChoiceOption {
  icon?: IconName;
}

export interface RadioCardsProps extends Omit<RadioGroupProps, "options"> {
  options: readonly RadioCardOption[];
}

/**
 * The radio group for a step where one of a few important options is chosen: each option is a
 * glass tile that takes the gold glow when selected. Tiles sit side by side and wrap; pass
 * `orientation="vertical"` to stack them.
 */
export function RadioCards({
  label,
  hideLabel,
  options,
  orientation = "horizontal",
  help,
  error,
  className,
  ...group
}: RadioCardsProps) {
  return (
    <RacRadioGroup
      {...group}
      orientation={orientation}
      isInvalid={hasError(error) || undefined}
      validationBehavior="aria"
      className={cx("lk-choice-group", className)}
    >
      <FieldLabel hidden={hideLabel}>{label}</FieldLabel>
      <div className="lk-radio-cards" data-orientation={orientation}>
        {options.map((option) => (
          <Radio
            key={option.value}
            value={option.value}
            isDisabled={option.isDisabled}
            className={({ isSelected }) =>
              cx(
                "lk-glass lk-glass-pad-sm lk-glass-interactive lk-radio-card lk-check-radio",
                isSelected && "lk-glass-selected",
              )
            }
          >
            {option.icon ? <Icon name={option.icon} size={20} /> : null}
            <span className="lk-check-text">
              <span className="lk-radio-card-title">{option.label}</span>
              {option.description ? <span className="lk-check-desc">{option.description}</span> : null}
            </span>
            <span className="lk-check-box" aria-hidden="true" />
          </Radio>
        ))}
      </div>
      <FieldMessage help={help} error={error} />
    </RacRadioGroup>
  );
}

export interface SwitchProps {
  label: ReactNode;
  description?: ReactNode;
  isSelected?: boolean;
  defaultSelected?: boolean;
  onChange?: (selected: boolean) => void;
  /** Ink instead of gold when on, for switches that sit beside a gold action. */
  tone?: "inverse";
  isDisabled?: boolean;
  name?: string;
  value?: string;
  "aria-label"?: string;
  className?: string;
}

/** An on/off setting that takes effect at once. */
export function Switch({ label, description, tone, className, ...props }: SwitchProps) {
  return (
    <RacSwitch
      {...props}
      className={cx("lk-switch", tone === "inverse" && "lk-switch-inverse", description ? "lk-switch-described" : null, className)}
    >
      <span className="lk-switch-track" aria-hidden="true">
        <span className="lk-switch-thumb" />
      </span>
      {description ? <ChoiceText label={label} description={description} /> : label ? <span>{label}</span> : null}
    </RacSwitch>
  );
}

export interface SliderProps {
  label: string;
  /** Keeps the label for screen readers only. */
  hideLabel?: boolean;
  min?: number;
  max?: number;
  step?: number;
  value?: number;
  defaultValue?: number;
  onChange?: (value: number) => void;
  /** Called once when a drag or key press ends. */
  onChangeEnd?: (value: number) => void;
  /** Text for the value bubble ("40%", "12 sheets"). */
  format?: (value: number) => string;
  showValue?: boolean;
  isDisabled?: boolean;
  className?: string;
}

/** Pick a number in a range by dragging; arrow keys step, Home and End jump to the ends. */
export function Slider({
  label,
  hideLabel = false,
  min = 0,
  max = 100,
  step = 1,
  value,
  defaultValue = 50,
  onChange,
  onChangeEnd,
  format = (current) => String(current),
  showValue = true,
  isDisabled,
  className,
}: SliderProps) {
  return (
    <RacSlider<number>
      minValue={min}
      maxValue={max}
      step={step}
      value={value}
      defaultValue={value === undefined ? defaultValue : undefined}
      onChange={onChange}
      onChangeEnd={onChangeEnd}
      isDisabled={isDisabled}
      className={cx("lk-slider-field", showValue && "lk-slider-has-value", className)}
    >
      <Label className={cx("lk-field-label", hideLabel && "sr-only")}>{label}</Label>
      <SliderTrack className="lk-slider">
        {({ state }) => {
          const percent = `${state.getThumbPercent(0) * 100}%`;
          return (
            <>
              <span className="lk-slider-track" />
              <span className="lk-slider-fill" style={{ width: percent }} />
              <SliderThumb className="lk-slider-thumb" />
              {showValue ? (
                <SliderOutput className="lk-slider-value" style={{ left: percent }}>
                  {format(state.getThumbValue(0))}
                </SliderOutput>
              ) : null}
            </>
          );
        }}
      </SliderTrack>
    </RacSlider>
  );
}
