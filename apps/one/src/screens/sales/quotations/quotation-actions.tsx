"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { changeQuoteCurrency, deleteQuote, previewCurrencyChange, transitionQuote, type CurrencyPreviewLine } from "@/features/sales/api";
import type { QuoteDetail } from "@/features/sales/types";
import type { useQuoteCommand } from "@/features/sales/use-quote-command";
import { commandButtons, type CommandButton } from "@/features/sales/workspace-model";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { humanise, useDuplicateQuotation } from "~/data/sales-deals";
import { ErrorBlock } from "~/shell/states";
import { useSession } from "@/lib/session/context";
import { ProformaCreateDialog } from "../proforma/create-dialog";
import { Badge, Banner, Button, DatePicker, Modal, Select, SkeletonText, Textarea, toast, type IconName, type MenuItem } from "~/ui";
import { ReasonModal, UnitPrice } from "./parts";

export type QuoteCommands = ReturnType<typeof useQuoteCommand>;

const LABEL: Record<string, string> = {
  submit_review: "Request approval",
  withdraw_review: "Withdraw request",
  mark_sent: "Mark as sent",
  mark_won: "Mark as won",
  mark_lost: "Mark as lost",
  cancel: "Cancel quotation",
  delete: "Delete draft",
  revise: "Revise",
  discard_revision: "Discard revision",
  extend_validity: "Extend validity",
  archive: "Archive",
  unarchive: "Restore from archive",
  correct_status: "Correct status",
};

const DONE: Record<string, string> = {
  submit_review: "Approval requested. An approver has it in their Inbox.",
  withdraw_review: "Request withdrawn. The quotation is a draft again.",
  mark_sent: "Marked as sent. The issued revision and its PDF are under Documents.",
  mark_won: "Marked as won.",
  mark_lost: "Marked as lost.",
  cancel: "Quotation cancelled.",
  revise: "Revision opened. The issued revision stays as it was.",
  discard_revision: "Revision discarded. The quotation is back to its last issued revision.",
  extend_validity: "Validity extended.",
  archive: "Quotation archived.",
  unarchive: "Quotation restored from the archive.",
  correct_status: "Status corrected.",
};

const ICON: Record<string, IconName> = {
  submit_review: "badgeCheck",
  withdraw_review: "undo",
  mark_sent: "send",
  mark_won: "thumbsUp",
  mark_lost: "thumbsDown",
  cancel: "xCircle",
  delete: "trash",
  revise: "edit",
  discard_revision: "undo",
  extend_validity: "calendar",
  archive: "archive",
  unarchive: "undo",
  correct_status: "refresh",
};

/** What the confirmation says before a step that is hard to take back. */
const CONFIRM: Record<string, { title: string; description: string }> = {
  mark_sent: {
    title: "Mark this quotation as sent",
    description: "This issues a numbered revision with its PDF and locks lines and terms. To change the offer afterwards you revise it.",
  },
  mark_lost: { title: "Mark this quotation as lost", description: "The customer went another way. The reason helps the next quotation." },
  cancel: { title: "Cancel this quotation", description: "It stays on record with its number, but nothing more can be done with it." },
  delete: { title: "Delete this draft", description: "The draft and its lines are removed. Its number stays reserved and is not reused." },
  discard_revision: {
    title: "Discard this revision",
    description: "Your changes since the last issued revision are dropped. The quotation returns to what the customer last received.",
  },
};

const SURFACED = new Set(["revise", "withdraw_review", "unarchive"]);
const DANGER = new Set(["cancel", "mark_lost", "delete", "discard_revision"]);
const WANTS_CONFIRMATION = new Set(["mark_sent", "mark_lost", "cancel", "delete", "discard_revision"]);

export const transitionLabel = (action: string) => LABEL[action] ?? humanise(action);

