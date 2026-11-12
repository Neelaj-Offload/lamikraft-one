"use client";

import { useId, type MouseEvent, type ReactNode } from "react";
import { FieldError as RacFieldError, Label as RacLabel, Text } from "react-aria-components";
import { cx } from "@/lib/cx";
import { Icon } from "./icon";

/** Control heights: 32px dense, 40px default, 48px large. */
export type FieldSize = "sm" | "md" | "lg";

/**
 * What every labelled input shares: a visible label, an "Optional" marker, help text and an error.
 *
 * Validation is reported, not enforced by the browser: fields use React Aria's "aria" behaviour, so
 * `isRequired` announces the field as required and `error` marks it invalid, but neither blocks a
 * form submit. The screen (or the server's 422) decides what is wrong and passes it as `error`.
 */
export interface FieldChromeProps {
  /** Visible label; a placeholder is never the label. */
  label: string;
  /** Marks the field "Optional" beside its label. Required fields carry no marker. */
  optional?: boolean;
  /** Keeps the label for screen readers only, when a heading or column already names the field. */
  hideLabel?: boolean;
  help?: ReactNode;
  /** What went wrong and what to do about it. Replaces the help text while present. */
  error?: ReactNode;
}

/** True when an `error` prop holds something to show. */
export function hasError(error: ReactNode): boolean {
  return error !== undefined && error !== null && error !== false && error !== "";
}

/** The `lk-input` box classes for a size and state. */
export function inputClass(options: {
  size?: FieldSize;
  glass?: boolean;
  invalid?: boolean;
  disabled?: boolean;
  readOnly?: boolean;
}): string {
  const { size = "md", glass, invalid, disabled, readOnly } = options;
  return cx(
    "lk-input",
    size !== "md" && `lk-input-${size}`,
    glass && "lk-input-glass",
    invalid && "lk-input-invalid",
    disabled && "lk-input-disabled",
    readOnly && "lk-input-readonly",
  );
}

/** Pressing the padding, icon or affix of an `lk-input` box puts the caret in its input. */
export function focusFieldControl(event: MouseEvent<HTMLElement>) {
  const target = event.target as HTMLElement;
  if (target.closest("input, textarea, button, a, [role='button'], [role='spinbutton']")) return;
  const control = event.currentTarget.querySelector<HTMLElement>("input, textarea");
  if (!control) return;
  event.preventDefault();
  control.focus();
}

/** Label for a React Aria field (it is associated with the control by the surrounding field). */
export function FieldLabel({
  children,
  optional,
  hidden,
  className,
}: {
  children: ReactNode;
  optional?: boolean;
  hidden?: boolean;
  className?: string;
}) {
  return (
    <RacLabel className={cx("lk-field-label", hidden && "sr-only", className)}>
      <span>{children}</span>
      {optional ? <span className="lk-field-optional">Optional</span> : null}
    </RacLabel>
  );
}

/** Help text for a React Aria field. */
export function FieldHelp({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <Text slot="description" className={cx("lk-field-help", className)}>
      {children}
    </Text>
  );
}

/**
 * Error text for a React Aria field. Shows `children` when given, otherwise the field's own
 * validation message (a date outside its allowed range). Renders nothing while the field is valid.
 */
export function FieldErrorText({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <RacFieldError className={cx("lk-field-error", className)}>
      {({ validationErrors }) => (
        <>
          <Icon name="alert" size={14} />
          <span>{hasError(children) ? children : validationErrors.join(" ")}</span>
        </>
      )}
    </RacFieldError>
  );
}

/** The line under a React Aria control: the error when there is one, otherwise the help text. */
export function FieldMessage({ help, error }: { help?: ReactNode; error?: ReactNode }) {
  return (
    <>
      <FieldErrorText>{error}</FieldErrorText>
      {help && !hasError(error) ? <FieldHelp>{help}</FieldHelp> : null}
    </>
  );
}

export interface FieldShellProps extends FieldChromeProps {
  /** Id of the label element, for `aria-labelledby` on the control or group inside. */
  labelId: string;
  /** Id of the help or error line, for `aria-describedby`. */
  messageId: string;
  /** When the control is a single native element, its id: the label then points at it. */
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}

/**
 * The same label / control / message frame for controls that are not a single React Aria field
 * (a drop zone, a custom group). The caller wires `labelId` and `messageId` to the control.
 */
export function FieldShell({
  label,
  optional,
  hideLabel,
  help,
  error,
  labelId,
  messageId,
  htmlFor,
  children,
  className,
}: FieldShellProps) {
  const labelClass = cx("lk-field-label", hideLabel && "sr-only");
  const labelBody = (
    <>
      <span>{label}</span>
      {optional ? <span className="lk-field-optional">Optional</span> : null}
    </>
  );
  return (
    <div className={cx("lk-field", className)}>
      {htmlFor ? (
        <label id={labelId} htmlFor={htmlFor} className={labelClass}>
          {labelBody}
        </label>
      ) : (
        <span id={labelId} className={labelClass}>
          {labelBody}
        </span>
      )}
      {children}
      {hasError(error) ? (
        <div id={messageId} className="lk-field-error" role="alert">
          <Icon name="alert" size={14} />
          <span>{error}</span>
        </div>
      ) : help ? (
        <div id={messageId} className="lk-field-help">
          {help}
        </div>
      ) : null}
    </div>
  );
}

export interface FormSectionProps {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * One titled group of fields on a glass panel. Fields sit in a grid: one column on phones, two
 * from 768px. A child spans both columns with `className="col-span-full"`.
 */
export function FormSection({ title, description, children, className }: FormSectionProps) {
  const headingId = useId();
  return (
    <section className={cx("lk-glass lk-glass-pad-lg lk-form-section", className)} aria-labelledby={headingId}>
      <div className="lk-form-section-head">
        <h2 id={headingId} className="t-h3">
          {title}
        </h2>
        {description ? <p className="lk-form-section-desc t-body-sm">{description}</p> : null}
      </div>
      <div className="lk-form-grid">{children}</div>
    </section>
  );
}

export interface FormActionsProps {
  /** Buttons in reading order, the main action last. On phones they stack with the main action on top. */
  children: ReactNode;
  /** Quiet status text at the start of the bar ("Unsaved changes", "Saved 2 minutes ago"). */
  note?: ReactNode;
  className?: string;
}

/**
 * The form's action bar. It stays at the bottom of the viewport while the form scrolls, above the
 * phone dock and the safe-area inset. Set `--lk-form-actions-bottom` to move it.
 */
export function FormActions({ children, note, className }: FormActionsProps) {
  return (
    <div className={cx("lk-glass lk-glass-strong lk-form-actions", className)}>
      {note ? <div className="lk-form-actions-note">{note}</div> : null}
      {children}
    </div>
  );
}
