"use client";

import { useState, type CSSProperties, type ReactNode } from "react";
import { cx } from "@/lib/cx";
import { formatDecimal, formatMoney, type MoneyValue } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import type { ReasonOption, StatusLook } from "~/data/finance";
import { riseIndex } from "~/lib/motion";
import { Page } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Button, ButtonLink, Dash, Modal, Select, Skeleton, SkeletonText, Textarea } from "~/ui";
import type { Route } from "next";

/** Small shared parts of the Finance screens. */

/** Inline style for a staggered entrance: `<li className="rise-plain" style={stagger(i)}>`. */
export const stagger = (index: number) => riseIndex(index) as CSSProperties;

export function StatusBadge({ look, size }: { look: StatusLook; size?: "sm" }) {
  return (
    <Badge tone={look.tone} dot size={size}>
      {look.label}
    </Badge>
  );
}

const DEMO_HINT = "Simulated: nothing is sent to a real accounting system or e-invoice provider.";

/** The label every simulated integration carries. */
export function DemoBadge() {
  return (
    <span title={DEMO_HINT} className="inline-flex flex-none">
      <Badge size="sm" outline>
        Demo
      </Badge>
      <span className="lk-sr-only">: {DEMO_HINT}</span>
    </span>
  );
}

/** A unit price keeps up to four decimal places; totals use `Money`. */
export function UnitPrice({ value, className }: { value: MoneyValue | null | undefined; className?: string }) {
  const { locale } = useZone();
  const text = value ? formatMoney(value, { locale, maxFractionDigits: 4 }) : null;
  if (text === null) return <Dash className={className} />;
  return <span className={cx("lk-tnum whitespace-nowrap", className)}>{text}</span>;
}

/** A percentage the server sent as a decimal string ("18.00" reads "18%"). */
export function Percent({ value, maxFractionDigits = 2, className }: { value: string | null | undefined; maxFractionDigits?: number; className?: string }) {
  const { locale } = useZone();
  const text = formatDecimal(value, { locale, maxFractionDigits });
  if (text === null) return <Dash className={className} />;
  return <span className={cx("lk-tnum whitespace-nowrap", className)}>{text}%</span>;
}

/** The header-shaped placeholder a record shows while it loads. */
export function RecordLoading({ what }: { what: string }) {
  return (
    <Page>
      <div className="lk-glass record-head" role="status" aria-label={`Loading ${what}`}>
        <Skeleton width="160px" height={14} />
        <Skeleton width="45%" height={32} />
        <SkeletonText lines={2} />
      </div>
      <LoadingBlock lines={6} label={`Loading ${what}`} />
    </Page>
  );
}

/** A record that could not load (not found, out of scope, or a failed request), with the way back. */
export function RecordProblem({ error, what, onRetry, backHref, backLabel }: { error: unknown; what: string; onRetry: () => void; backHref: Route; backLabel: string }) {
  return (
    <Page>
      <ErrorBlock error={error} what={what} onRetry={onRetry} />
      <div>
        <ButtonLink href={backHref} variant="secondary" iconLeft="arrowLeft">
          {backLabel}
        </ButtonLink>
      </div>
    </Page>
  );
}

/**
 * A confirmation that takes one of the command's reason codes and, where the endpoint accepts one,
 * a note. The confirm button names the verb; the dialog stays open while the command runs and
 * when it fails (the command hook has already said why in a toast).
 */
export function CodeReasonDialog({
  isOpen,
  onClose,
  title,
  description,
  reasons,
  confirmLabel,
  cancelLabel = "Keep as it is",
  tone = "default",
  note: withNote = true,
  onConfirm,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  reasons: readonly ReasonOption[];
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  /** False when the endpoint takes a reason code only. */
  note?: boolean;
  onConfirm: (code: string, note: string) => Promise<boolean>;
}) {
  const [code, setCode] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const reset = () => {
    setCode(null);
    setNote("");
    setError(false);
  };
  const close = () => {
    if (busy) return;
    reset();
    onClose();
  };
  const confirm = async () => {
    if (!code) {
      setError(true);
      return;
    }
    setBusy(true);
    try {
      if (await onConfirm(code, note.trim())) {
        reset();
        onClose();
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => (open ? undefined : close())}
      size="sm"
      title={title}
      description={description}
      actions={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={tone === "danger" ? "danger" : "inverse"} loading={busy} onPress={() => void confirm()}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Select
          label="Reason"
          placeholder="Choose a reason"
          options={reasons.map((reason) => ({ value: reason.id, label: reason.label }))}
          value={code}
          onChange={(value) => {
            setCode(value);
            setError(false);
          }}
          isRequired
          error={error ? "Choose the reason. It is kept in the history." : undefined}
        />
        {withNote ? <Textarea label="Note" optional rows={2} maxLength={500} value={note} onChange={setNote} /> : null}
      </div>
    </Modal>
  );
}

/** A quiet ledger line on an inverse panel: label left, figure right. */
export function LedgerLine({ label, children, strong = false }: { label: ReactNode; children: ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className={cx("t-body-sm", strong ? "" : "opacity-70")}>{label}</dt>
      <dd className={cx("lk-tnum m-0 text-right", strong ? "t-label" : "t-body")}>{children}</dd>
    </div>
  );
}
