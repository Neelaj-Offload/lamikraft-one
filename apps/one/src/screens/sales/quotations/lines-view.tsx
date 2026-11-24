"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { previewQuote, quoteLinesCsvHref, removeQuoteLine, updateQuoteLine } from "@/features/sales/api";
import type { QuoteDetail, QuoteLine } from "@/features/sales/types";
import { lineEditIsDirty, lineEditOf, lineUpdatePlan, previewRequest, priceDiffersFromList, type LineEdit } from "@/features/sales/workspace-model";
import { queryKeys } from "@/lib/api/query-keys";
import { useDebouncedValue } from "@/lib/hooks";
import { quotationStatus } from "~/data/sales-deals";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Code,
  ConfirmDialog,
  DataTable,
  DecimalField,
  Drawer,
  EmptyState,
  GlassPanel,
  Icon,
  Money,
  Qty,
  TextField,
  type Column,
} from "~/ui";
import { LineAddDrawer } from "./line-add-drawer";
import { UnitPrice } from "./parts";
import type { QuoteCommands } from "./quotation-actions";
import { QuotationTotals } from "./totals";

const ADVISORY: Record<string, string> = {
  PRICE_CHANGED_SINCE_SNAPSHOT: "The list price has changed since this line was priced.",
  NOT_CARTON_MULTIPLE: "Not a whole number of cartons.",
  BELOW_ORDER_VALUE_RECOMMENDATION: "Below the recommended order quantity.",
};
const KIND: Record<QuoteLine["line_type"], string> = { catalog: "Catalogue", custom: "Custom product", manual: "Charge" };
const LINE_CONFLICT = "Someone changed this quotation while you were editing. The latest version is shown; check the line and save again.";

const advisoriesOf = (line: QuoteLine) => line.advisories.map((code) => ADVISORY[code]).filter((text): text is string => Boolean(text));

