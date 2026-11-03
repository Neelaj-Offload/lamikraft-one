"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Input, TextField as RacTextField } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Switch } from "@/components/ui/choice";
import { DataTable } from "@/components/ui/data-table";
import { DescriptionList } from "@/components/ui/description-list";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { ComboBox, Select } from "@/components/ui/select";
import { Conflict, Loading } from "@/components/ui/states";
import { fieldErrorClasses, inputClasses, linkClasses } from "@/components/ui/styles";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { conflictFromError, ProblemError, type ConflictInfo } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { cx } from "@/lib/cx";
import { normaliseDecimalInput } from "@/lib/format/decimal";
import { formatDate } from "@/lib/format/time";
import { useDebouncedValue, useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { archivePlan, calculatePlan, createPlan, duplicatePlan, fetchPlan, searchCuttingProducts, updatePlan, verifyBoards } from "./api";
import {
  applyProduct,
  blankRow,
  dirtyParts,
  formOf,
  hasErrors,
  isBlankRow,
  planChanges,
  rowsToRequest,
  serverErrors,
  settingsChanges,
  validateForm,
  type EditorForm,
  type EditorRow,
  type EditorSettings,
  type FormErrors,
  type RowField,
} from "./editor-model";
import { cuttingMessages as m } from "./messages";
import { QueryFailure } from "./query-failure";
import { PlanStatusPill } from "./plan-list";
import { Results } from "./results";
import { GRAIN_RULES, MODES, type GrainRule, type Mode, type PlanDetail } from "./types";

const EMPTY_ERRORS: FormErrors = { rows: {}, settings: {}, general: [] };
/** Poll while the calculation job runs (large plans); stop as soon as it is idle or failed. */
export const CALC_POLL_MS = 1500;

export function calcPollInterval(plan: PlanDetail | undefined): number | false {
  return plan && (plan.calculation.status === "queued" || plan.calculation.status === "running") ? CALC_POLL_MS : false;
}

function problemText(error: unknown): string | undefined {
  if (!(error instanceof ProblemError)) return undefined;
  return [error.detail ?? error.title, error.request_id ? `Reference: ${error.request_id}` : null].filter(Boolean).join(" ");
}

/** A saved plan: its editor (when editable), the stored latest layout and the plan's commands. */
export function PlanWorkspace({ planId }: { planId: string }) {
  const query = useQuery({
    queryKey: queryKeys.cutting.plan(planId),
    queryFn: ({ signal }) => fetchPlan(planId, signal),
    refetchInterval: (q) => calcPollInterval(q.state.data),
  });
  if (query.isPending) return <Loading label={m.list.loading} variant="detail" />;
  if (query.isError) return <QueryFailure error={query.error} what="the cut plan" onRetry={() => void query.refetch()} />;
  return <PlanScreen key={query.data.id} plan={query.data} />;
}

/** A new plan: three blank rows and the company's board defaults until the first save. */
export function NewPlan() {
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <Link href="/operations/cutting" className="text-sm">
          {m.editor.back}
        </Link>
        <h1 className="text-[26px] leading-tight font-bold tracking-tight text-ink md:text-3xl">{m.editor.newTitle}</h1>
      </header>
      <Editor plan={null} />
    </div>
  );
}

