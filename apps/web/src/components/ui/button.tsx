"use client";

import { useId, type ReactNode } from "react";
import { Button as RacButton, type ButtonProps as RacButtonProps } from "react-aria-components";
import { buttonClasses, iconButtonClasses, type ButtonSize, type ButtonVariant } from "./styles";

/**
 * "No dead buttons" (frontend_verification §15): a button either does something when pressed
 * (`onPress`) or submits its form (`type="submit"`); links are `LinkButton`. A disabled button
 * must say why, and the reason becomes its accessible description.
 */
type ButtonAction =
  | { onPress: NonNullable<RacButtonProps["onPress"]>; type?: "button" }
  | { type: "submit"; onPress?: RacButtonProps["onPress"] };

type ButtonAvailability = { isDisabled?: false; disabledReason?: undefined } | { isDisabled: true; disabledReason: string };

type BaseProps = Omit<RacButtonProps, "onPress" | "type" | "isDisabled" | "className" | "children" | "style">;

export type ButtonProps = BaseProps &
  ButtonAction &
  ButtonAvailability & {
    variant?: ButtonVariant;
    size?: ButtonSize;
    /** Text shown while `isPending` (default: the normal label). Never a spinner. */
    pendingLabel?: string;
    /** Decorative leading icon. */
    icon?: ReactNode;
    className?: string;
    children: ReactNode;
  };

export function Button({
  variant = "secondary",
  size = "md",
  pendingLabel,
  icon,
  className,
  children,
  isDisabled,
  disabledReason,
  isPending,
  ...props
}: ButtonProps) {
  const reasonId = useId();
  const describedBy = [props["aria-describedby"], isDisabled ? reasonId : null].filter(Boolean).join(" ") || undefined;
  return (
    <>
      <RacButton
        {...props}
        isDisabled={isDisabled}
        isPending={isPending}
        aria-describedby={describedBy}
        className={buttonClasses(variant, size, className)}
      >
        {icon}
        <span>{isPending && pendingLabel ? pendingLabel : children}</span>
      </RacButton>
      {isDisabled ? (
        <span id={reasonId} className="sr-only">
          {disabledReason}
        </span>
      ) : null}
    </>
  );
}

export type IconButtonProps = BaseProps &
  ButtonAction &
  ButtonAvailability & {
    /** Accessible name; icon-only controls are otherwise unnamed. */
    label: string;
    variant?: "quiet" | "secondary";
    className?: string;
    children: ReactNode;
  };

/** Square 44 px (36 px with a mouse) icon control with a required accessible name. */
export function IconButton({ label, variant = "quiet", className, children, isDisabled, disabledReason, ...props }: IconButtonProps) {
  const reasonId = useId();
  return (
    <>
      <RacButton
        {...props}
        aria-label={label}
        isDisabled={isDisabled}
        aria-describedby={isDisabled ? reasonId : props["aria-describedby"]}
        className={iconButtonClasses(variant, className)}
      >
        {children}
      </RacButton>
      {isDisabled ? (
        <span id={reasonId} className="sr-only">
          {disabledReason}
        </span>
      ) : null}
    </>
  );
}
