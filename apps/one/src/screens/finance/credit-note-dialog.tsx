"use client";

import { useState } from "react";
import type { InvoiceDetail } from "@/features/finance/api";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { formatQuantity } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { CREDIT_REASONS } from "~/data/finance";
import { Banner, Button, DecimalField, Modal, Select } from "~/ui";

/**
 * Start a credit note against an issued invoice: the reason, then the quantity to credit on each
 * line that still has something creditable. It creates a draft, which opens for approval and issue.
 */
export function CreditNoteDialog({
  doc,
  isOpen,
  onClose,
  onCreate,
}: {
  doc: InvoiceDetail;
  isOpen: boolean;
  onClose: () => void;
  onCreate: (lines: { invoice_line_id: string; quantity: string }[], reasonCode: string) => Promise<boolean>;
}) {
  const { locale } = useZone();
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [reason, setReason] = useState<string>(CREDIT_REASONS[0]?.id ?? "");
  const [nothing, setNothing] = useState(false);
  const [busy, setBusy] = useState(false);
  const creditable = doc.lines.filter((line) => isPositiveDecimalStr(line.creditable_quantity));
  const lines = Object.entries(quantities)
    .filter(([, quantity]) => isPositiveDecimalStr(quantity))
    .map(([invoice_line_id, quantity]) => ({ invoice_line_id, quantity }));

  const close = () => {
    if (busy) return;
    setQuantities({});
    setNothing(false);
    onClose();
  };
  const create = async () => {
    if (lines.length === 0) {
      setNothing(true);
      return;
    }
    setBusy(true);
    try {
      if (await onCreate(lines, reason)) {
        setQuantities({});
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
      title={`Credit note against ${doc.document_number ?? "this invoice"}`}
      description="Enter what to credit on each line. A draft credit note is created, ready for approval and issue."
      actions={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Cancel
          </Button>
          <Button variant="inverse" loading={busy} onPress={() => void create()}>
            Create draft credit note
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {nothing ? (
          <Banner tone="ember" title="Nothing to credit yet.">
            Enter a quantity above zero on at least one line.
          </Banner>
        ) : null}
        <Select label="Reason" options={CREDIT_REASONS.map((option) => ({ value: option.id, label: option.label }))} value={reason} onChange={setReason} isRequired />
        {creditable.length === 0 ? (
          <p className="t-body-sm text-ink-3">Every line of this invoice has already been credited in full.</p>
        ) : (
          creditable.map((line) => (
            <DecimalField
              key={line.id}
              label={`Quantity to credit on line ${line.line_no}`}
              help={`${line.description} · up to ${formatQuantity({ value: line.creditable_quantity ?? "0", uom: line.uom_code }, { locale }) ?? line.creditable_quantity}`}
              value={quantities[line.id] ?? ""}
              suffix={line.uom_code}
              onChange={(value) => {
                setQuantities((current) => ({ ...current, [line.id]: value }));
                if (nothing) setNothing(false);
              }}
            />
          ))
        )}
      </div>
    </Modal>
  );
}
