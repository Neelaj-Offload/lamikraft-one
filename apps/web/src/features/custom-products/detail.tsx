"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useMemo, useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { DescriptionList } from "@/components/ui/description-list";
import { LocalDate, LocalDateTime, Money } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { Select } from "@/components/ui/select";
import { ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { TextArea, TextField } from "@/components/ui/text-field";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { useResourceCommand } from "@/features/sales/resource-command";
import { commercialMessages as c } from "@/messages/commercial";
import {
  archiveCustomProduct,
  createCustomProduct,
  decideSpecRevision,
  duplicateCustomProduct,
  executePromotion,
  fetchCosting,
  fetchCustomHistory,
  fetchCustomProduct,
  recordCosting,
  recordSpecRevision,
  requestPromotion,
  transitionCustomProduct,
  updateCustomProduct,
  type CustomProductDetail,
} from "./api";
import { CustomProductCreate, CustomProductFields, customBody, customFormOf, type CustomForm } from "./form";
import { CustomStatusPill } from "./list";

const m = c.customProducts;

/** The create page: posts the product and opens it. */
export function NewCustomProduct() {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const commands = useResourceCommand("custom_product:new", [queryKeys.sales.all()]);
  if (!permissionKeys.has("sales.custom_product.create")) return <PermissionDenied area={m.newProduct} />;
  const submit = async (body: Record<string, unknown>) => {
    const outcome = await commands.run("create", [JSON.stringify(body)], (key) => createCustomProduct(body, key), {
      failed: c.common.failed(m.create),
    });
    if (outcome.ok) {
      router.push(outcome.value.path as Parameters<typeof router.push>[0]);
      return {};
    }
    return outcome.fieldErrors;
  };
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <Link href="/sales/custom-products" className="text-sm">
          {m.back}
        </Link>
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.newProduct}</h1>
        <p className="text-ink-muted">{m.intro}</p>
      </header>
      <CustomProductCreate onSubmit={submit} pending={commands.pending === "create"} offline={commands.offline} />
    </div>
  );
}

export function CustomProductView({ customProductId }: { customProductId: string }) {
  const query = useQuery({ queryKey: queryKeys.sales.customProduct(customProductId), queryFn: ({ signal }) => fetchCustomProduct(customProductId, signal) });
  if (query.isPending) return <Loading label={m.loading} variant="detail" />;
  if (query.isError) {
    if (isProblemError(query.error) && query.error.status === 403) return <PermissionDenied area={m.title} />;
    return <ErrorState error={query.error} what={m.loading} onRetry={() => void query.refetch()} />;
  }
  return <Detail product={query.data} />;
}