export interface QuotationActions {
  /** The forward step the server allows right now (request approval, mark as sent, mark as won), if any. */
  forward: CommandButton | null;
  /** One secondary step worth showing beside it (revise, withdraw, restore). */
  surfaced: CommandButton | null;
  /** Everything else, for the "More" menu. */
  menu: MenuItem[];
  start: (button: CommandButton) => void;
  pending: string | null;
  dialogs: ReactNode;
}

/**
 * The quotation's commands, rendered only from what the server allows (`allowed_transitions`,
 * `capabilities`). One forward action leads; destructive ones sit last in the menu and always confirm.
 */
export function useQuotationActions(quote: QuoteDetail, commands: QuoteCommands): QuotationActions {
  const router = useRouter();
  const [asking, setAsking] = useState<CommandButton | null>(null);
  const [extending, setExtending] = useState(false);
  const [currencyOpen, setCurrencyOpen] = useState(false);
  const [proforma, setProforma] = useState<{ mode: "new" | "past"; round: number } | null>(null);
  const { permissionKeys } = useSession();
  const copy = useDuplicateQuotation(quote);
  const buttons = commandButtons(quote).map((button) => ({ ...button, label: transitionLabel(button.action) }));
  const offline = Boolean(commands.offline);

  const perform = async (button: CommandButton, reason: string | null): Promise<boolean> => {
    if (button.action === "delete") {
      const outcome = await commands.run(
        "delete",
        [quote.version],
        async (key) => {
          await deleteQuote(quote, key);
          return null;
        },
        { failed: "The draft was not deleted", conflictMessage: "This quotation changed. The actions shown are the ones allowed now." },
      );
      if (outcome.ok) {
        toast.success("Draft deleted", { description: "Its number stays reserved." });
        router.push("/sales/quotes");
      }
      return outcome.ok;
    }
    const outcome = await commands.run(
      button.action,
      [quote.version, reason],
      (key) => transitionQuote(quote, { action: button.action, ...(reason ? { reason } : {}) }, key),
      {
        done: DONE[button.action] ?? button.label,
        failed: `${button.label} did not go through`,
        conflictMessage: "This quotation changed. The actions shown are the ones allowed now.",
        invalidation: "sales.quote_transition",
      },
    );
    return outcome.ok;
  };

  const start = (button: CommandButton) => {
    if (offline) return;
    if (button.action === "extend_validity") setExtending(true);
    else if (button.requiresReason || WANTS_CONFIRMATION.has(button.action)) setAsking(button);
    else void perform(button, null);
  };

  const forward = buttons.find((button) => button.variant === "primary") ?? null;
  const surfaced = buttons.find((button) => SURFACED.has(button.action)) ?? null;
  const rest = buttons.filter((button) => button !== forward && button !== surfaced);
  const caps = quote.capabilities;

  const menu: MenuItem[] = [];
  for (const button of rest.filter((b) => !DANGER.has(b.action))) {
    menu.push({ id: button.action, label: button.label, icon: ICON[button.action], isDisabled: offline, onAction: () => start(button) });
  }
  if (caps.duplicate?.allowed) {
    menu.push({
      id: "duplicate",
      label: "Duplicate",
      icon: "copy",
      description: "A new draft with the same lines and prices",
      isDisabled: offline || copy.pending,
      onAction: () => void copy.duplicate("keep"),
    });
    menu.push({
      id: "duplicate-refresh",
      label: "Duplicate at today's prices",
      icon: "refresh",
      description: "A new draft, repriced from the current lists",
      isDisabled: offline || copy.pending,
      onAction: () => void copy.duplicate("refresh"),
    });
  }
  // proforma invoices (module 3): from a sent, revised or won quotation
  const piReady = ["sent", "revised", "won"].includes(quote.status);
  if (piReady && permissionKeys.has("sales.proforma.create")) {
    menu.push({
      id: "proforma",
      label: "Create proforma invoice",
      icon: "receipt",
      description: "A PI with these items, for the client to pay against",
      isDisabled: offline,
      onAction: () => setProforma((p) => ({ mode: "new", round: (p?.round ?? 0) + 1 })),
    });
    if (permissionKeys.has("sales.proforma.import")) {
      menu.push({
        id: "proforma-past",
        label: "Enter an issued PI",
        icon: "history",
        description: "A PI sent before Lamikraft One, with its original number",
        isDisabled: offline,
        onAction: () => setProforma((p) => ({ mode: "past", round: (p?.round ?? 0) + 1 })),
      });
    }
  }
  if (caps.change_currency?.allowed) {
    menu.push({ id: "currency", label: "Change currency", icon: "banknote", isDisabled: offline, onAction: () => setCurrencyOpen(true) });
  }
  const danger = rest.filter((b) => DANGER.has(b.action));
  if (danger.length > 0) {
    if (menu.length > 0) menu.push({ id: "sep-danger", separator: true });
    for (const button of danger) {
      menu.push({ id: button.action, label: button.label, icon: ICON[button.action], tone: "danger", isDisabled: offline, onAction: () => start(button) });
    }
  }

  const confirm = asking ? CONFIRM[asking.action] : undefined;
  const dialogs = (
    <>
      <ReasonModal
        isOpen={asking !== null}
        onOpenChange={(open) => (open ? undefined : setAsking(null))}
        title={confirm?.title ?? asking?.label ?? ""}
        description={confirm?.description ?? quote.quote_number}
        confirmLabel={asking?.label ?? ""}
        tone={asking && DANGER.has(asking.action) ? "danger" : "default"}
        reason={asking?.requiresReason ? "required" : asking && (asking.action === "delete" || asking.action === "mark_sent") ? "none" : "optional"}
        reasonHelp="Kept in the quotation's history."
        onConfirm={async (reason) => {
          if (!asking) return;
          if (await perform(asking, reason)) setAsking(null);
        }}
      />
      <ExtendValidityDialog quote={quote} commands={commands} isOpen={extending} onOpenChange={setExtending} />
      {proforma ? (
        <ProformaCreateDialog
          key={`proforma-${proforma.round}`}
          quote={{ id: quote.id, number: quote.quote_number, customer: quote.party.display_name }}
          mode={proforma.mode}
          isOpen
          onOpenChange={(open) => (open ? undefined : setProforma(null))}
        />
      ) : null}
      {caps.change_currency?.allowed ? <CurrencyDialog quote={quote} commands={commands} isOpen={currencyOpen} onOpenChange={setCurrencyOpen} /> : null}
    </>
  );

  return { forward, surfaced, menu, start, pending: commands.pending, dialogs };
}

