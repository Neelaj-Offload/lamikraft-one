"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { billAction, createBill, fetchBills, type BillRead, type PoDetail } from "@/features/procurement/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr, trimDecimalStr } from "@/lib/format/decimal";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Banner, Button, Code, DatePicker, DateText, DecimalField, Drawer, EmptyState, GlassPanel, Icon, KeyValue, Money, TextField } from "~/ui";
import { BILL_STATUS, count, FAILED, MATCH_EXCEPTION, matchStatus } from "./labels";
import { stagger, StatusBadge } from "./parts";

/**
 * Vendor bills against a purchase order. Each bill is matched three ways as it is recorded: what
 * was ordered, what was accepted, what is billed. A matched bill is handed to finance.
 */
export function BillsView({ po }: { po: PoDetail }) {
  const key = useMemo(() => queryKeys.procurement.bills(po.id), [po.id]);
  const denied = po.capabilities.bill?.reason_code === "permission_denied";
  const bills = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchBills(po.id, signal), enabled: !denied });
  const [adding, setAdding] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const canAdd = Boolean(po.capabilities.bill?.allowed);
  const add = () => {
    setAttempt((n) => n + 1);
    setAdding(true);
  };

  // A link to one bill ("#bill-{id}") scrolls to it once the bills are on screen.
  const loaded = bills.data !== undefined;
  useEffect(() => {
    if (!loaded) return;
    const hash = window.location.hash;
    if (hash.startsWith("#bill-")) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [loaded]);

  return (
    <div className="stack">
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="t-h3">Vendor bills</h2>
          <p className="t-body-sm text-ink-3">Each bill is checked against the order and against what quality accepted. A bill that matches goes to finance.</p>
        </div>
        {canAdd ? (
          <Button variant="secondary" iconLeft="plus" onPress={add}>
            Record vendor bill
          </Button>
        ) : null}
      </div>

      {denied ? (
        <GlassPanel padding="md" className="rise">
          <EmptyState compact icon="lock" title="Bill details are not part of your role" text={`${count(po.bills.length, "bill is", "bills are")} recorded against this order. Ask a workspace admin if you need to see them.`} />
        </GlassPanel>
      ) : bills.isPending ? (
        <LoadingBlock lines={5} label="Loading vendor bills" />
      ) : bills.isError ? (
        <ErrorBlock error={bills.error} what="Vendor bills" onRetry={() => void bills.refetch()} />
      ) : bills.data.items.length === 0 ? (
        <GlassPanel padding="md" className="rise">
          <EmptyState
            compact
            icon="receipt"
            title="No vendor bill recorded yet"
            text={canAdd ? "When the vendor's bill arrives, record it here. It is matched to the order and the accepted goods at once." : "The vendor's bill is listed here once someone records it."}
            actions={
              canAdd ? (
                <Button variant="inverse" iconLeft="plus" onPress={add}>
                  Record the first bill
                </Button>
              ) : null
            }
          />
        </GlassPanel>
      ) : (
        bills.data.items.map((bill, index) => <BillCard key={bill.id} bill={bill} poId={po.id} index={index} />)
      )}

      {canAdd ? <BillDrawer key={attempt} po={po} isOpen={adding} onClose={() => setAdding(false)} /> : null}
    </div>
  );
}

