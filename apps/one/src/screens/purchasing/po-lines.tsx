"use client";

import { useMemo, useState } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { moveExpectedDate, type PoDetail, type PoLine } from "@/features/procurement/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { UnitPrice } from "~/screens/sales/quotations/parts";
import { Badge, Button, DataTable, DatePicker, DateText, Drawer, EmptyState, GlassPanel, KeyValue, Modal, Money, Qty, type Column } from "~/ui";
import { FAILED } from "./labels";
import { LineName } from "./parts";

/** The lines of a purchase order. Six columns say what is due; a line opens for its full count. */
export function PoLinesView({ po }: { po: PoDetail }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [movingId, setMovingId] = useState<string | null>(null);
  const open = po.lines.find((line) => line.id === openId) ?? null;
  const moving = po.lines.find((line) => line.id === movingId) ?? null;
  const canMove = Boolean(po.capabilities.change_expected_date?.allowed);
  const qty = (value: string, unit: string) => <Qty value={{ value, uom: unit }} />;

  const columns: Column<PoLine>[] = [
    { key: "item", header: "Line", primary: true, cell: (line) => <LineName lineNo={line.line_no} name={line.product.name} productKey={line.product.product_key} /> },
    {
      key: "expected",
      header: "Expected",
      cell: (line) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <DateText value={line.expected_date} style="business" />
          {line.is_overdue ? (
            <Badge tone="ember" size="sm" icon="clock">
              Late
            </Badge>
          ) : null}
        </span>
      ),
    },
    { key: "ordered", header: "Ordered", numeric: true, cell: (line) => qty(line.quantity, line.unit) },
    { key: "received", header: "Received", numeric: true, cell: (line) => qty(line.qty_received, line.unit) },
    {
      key: "outstanding",
      header: "Still to come",
      numeric: true,
      cell: (line) => <span className={isPositiveDecimalStr(line.qty_outstanding) ? "t-label text-ink" : "text-ink-3"}>{qty(line.qty_outstanding, line.unit)}</span>,
    },
    { key: "amount", header: "Amount", numeric: true, hideOnMobile: true, cell: (line) => <Money value={{ amount: line.line_amount, currency: po.currency }} /> },
  ];

  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Lines</h2>
        <p className="t-body-sm text-ink-3">
          Open a line for its full count: accepted, rejected, in QC and billed{canMove ? ", and to move its expected date" : ""}.
        </p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Lines of ${po.po_number}`}
          columns={columns}
          rows={po.lines}
          rowKey={(line) => line.id}
          onRowAction={(line) => setOpenId(line.id)}
          selectedKey={openId ?? undefined}
          empty={<EmptyState compact icon="list" title="This purchase order has no lines" text="It was created without any products." />}
        />
      </GlassPanel>

      <LineDrawer
        po={po}
        line={open}
        canMove={canMove}
        onClose={() => setOpenId(null)}
        onMove={(line) => {
          setOpenId(null);
          setMovingId(line.id);
        }}
      />
      {moving ? <MoveDateDialog key={moving.id} po={po} line={moving} onClose={() => setMovingId(null)} /> : null}
    </div>
  );
}

function LineDrawer({ po, line, canMove, onClose, onMove }: { po: PoDetail; line: PoLine | null; canMove: boolean; onClose: () => void; onMove: (line: PoLine) => void }) {
  const movable = line !== null && canMove && isPositiveDecimalStr(line.qty_outstanding);
  const qty = (value: string) => (line ? <Qty value={{ value, uom: line.unit }} /> : null);
  return (
    <Drawer
      isOpen={line !== null}
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={line ? `Line ${line.line_no}` : ""}
      description={line ? `${line.product.name} · ${line.product.product_key}` : undefined}
      footer={
        <>
          {movable && line ? (
            <Button variant="secondary" iconLeft="calendar" className="mr-auto" onPress={() => onMove(line)}>
              Move expected date
            </Button>
          ) : null}
          <Button variant="ghost" onPress={onClose}>
            Close
          </Button>
        </>
      }
    >
      {line ? (
        <div className="flex flex-col gap-5">
          <div className="flex items-end justify-between gap-4 rounded-md border border-line bg-surface p-4">
            <div className="flex flex-col gap-0.5">
              <span className="t-overline text-ink-3">Still to come</span>
              <span className="t-stat text-ink">{qty(line.qty_outstanding)}</span>
            </div>
            <span className="flex flex-col items-end gap-1">
              <span className="t-caption text-ink-3">
                Expected <DateText value={line.expected_date} style="business" />
              </span>
              {line.is_overdue ? (
                <Badge tone="ember" size="sm" icon="clock">
                  Late
                </Badge>
              ) : null}
            </span>
          </div>
          <KeyValue
            rows
            items={[
              { label: "Ordered", value: qty(line.quantity) },
              { label: "Received", value: qty(line.qty_received) },
              { label: "Accepted", value: qty(line.qty_accepted) },
              { label: "Rejected", value: qty(line.qty_rejected) },
              { label: "In QC", value: qty(line.qty_pending_qc) },
              { label: "Billed", value: qty(line.qty_billed) },
              { label: "Cancelled", value: qty(line.qty_cancelled) },
              { label: "Unit price", value: <UnitPrice amount={line.unit_price} currency={po.currency} /> },
              { label: "Amount", value: <Money value={{ amount: line.line_amount, currency: po.currency }} />, total: true },
            ]}
          />
          {line.price_override_reason ? <p className="t-body-sm text-ink-3">Price changed from the vendor list price: {line.price_override_reason}</p> : null}
          <p className="t-caption text-ink-3">
            Purchase order {po.po_number}. Accepted and rejected quantities come from quality inspections.
          </p>
        </div>
      ) : null}
    </Drawer>
  );
}

function MoveDateDialog({ po, line, onClose }: { po: PoDetail; line: PoLine; onClose: () => void }) {
  const key = useMemo(() => queryKeys.procurement.order(po.id), [po.id]);
  const { run, pending, offline } = useCommand<PoDetail>(key);
  const [date, setDate] = useState<string | null>(line.expected_date);
  const [checked, setChecked] = useState(false);
  const busy = pending === "move";
  const close = () => {
    if (!busy) onClose();
  };
  const confirm = async () => {
    setChecked(true);
    if (!date) return;
    const moved = await run("move", (k) => moveExpectedDate(po.id, line, date, k), { done: "Expected date moved", failed: FAILED, write: (next) => next });
    if (moved) onClose();
  };
  return (
    <Modal
      isOpen
      onOpenChange={(open) => (open ? undefined : close())}
      size="sm"
      title={`Move the expected date of line ${line.line_no}`}
      description={`${line.product.name}. Use the date the vendor now promises, so late lines stay honest.`}
      actions={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Keep the date
          </Button>
          <Button variant="inverse" loading={busy} isDisabled={Boolean(offline)} onPress={() => void confirm()}>
            Move date
          </Button>
        </>
      }
    >
      <DatePicker label="New expected date" value={date} onChange={setDate} isRequired error={checked && !date ? "Choose the new date." : offline ? offline : undefined} />
    </Modal>
  );
}
