"use client";

import type { ReactElement, ReactNode } from "react";
import { Tooltip as RacTooltip, TooltipTrigger } from "react-aria-components";

/**
 * Supplementary hint on hover and keyboard focus. Never the only place information lives:
 * the trigger keeps its own accessible name. Wraps a React Aria Button or Link.
 */
export function Tooltip({ content, children, delay = 600 }: { content: ReactNode; children: ReactElement; delay?: number }) {
  return (
    <TooltipTrigger delay={delay} closeDelay={100}>
      {children}
      <RacTooltip
        offset={6}
        className="max-w-64 rounded-md bg-ink px-2.5 py-1.5 text-sm text-canvas shadow-md entering:animate-pop-in exiting:animate-pop-out"
      >
        {content}
      </RacTooltip>
    </TooltipTrigger>
  );
}