function Detail({ product }: { product: CustomProductDetail }) {
  const router = useRouter();
  const keys = useMemo(() => [queryKeys.sales.customProduct(product.id), ["sales", "custom-products"], queryKeys.sales.customProductHistory(product.id)], [product.id]);
  const commands = useResourceCommand(`custom_product:${product.id}`, keys);
  const [asking, setAsking] = useState<{ action: string; label: string; requiresReason: boolean } | null>(null);
  const caps = product.capabilities;
  const allowed = (name: string) => caps[name]?.allowed === true;

  const perform = async (action: string, label: string, reason: string | null) => {
    if (action === "__archive" || action === "__unarchive") {
      await commands.run(action, [product.version, reason], () => archiveCustomProduct(product, action === "__archive", reason), {
        done: label,
        failed: c.common.failed(label),
        conflictMessage: c.common.conflict,
      });
    } else {
      await commands.run(action, [product.version, reason], () => transitionCustomProduct(product, action, reason), {
        done: label,
        failed: c.common.failed(label),
        conflictMessage: c.common.conflict,
      });
    }
    setAsking(null);
  };

  const duplicate = async () => {
    const outcome = await commands.run("duplicate", [product.version], (key) => duplicateCustomProduct(product.id, key), {
      failed: c.common.failed(m.duplicate),
    });
    if (outcome.ok) router.push(outcome.value.path as Parameters<typeof router.push>[0]);
  };

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <Link href="/sales/custom-products" className="text-sm">
          {m.back}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[26px] leading-tight font-bold tracking-tight text-ink md:text-3xl">
            <span className="font-mono">{product.custom_code}</span> · {product.product_name}
          </h1>
          <CustomStatusPill status={product.status} />
        </div>
        <p className="text-ink-muted">
          {m.types[product.custom_type] ?? product.custom_type}
          {product.party ? ` · ${product.party.display_name}` : product.legacy_customer_name ? ` · ${product.legacy_customer_name}` : ""}
          {product.owner.display_name ? ` · ${product.owner.display_name}` : ""}
        </p>
        {product.status_reason ? <p className="text-sm text-ink">{product.status_reason}</p> : null}
        {product.archived_at ? (
          <p role="note" className="rounded-md border px-3 py-2 text-sm text-ink">
            {m.archivedNote}
          </p>
        ) : null}
        {product.promoted_product_id ? (
          <p role="note" className="text-sm text-ink">
            {m.convertedNote} <Link href={`/products/${product.promoted_product_id}`}>{m.openProduct}</Link>
          </p>
        ) : null}
      </header>

      <section aria-label={m.sections.actions} className="flex flex-col gap-3">
        <h2 className="text-lg font-[650] text-ink">{m.sections.actions}</h2>
        <div className="flex flex-wrap gap-2" data-testid="custom-product-actions">
          {product.allowed_transitions.map((t) => (
            <Button
              key={t.action}
              variant={t.action === "reject" ? "danger" : t.action === "approve" ? "primary" : "secondary"}
              isPending={commands.pending === t.action}
              pendingLabel={c.common.saving}
              onPress={() => (t.requires_reason ? setAsking({ action: t.action, label: m.transitions[t.action] ?? c.human(t.action), requiresReason: true }) : void perform(t.action, m.transitions[t.action] ?? c.human(t.action), null))}
              {...unavailableWhen(commands.offline)}
            >
              {m.transitions[t.action] ?? c.human(t.action)}
            </Button>
          ))}
          {allowed("duplicate") ? (
            <Button variant="secondary" onPress={() => void duplicate()} isPending={commands.pending === "duplicate"} {...unavailableWhen(commands.offline)}>
              {m.duplicate}
            </Button>
          ) : null}
          {allowed("archive") ? (
            <Button variant="danger" onPress={() => setAsking({ action: "__archive", label: m.archive, requiresReason: false })} {...unavailableWhen(commands.offline)}>
              {m.archive}
            </Button>
          ) : null}
          {product.archived_at && caps.archive?.reason_code === "custom_product_archived" ? (
            <Button variant="secondary" onPress={() => void perform("__unarchive", m.unarchive, null)} {...unavailableWhen(commands.offline)}>
              {m.unarchive}
            </Button>
          ) : null}
        </div>
        {product.allowed_transitions.length === 0 ? <p className="text-sm text-ink-muted">{m.noTransitions}</p> : null}
        {commands.offline ? <p className="text-sm text-warning-text">{commands.offline}</p> : null}
        <ReasonDialog
          title={asking?.label ?? ""}
          description={`${product.custom_code} · ${product.product_name}`}
          requireNote={asking?.requiresReason ?? false}
          noteLabel={c.common.reason}
          confirmLabel={asking?.label ?? ""}
          isOpen={asking !== null}
          isPending={commands.pending !== null}
          disabledReason={commands.offline}
          onOpenChange={(open) => (open ? null : setAsking(null))}
          onConfirm={(_, note) => (asking ? void perform(asking.action, asking.label, note || null) : undefined)}
        />
      </section>

      <EditSection product={product} commands={commands} />
      <SpecRevisions product={product} commands={commands} />
      <Promotion product={product} commands={commands} />
      <Quotes product={product} />
      <Costing product={product} />
      <History product={product} />
    </div>
  );
}

type Commands = ReturnType<typeof useResourceCommand>;

