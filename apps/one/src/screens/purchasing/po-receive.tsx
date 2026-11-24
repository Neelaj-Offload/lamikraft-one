"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { receiveGoods, type PoDetail } from "@/features/procurement/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr, trimDecimalStr } from "@/lib/format/decimal";
import { Badge, Banner, Button, DecimalField, Drawer, Qty, TextField } from "~/ui";
import { count, FAILED } from "./labels";
import { asRoute } from "./views";

interface Entry {
  qty: string;
  lot: string;
}

/**
 * Receive goods against a purchase order: what arrived on each open line, its lot where the
 * product is tracked by lot, and the vendor's challan number. One command creates the receipt and
 * posts it to stock; the receipt then opens.
 */
export function ReceiveDrawer({ po, isOpen, onClose }: { po: PoDetail; isOpen: boolean; onClose: () => void }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.procurement.order(po.id), [po.id]);
  const { run, pending, offline } = useCommand<null>(key);
  const open = po.lines.filter((line) => isPositiveDecimalStr(line.qty_receivable));
  const [values, setValues] = useState<Record<string, Entry>>(() => Object.fromEntries(open.map((line) => [line.id, { qty: trimDecimalStr(line.qty_outstanding), lot: "" }])));
  const [challan, setChallan] = useState("");
  const [checked, setChecked] = useState(false);
  const busy = pending === "receive";

  const entry = (id: string): Entry => values[id] ?? { qty: "", lot: "" };
  const arriving = open.filter((line) => isPositiveDecimalStr(entry(line.id).qty));
  const lotMissing = (lineId: string, tracked: boolean) => tracked && isPositiveDecimalStr(entry(lineId).qty) && entry(lineId).lot.trim() === "";
  const anyLotMissing = arriving.some((line) => lotMissing(line.id, line.product.track_lots));
  const needsQc = arriving.filter((line) => line.product.qc_required).length;

  const close = () => {
    if (!busy) onClose();
  };
  const submit = async () => {
    setChecked(true);
    if (arriving.length === 0 || anyLotMissing) return;
    const grn = await run(
      "receive",
      (k) =>
        receiveGoods(
          po.id,
          arriving.map((line) => ({ po_line_id: line.id, quantity: entry(line.id).qty, lot_code: entry(line.id).lot || null })),
          challan,
          k,
        ),
      { done: "Receipt posted", failed: FAILED },
    );
    if (grn) router.push(asRoute(grn.path));
  };

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={(next) => (next ? undefined : close())}
      width="lg"
      title="Receive goods"
      description={`Enter what arrived from ${po.vendor.display_name}. It is added to stock at ${po.warehouse.name} as soon as you post.`}
      footer={
        <>
          <span className="t-caption mr-auto self-center text-ink-3">{arriving.length > 0 ? `${count(arriving.length, "line", "lines")} arriving` : "Nothing entered yet"}</span>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Cancel
          </Button>
          <Button iconLeft="packageOpen" loading={busy} isDisabled={Boolean(offline)} onPress={() => void submit()}>
            Post receipt
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {offline ? (
          <Banner tone="amber" title="You are offline.">
            The receipt can be posted once the connection is back.
          </Banner>
        ) : null}
        {checked && arriving.length === 0 ? (
          <Banner tone="ember" title="Nothing to receive yet.">
            Enter the quantity that arrived on at least one line.
          </Banner>
        ) : null}
        {open.length === 0 ? (
          <Banner tone="cobalt" title="Every line has arrived in full.">
            There is nothing left to receive against this order.
          </Banner>
        ) : null}
        {needsQc > 0 ? (
          <Banner tone="cobalt" icon="flask">
            {count(needsQc, "line needs", "lines need")} a quality check. Those goods wait in QC hold until they are inspected.
          </Banner>
        ) : null}

        {open.map((line) => {
          const value = entry(line.id);
          return (
            <div key={line.id} className="flex min-w-0 flex-col gap-4 rounded-md border border-line bg-surface p-4">
              <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="t-overline text-ink-3">Line {line.line_no}</span>
                  <span className="t-label text-ink">{line.product.name}</span>
                  <span className="t-caption lk-mono text-ink-3">{line.product.product_key}</span>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="t-caption text-ink-3">
                    Still to come: <Qty value={{ value: line.qty_outstanding, uom: line.unit }} className="text-ink" />
                  </span>
                  {line.product.qc_required ? (
                    <Badge tone="cobalt" size="sm" icon="flask">
                      Needs QC
                    </Badge>
                  ) : null}
                </div>
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <DecimalField
                  label="Quantity arrived"
                  value={value.qty}
                  suffix={line.unit}
                  onChange={(qty) => setValues((all) => ({ ...all, [line.id]: { qty, lot: all[line.id]?.lot ?? "" } }))}
                  help="Leave empty if none of this line came."
                />
                {line.product.track_lots ? (
                  <TextField
                    label="Lot code"
                    value={value.lot}
                    maxLength={60}
                    isRequired
                    onChange={(lot) => setValues((all) => ({ ...all, [line.id]: { qty: all[line.id]?.qty ?? "", lot } }))}
                    error={checked && lotMissing(line.id, true) ? "This product is tracked by lot. Enter the lot code from the vendor's label." : undefined}
                  />
                ) : null}
              </div>
            </div>
          );
        })}

        <TextField label="Vendor challan number" optional value={challan} onChange={setChallan} maxLength={80} help="The delivery note that came with the goods." />
      </div>
    </Drawer>
  );
}
