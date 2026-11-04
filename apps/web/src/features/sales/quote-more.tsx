"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { Dialog } from "@/components/ui/dialog";
import { Money } from "@/components/ui/format";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { Select } from "@/components/ui/select";
import { ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { salesMessages as m } from "@/messages/sales";
import {
  changeQuoteCurrency,
  compareRevisions,
  duplicateQuote,
  previewCurrencyChange,
  quoteLinesCsvHref,
  restoreRevision,
  transitionQuote,
  type CurrencyPreviewLine,
} from "./api";
import { problemDescription, type useQuoteCommand } from "./use-quote-command";
import type { QuoteDetail } from "./types";

const x = m.workspace.more;
const cmp = m.workspace.compare;
type Commands = ReturnType<typeof useQuoteCommand>;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Duplicate, currency change and the lines CSV: each shown only when the server's capabilities allow it. */
export function MoreActions({ quote, commands }: { quote: QuoteDetail; commands: Commands }) {
  const router = useRouter();
  const titleId = useId();
  const [refresh, setRefresh] = useState(false);
  const [currencyOpen, setCurrencyOpen] = useState(false);
  const [keys] = useState(() => createCommandKeys());
  const [duplicating, setDuplicating] = useState(false);
  const caps = quote.capabilities;
  const canDuplicate = caps.duplicate?.allowed === true;
  const canCurrency = caps.change_currency?.allowed === true;
  const canLines = caps.export_lines?.allowed === true;
  const expired = quote.is_expired === true;
  if (!canDuplicate && !canCurrency && !canLines && !expired) return null;

  const duplicate = async () => {
    const body = { price_mode: refresh ? ("refresh" as const) : ("keep" as const) };
    const signature = commandSignature(quote.id, "duplicate", quote.version, body.price_mode);
    const attempt = keys.attempt(signature, () => body);
    setDuplicating(true);
    try {
      const copy = await duplicateQuote(quote.id, attempt.payload, attempt.key);
      keys.settle(signature);
      toast.success(x.duplicated(copy.quote_number));
      router.push(copy.path as Parameters<typeof router.push>[0]);
    } catch (error) {
      keys.settle(signature, error);
      toast.error(m.workspace.failed(x.duplicate), { description: problemDescription(error) });
    } finally {
      setDuplicating(false);
    }
  };

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {x.title}
      </h2>
      {expired ? (
        <p role="note" className="text-sm text-warning-text">
          {x.expired}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3" data-testid="quote-more">
        {canDuplicate ? (
          <>
            <Button variant="secondary" onPress={() => void duplicate()} isPending={duplicating} {...unavailableWhen(commands.offline)}>
              {x.duplicate}
            </Button>
            <Checkbox isSelected={refresh} onChange={setRefresh}>
              {x.refreshPrices}
            </Checkbox>
          </>
        ) : null}
        {canCurrency ? (
          <Button variant="secondary" onPress={() => setCurrencyOpen(true)} {...unavailableWhen(commands.offline)}>
            {x.changeCurrency}
          </Button>
        ) : null}
        {canLines ? (
          <a href={quoteLinesCsvHref(quote.id)} className={linkClasses} download>
            {x.linesCsv}
          </a>
        ) : null}
      </div>
      {canCurrency ? <CurrencyDialog quote={quote} commands={commands} isOpen={currencyOpen} onOpenChange={setCurrencyOpen} /> : null}
    </section>
  );
}

function CurrencyDialog({ quote, commands, isOpen, onOpenChange }: { quote: QuoteDetail; commands: Commands; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const [target, setTarget] = useState<string>(CURRENCIES.find((code) => code !== quote.currency) ?? "EUR");
  const [blocked, setBlocked] = useState<CurrencyPreviewLine[] | null>(null);
  const preview = useQuery({
    queryKey: queryKeys.sales.currencyPreview(quote.id, target),
    queryFn: ({ signal }) => previewCurrencyChange(quote.id, target, signal),
    enabled: isOpen && target !== quote.currency,
  });
  const apply = async () => {
    setBlocked(null);
    const outcome = await commands.run("change_currency", [quote.version, target], (key) => changeQuoteCurrency(quote, target, key), {
      done: x.currencyDone(target),
      failed: m.workspace.failed(x.currencyApply),
      conflictMessage: m.workspace.transitionConflict,
    });
    if (outcome.ok) onOpenChange(false);
    else if (outcome.error instanceof ProblemError && outcome.error.code === "currency_change_blocked") {
      const lines = (outcome.error.problem as { lines?: unknown }).lines;
      setBlocked(Array.isArray(lines) ? (lines as CurrencyPreviewLine[]) : []);
    }
  };
  const lines = blocked ?? preview.data?.lines ?? [];
  return (
    <Dialog
      title={x.currencyTitle}
      description={`${quote.quote_number} · ${quote.currency}`}
      size="lg"
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onPress={() => void apply()}
            isPending={commands.pending === "change_currency"}
            {...unavailableWhen(commands.offline ?? (preview.data && !preview.data.applicable ? x.currencyBlocked(preview.data.blocked_count) : null))}
          >
            {x.currencyApply}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-ink-muted">{x.currencyIntro}</p>
        <Select
          label={x.currencyTo}
          options={CURRENCIES.filter((code) => code !== quote.currency).map((code) => ({ id: code, label: code }))}
          value={target}
          onChange={(value) => (value ? (setTarget(value), setBlocked(null)) : null)}
        />
        {preview.isPending ? (
          <Loading label={x.currencyTitle} variant="inline" />
        ) : preview.isError ? (
          <ErrorState error={preview.error} what={x.currencyTitle} compact headingLevel={3} backToToday={false} onRetry={() => void preview.refetch()} />
        ) : (
          <>
            {preview.data && preview.data.blocked_count > 0 ? (
              <p role="alert" className="text-sm text-danger">
                {x.currencyBlocked(preview.data.blocked_count)}
              </p>
            ) : null}
            <ul className="flex flex-col divide-y border-y" aria-label={x.currencyTitle}>
              {lines.map((line) => (
                <li key={line.line_id} className="flex flex-col gap-0.5 py-2">
                  <span className="text-ink">
                    {line.line_no}. {line.description}
                  </span>
                  <span className="text-sm">
                    {line.from_unit_price ? <Money value={{ amount: line.from_unit_price, currency: quote.currency }} maxFractionDigits={4} /> : "—"} →{" "}
                    {line.to_unit_price ? <Money value={{ amount: line.to_unit_price, currency: target }} maxFractionDigits={4} /> : "—"} ·{" "}
                    <span className={line.status === "blocked" ? "text-danger" : "text-ink-muted"}>{x.currencyMethod[line.method] ?? line.method}</span>
                  </span>
                  <span className="text-xs text-ink-muted">{line.explanation}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Dialog>
  );
}

export function ExtendValidityDialog({ quote, commands, isOpen, onOpenChange }: { quote: QuoteDetail; commands: Commands; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const confirm = async () => {
    if (!ISO_DATE.test(date)) return setError("Use YYYY-MM-DD.");
    const outcome = await commands.run(
      "extend_validity",
      [quote.version, date],
      (key) => transitionQuote(quote, { action: "extend_validity", valid_until: date, ...(reason.trim() ? { reason: reason.trim() } : {}) }, key),
      { done: m.workspace.transitionDone.extend_validity, failed: m.workspace.failed(m.workspace.transitions.extend_validity!), conflictMessage: m.workspace.transitionConflict },
    );
    if (outcome.ok) onOpenChange(false);
    else if (outcome.error instanceof ProblemError && outcome.error.status === 422) setError(outcome.error.validationIssues[0]?.msg ?? outcome.error.detail ?? null);
  };
  return (
    <Dialog
      title={m.workspace.transitions.extend_validity!}
      description={quote.quote_number}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            Cancel
          </Button>
          <Button variant="primary" onPress={() => void confirm()} isPending={commands.pending === "extend_validity"} {...unavailableWhen(commands.offline)}>
            {m.workspace.transitions.extend_validity}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <TextField label={x.validUntil} description={x.validUntilHint} placeholder={quote.valid_until ?? "2026-12-31"} value={date} onChange={setDate} isRequired errorMessage={error ?? undefined} />
        <TextField label={m.workspace.reasonLabel} value={reason} onChange={setReason} maxLength={500} />
      </div>
    </Dialog>
  );
}

/** Restore an issued revision into the working copy (shown with `capabilities.restore`). */
export function RestoreRevisionButton({ quote, revisionNo }: { quote: QuoteDetail; revisionNo: number }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [keys] = useState(() => createCommandKeys());
  const queryClient = useQueryClient();
  if (quote.capabilities.restore?.allowed !== true) return null;
  const confirm = async (reason: string) => {
    const signature = commandSignature(quote.id, "restore", quote.version, revisionNo);
    const attempt = keys.attempt(signature, () => null);
    setPending(true);
    try {
      const fresh = await restoreRevision(quote, revisionNo, reason || null, attempt.key);
      keys.settle(signature);
      if (fresh) queryClient.setQueryData(queryKeys.sales.quote(quote.id), fresh);
      await queryClient.invalidateQueries({ queryKey: queryKeys.sales.all() });
      toast.success(cmp.restored(revisionNo));
      setOpen(false);
    } catch (error) {
      keys.settle(signature, error);
      toast.error(m.workspace.failed(cmp.restore(revisionNo)), { description: problemDescription(error) });
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <Button size="sm" variant="quiet" onPress={() => setOpen(true)}>
        {cmp.restore(revisionNo)}
      </Button>
      <ReasonDialog
        title={cmp.restoreTitle(revisionNo)}
        description={cmp.restoreIntro}
        noteLabel={m.workspace.reasonLabel}
        confirmLabel={cmp.restore(revisionNo)}
        isOpen={open}
        isPending={pending}
        onOpenChange={setOpen}
        onConfirm={(_, note) => void confirm(note)}
      />
    </>
  );
}

/** Header, lines by line_key and totals between two issued revisions, or a revision and the working copy. */
export function CompareRevisions({ quote, revisions }: { quote: QuoteDetail; revisions: number[] }) {
  const [from, setFrom] = useState<number>(revisions[0] ?? 1);
  const [to, setTo] = useState<number | null>(null);
  const [run, setRun] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.sales.quoteCompare(quote.id, from, to),
    queryFn: ({ signal }) => compareRevisions(quote.id, from, to, signal),
    enabled: run,
  });
  const options = revisions.map((n) => ({ id: String(n), label: m.workspace.revisionLabel(n) }));
  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <h3 className="font-semibold text-ink">{cmp.title}</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Select label={cmp.from} options={options} value={String(from)} onChange={(value) => (value ? (setFrom(Number.parseInt(value, 10)), setRun(false)) : null)} />
        <Select label={cmp.to} options={[{ id: "", label: cmp.working }, ...options]} value={to === null ? "" : String(to)} onChange={(value) => (setTo(value ? Number.parseInt(value, 10) : null), setRun(false))} />
        <Button variant="secondary" onPress={() => setRun(true)}>
          {cmp.run}
        </Button>
      </div>
      {!run ? null : query.isPending ? (
        <Loading label={cmp.title} variant="inline" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={cmp.title} compact headingLevel={3} backToToday={false} onRetry={() => void query.refetch()} />
      ) : (
        <div className="flex flex-col gap-2 text-sm" aria-live="polite">
          <p className="font-semibold text-ink">{query.data.summary}</p>
          {query.data.header.length > 0 ? (
            <ul className="list-disc ps-5">
              {query.data.header.map((change) => (
                <li key={change.field}>
                  {m.workspace.fieldLabels[change.field] ?? change.field}: {String(change.before ?? "—")} → {String(change.after ?? "—")}
                </li>
              ))}
            </ul>
          ) : null}
          <ul className="flex flex-col divide-y border-y">
            {query.data.lines
              .filter((line) => line.change !== "unchanged")
              .map((line) => (
                <li key={line.line_key} className="py-1.5">
                  <span className="font-semibold">{cmp.change[line.change] ?? line.change}</span> · {line.description}
                  {line.changes.length > 0 ? (
                    <span className="text-ink-muted"> ({line.changes.map((c) => `${c.field}: ${String(c.before ?? "—")} → ${String(c.after ?? "—")}`).join("; ")})</span>
                  ) : null}
                </li>
              ))}
          </ul>
          <ul className="flex flex-col gap-0.5">
            {query.data.totals
              .filter((total) => total.delta !== null && total.delta !== "0.00")
              .map((total) => (
                <li key={total.field}>
                  {total.field.replace(/_/g, " ")}: {total.before ?? "—"} → {total.after ?? "—"} ({total.delta})
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  );
}