// ---------------------------------------------------------------------------------------------

function ExtendValidityDialog({ quote, commands, isOpen, onOpenChange }: { quote: QuoteDetail; commands: QuoteCommands; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const [date, setDate] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const close = (open: boolean) => {
    if (!open) {
      setDate(null);
      setReason("");
      setError(null);
    }
    onOpenChange(open);
  };
  const confirm = async () => {
    if (!date) {
      setError("Choose the new last day the prices hold.");
      return;
    }
    const outcome = await commands.run(
      "extend_validity",
      [quote.version, date],
      (key) => transitionQuote(quote, { action: "extend_validity", valid_until: date, ...(reason.trim() ? { reason: reason.trim() } : {}) }, key),
      { done: DONE.extend_validity, failed: "The validity was not extended", conflictMessage: "This quotation changed. The actions shown are the ones allowed now." },
    );
    if (outcome.ok) close(false);
    else if (outcome.error instanceof ProblemError && outcome.error.status === 422) {
      setError(outcome.error.validationIssues[0]?.msg ?? outcome.error.detail ?? "Choose a later date, at most a year ahead.");
    }
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={close}
      size="sm"
      title="Extend the validity"
      description={`${quote.quote_number} keeps its prices; only the last day they hold moves.`}
      actions={
        <>
          <Button variant="ghost" onPress={() => close(false)}>
            Keep the date
          </Button>
          <Button variant="inverse" loading={commands.pending === "extend_validity"} isDisabled={Boolean(commands.offline)} onPress={() => void confirm()}>
            Extend validity
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <DatePicker
          label="Valid until"
          value={date}
          onChange={(value) => {
            setDate(value);
            setError(null);
          }}
          minValue={quote.valid_until ?? undefined}
          isRequired
          help="Later than today's date, at most a year ahead."
          error={error ?? undefined}
        />
        <Textarea label="Reason" optional rows={2} maxLength={500} value={reason} onChange={setReason} />
      </div>
    </Modal>
  );
}

const METHOD: Record<string, string> = { list: "From the price list", fx: "Approved exchange rate", custom_price: "Custom product price", none: "No price" };

function CurrencyDialog({ quote, commands, isOpen, onOpenChange }: { quote: QuoteDetail; commands: QuoteCommands; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
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
      done: `The quotation is now in ${target}.`,
      failed: "The currency was not changed",
      conflictMessage: "This quotation changed. The actions shown are the ones allowed now.",
    });
    if (outcome.ok) onOpenChange(false);
    else if (outcome.error instanceof ProblemError && outcome.error.code === "currency_change_blocked") {
      const lines = (outcome.error.problem as { lines?: unknown }).lines;
      setBlocked(Array.isArray(lines) ? (lines as CurrencyPreviewLine[]) : []);
    }
  };
  const lines = blocked ?? preview.data?.lines ?? [];
  const blockedCount = preview.data?.blocked_count ?? 0;
  const cannotApply = Boolean(preview.data && !preview.data.applicable);
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="lg"
      title="Change the currency"
      description={`${quote.quote_number} is in ${quote.currency}. Every line is repriced from a price list, the custom product's own price or an approved exchange rate. Nothing is relabelled.`}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Keep {quote.currency}
          </Button>
          <Button variant="inverse" loading={commands.pending === "change_currency"} isDisabled={Boolean(commands.offline) || cannotApply || preview.isPending} onPress={() => void apply()}>
            Change to {target}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Select
          label="New currency"
          options={CURRENCIES.filter((code) => code !== quote.currency).map((code) => ({ value: code, label: code }))}
          value={target}
          onChange={(value) => {
            setTarget(value);
            setBlocked(null);
          }}
        />
        {preview.isPending ? (
          <SkeletonText lines={4} />
        ) : preview.isError ? (
          <ErrorBlock error={preview.error} what="The new prices" onRetry={() => void preview.refetch()} />
        ) : (
          <>
            {blockedCount > 0 ? (
              <Banner tone="ember" title={blockedCount === 1 ? "1 line has no price in that currency." : `${blockedCount} lines have no price in that currency.`}>
                Add a price or an approved exchange rate for them, then try again.
              </Banner>
            ) : null}
            <ul aria-label="Line prices in the new currency" className="flex flex-col">
              {lines.map((line) => (
                <li key={line.line_id} className="hairline-top flex flex-col gap-1 py-3 first:border-t-0 first:pt-0">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <span className="t-label min-w-0 text-ink">
                      <span className="lk-tnum text-ink-3">{line.line_no}. </span>
                      {line.description}
                    </span>
                    <span className="t-body-sm flex items-baseline gap-2 text-ink-2">
                      <UnitPrice amount={line.from_unit_price} currency={quote.currency} />
                      <span aria-hidden="true">→</span>
                      <span className="sr-only">becomes</span>
                      <UnitPrice amount={line.to_unit_price} currency={target} className="t-label text-ink" />
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={line.status === "blocked" ? "ember" : "neutral"} size="sm">
                      {METHOD[line.method] ?? humanise(line.method)}
                    </Badge>
                    <span className="t-caption text-ink-3">{line.explanation}</span>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Modal>
  );
}