function PlanScreen({ plan }: { plan: PlanDetail }) {
  const editable = plan.capabilities.update?.allowed === true;
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <Link href="/operations/cutting" className="text-sm">
          {m.editor.back}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-[26px] leading-tight font-bold tracking-tight text-ink md:text-3xl">{plan.plan_number}</h1>
          <PlanStatusPill status={plan.status} />
        </div>
        <p className="text-ink">
          {plan.name}
          <span className="text-ink-muted"> · {plan.owner.display_name ?? ""}</span>
        </p>
        {plan.duplicated_from ? <p className="text-sm text-ink-muted">{m.editor.copyOf(plan.duplicated_from)}</p> : null}
      </header>
      {editable ? <Editor plan={plan} /> : <ReadOnlyInputs plan={plan} />}
      <Verification plan={plan} />
      {plan.latest_calculation ? (
        <>
          {plan.stale ? (
            <p role="note" className="rounded-md border border-warning-text/40 bg-warning-bg px-4 py-3 text-ink">
              {m.editor.stale}
            </p>
          ) : null}
          <Results calc={plan.latest_calculation} />
        </>
      ) : plan.calculation.status === "idle" ? (
        <p className="text-ink-muted">{m.results.none}</p>
      ) : null}
      <PlanCommands plan={plan} />
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// The editor

function Editor({ plan }: { plan: PlanDetail | null }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const online = useOnline();
  const { zone } = useSession();
  const formId = useId();
  const [commandKeys] = useState(() => createCommandKeys());
  const [state, setState] = useState<{ base: EditorForm; form: EditorForm; version: number }>(() => {
    const base = formOf(plan);
    return { base, form: base, version: plan?.version ?? 0 };
  });
  const [errors, setErrors] = useState<FormErrors>(EMPTY_ERRORS);
  const [conflict, setConflict] = useState<ConflictInfo | null>(null);
  const [pending, setPending] = useState<"save" | "calculate" | null>(null);
  const firstInputs = useRef(new Map<string, HTMLInputElement>());
  const dirty = plan ? dirtyParts(state.base, state.form) : ["items" as const];

  // A newer server version with no local edits (another tab, the job finishing): show it.
  if (plan && plan.version !== state.version && dirtyParts(state.base, state.form).length === 0 && !conflict) {
    const base = formOf(plan);
    setState({ base, form: base, version: plan.version });
  }

  const setForm = (form: EditorForm) => setState((s) => ({ ...s, form }));
  const setRow = (key: string, change: Partial<EditorRow>) =>
    setForm({ ...state.form, rows: state.form.rows.map((row) => (row.key === key ? { ...row, ...change } : row)) });
  const setSetting = <K extends keyof EditorSettings>(key: K, value: EditorSettings[K]) =>
    setForm({ ...state.form, settings: { ...state.form.settings, [key]: value } });
  const addRow = (focus = true) => {
    const row = blankRow();
    setForm({ ...state.form, rows: [...state.form.rows, row] });
    if (focus) requestAnimationFrame(() => firstInputs.current.get(row.key)?.focus());
  };
  const removeRow = (key: string) => setForm({ ...state.form, rows: state.form.rows.filter((row) => row.key !== key) });

  const offline = online ? null : "You're offline";

  const save = async (event?: FormEvent<HTMLFormElement>): Promise<PlanDetail | null> => {
    event?.preventDefault();
    const local = validateForm(state.form);
    setErrors(local);
    if (hasErrors(local)) return null;
    const body = plan
      ? planChanges(state.base, state.form)
      : { name: state.form.name.trim(), items: rowsToRequest(state.form.rows), settings: settingsChanges(null, state.form.settings) };
    if (plan && Object.keys(body).length === 0) return plan;
    const signature = commandSignature(plan?.id ?? "new", "save", state.version, JSON.stringify(body));
    const attempt = commandKeys.attempt(signature, () => null);
    setPending("save");
    try {
      const saved = plan ? await updatePlan({ id: plan.id, version: state.version }, body, attempt.key) : await createPlan(body, attempt.key);
      commandKeys.settle(signature);
      queryClient.setQueryData(queryKeys.cutting.plan(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.allPlans() });
      setConflict(null);
      setErrors(EMPTY_ERRORS);
      if (!plan) {
        toast.success(m.editor.created(saved.plan_number));
        router.replace(saved.path as Parameters<typeof router.replace>[0]);
      } else {
        const base = formOf(saved);
        setState({ base, form: base, version: saved.version });
        toast.success(m.editor.saved);
      }
      return saved;
    } catch (error) {
      commandKeys.settle(signature, error);
      const info = conflictFromError(error);
      if (info && plan) {
        setConflict(info);
      } else if (error instanceof ProblemError && error.validationIssues.length) {
        setErrors(serverErrors(error.validationIssues, state.form.rows));
      } else {
        toast.error(m.editor.failed(m.editor.save), { description: problemText(error) });
      }
      return null;
    } finally {
      setPending(null);
    }
  };

  /** 409: reload the server's version (discarding mine) or keep mine on top of it (re-save against the new version). */
  const reloadTheirs = async () => {
    if (!plan) return;
    const fresh = await fetchPlan(plan.id);
    queryClient.setQueryData(queryKeys.cutting.plan(plan.id), fresh);
    const base = formOf(fresh);
    setConflict(null);
    setState({ base, form: base, version: fresh.version });
  };
  const keepMine = async () => {
    if (!plan) return;
    const fresh = await fetchPlan(plan.id);
    setConflict(null);
    setState((s) => ({ base: formOf(fresh), form: s.form, version: fresh.version }));
  };

  const calculate = async () => {
    if (!plan) return;
    const signature = commandSignature(plan.id, "calculate", state.version);
    const attempt = commandKeys.attempt(signature, () => null);
    setPending("calculate");
    try {
      const result = await calculatePlan({ id: plan.id, version: state.version }, attempt.key);
      commandKeys.settle(signature);
      queryClient.setQueryData(queryKeys.cutting.plan(plan.id), result);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.allPlans() });
      if (result.calculation.status === "idle") toast.success(m.editor.calculated);
    } catch (error) {
      commandKeys.settle(signature, error);
      if (conflictFromError(error)) {
        setConflict(conflictFromError(error));
      } else {
        toast.error(m.editor.failed(m.editor.calculate), { description: problemText(error) });
      }
    } finally {
      setPending(null);
    }
  };

  const onRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, row: EditorRow, index: number) => {
    if (event.key !== "Enter" || (event.target as HTMLElement).tagName !== "INPUT") return;
    event.preventDefault();
    const next = state.form.rows[index + 1];
    if (next) firstInputs.current.get(next.key)?.focus();
    else if (!isBlankRow(row)) addRow();
  };

  const s = state.form.settings;
  const calc = plan?.calculation;
  const busy = calc && (calc.status === "queued" || calc.status === "running");
  const canCalculate = plan?.capabilities.calculate?.allowed === true;
  const calculateBlocked = offline ?? (dirty.length > 0 ? m.editor.saveFirst : busy ? m.editor.calculating : !canCalculate ? m.editor.readOnly : null);

  return (
    <form id={formId} onSubmit={(event) => void save(event)} noValidate className="flex flex-col gap-6">
      {conflict ? (
        <Conflict
          conflict={conflict}
          changedAtLabel={conflict.changedAt ? formatDate(conflict.changedAt, zone) : null}
          onReview={() => void reloadTheirs()}
          onKeepMine={() => void keepMine()}
        />
      ) : null}
      <TextField
        label={m.editor.name}
        placeholder={m.editor.namePlaceholder}
        value={state.form.name}
        onChange={(name) => setForm({ ...state.form, name })}
        maxLength={200}
        isRequired
        errorMessage={errors.name}
        className="max-w-xl"
      />

      <section aria-labelledby={`${formId}-pieces`} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 id={`${formId}-pieces`} className="text-lg font-[650] text-ink">
            {m.editor.pieces}
          </h2>
          <p className="text-sm text-ink-muted">{m.editor.piecesHint}</p>
        </div>
        <ProductPicker
          onPick={(product) => {
            const blank = state.form.rows.find(isBlankRow);
            const rows = blank
              ? state.form.rows.map((row) => (row.key === blank.key ? applyProduct(row, product) : row))
              : [...state.form.rows, applyProduct(blankRow(), product)];
            setForm({ ...state.form, rows });
          }}
        />
        {errors.general.length ? (
          <ul className={fieldErrorClasses} role="alert">
            {errors.general.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        ) : Object.keys(errors.rows).length ? (
          <p className={fieldErrorClasses} role="alert">
            {m.editor.rowErrors}
          </p>
        ) : null}
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[860px] border-collapse text-sm">
            <caption className="sr-only">{m.editor.pieces}</caption>
            <thead className="bg-surface-sunken text-start text-xs font-semibold text-ink-muted">
              <tr>
                <th scope="col" className="w-8 px-2 py-2 text-end">#</th>
                <th scope="col" className="px-2 py-2 text-start">{m.editor.sku}</th>
                <th scope="col" className="px-2 py-2 text-start">{m.editor.decor}</th>
                <th scope="col" className="px-2 py-2 text-end">{m.editor.thickness}</th>
                <th scope="col" className="px-2 py-2 text-end">{m.editor.length}</th>
                <th scope="col" className="px-2 py-2 text-end">{m.editor.width}</th>
                <th scope="col" className="px-2 py-2 text-end">{m.editor.quantity}</th>
                <th scope="col" className="px-2 py-2 text-start">{m.editor.grain}</th>
                <th scope="col" className="px-2 py-2">
                  <span className="sr-only">{m.editor.removeRow(0)}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {state.form.rows.map((row, index) => (
                <tr key={row.key} className="border-t align-top" onKeyDown={(event) => onRowKeyDown(event, row, index)}>
                  <td className="tabular px-2 py-2 text-end text-ink-muted">{index + 1}</td>
                  <Cell row={row} index={index} field="sku" errors={errors} onChange={(v) => setRow(row.key, { sku: v, product_id: null })}
                        inputRef={(el) => (el ? firstInputs.current.set(row.key, el) : firstInputs.current.delete(row.key))} />
                  <Cell row={row} index={index} field="decor" errors={errors} onChange={(v) => setRow(row.key, { decor: v })} />
                  <Cell row={row} index={index} field="thickness_mm" errors={errors} decimal={3} onChange={(v) => setRow(row.key, { thickness_mm: v || null })} />
                  <Cell row={row} index={index} field="length_mm" errors={errors} decimal={1} onChange={(v) => setRow(row.key, { length_mm: v || null })} />
                  <Cell row={row} index={index} field="width_mm" errors={errors} decimal={1} onChange={(v) => setRow(row.key, { width_mm: v || null })} />
                  <Cell row={row} index={index} field="quantity" errors={errors} decimal={0} onChange={(v) => setRow(row.key, { quantity: v || null })} />
                  <td className="px-2 py-2">
                    <select
                      aria-label={`${m.editor.grain}, ${m.editor.row(index + 1)}`}
                      value={row.grain_rule}
                      onChange={(event) => setRow(row.key, { grain_rule: (GRAIN_RULES.find((r) => r === event.target.value) ?? "inherit") as GrainRule })}
                      className={cx(inputClasses, "min-w-32")}
                    >
                      {GRAIN_RULES.map((rule) => (
                        <option key={rule} value={rule}>
                          {m.grainRules[rule]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-2">
                    <Button size="sm" variant="quiet" onPress={() => removeRow(row.key)} aria-label={m.editor.removeRow(index + 1)}>
                      ×
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <Button size="sm" onPress={() => addRow()}>
            {m.editor.addRow}
          </Button>
        </div>
      </section>

      <section aria-labelledby={`${formId}-settings`} className="flex flex-col gap-3">
        <h2 id={`${formId}-settings`} className="text-lg font-[650] text-ink">
          {m.editor.settings}
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <NumberField label={m.editor.boardLength} value={s.board_length_mm} onChange={(v) => setSetting("board_length_mm", v)} maxFractionDigits={1} errorMessage={errors.settings.board_length_mm} isRequired />
          <NumberField label={m.editor.boardWidth} value={s.board_width_mm} onChange={(v) => setSetting("board_width_mm", v)} maxFractionDigits={1} errorMessage={errors.settings.board_width_mm} isRequired />
          <NumberField label={m.editor.margin} value={s.margin_mm} onChange={(v) => setSetting("margin_mm", v)} maxFractionDigits={1} errorMessage={errors.settings.margin_mm} isRequired />
          <NumberField label={m.editor.gap} value={s.gap_mm} onChange={(v) => setSetting("gap_mm", v)} maxFractionDigits={1} errorMessage={errors.settings.gap_mm} isRequired />
          <Select
            label={m.editor.mode}
            options={MODES.map((mode) => ({ id: mode, label: m.modes[mode] ?? mode }))}
            value={s.mode}
            onChange={(value) => setSetting("mode", (MODES.find((mode) => mode === value) ?? "nested") as Mode)}
          />
        </div>
        <Switch isSelected={s.oversize_enabled} onChange={(value) => setSetting("oversize_enabled", value)}>
          {m.editor.oversize(plan?.settings.oversize_mm ?? "10")}
        </Switch>
        <p className="-mt-1 text-sm text-ink-muted">{m.editor.oversizeHint}</p>
        <Switch isSelected={s.overproduction_enabled} onChange={(value) => setSetting("overproduction_enabled", value)}>
          {m.editor.overproduction}
        </Switch>
        <p className="-mt-1 text-sm text-ink-muted">{m.editor.overproductionHint}</p>
        {s.overproduction_enabled ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <NumberField label={m.editor.maxExtraQty} value={s.max_extra_qty} onChange={(v) => setSetting("max_extra_qty", v)} maxFractionDigits={0} errorMessage={errors.settings.max_extra_qty} />
            <NumberField label={m.editor.maxExtraPct} value={s.max_extra_pct} onChange={(v) => setSetting("max_extra_pct", v)} maxFractionDigits={2} errorMessage={errors.settings.max_extra_pct} />
          </div>
        ) : null}
        {plan ? <p className="text-sm text-ink-muted">{m.editor.usable(plan.settings.usable_length_mm, plan.settings.usable_width_mm)}</p> : null}
      </section>

      {calc?.status === "queued" || calc?.status === "running" ? (
        <p role="status" className="rounded-md border border-info/40 bg-info-bg px-4 py-3 text-ink">
          {m.editor.queued(calc.pieces)}
        </p>
      ) : calc?.status === "failed" ? (
        <p role="alert" className="rounded-md border border-danger/40 bg-danger-bg px-4 py-3 text-ink">
          {m.editor.calcFailed}: {calc.error?.detail}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button
          type="submit"
          variant={plan && dirty.length === 0 ? "secondary" : "primary"}
          isPending={pending === "save"}
          pendingLabel={plan ? m.editor.saving : m.editor.creating}
          {...unavailableWhen(offline ?? (plan && dirty.length === 0 ? m.editor.noChanges : null))}
        >
          {plan ? m.editor.save : m.editor.create}
        </Button>
        {plan ? (
          <Button
            variant={dirty.length === 0 ? "primary" : "secondary"}
            onPress={() => void calculate()}
            isPending={pending === "calculate"}
            pendingLabel={m.editor.calculating}
            {...unavailableWhen(calculateBlocked)}
          >
            {m.editor.calculate}
          </Button>
        ) : null}
        {plan && dirty.length > 0 ? (
          <Button variant="quiet" onPress={() => setState((st) => ({ ...st, form: st.base }))}>
            {m.editor.discard}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function Cell({
  row,
  index,
  field,
  errors,
  decimal,
  onChange,
  inputRef,
}: {
  row: EditorRow;
  index: number;
  field: RowField;
  errors: FormErrors;
  decimal?: number;
  onChange: (value: string) => void;
  inputRef?: (el: HTMLInputElement | null) => void;
}) {
  const label = { sku: m.editor.sku, decor: m.editor.decor, thickness_mm: m.editor.thickness, length_mm: m.editor.length, width_mm: m.editor.width, quantity: m.editor.quantity }[field];
  const error = errors.rows[row.key]?.[field];
  const errorId = `${row.key}-${field}-error`;
  const value = row[field] ?? "";
  return (
    <td className="px-2 py-2">
      <RacTextField
        aria-label={`${label}, ${m.editor.row(index + 1)}`}
        value={value}
        onChange={onChange}
        onBlur={() => {
          if (decimal === undefined || !value) return;
          const normal = normaliseDecimalInput(value, { maxFractionDigits: decimal });
          if (normal.ok && normal.value !== null && normal.value !== value) onChange(normal.value);
        }}
        isInvalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
        className="flex flex-col gap-1"
      >
        <Input
          ref={inputRef}
          inputMode={decimal === undefined ? "text" : decimal === 0 ? "numeric" : "decimal"}
          maxLength={field === "sku" ? 120 : field === "decor" ? 80 : 12}
          className={cx(inputClasses, decimal !== undefined && "tabular text-end", field === "sku" ? "min-w-40" : field === "decor" ? "min-w-24" : "min-w-20")}
        />
        {error ? (
          <span id={errorId} className="text-xs font-medium text-danger">
            {error}
          </span>
        ) : null}
      </RacTextField>
    </td>
  );
}

function ProductPicker({ onPick }: { onPick: (product: Awaited<ReturnType<typeof searchCuttingProducts>>[number]) => void }) {
  const [text, setText] = useState("");
  const q = useDebouncedValue(text.trim(), 250);
  const { permissionKeys } = useSession();
  const enabled = q.length >= 2 && permissionKeys.has("cutting.calculation.run");
  const query = useQuery({
    queryKey: queryKeys.cutting.products(q),
    queryFn: ({ signal }) => searchCuttingProducts(q, signal),
    enabled,
    staleTime: 30_000,
  });
  const options = enabled ? (query.data ?? []) : [];
  return (
    <ComboBox
      label={m.editor.product}
      placeholder={m.editor.productPlaceholder}
      emptyText={text.trim().length < 2 ? m.editor.productPlaceholder : m.editor.productEmpty}
      options={options.map((p) => ({
        id: p.product_id,
        label: p.product_name,
        detail: [p.product_key, p.decor, p.thickness_mm ? `${p.thickness_mm} mm` : null, p.grain_locked ? m.editor.locked : null].filter(Boolean).join(" · "),
      }))}
      value={null}
      inputValue={text}
      onInputChange={setText}
      onChange={(id) => {
        const chosen = options.find((p) => p.product_id === id);
        if (chosen) {
          onPick(chosen);
          setText("");
        }
      }}
      className="max-w-xl"
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Read-only inputs, verification and plan commands

function ReadOnlyInputs({ plan }: { plan: PlanDetail }) {
  const s = plan.settings;
  return (
    <section className="flex flex-col gap-4">
      <p className="text-sm text-ink-muted">{m.editor.readOnly}</p>
      <DataTable
        caption={m.editor.pieces}
        columns={[
          { id: "sku", header: m.editor.sku, isRowHeader: true, mobile: "title", cell: (i) => i.sku },
          { id: "decor", header: m.editor.decor, mobile: "key", cell: (i) => i.decor ?? "—" },
          { id: "thickness", header: m.editor.thickness, numeric: true, cell: (i) => i.thickness_mm },
          { id: "size", header: `${m.editor.length} × ${m.editor.width}`, numeric: true, cell: (i) => `${i.length_mm} × ${i.width_mm}` },
          { id: "qty", header: m.editor.quantity, numeric: true, mobile: "amount", cell: (i) => i.quantity },
          { id: "grain", header: m.editor.grain, cell: (i) => m.grainRules[i.grain_rule] },
        ]}
        rows={plan.items}
        rowId={(i) => i.id ?? String(i.line_no)}
      />
      <DescriptionList
        items={[
          { term: m.editor.boardLength, description: s.board_length_mm, numeric: true },
          { term: m.editor.boardWidth, description: s.board_width_mm, numeric: true },
          { term: m.editor.margin, description: s.margin_mm, numeric: true },
          { term: m.editor.gap, description: s.gap_mm, numeric: true },
          { term: m.editor.mode, description: m.modes[s.mode] ?? s.mode },
          { term: m.editor.oversize(s.oversize_mm), description: s.oversize_enabled ? "On" : "Off" },
          { term: m.editor.overproduction, description: s.overproduction_enabled ? `On, at most ${s.max_extra_qty} or ${s.max_extra_pct} %` : "Off" },
        ]}
      />
    </section>
  );
}

function Verification({ plan }: { plan: PlanDetail }) {
  const queryClient = useQueryClient();
  const [length, setLength] = useState<string | null>(null);
  const [width, setWidth] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [keys] = useState(() => createCommandKeys());
  const v = plan.verification;
  if (!v.required) return null;
  const titleId = `${plan.id}-verify`;
  if (v.verified) {
    return (
      <p role="note" className="rounded-md border border-success/40 bg-success-bg px-4 py-3 text-ink">
        {m.verify.verified(v.verified_by?.display_name ?? "")}
      </p>
    );
  }
  const canVerify = plan.capabilities.verify?.allowed === true;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!length || !width) return;
    const signature = commandSignature(plan.id, "verify", plan.version, length, width);
    const attempt = keys.attempt(signature, () => null);
    setPending(true);
    try {
      const saved = await verifyBoards(plan, { length_mm: length, width_mm: width, note }, attempt.key);
      keys.settle(signature);
      queryClient.setQueryData(queryKeys.cutting.plan(plan.id), saved);
      toast.success(m.verify.done);
    } catch (error) {
      keys.settle(signature, error);
      if (conflictFromError(error)) void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.plan(plan.id) });
      toast.error(m.editor.failed(m.verify.submit), { description: problemText(error) });
    } finally {
      setPending(false);
    }
  };
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3 rounded-md border border-warning-text/40 bg-warning-bg px-4 py-4">
      <h2 id={titleId} className="text-base font-bold text-ink">
        {m.verify.title}
      </h2>
      <p className="text-ink">{m.verify.body(v.assumed_length_mm ?? "", v.assumed_width_mm ?? "")}</p>
      {v.outcome === "smaller_than_assumed" ? <p className="font-medium text-danger">{m.verify.tooSmall}</p> : null}
      {canVerify ? (
        <form onSubmit={(event) => void submit(event)} className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[repeat(3,minmax(0,1fr))_auto]">
          <NumberField label={m.verify.length} value={length} onChange={setLength} maxFractionDigits={1} isRequired />
          <NumberField label={m.verify.width} value={width} onChange={setWidth} maxFractionDigits={1} isRequired />
          <TextArea label={m.verify.note} value={note} onChange={setNote} rows={1} />
          <Button type="submit" variant="primary" isPending={pending} {...unavailableWhen(!length || !width ? m.verify.length : null)}>
            {m.verify.submit}
          </Button>
        </form>
      ) : null}
    </section>
  );
}

function PlanCommands({ plan }: { plan: PlanDetail }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [keys] = useState(() => createCommandKeys());
  const [asking, setAsking] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const canArchive = plan.allowed_transitions.some((t) => t.action === "archive");
  const canDuplicate = plan.capabilities.duplicate?.allowed === true;
  const exports = plan.exports;
  if (!canArchive && !canDuplicate && !exports.csv) return null;

  const run = async (name: string, call: (key: string) => Promise<PlanDetail>, done: (p: PlanDetail) => void) => {
    const signature = commandSignature(plan.id, name, plan.version);
    const attempt = keys.attempt(signature, () => null);
    setPending(name);
    try {
      const result = await call(attempt.key);
      keys.settle(signature);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.allPlans() });
      done(result);
    } catch (error) {
      keys.settle(signature, error);
      if (conflictFromError(error)) void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.plan(plan.id) });
      toast.error(m.editor.failed(name === "archive" ? m.editor.archive : m.editor.duplicate), { description: problemText(error) });
    } finally {
      setPending(null);
    }
  };

  return (
    <section aria-label={m.editor.exports} className="flex flex-col gap-3 border-t pt-6">
      {exports.csv ? (
        <div className="flex flex-col gap-2">
          <h2 className="text-lg font-[650] text-ink">{m.editor.exports}</h2>
          <ul className="flex flex-wrap gap-x-5 gap-y-2">
            <li>
              <a href={exports.csv} className={linkClasses}>{m.editor.csv}</a>
            </li>
            {exports.summary_csv ? (
              <li>
                <a href={exports.summary_csv} className={linkClasses}>{m.editor.summaryCsv}</a>
              </li>
            ) : null}
            {exports.pdf ? (
              <li>
                <a href={exports.pdf} target="_blank" rel="noopener" className={linkClasses}>{m.editor.pdf}</a>
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {canDuplicate ? (
          <Button
            isPending={pending === "duplicate"}
            onPress={() =>
              void run("duplicate", (key) => duplicatePlan(plan, key), (copy) => {
                queryClient.setQueryData(queryKeys.cutting.plan(copy.id), copy);
                toast.success(m.editor.duplicated(copy.plan_number));
                router.push(copy.path as Parameters<typeof router.push>[0]);
              })
            }
          >
            {m.editor.duplicate}
          </Button>
        ) : null}
        {canArchive ? (
          <Button variant="danger" onPress={() => setAsking(true)}>
            {m.editor.archive}
          </Button>
        ) : null}
      </div>
      <ReasonDialog
        title={m.editor.archive}
        description={m.editor.archiveConfirm}
        confirmLabel={m.editor.archive}
        isOpen={asking}
        isPending={pending === "archive"}
        onOpenChange={setAsking}
        onConfirm={() =>
          void run("archive", (key) => archivePlan(plan, key), (saved) => {
            setAsking(false);
            queryClient.setQueryData(queryKeys.cutting.plan(plan.id), saved);
            toast.success(m.editor.archived);
          })
        }
      />
    </section>
  );
}
