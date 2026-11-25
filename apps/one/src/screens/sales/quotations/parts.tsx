"use client";

import { useState, type CSSProperties, type ReactNode } from "react";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { riseIndex } from "~/lib/motion";
import { Badge, Button, Dash, Icon, Modal, Textarea } from "~/ui";
import type { StatusLook } from "~/data/sales-deals";

/** Small shared parts of the Sales: deals screens (quotations, orders, custom products). */

/** Inline style for a staggered entrance: `<li className="rise-plain" style={stagger(i)}>`. */
export const stagger = (index: number) => riseIndex(index) as CSSProperties;

export function StatusBadge({ look, size }: { look: StatusLook; size?: "sm" }) {
  return (
    <Badge tone={look.tone} dot size={size}>
      {look.label}
    </Badge>
  );
}

/** A unit price keeps up to four decimal places (9.4950 stays 9.495); totals use `Money`. */
export function UnitPrice({ amount, currency, className }: { amount: string | null | undefined; currency: string; className?: string }) {
  const { locale } = useZone();
  const text = amount ? formatMoney({ amount, currency }, { locale, maxFractionDigits: 4 }) : null;
  if (text === null) return <Dash className={className} />;
  return <span className={cx("lk-tnum whitespace-nowrap", className)}>{text}</span>;
}

export type StepState = "done" | "current" | "todo";

export interface StepItem {
  id: string;
  label: string;
  /** A short line under the label on wide screens: a date, a count, what happens here. */
  hint?: ReactNode;
  state: StepState;
}

/**
 * A step indicator: where a flow or a record stands. Done steps are inked with a tick, the current
 * step carries the gold ring, later steps wait in outline. On phones only the current label shows.
 */
export function Steps({ label, steps, className }: { label: string; steps: readonly StepItem[]; className?: string }) {
  const currentIndex = steps.findIndex((step) => step.state === "current");
  return (
    <ol aria-label={label} className={cx("flex min-w-0 items-start gap-2", className)}>
      {steps.map((step, index) => (
        <li
          key={step.id}
          aria-current={step.state === "current" ? "step" : undefined}
          className={cx("rise-plain flex min-w-0 items-start gap-2", index < steps.length - 1 ? "flex-1" : "flex-none")}
          style={stagger(index)}
        >
          <div className="flex min-w-0 items-center gap-2 sm:items-start">
            <span
              className={cx(
                "t-label lk-tnum flex h-7 w-7 flex-none items-center justify-center rounded-pill border",
                step.state === "done" && "border-inverse bg-inverse text-on-inverse",
                step.state === "current" && "border-gold-strong bg-gold-soft text-gold-strong",
                step.state === "todo" && "border-line-strong text-ink-3",
              )}
            >
              {step.state === "done" ? <Icon name="check" size={14} /> : index + 1}
            </span>
            <span className={cx("min-w-0 flex-col gap-0.5 sm:flex", step.state === "current" || (currentIndex === -1 && index === steps.length - 1) ? "flex" : "hidden")}>
              <span className={cx("t-label", step.state === "todo" ? "text-ink-3" : "text-ink")}>
                {step.label}
                <span className="sr-only">{step.state === "done" ? " (done)" : step.state === "current" ? " (current)" : " (to do)"}</span>
              </span>
              {step.hint ? <span className="t-caption hidden text-ink-3 sm:block">{step.hint}</span> : null}
            </span>
          </div>
          {index < steps.length - 1 ? (
            <span aria-hidden="true" className={cx("mt-3.5 h-px min-w-3 flex-1 sm:min-w-6", step.state === "done" ? "bg-ink-3" : "bg-line-strong")} />
          ) : null}
        </li>
      ))}
    </ol>
  );
}

/**
 * A confirmation that takes a reason: required when the server asks for one, optional otherwise
 * (the old screens sent an optional reason with discard, restore and archive). The confirm button
 * names the verb; the dialog stays open while the command runs and on failure.
 */
export function ReasonModal({
  isOpen,
  onOpenChange,
  title,
  description,
  confirmLabel,
  tone = "default",
  reason = "optional",
  reasonLabel = "Reason",
  reasonHelp,
  onConfirm,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  confirmLabel: string;
  tone?: "default" | "danger";
  reason?: "required" | "optional" | "none";
  reasonLabel?: string;
  reasonHelp?: ReactNode;
  onConfirm: (reason: string | null) => Promise<unknown> | void;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const close = (open: boolean) => {
    if (busy) return;
    if (!open) {
      setText("");
      setError(null);
    }
    onOpenChange(open);
  };
  const confirm = async () => {
    const value = text.trim();
    if (reason === "required" && value.length < 3) {
      setError("Give a reason in a few words. It is kept in the history.");
      return;
    }
    setBusy(true);
    try {
      await onConfirm(value || null);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={close}
      title={title}
      description={description}
      size="sm"
      actions={
        <>
          <Button variant="ghost" onPress={() => close(false)} isDisabled={busy}>
            Keep as it is
          </Button>
          <Button variant={tone === "danger" ? "danger" : "inverse"} loading={busy} onPress={() => void confirm()}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {reason === "none" ? null : (
        <Textarea
          label={reasonLabel}
          optional={reason === "optional"}
          isRequired={reason === "required"}
          rows={2}
          maxLength={500}
          value={text}
          onChange={(value) => {
            setText(value);
            if (error) setError(null);
          }}
          help={reasonHelp}
          error={error ?? undefined}
        />
      )}
    </Modal>
  );
}

/** The closing figure of a ledger: a label on the left, the amount in stat numerals on the right. */
export function TotalFigure({ label, note, children, size = "lg" }: { label: string; note?: ReactNode; children: ReactNode; size?: "lg" | "xl" }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="t-overline text-ink-3">{label}</span>
        {note ? <span className="t-caption text-ink-3">{note}</span> : null}
      </div>
      <span className={cx(size === "xl" ? "t-stat-xl" : "t-stat", "ml-auto text-right text-ink")}>{children}</span>
    </div>
  );
}
