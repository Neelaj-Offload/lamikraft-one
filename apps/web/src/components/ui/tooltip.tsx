"use client";

import type { ReactElement, ReactNode } from "react";
import { Tooltip as RacTooltip, TooltipTrigger, type TooltipProps as RacTooltipProps } from "react-aria-components";

/**
 * Supplementary hint on hover and keyboard focus. Never the only place information lives:
 * the trigger keeps its own accessible name. Wraps a React Aria Button or Link.
 */
export function Tooltip({
  content,
  children,
  delay = 600,
  isDisabled = false,
  placement,
}: {
  content: ReactNode;
  children: ReactElement;
  delay?: number;
  /** For hints that only apply in some layouts (labels of the collapsed sidebar). */
  isDisabled?: boolean;
  placement?: RacTooltipProps["placement"];
}) {
  return (
    <TooltipTrigger delay={delay} closeDelay={100} isDisabled={isDisabled}>
      {children}
      <RacTooltip
        offset={6}
        placement={placement}
        className="max-w-64 rounded-md bg-ink px-2.5 py-1.5 text-sm text-canvas shadow-md entering:animate-pop-in exiting:animate-pop-out"
      >
        {content}
      </RacTooltip>
    </TooltipTrigger>
  );
}