function EditSection({ product, commands }: { product: CustomProductDetail; commands: Commands }) {
  const editable = product.capabilities.update?.allowed === true;
  const [state, setState] = useState<{ base: CustomForm; form: CustomForm; version: number }>(() => {
    const base = customFormOf(product);
    return { base, form: base, version: product.version };
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const changes = customBody(state.form, state.base);
  const dirty = Object.keys(changes).length > 0;
  if (product.version !== state.version && !dirty) {
    const base = customFormOf(product);
    setState({ base, form: base, version: product.version });
  }
  const set = <K extends keyof CustomForm>(field: K, value: CustomForm[K]) => setState((current) => ({ ...current, form: { ...current.form, [field]: value } }));
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!dirty) return;
    const outcome = await commands.run("update", [state.version, JSON.stringify(changes)], () => updateCustomProduct({ id: product.id, version: state.version }, changes), {
      done: c.common.saved,
      failed: c.common.failed(c.common.save),
      conflictMessage: c.common.conflict,
    });
    if (outcome.ok) {
      const base = customFormOf(outcome.value);
      setState({ base, form: base, version: outcome.value.version });
      setErrors({});
    } else setErrors(outcome.fieldErrors);
  };
  if (!editable) {
    const d = (value: string | null | undefined) => (value && value.trim() ? value : c.common.noValue);
    return (
      <section aria-label={m.sections.specification} className="flex flex-col gap-4">
        <h2 className="text-lg font-[650] text-ink">{m.sections.specification}</h2>
        <DescriptionList
          items={[
            { term: m.fields.base_product_id!, description: d(product.base_product_key) },
            { term: m.fields.inquiry_reference!, description: d(product.inquiry_reference) },
            { term: m.fields.category_id!, description: d([product.category_name, product.subcategory_name].filter(Boolean).join(" / ")) },
            { term: m.fields.dimensions_text!, description: d(product.dimensions_text) },
            { term: m.fields.thickness_mm!, description: d(product.thickness_text ?? product.thickness_mm) },
            { term: m.fields.decor_no!, description: d([product.decor_no, product.decor_name].filter(Boolean).join(" · ")) },
            { term: m.fields.finish!, description: d(product.finish) },
            { term: m.fields.shape!, description: d(product.shape) },
            { term: m.fields.handle_type!, description: d(product.handle_type) },
            { term: m.fields.packaging_notes!, description: d(product.packaging_notes) },
            { term: m.fields.quoted_price!, description: product.quoted_price ? <Money value={product.quoted_price} /> : c.common.noValue },
            { term: m.fields.remarks!, description: <span className="whitespace-pre-line">{d(product.remarks)}</span> },
          ]}
        />
      </section>
    );
  }
  return (
    <section aria-label={m.edit} className="flex flex-col gap-4">
      <h2 className="text-lg font-[650] text-ink">{m.edit}</h2>
      <Form onSubmit={(event) => void save(event)} className="flex flex-col gap-6" validationBehavior="aria">
        <CustomProductFields form={state.form} set={set} errors={errors} />
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant={dirty ? "primary" : "secondary"} isPending={commands.pending === "update"} pendingLabel={c.common.saving} {...unavailableWhen(commands.offline ?? (dirty ? null : "No changes to save"))}>
            {c.common.save}
          </Button>
          {dirty ? (
            <Button variant="quiet" onPress={() => setState((current) => ({ ...current, form: current.base }))}>
              {c.common.cancel}
            </Button>
          ) : null}
        </div>
      </Form>
    </section>
  );
}