function BillCard({ bill, poId, index }: { bill: BillRead; poId: string; index: number }) {
  const key = useMemo(() => queryKeys.procurement.bills(poId), [poId]);
  const { run, pending, offline } = useCommand<null>(key);
  const money = (amount: string) => <Money value={{ amount, currency: bill.currency }} />;
  const canMatch = Boolean(bill.capabilities.match?.allowed);
  const canHandOff = Boolean(bill.capabilities.hand_off?.allowed);
  return (
    <GlassPanel as="article" id={`bill-${bill.id}`} padding="md" className="rise flex min-w-0 scroll-mt-24 flex-col gap-5" style={stagger(index)}>
      <header className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="t-h4 flex flex-wrap items-center gap-2">
            <span className="sr-only">Bill </span>
            <Code>{bill.bill_number}</Code>
            <StatusBadge look={matchStatus(bill.match_status)} />
          </h3>
          <p className="t-body-sm text-ink-3">
            Dated <DateText value={bill.bill_date} style="business" /> · {BILL_STATUS[bill.status] ?? bill.status}
            {bill.handed_off_at ? (
              <>
                {" "}
                on <DateText value={bill.handed_off_at} style="date" />
              </>
            ) : null}
          </p>
        </div>
        {canMatch || canHandOff ? (
          <div className="flex flex-wrap gap-2">
            {canMatch ? (
              <Button variant="secondary" size="sm" iconLeft="refresh" loading={pending === "match"} isDisabled={Boolean(offline)} onPress={() => void run("match", (k) => billAction(bill, "match", k), { done: "Bill matched again", failed: FAILED })}>
                Match again
              </Button>
            ) : null}
            {canHandOff ? (
              <Button variant="inverse" size="sm" iconRight="arrowRight" loading={pending === "hand"} isDisabled={Boolean(offline)} onPress={() => void run("hand", (k) => billAction(bill, "hand-off", k), { done: "Handed to finance", failed: FAILED })}>
                Hand to finance
              </Button>
            ) : null}
          </div>
        ) : null}
      </header>

      {bill.match_exceptions.length > 0 ? (
        <div className="flex flex-col gap-2 rounded-md border border-line bg-surface p-4">
          <span className="t-overline text-ink-3">Why it does not match</span>
          <ul className="flex flex-col gap-2">
            {bill.match_exceptions.map((exception, i) => (
              <li key={`${exception.code}-${i}`} className="t-body-sm flex min-w-0 items-start gap-2 text-ink">
                <Icon name="alert" size={16} className="mt-0.5 flex-none text-ember" />
                <span className="min-w-0">
                  {MATCH_EXCEPTION[exception.code] ?? exception.code}
                  {exception.line_no ? `, line ${exception.line_no}` : ""}
                  {exception.expected != null ? (
                    <span className="lk-tnum text-ink-2">
                      {" "}
                      (expected {trimDecimalStr(exception.expected)}, billed {exception.actual != null ? trimDecimalStr(exception.actual) : "nothing"})
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <KeyValue
        rows
        columns={2}
        items={[
          { label: "Subtotal as billed", value: money(bill.subtotal_amount) },
          { label: "Lines add up to", value: money(bill.computed_subtotal) },
          { label: "Tax as billed", value: money(bill.tax_amount) },
          { label: "Total as billed", value: money(bill.total_amount), total: true },
        ]}
      />
    </GlassPanel>
  );
}

interface BillLineEntry {
  qty: string;
  price: string;
}

function BillDrawer({ po, isOpen, onClose }: { po: PoDetail; isOpen: boolean; onClose: () => void }) {
  const key = useMemo(() => queryKeys.procurement.bills(po.id), [po.id]);
  const { run, pending, offline } = useCommand<null>(key);
  const billable = po.lines.filter((line) => isPositiveDecimalStr(line.qty_billable));
  const [number, setNumber] = useState("");
  const [date, setDate] = useState<string | null>(null);
  const [subtotal, setSubtotal] = useState("");
  const [tax, setTax] = useState("0");
  const [total, setTotal] = useState("");
  const [lines, setLines] = useState<Record<string, BillLineEntry>>(() =>
    Object.fromEntries(billable.map((line) => [line.id, { qty: trimDecimalStr(line.qty_billable), price: trimDecimalStr(line.unit_price) }])),
  );
  const [checked, setChecked] = useState(false);
  const busy = pending === "bill";

  const entry = (id: string): BillLineEntry => lines[id] ?? { qty: "", price: "" };
  const chosen = billable.filter((line) => entry(line.id).qty !== "" && entry(line.id).price !== "");
  const missing = !number.trim() || !date || !subtotal || !total || chosen.length === 0;
  const close = () => {
    if (!busy) onClose();
  };
  const submit = async () => {
    setChecked(true);
    if (missing || !date) return;
    const bill = await run(
      "bill",
      (k) =>
        createBill(
          po.id,
          {
            bill_number: number.trim(),
            bill_date: date,
            subtotal_amount: subtotal,
            tax_amount: tax || "0",
            total_amount: total,
            lines: chosen.map((line) => ({ po_line_id: line.id, quantity: entry(line.id).qty, unit_price: entry(line.id).price })),
          },
          k,
        ),
      { done: "Bill recorded and matched", failed: FAILED },
    );
    if (bill) onClose();
  };

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={(next) => (next ? undefined : close())}
      width="lg"
      title="Record a vendor bill"
      description={`Copy the figures from ${po.vendor.display_name}'s bill as printed. It is matched to the order and the accepted goods when you save.`}
      footer={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Cancel
          </Button>
          <Button loading={busy} isDisabled={Boolean(offline)} onPress={() => void submit()}>
            Record bill
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-6">
        {offline ? (
          <Banner tone="amber" title="You are offline.">
            The bill can be recorded once the connection is back.
          </Banner>
        ) : null}
        {billable.length === 0 ? (
          <Banner tone="cobalt" title="Nothing can be billed yet.">
            A line can be billed once its goods have been received and accepted.
          </Banner>
        ) : checked && chosen.length === 0 ? (
          <Banner tone="ember" title="No lines are on the bill.">
            Give at least one line a quantity and a unit price.
          </Banner>
        ) : null}

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <TextField label="Bill number" value={number} onChange={setNumber} maxLength={80} isRequired error={checked && !number.trim() ? "Enter the number printed on the bill." : undefined} />
          <DatePicker label="Bill date" value={date} onChange={setDate} isRequired error={checked && !date ? "Choose the date printed on the bill." : undefined} />
          <DecimalField label="Subtotal as billed" prefix={po.currency} value={subtotal} onChange={setSubtotal} isRequired error={checked && !subtotal ? "Enter the subtotal before tax." : undefined} />
          <DecimalField label="Tax as billed" prefix={po.currency} value={tax} onChange={setTax} />
          <DecimalField className="sm:col-span-2" label="Total as billed" prefix={po.currency} value={total} onChange={setTotal} isRequired error={checked && !total ? "Enter the total the vendor asks for." : undefined} />
        </div>

        {billable.length > 0 ? (
          <fieldset className="flex min-w-0 flex-col gap-3">
            <legend className="mb-3 flex flex-col gap-1">
              <span className="t-h4 text-ink">Lines on the bill</span>
              <span className="t-body-sm text-ink-3">Filled in with what can be billed at the order price. Change them to what the bill says; clear a line that is not on it.</span>
            </legend>
            {billable.map((line) => {
              const value = entry(line.id);
              return (
                <div key={line.id} className="flex min-w-0 flex-col gap-4 rounded-md border border-line bg-surface p-4">
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="t-overline text-ink-3">Line {line.line_no}</span>
                    <span className="t-label text-ink">{line.product.name}</span>
                    <span className="t-caption lk-mono text-ink-3">{line.product.product_key}</span>
                  </div>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <DecimalField
                      label="Quantity billed"
                      suffix={line.unit}
                      value={value.qty}
                      onChange={(qty) => setLines((all) => ({ ...all, [line.id]: { qty, price: all[line.id]?.price ?? "" } }))}
                    />
                    <DecimalField
                      label="Unit price billed"
                      prefix={po.currency}
                      value={value.price}
                      onChange={(price) => setLines((all) => ({ ...all, [line.id]: { qty: all[line.id]?.qty ?? "", price } }))}
                    />
                  </div>
                </div>
              );
            })}
          </fieldset>
        ) : null}
      </div>
    </Drawer>
  );
}
