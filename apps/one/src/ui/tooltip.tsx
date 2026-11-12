"use client";

import type { DOMAttributes, ReactElement, ReactNode } from "react";
import {
  Focusable,
  OverlayArrow,
  Tooltip as RacTooltip,
  TooltipTrigger,
  type TooltipProps as RacTooltipProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";

export interface TooltipProps {
  text: ReactNode;
  /** A key hint shown after the text, e.g. "/" or "Ctrl K". */
  shortcut?: string;
  placement?: RacTooltipProps["placement"];
  /**
   * The trigger must be able to take focus. Buttons and icon buttons from this library already
   * can. Set this for anything else that renders a real focusable element and passes props and
   * `ref` through to it (a `next/link`, `ButtonLink`, `TextLink`). Plain DOM elements are
   * detected and need nothing.
   */
  focusable?: boolean;
  isDisabled?: boolean;
  className?: string;
  children: ReactElement;
}

/**
 * A supplementary hint on hover (after 500ms) and on keyboard focus. Never the only place a
 * piece of information lives: the trigger keeps its own accessible name. Not shown on touch.
 */
export function Tooltip({ text, shortcut, placement = "top", focusable, isDisabled, className, children }: TooltipProps) {
  const wrap = focusable ?? typeof children.type === "string";
  return (
    <TooltipTrigger delay={500} closeDelay={80} isDisabled={isDisabled}>
      {wrap ? <Focusable>{children as ReactElement<DOMAttributes<Element>, string>}</Focusable> : children}
      <RacTooltip placement={placement} offset={8} className={cx("lk-tooltip lk-tooltip-floating", className)}>
        <OverlayArrow className="lk-tooltip-arrow">
          <span />
        </OverlayArrow>
        {text}
        {shortcut ? <kbd>{shortcut}</kbd> : null}
      </RacTooltip>
    </TooltipTrigger>
  );
}