function SpecRevisions({ product, commands }: { product: CustomProductDetail; commands: Commands }) {
  const titleId = useId();
  const editable = product.capabilities.update?.allowed === true;
  const [reference, setReference] = useState("");
  const [feedback, setFeedback] = useState("");
  const record = async () => {
    await commands.run("spec", [product.version, reference, feedback], () => recordSpecRevision(product.id, { sample_reference: reference.trim() || null, feedback: feedback.trim() || null }), {
      done: m.specRecorded,
      failed: c.common.failed(m.recordSpec),
    });
    setReference("");
    setFeedback("");
  };
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.sections.specRevisions}
      </h2>
      {product.spec_revisions.length === 0 ? (
        <p className="text-ink-muted">{m.noSpecs}</p>
      ) : (
        <ol className="flex flex-col divide-y border-y">
          {product.spec_revisions.map((rev) => (
            <li key={rev.id} className="flex flex-wrap items-start justify-between gap-2 py-3">
              <div className="flex flex-col gap-0.5">
                <span className="font-semibold text-ink">
                  {m.revision(rev.revision_no)} · {m.specOutcome[rev.outcome] ?? rev.outcome}
                </span>
                <span className="text-sm text-ink-muted">
                  <LocalDateTime value={rev.created_at} />
                  {rev.sample_number ? ` · ${rev.sample_number}` : ""}
                  {rev.sample_reference ? ` · ${rev.sample_reference}` : ""}
                </span>
                {rev.feedback ? <span className="text-sm text-ink">{rev.feedback}</span> : null}
              </div>
              {editable && rev.outcome === "pending" ? (
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" onPress={() => void commands.run("spec_ok", [rev.id], () => decideSpecRevision(product.id, rev, "approved"), { done: m.approveSpec, failed: c.common.failed(m.approveSpec), conflictMessage: c.common.conflict })}>
                    {m.approveSpec}
                  </Button>
                  <Button size="sm" variant="danger" onPress={() => void commands.run("spec_no", [rev.id], () => decideSpecRevision(product.id, rev, "rejected"), { done: m.rejectSpec, failed: c.common.failed(m.rejectSpec), conflictMessage: c.common.conflict })}>
                    {m.rejectSpec}
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      {editable ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <TextField label={m.sampleReference} value={reference} onChange={setReference} maxLength={120} />
          <TextField label={m.feedback} value={feedback} onChange={setFeedback} maxLength={4000} />
          <Button variant="secondary" onPress={() => void record()} isPending={commands.pending === "spec"} {...unavailableWhen(commands.offline)}>
            {m.recordSpec}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function Promotion({ product, commands }: { product: CustomProductDetail; commands: Commands }) {
  const titleId = useId();
  const [open, setOpen] = useState(false);
  const [productKey, setProductKey] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const promote = product.capabilities.promote;
  const canExecute = product.capabilities.execute_promotion?.allowed === true;
  if (product.promotions.length === 0 && !promote?.allowed && product.status !== "approved") return null;
  const submit = async () => {
    const outcome = await commands.run("promote", [product.version, productKey], () => requestPromotion(product.id, { product_key: productKey.trim(), display_sku: productKey.trim() }), {
      done: m.promotionRequested,
      failed: c.common.failed(m.requestPromotion),
    });
    if (outcome.ok) setOpen(false);
    else setErrors(outcome.fieldErrors);
  };
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.sections.promotion}
      </h2>
      {product.promotions.map((promo) => (
        <div key={promo.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2">
          <span className="text-ink">
            {String(promo.payload.product_key ?? "")} · {m.promotionStatus[promo.status] ?? promo.status}
            {promo.failure_reason ? ` · ${promo.failure_reason}` : ""}
          </span>
          {promo.status === "failed" && canExecute ? (
            <Button size="sm" variant="secondary" onPress={() => void commands.run("execute", [promo.id], () => executePromotion(product.id, promo.id), { failed: c.common.failed(m.executePromotion) })}>
              {m.executePromotion}
            </Button>
          ) : null}
        </div>
      ))}
      {promote?.allowed ? (
        <div>
          <Button variant="primary" onPress={() => setOpen(true)} {...unavailableWhen(commands.offline)}>
            {m.requestPromotion}
          </Button>
        </div>
      ) : (
        <p className="text-sm text-ink-muted">{m.promotionNeedsApproval}</p>
      )}
      <Dialog
        title={m.requestPromotion}
        description={`${product.custom_code} · ${product.product_name}`}
        isOpen={open}
        onOpenChange={setOpen}
        footer={(close) => (
          <>
            <Button variant="quiet" onPress={close}>
              {c.common.cancel}
            </Button>
            <Button variant="primary" onPress={() => void submit()} isPending={commands.pending === "promote"} {...unavailableWhen(commands.offline ?? (productKey.trim() ? null : "Enter the product key"))}>
              {m.requestPromotion}
            </Button>
          </>
        )}
      >
        <TextField label={m.productKey} value={productKey} onChange={setProductKey} maxLength={120} isRequired errorMessage={errors.product_key ?? errors.category_id} />
      </Dialog>
    </section>
  );
}

function Quotes({ product }: { product: CustomProductDetail }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.sections.quotes}
      </h2>
      {product.quotes.length === 0 ? (
        <p className="text-ink-muted">{m.noQuotes}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {product.quotes.map((q) => (
            <li key={`${q.quote_id}-${q.line_no}`}>
              <Link href={`/sales/quotes/${q.quote_id}`} className="font-mono">
                {q.quote_number}
              </Link>{" "}
              <span className="text-sm text-ink-muted">· line {q.line_no}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Costing({ product }: { product: CustomProductDetail }) {
  const titleId = useId();
  const canRead = product.capabilities.read_costing?.allowed === true;
  const canWrite = product.capabilities.record_costing?.allowed === true;
  const query = useQuery({
    queryKey: queryKeys.sales.customProductCosting(product.id),
    queryFn: ({ signal }) => fetchCosting(product.id, signal),
    enabled: canRead,
  });
  const commands = useResourceCommand(`costing:${product.id}`, [queryKeys.sales.customProductCosting(product.id)]);
  const [amount, setAmount] = useState<string | null>(null);
  const [currency, setCurrency] = useState<string>("EUR");
  const [basis, setBasis] = useState("");
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3" data-restricted={canRead ? "true" : undefined}>
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.sections.costing}
      </h2>
      {!canRead ? (
        <p className="text-sm text-ink-muted">{m.costingRestricted}</p>
      ) : query.isPending ? (
        <Loading label={m.sections.costing} variant="inline" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.sections.costing} compact headingLevel={3} backToToday={false} onRetry={() => void query.refetch()} />
      ) : query.data.length === 0 ? (
        <p className="text-ink-muted">{m.noCosting}</p>
      ) : (
        <ol className="flex flex-col divide-y border-y">
          {query.data.map((row) => (
            <li key={row.id} className="flex flex-wrap justify-between gap-2 py-2">
              <span>
                {c.common.version(row.cost_version)} · <Money value={row.cost} />
                {row.basis_note ? ` · ${row.basis_note}` : ""}
              </span>
              <span className="text-sm text-ink-muted">
                <LocalDate value={row.recorded_at.slice(0, 10)} />
                {row.recorded_by?.display_name ? ` · ${row.recorded_by.display_name}` : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
      {canWrite ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_auto_1fr_auto] md:items-end">
          <NumberField label={m.costAmount} value={amount} onChange={setAmount} currency={currency} />
          <Select label={m.costCurrency} options={CURRENCIES.map((code) => ({ id: code, label: code }))} value={currency} onChange={(value) => setCurrency(value ?? "EUR")} />
          <TextArea label={m.basisNote} value={basis} onChange={setBasis} rows={1} />
          <Button
            variant="secondary"
            onPress={() =>
              amount
                ? void commands
                    .run("cost", [amount, currency], () => recordCosting(product.id, { cost_amount: amount, cost_currency: currency, basis_note: basis.trim() || null }), {
                      done: m.costingRecorded,
                      failed: c.common.failed(m.recordCosting),
                    })
                    .then((outcome) => (outcome.ok ? (setAmount(null), setBasis("")) : null))
                : undefined
            }
            {...unavailableWhen(commands.offline ?? (amount ? null : "Enter the cost"))}
          >
            {m.recordCosting}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function History({ product }: { product: CustomProductDetail }) {
  const titleId = useId();
  const query = useQuery({ queryKey: queryKeys.sales.customProductHistory(product.id), queryFn: ({ signal }) => fetchCustomHistory(product.id, signal) });
  const status = (code: string) => m.status[code] ?? code;
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.sections.history}
      </h2>
      {query.isPending ? (
        <Loading label={m.sections.history} variant="inline" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.sections.history} compact headingLevel={3} backToToday={false} onRetry={() => void query.refetch()} />
      ) : query.data.length === 0 ? (
        <p className="text-ink-muted">{m.noHistory}</p>
      ) : (
        <ol className="flex flex-col divide-y border-y">
          {query.data.map((entry) => (
            <li key={entry.id} className="flex flex-col gap-0.5 py-2">
              <span className="text-ink">
                {c.human(entry.action)}: {m.historyLine(status(entry.from_status), status(entry.to_status))}
              </span>
              <span className="text-sm text-ink-muted">
                <LocalDateTime value={entry.occurred_at} />
                {entry.actor?.display_name ? ` · ${entry.actor.display_name}` : ""}
              </span>
              {entry.reason ? <span className="text-sm text-ink">{entry.reason}</span> : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