function columns(quote: QuoteDetail): Column<QuoteLine>[] {
  return [
    {
      key: "item",
      header: "Line",
      primary: true,
      cell: (line) => (
        <span className="flex min-w-0 items-start gap-3">
          <span className="t-caption lk-tnum mt-0.5 w-5 flex-none text-right text-ink-3">{line.line_no}</span>
          <span className="flex min-w-0 flex-col gap-1">
            <span className="t-label text-ink">{line.description}</span>
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              {line.product_key ? <Code>{line.product_key}</Code> : <span className="t-caption text-ink-3">{KIND[line.line_type]}</span>}
              {line.is_overridden ? (
                <Badge tone="amber" size="sm">
                  Price changed
                </Badge>
              ) : null}
            </span>
            {line.recommendation?.label ? <span className="t-caption text-ink-3">{line.recommendation.label}</span> : null}
            {advisoriesOf(line).map((text) => (
              <span key={text} className="t-caption flex items-start gap-1.5 text-amber-text">
                <Icon name="alert" size={14} className="mt-px flex-none" />
                {text}
              </span>
            ))}
            {line.is_overridden && line.override_reason ? <span className="t-caption text-ink-3">Reason: {line.override_reason}</span> : null}
          </span>
        </span>
      ),
    },
    { key: "quantity", header: "Quantity", numeric: true, width: "140px", cell: (line) => <Qty value={{ value: line.quantity, uom: line.unit_code }} /> },
    {
      key: "price",
      header: "Unit price",
      numeric: true,
      width: "150px",
      cell: (line) => (
        <span className="flex flex-col items-end">
          <UnitPrice amount={line.unit_price} currency={quote.currency} />
          {line.is_overridden && line.default_unit_price ? (
            <span className="t-caption text-ink-3">
              list <UnitPrice amount={line.default_unit_price} currency={quote.currency} />
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "total",
      header: "Line total",
      numeric: true,
      width: "160px",
      cell: (line) => <Money value={line.line_total ? { amount: line.line_total, currency: quote.currency } : null} className="t-label text-ink" />,
    },
  ];
}

/** The lines and the totals. Adding or editing a line happens in a drawer, one decision per step. */
export function LinesView({ quote, editable, commands }: { quote: QuoteDetail; editable: boolean; commands: QuoteCommands }) {
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const editing = quote.lines.find((line) => line.id === editingId) ?? null;
  const canExport = quote.capabilities.export_lines?.allowed === true;
  const status = quotationStatus(quote.status).label.toLowerCase();

  return (
    <div className="stack">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="t-h3">Lines</h2>
          <p className="t-body-sm text-ink-3">
            {editable
              ? "Open a line to change its quantity or price. Totals are worked out by the server each time."
              : `Lines are locked while the quotation is ${status}.${quote.status === "sent" ? " Revise it to change them." : ""}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canExport && quote.lines.length > 0 ? (
            <ButtonLink external href={quoteLinesCsvHref(quote.id)} download variant="ghost" size="sm" iconLeft="download">
              Lines as CSV
            </ButtonLink>
          ) : null}
          {editable && quote.lines.length > 0 ? (
            <Button variant="inverse" iconLeft="plus" onPress={() => setAdding(true)} isDisabled={Boolean(commands.offline)}>
              Add line
            </Button>
          ) : null}
        </div>
      </div>

      <GlassPanel padding="none" className="min-w-0">
        <DataTable
          label={`Lines of ${quote.quote_number}`}
          columns={columns(quote)}
          rows={quote.lines}
          rowKey={(line) => line.id}
          onRowAction={editable ? (line) => setEditingId(line.id) : undefined}
          selectedKey={editingId ?? undefined}
          empty={
            <EmptyState
              icon="list"
              title="No lines yet"
              text={editable ? "Add a catalogue product, a custom product or a charge. Each one is priced for this customer as it goes in." : "This quotation was closed without lines."}
              actions={
                editable ? (
                  <Button iconLeft="plus" onPress={() => setAdding(true)} isDisabled={Boolean(commands.offline)}>
                    Add the first line
                  </Button>
                ) : undefined
              }
            />
          }
        />
      </GlassPanel>

      {quote.lines.length > 0 ? (
        <div className="flex justify-end">
          <QuotationTotals quote={quote} className="w-full md:max-w-md" />
        </div>
      ) : null}

      {editable ? <LineAddDrawer quote={quote} commands={commands} isOpen={adding} onOpenChange={setAdding} /> : null}
      {editable && editing ? (
        <LineEditDrawer key={editing.id} quote={quote} line={editing} commands={commands} onClose={() => setEditingId(null)} />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------

function LineEditDrawer({ quote, line, commands, onClose }: { quote: QuoteDetail; line: QuoteLine; commands: QuoteCommands; onClose: () => void }) {
  const [edit, setEdit] = useState<LineEdit>(() => lineEditOf(line));
  const [error, setError] = useState<"quantity" | "price" | "reason" | null>(null);
  const [removing, setRemoving] = useState(false);
  const dirty = lineEditIsDirty(line, edit);
  const differs = priceDiffersFromList(line, edit.unit_price);

  // The server's own preview of this edit, a moment after typing stops.
  const request = previewRequest(quote, { [line.id]: edit });
  const signature = useDebouncedValue(request ? JSON.stringify(request) : null, 400);
  const preview = useQuery({
    queryKey: queryKeys.sales.quotePreview(quote.id, signature ?? ""),
    queryFn: ({ signal }) => previewQuote(JSON.parse(signature!) as NonNullable<typeof request>, signal),
    enabled: signature !== null,
    staleTime: 30_000,
  });
  const live = request && preview.data && signature === JSON.stringify(request) ? preview.data : null;
  const lineTotal = live ? (live.line_totals[line.line_key] ?? null) : line.line_total;

  const save = async () => {
    const plan = lineUpdatePlan(line, edit);
    if (!plan.ok) {
      setError(plan.error);
      return;
    }
    setError(null);
    if (Object.keys(plan.body).length === 0) {
      onClose();
      return;
    }
    const outcome = await commands.run("update_line", [line.id, quote.version, JSON.stringify(plan.body)], (key) => updateQuoteLine(quote, line.id, plan.body, key), {
      done: "Line saved",
      failed: "The line was not saved",
      conflictMessage: LINE_CONFLICT,
    });
    if (outcome.ok) onClose();
  };

  const remove = async () => {
    const outcome = await commands.run("remove_line", [line.id, quote.version], (key) => removeQuoteLine(quote, line.id, key), {
      done: "Line removed",
      failed: "The line was not removed",
      conflictMessage: LINE_CONFLICT,
    });
    if (outcome.ok) onClose();
    else throw outcome.error;
  };

  const busy = commands.pending !== null;
  return (
    <>
      <Drawer
        isOpen
        onOpenChange={(open) => (open ? undefined : onClose())}
        title={`Line ${line.line_no}`}
        description={[line.description, line.product_key].filter(Boolean).join(" · ")}
        footer={
          <>
            <Button variant="ghost" iconLeft="trash" className="mr-auto" onPress={() => setRemoving(true)} isDisabled={busy || Boolean(commands.offline)}>
              Remove line
            </Button>
            <Button variant="ghost" onPress={onClose}>
              {dirty ? "Discard" : "Close"}
            </Button>
            <Button onPress={() => void save()} loading={commands.pending === "update_line"} isDisabled={!dirty || Boolean(commands.offline)}>
              Save line
            </Button>
          </>
        }
      >
        <form
          className="flex flex-col gap-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          {advisoriesOf(line).length > 0 ? (
            <Banner tone="amber">
              {advisoriesOf(line).join(" ")}
            </Banner>
          ) : null}
          {line.recommendation?.explanation ? <p className="t-body-sm text-ink-3">{line.recommendation.explanation}</p> : null}
          <DecimalField
            label="Quantity"
            value={edit.quantity ?? ""}
            onChange={(value) => setEdit((current) => ({ ...current, quantity: value || null }))}
            suffix={line.unit_code || undefined}
            maxFractionDigits={4}
            isRequired
            error={error === "quantity" ? "Enter a quantity above zero." : undefined}
          />
          <DecimalField
            label="Unit price"
            value={edit.unit_price ?? ""}
            onChange={(value) => setEdit((current) => ({ ...current, unit_price: value || null }))}
            prefix={quote.currency}
            maxFractionDigits={4}
            help={
              line.default_unit_price ? (
                <>
                  List price <UnitPrice amount={line.default_unit_price} currency={quote.currency} />. Enter it again to drop a changed price.
                </>
              ) : undefined
            }
            error={error === "price" ? "Enter the price per unit." : undefined}
          />
          {differs ? (
            <TextField
              label="Why does the price differ from the list?"
              value={edit.override_reason}
              onChange={(value) => setEdit((current) => ({ ...current, override_reason: value }))}
              maxLength={500}
              isRequired
              help="A changed price sends the quotation for approval. The approver reads this."
              error={error === "reason" ? "Say why the price differs from the list price." : undefined}
            />
          ) : null}

          <dl className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4" aria-live="polite">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="t-body-sm text-ink-2">This line</dt>
              <dd className="t-stat-sm text-ink">
                <Money value={lineTotal ? { amount: lineTotal, currency: quote.currency } : null} />
              </dd>
            </div>
            <div className="hairline-top flex items-baseline justify-between gap-4 pt-3">
              <dt className="t-body-sm text-ink-2">Quotation total</dt>
              <dd className="t-stat text-ink">
                <Money value={live ? (live.grand_total ? { amount: live.grand_total, currency: quote.currency } : null) : quote.totals.grand_total} />
              </dd>
            </div>
            <p className="t-caption text-ink-3">
              {!dirty
                ? "As saved."
                : live
                  ? "A preview of your change. Nothing is saved until you save the line."
                  : request && preview.isError
                    ? "A live preview is not available right now. The figures shown are the saved ones."
                    : request
                      ? "Working out the new totals…"
                      : "The saved figures. New totals appear once the line is saved."}
            </p>
          </dl>
          {/* Lets Enter in a field save the line. */}
          <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
        </form>
      </Drawer>
      <ConfirmDialog
        isOpen={removing}
        onOpenChange={setRemoving}
        tone="danger"
        title={`Remove line ${line.line_no}`}
        description={`${line.description} leaves the quotation and the totals are worked out again. You can add it back while this is a draft.`}
        confirmLabel="Remove line"
        onConfirm={remove}
      />
    </>
  );
}
