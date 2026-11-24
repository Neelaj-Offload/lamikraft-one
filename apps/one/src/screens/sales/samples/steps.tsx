import type { CSSProperties, ReactNode } from "react";
import { cx } from "@/lib/cx";
import { riseIndex } from "~/lib/motion";
import { Icon, type IconName } from "~/ui/icon";

/**
 * A journey as steps: done, current, still to come. A row from 768px, a column on phones. Used
 * for a sample's journey and an enquiry's pipeline. (`~/ui` has no step indicator; this is built
 * from tokens only.) No directive: it renders on the server or the client.
 */

export interface StepItem {
  id: string;
  label: string;
  /** A date, a reference or a short note under the label. */
  caption?: ReactNode;
  icon: IconName;
}

type StepState = "done" | "current" | "todo";

const MARKER: Record<StepState, CSSProperties> = {
  done: { background: "var(--inverse)", color: "var(--on-inverse)", borderColor: "var(--inverse)" },
  current: { background: "var(--gold-soft)", color: "var(--gold-strong)", borderColor: "var(--gold)" },
  todo: { background: "var(--surface)", color: "var(--ink-3)", borderColor: "var(--line-strong)" },
};

const SPOKEN: Record<StepState, string> = { done: ", done", current: ", current step", todo: ", not yet" };

export function Steps({
  label,
  steps,
  current,
  complete = false,
  halted = false,
  className,
}: {
  /** The record stopped at `current` (cancelled): that step is shown as not reached, not as "act here". */
  halted?: boolean;
  /** Names the list for assistive technology ("Sample journey"). */
  label: string;
  steps: readonly StepItem[];
  /** Index of the step the record is on; -1 when it has left the journey. */
  current: number;
  /** Every step is done (a closed record). */
  complete?: boolean;
  className?: string;
}) {
  return (
    <ol aria-label={label} className={cx("m-0 grid list-none p-0 md:auto-cols-fr md:grid-flow-col", className)}>
      {steps.map((step, index) => {
        const state: StepState = complete || (current >= 0 && index < current) ? "done" : index === current && !halted ? "current" : "todo";
        const reached = complete || (current >= 0 && index < current);
        return (
          <li
            key={step.id}
            className="rise-plain relative flex gap-3 pb-6 last:pb-0 md:flex-col md:pb-0 md:pr-4"
            style={riseIndex(index) as CSSProperties}
            aria-current={state === "current" ? "step" : undefined}
          >
            {index < steps.length - 1 ? (
              <span
                aria-hidden="true"
                className="absolute bottom-0 left-[17px] top-9 w-px md:bottom-auto md:left-9 md:right-0 md:top-[17px] md:h-px md:w-auto"
                style={{ background: reached ? "var(--inverse)" : "var(--line-strong)" }}
              />
            ) : null}
            <span className="relative z-[1] grid size-9 flex-none place-items-center rounded-pill border" style={MARKER[state]}>
              <Icon name={state === "done" ? "check" : step.icon} size={16} />
            </span>
            <span className="flex min-w-0 flex-col gap-0.5 pt-1.5 md:pt-0">
              <span className={cx("t-label", state === "todo" ? "text-ink-3" : "text-ink")}>
                {step.label}
                <span className="lk-sr-only">{SPOKEN[state]}</span>
              </span>
              {step.caption ? <span className="t-caption text-ink-3">{step.caption}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
