"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { RailContent } from "@/components/shell/context-rail";
import { ComposerDock } from "@/components/shell/composer-dock";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Switch } from "@/components/ui/choice";
import { DescriptionList } from "@/components/ui/description-list";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { Select } from "@/components/ui/select";
import { Conflict, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { Composer } from "@/features/assistant/composer";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { conflictFromError, type ConflictInfo } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { formatDate } from "@/lib/format/time";
import { salesMessages as m } from "@/messages/sales";
import { deleteQuote, fetchQuote, fetchQuoteHistory, fetchQuoteRevisions, transitionQuote, updateQuoteHeader } from "./api";
import { QuoteStatusPill } from "./quote-list";
import { QuoteLines } from "./quote-lines";
import { INCOTERMS, PRICE_TYPES, type QuoteDetail } from "./types";
import { useQuoteCommand } from "./use-quote-command";
import {
  commandButtons,
  dirtyHeaderFields,
  headerChanges,
  headerFormOf,
  mergeHeaderConflict,
  reviewReasonsText,
  type CommandButton,
  type HeaderConflictState,
  type HeaderForm,
} from "./workspace-model";
import { useRecentRecord } from "@/lib/recent/recent-records";

/** The quote workspace: terms, lines, server totals, the allowed commands, history and revisions. */
export function QuoteWorkspace({ quoteId }: { quoteId: string }) {
  const query = useQuery({ queryKey: queryKeys.sales.quote(quoteId), queryFn: ({ signal }) => fetchQuote(quoteId, signal) });
  useRecentRecord("sales.quote", query.data?.id, query.isSuccess);
  if (query.isPending) return <Loading label={m.workspace.loading} variant="detail" />;
  if (query.isError) return <ErrorState error={query.error} what={m.workspace.loading} onRetry={() => void query.refetch()} />;
  return <Workspace quote={query.data} />;
}

function Workspace({ quote }: { quote: QuoteDetail }) {
  const commands = useQuoteCommand(quote.id);
  const editable = quote.status === "draft" && quote.capabilities.update?.allowed === true;
  const [header, setHeader] = useState<{ base: HeaderForm; form: HeaderForm; version: number } | null>(null);

  useScreenContribution({
    focus: { type: "sales.quote", id: quote.id, version: quote.version },
    related: [{ type: "parties.party", id: quote.party.id, version: null }],
    lists: [
      {
        key: "lines",
        rows: quote.lines.map((line) => ({ type: "sales.quote_line", id: line.id, version: quote.version, ordinal: line.line_no })),
      },
    ],
    draft: header
      ? {
          form_key: "sales.quote.header",
          record_ref: quote.id,
          dirty_fields: dirtyHeaderFields(header.base, header.form),
          values: Object.fromEntries(dirtyHeaderFields(header.base, header.form).map((field) => [field, header.form[field]])),
        }
      : null,
  });

  return (
    <div className="flex flex-col gap-8 pb-40 md:pb-0">
      <header className="flex flex-col gap-2">
        <Link href="/sales/quotes" className="text-sm">
          {m.workspace.back}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-[26px] leading-tight font-bold tracking-tight text-ink md:text-3xl">{quote.quote_number}</h1>
          <QuoteStatusPill status={quote.status} />
        </div>
        <p className="text-ink">
          {quote.party.display_name}
          <span className="text-ink-muted">
            {" "}
            · {quote.party.party_number} · {quote.currency}
          </span>
        </p>
        {m.workspace.origin[quote.origin] ? <p className="text-sm text-ink-muted">{m.workspace.origin[quote.origin]}</p> : null}
      </header>

      <ReviewBanner quote={quote} />

      <HeaderSection quote={quote} editable={editable} commands={commands} onDraft={setHeader} />

      <QuoteLines quote={quote} editable={editable} commands={commands} />

      <Commands quote={quote} commands={commands} />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <Revisions quote={quote} />
        <History quote={quote} />
      </div>

      <RailContent>
        <QuoteContext quote={quote} />
      </RailContent>

      <section aria-label={m.workspace.dock} className="flex flex-col gap-2 border-t pt-6">
        <h2 className="text-lg font-[650] text-ink max-md:sr-only">{m.workspace.dock}</h2>
        <ComposerDock>
          <Composer variant="dock" />
        </ComposerDock>
      </section>
    </div>
  );
}

function ReviewBanner({ quote }: { quote: QuoteDetail }) {
  const review = quote.review;
  if (!review.requires_approval && !review.review_proposal_id) return null;
  const proposalId = review.review_proposal_id ?? review.approved_proposal_id;
  return (
    <div className="flex flex-col gap-1 rounded-md border border-warning-text/40 bg-warning-bg px-4 py-3 text-ink" role="note">
      {review.approval_current ? (
        <p>{m.workspace.reviewApproved}</p>
      ) : review.review_proposal_id ? (
        <p>{m.workspace.reviewPending}</p>
      ) : (
        <p>{m.workspace.reviewNeeded(reviewReasonsText(review.reasons))}</p>
      )}
      {proposalId ? (
        <Link href={`/inbox/approvals/${encodeURIComponent(proposalId)}`} className="text-sm">
          {m.workspace.reviewOpen}
        </Link>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Terms (header) with the 409 three-way state

function HeaderSection({
  quote,
  editable,
  commands,
  onDraft,
}: {
  quote: QuoteDetail;
  editable: boolean;
  commands: ReturnType<typeof useQuoteCommand>;
  onDraft: (draft: { base: HeaderForm; form: HeaderForm; version: number } | null) => void;
}) {
  const titleId = useId();
  const { zone } = useSession();
  const [state, setState] = useState<{ base: HeaderForm; form: HeaderForm; version: number }>(() => {
    const base = headerFormOf(quote);
    return { base, form: base, version: quote.version };
  });
  const [conflict, setConflict] = useState<{ info: ConflictInfo; merge: HeaderConflictState } | null>(null);
  const dirty = dirtyHeaderFields(state.base, state.form);

  // A newer server version with no local edits: show it (someone else, or a line command, changed the quote).
  if (quote.version !== state.version && dirty.length === 0 && !conflict) {
    const base = headerFormOf(quote);
    setState({ base, form: base, version: quote.version });
  }

  const update = (next: { base: HeaderForm; form: HeaderForm; version: number }) => {
    setState(next);
    onDraft(dirtyHeaderFields(next.base, next.form).length > 0 ? next : null);
  };
  const set = <K extends keyof HeaderForm>(field: K, value: HeaderForm[K]) => update({ ...state, form: { ...state.form, [field]: value } });

  const save = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const changes = headerChanges(state.base, state.form);
    if (Object.keys(changes).length === 0) return;
    const target = { id: quote.id, version: state.version };
    await commands.run("update_header", [state.version, JSON.stringify(changes)], (key) => updateQuoteHeader(target, changes, key), {
      done: m.workspace.saved,
      failed: m.workspace.failed(m.workspace.save),
      onConflict: async (error) => {
        const info = conflictFromError(error)!;
        const fresh = await fetchQuote(quote.id);
        const merge = mergeHeaderConflict(state.base, state.form, fresh, { changedBy: info.changedBy, changedAt: info.changedAt });
        setConflict({ info, merge });
        update({ base: merge.base, form: merge.form, version: merge.version });
        void commands.reload();
      },
    }).then((outcome) => {
      if (outcome.ok) {
        const fresh = outcome.quote ?? quote;
        const base = headerFormOf(fresh);
        setConflict(null);
        update({ base, form: base, version: fresh.version });
      }
    });
  };

  const discardMine = () => {
    const base = conflict ? conflict.merge.base : headerFormOf(quote);
    setConflict(null);
    update({ base, form: base, version: conflict ? conflict.merge.version : quote.version });
  };

  const label = (field: string) => m.workspace.fieldLabels[field] ?? field;
  if (!editable) {
    // Outside draft the terms are a record, not a form: disabled empty inputs read as missing data.
    const terms = headerFormOf(quote);
    const shown = (value: string | null | undefined) => (value && value.trim() !== "" ? value : "—");
    return (
      <section aria-labelledby={titleId} className="flex flex-col gap-4">
        <h2 id={titleId} className="text-lg font-[650] text-ink">
          {m.workspace.header}
        </h2>
        <DescriptionList
          items={[
            { term: label("price_type"), description: m.priceTypes[terms.price_type] ?? terms.price_type },
            { term: label("incoterm"), description: [terms.incoterm, terms.incoterm_place].filter(Boolean).join(" · ") || "—" },
            { term: label("payment_terms"), description: shown(terms.payment_terms) },
            { term: label("validity_days"), description: shown(terms.validity_days), numeric: true },
            { term: label("customer_reference"), description: shown(terms.customer_reference) },
            { term: label("remarks"), description: <span className="whitespace-pre-line">{shown(terms.remarks)}</span> },
            { term: label("apply_minimum_surcharge"), description: terms.apply_minimum_surcharge ? m.workspace.surchargeOn : m.workspace.surchargeOff },
          ]}
        />
        {quote.valid_until ? (
          <p className="text-sm text-ink-muted">
            {m.workspace.validUntil}: <LocalDate value={quote.valid_until} />
          </p>
        ) : null}
      </section>
    );
  }
  const disabled = !editable;
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-4">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.workspace.header}
      </h2>
      {conflict ? (
        <div className="flex flex-col gap-2">
          <Conflict
            conflict={conflict.info}
            changedAtLabel={conflict.info.changedAt ? formatDate(conflict.info.changedAt, zone) : null}
            onReview={discardMine}
            onKeepMine={() => void save()}
          />
          <p className="text-sm text-ink">
            {conflict.merge.conflicts.length > 0
              ? m.workspace.conflictFields(conflict.merge.conflicts.map(label).join(", "))
              : m.workspace.conflictNone}
          </p>
          {conflict.merge.adopted.length > 0 ? <p className="text-sm text-ink-muted">{m.workspace.conflictAdopted(conflict.merge.adopted.map(label).join(", "))}</p> : null}
        </div>
      ) : null}
      <Form onSubmit={(event) => void save(event)} className="flex flex-col gap-4" validationBehavior="aria">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Select
            label={label("price_type")}
            options={PRICE_TYPES.map((type) => ({ id: type, label: m.priceTypes[type] ?? type }))}
            value={state.form.price_type}
            onChange={(value) => set("price_type", PRICE_TYPES.find((type) => type === value) ?? state.form.price_type)}
            isDisabled={disabled}
          />
          <Select
            label={label("incoterm")}
            options={[{ id: "", label: m.create.noIncoterm }, ...INCOTERMS.map((term) => ({ id: term, label: term }))]}
            value={state.form.incoterm ?? ""}
            onChange={(value) => set("incoterm", value || null)}
            isDisabled={disabled}
          />
          <TextField label={label("incoterm_place")} value={state.form.incoterm_place} onChange={(value) => set("incoterm_place", value)} maxLength={120} isDisabled={disabled} />
          <TextField label={label("payment_terms")} value={state.form.payment_terms} onChange={(value) => set("payment_terms", value)} maxLength={200} isDisabled={disabled} />
          <NumberField label={label("validity_days")} value={state.form.validity_days} onChange={(value) => set("validity_days", value)} maxFractionDigits={0} isDisabled={disabled} />
          <TextField label={label("customer_reference")} value={state.form.customer_reference} onChange={(value) => set("customer_reference", value)} maxLength={120} isDisabled={disabled} />
        </div>
        <TextArea label={label("remarks")} value={state.form.remarks} onChange={(value) => set("remarks", value)} isDisabled={disabled} />
        <Switch isSelected={state.form.apply_minimum_surcharge} onChange={(value) => set("apply_minimum_surcharge", value)} isDisabled={disabled}>
          {m.create.surcharge}
        </Switch>
        {editable ? (
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              variant={dirty.length > 0 ? "primary" : "secondary"}
              isPending={commands.pending === "update_header"}
              pendingLabel={m.workspace.saving}
              {...unavailableWhen(commands.offline ?? (dirty.length === 0 ? m.workspace.noChanges : null))}
            >
              {m.workspace.save}
            </Button>
            {dirty.length > 0 ? (
              <Button variant="quiet" onPress={discardMine}>
                {m.workspace.discard}
              </Button>
            ) : null}
          </div>
        ) : null}
      </Form>
      {quote.valid_until ? (
        <p className="text-sm text-ink-muted">
          {m.workspace.validUntil}: <LocalDate value={quote.valid_until} />
        </p>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------------------------
// Commands: only what `allowed_transitions` (and `capabilities.delete`) offer

function Commands({ quote, commands }: { quote: QuoteDetail; commands: ReturnType<typeof useQuoteCommand> }) {
  const router = useRouter();
  const titleId = useId();
  const [asking, setAsking] = useState<CommandButton | null>(null);
  const buttons = commandButtons(quote);

  const perform = async (button: CommandButton, reason: string | null) => {
    if (button.action === "delete") {
      const outcome = await commands.run("delete", [quote.version], async (key) => {
        await deleteQuote(quote, key);
        return null;
      }, { failed: m.workspace.failed(button.label), conflictMessage: m.workspace.transitionConflict });
      if (outcome.ok) {
        toast.success(m.workspace.deleted);
        router.push("/sales/quotes");
      }
      return;
    }
    await commands.run(
      button.action,
      [quote.version, reason],
      (key) => transitionQuote(quote, { action: button.action, ...(reason ? { reason } : {}) }, key),
      {
        done: m.workspace.transitionDone[button.action] ?? button.label,
        failed: m.workspace.failed(button.label),
        conflictMessage: m.workspace.transitionConflict,
        invalidation: "sales.quote_transition",
      },
    );
    setAsking(null);
  };

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.workspace.actions}
      </h2>
      {buttons.length === 0 ? (
        <p className="text-ink-muted">{m.workspace.noTransitions}</p>
      ) : (
        <div className="flex flex-wrap gap-2" data-testid="quote-commands">
          {buttons.map((button) => (
            <Button
              key={button.action}
              variant={button.variant}
              isPending={commands.pending === button.action}
              pendingLabel={m.workspace.saving}
              onPress={() => (button.requiresReason || button.action === "delete" ? setAsking(button) : void perform(button, null))}
              {...unavailableWhen(commands.offline)}
            >
              {button.label}
            </Button>
          ))}
        </div>
      )}
      {commands.offline ? <p className="text-sm text-warning-text">{commands.offline}</p> : null}
      <ReasonDialog
        title={asking?.label ?? ""}
        description={quote.quote_number}
        requireNote={asking?.requiresReason ?? false}
        noteLabel={m.workspace.reasonLabel}
        confirmLabel={asking?.label ?? ""}
        isOpen={asking !== null}
        isPending={commands.pending !== null}
        disabledReason={commands.offline}
        onOpenChange={(open) => (open ? null : setAsking(null))}
        onConfirm={(_, note) => (asking ? void perform(asking, note || null) : undefined)}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------------------------
// Revisions, history and the context rail

function Revisions({ quote }: { quote: QuoteDetail }) {
  const titleId = useId();
  const query = useQuery({
    queryKey: queryKeys.sales.quoteRevisions(quote.id),
    queryFn: ({ signal }) => fetchQuoteRevisions(quote.id, signal),
  });
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.workspace.revisions}
      </h2>
      {query.isPending ? (
        <Loading label={m.workspace.revisions} variant="inline" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.workspace.revisions} onRetry={() => void query.refetch()} headingLevel={3} compact backToToday={false} />
      ) : query.data.length === 0 ? (
        <p className="text-ink-muted">{m.workspace.noRevisions}</p>
      ) : (
        <ul className="flex flex-col divide-y border-y">
          {query.data.map((revision) => (
            <li key={revision.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div className="flex flex-col">
                <span className="font-semibold text-ink">{m.workspace.revisionLabel(revision.revision_no)}</span>
                <span className="text-sm text-ink-muted">
                  <LocalDateTime value={revision.issued_at} />
                  {revision.valid_until ? (
                    <>
                      {" · "}
                      {m.workspace.validUntil} <LocalDate value={revision.valid_until} />
                    </>
                  ) : null}
                </span>
              </div>
              {/* A real link: the PDF streams from the API (inline, sandboxed), not a page. */}
              <a href={revision.document_path} className={linkClasses} type="application/pdf">
                {m.workspace.pdf(revision.revision_no)}
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function History({ quote }: { quote: QuoteDetail }) {
  const titleId = useId();
  const query = useQuery({
    queryKey: queryKeys.sales.quoteHistory(quote.id),
    queryFn: ({ signal }) => fetchQuoteHistory(quote.id, signal),
  });
  const status = (code: string) => m.status[code] ?? code;
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.workspace.history}
      </h2>
      {query.isPending ? (
        <Loading label={m.workspace.history} variant="inline" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.workspace.history} onRetry={() => void query.refetch()} headingLevel={3} compact backToToday={false} />
      ) : query.data.length === 0 ? (
        <p className="text-ink-muted">{m.workspace.noHistory}</p>
      ) : (
        <ol className="flex flex-col divide-y border-y">
          {query.data.map((entry) => (
            <li key={entry.id} className="flex flex-col gap-0.5 py-3">
              <span className="text-ink">{m.workspace.historyLine(status(entry.from_status), status(entry.to_status))}</span>
              <span className="text-sm text-ink-muted">
                <LocalDateTime value={entry.occurred_at} />
                {entry.actor?.display_name ? ` · ${entry.actor.display_name}` : null}
              </span>
              {entry.reason ? <span className="text-sm text-ink">{entry.reason}</span> : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function QuoteContext({ quote }: { quote: QuoteDetail }) {
  const snapshot = quote.party_snapshot;
  return (
    <div className="flex flex-col gap-4 text-sm">
      <h2 className="text-base font-[650] text-ink">{m.workspace.context}</h2>
      <DescriptionList
        items={[
          { term: m.workspace.customer, description: snapshot ? `${snapshot.display_name} (${snapshot.country_code})` : quote.party.display_name },
          ...(snapshot?.contact_name ? [{ term: m.workspace.contact, description: [snapshot.contact_name, snapshot.contact_email].filter(Boolean).join(" · ") }] : []),
          { term: m.workspace.owner, description: quote.owner.display_name ?? "—" },
          { term: m.workspace.created, description: <LocalDateTime value={quote.created_at} /> },
        ]}
      />
      {quote.enquiry_id ? (
        <Link href={`/sales/enquiries/${encodeURIComponent(quote.enquiry_id)}`}>{m.workspace.openEnquiry}</Link>
      ) : null}
      {quote.origin_message_id ? <Link href="/sales/customer-messages">{m.workspace.openMessages}</Link> : null}
    </div>
  );
}
