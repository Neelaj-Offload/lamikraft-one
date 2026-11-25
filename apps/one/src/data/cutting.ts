"use client";

/**
 * Data helpers for the cut plan screens (`/operations/cutting`).
 *
 * The API calls, parsers, types, list state and the editor model come from the old app's non-visual
 * modules (`@/features/cutting/{api,types,list-state,editor-model}`). This file holds only what
 * lived inside old *view* files and so could not be imported: the plan query with its polling, the
 * editor's save / calculate / conflict handling, the plan commands (duplicate, archive, verify,
 * offcut choice), the grain lock commands and the catalogue search. Endpoints, bodies, idempotency
 * keys, optimistic versions and cache keys are the same as before.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useState } from "react";
import {
  addGrainLock,
  archivePlan,
  calculatePlan,
  createPlan,
  duplicatePlan,
  fetchGrainLocks,
  fetchOffcutCandidates,
  fetchPlan,
  removeGrainLock,
  saveOffcuts,
  searchCuttingProducts,
  updatePlan,
  verifyBoards,
} from "@/features/cutting/api";
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
} from "@/features/cutting/editor-model";
import type { CuttingProduct, GrainLock, GrainLockList, PlanDetail } from "@/features/cutting/types";
import { problemDescription } from "@/features/sales/use-quote-command";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { conflictFromError, ProblemError, type ConflictInfo } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { compareDecimalStr } from "@/lib/format/decimal";
import { useDebouncedValue, useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { toast, type Tone } from "~/ui";

/** `router.push` and `Link` want typed routes; API paths and built URLs are plain strings. */
export const asRoute = (path: string) => path as Route;

// ---------------------------------------------------------------------------------------------
// Vocabulary

export interface StatusLook {
  label: string;
  tone: Tone;
}

const PLAN_STATUS: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  calculated: { label: "Calculated", tone: "leaf" },
  released: { label: "Released", tone: "cobalt" },
  archived: { label: "Archived", tone: "neutral" },
};

export function planStatus(status: string): StatusLook {
  return PLAN_STATUS[status] ?? { label: status.replace(/_/g, " "), tone: "neutral" };
}

export const MODE_LABEL: Record<string, string> = { nested: "Nested, for the CNC", guillotine: "Guillotine, for the panel saw" };
export const MODE_SHORT: Record<string, string> = { nested: "Nested", guillotine: "Guillotine" };
export const GRAIN_LABEL: Record<string, string> = { inherit: "By decor", locked: "Never rotate", free: "May rotate" };

export const UNFIT_LABEL: Record<string, string> = {
  exceeds_usable_board: "Larger than the usable board",
  grain_lock_prevents_rotation: "Fits only when rotated, and the grain is locked",
  board_supply_exhausted: "No boards left",
  max_boards_limit: "Board limit reached",
};

export const GROUP_WARNING: Record<string, string> = {
  blank_decor_treated_as_locked: "Pieces without a decor are treated as grain-locked.",
  oversize_requires_physical_verification: "This layout assumes oversize boards. Measure the boards before the plan is released.",
};

/** Whether a calculation job is in flight for this plan. */
export function isCalculating(plan: Pick<PlanDetail, "calculation">): boolean {
  return plan.calculation.status === "queued" || plan.calculation.status === "running";
}

// ---------------------------------------------------------------------------------------------
// Reads

/** Poll while the calculation job runs (large plans); stop as soon as it is idle or failed. */
export const CALC_POLL_MS = 1500;

/** A saved plan, refreshed every 1.5 seconds while its layout is being calculated in the background. */
export function usePlan(planId: string) {
  return useQuery({
    queryKey: queryKeys.cutting.plan(planId),
    queryFn: ({ signal }) => fetchPlan(planId, signal),
    refetchInterval: (query) => (query.state.data && isCalculating(query.state.data) ? CALC_POLL_MS : false),
  });
}

/** Catalogue products for the cut list, searched on the server from two characters (needs the right to calculate). */
export function useCuttingProductSearch(text: string) {
  const { permissionKeys } = useSession();
  const q = useDebouncedValue(text.trim(), 250);
  const allowed = permissionKeys.has("cutting.calculation.run");
  const enabled = allowed && q.length >= 2;
  const query = useQuery({
    queryKey: queryKeys.cutting.products(q),
    queryFn: ({ signal }) => searchCuttingProducts(q, signal),
    enabled,
    staleTime: 30_000,
  });
  return { allowed, products: enabled ? (query.data ?? []) : [], isSearching: enabled && query.isFetching };
}

/** Measured offcut lots on hand that this plan could cut from. */
export function useOffcutCandidates(planId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.cutting.offcutCandidates(planId),
    queryFn: ({ signal }) => fetchOffcutCandidates(planId, signal),
    enabled,
  });
}

// ---------------------------------------------------------------------------------------------
// The plan editor: name, cut list and board settings

const NO_ERRORS: FormErrors = { rows: {}, settings: {}, general: [] };

export type { EditorForm, EditorRow, EditorSettings, FormErrors };

export interface PlanEditor {
  form: EditorForm;
  errors: FormErrors;
  /** Set when a save or a calculation met a newer version on the server. */
  conflict: ConflictInfo | null;
  pending: "save" | "calculate" | null;
  /** Unsaved changes (always true for a plan that does not exist yet). */
  dirty: boolean;
  offline: boolean;
  setName: (name: string) => void;
  setRow: (key: string, change: Partial<EditorRow>) => void;
  setSetting: <K extends keyof EditorSettings>(key: K, value: EditorSettings[K]) => void;
  /** Adds a blank row and returns its key, so the screen can move focus to it. */
  addRow: () => string;
  removeRow: (key: string) => void;
  /** A catalogue product fills the first blank row, or a new one. */
  pickProduct: (product: CuttingProduct) => void;
  /** Runs the client checks, shows their messages and returns them. */
  check: () => FormErrors;
  /** Creates or saves the plan; null when it did not go through (the errors or the conflict say why). */
  save: () => Promise<PlanDetail | null>;
  calculate: () => Promise<void>;
  discard: () => void;
  /** After a conflict: take the server's version and drop mine. */
  loadTheirs: () => Promise<void>;
  /** After a conflict: keep my edits and save them over the server's version next. */
  keepMine: () => Promise<void>;
}

/**
 * The editor's state for a saved plan (`plan`) or a new one (`null`). Only what changed is sent
 * (plus the expected version); a 409 becomes `conflict`, a 422 lands on the rows and fields.
 */
export function usePlanEditor(plan: PlanDetail | null): PlanEditor {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [commandKeys] = useState(() => createCommandKeys());
  const [state, setState] = useState<{ base: EditorForm; form: EditorForm; version: number }>(() => {
    const base = formOf(plan);
    return { base, form: base, version: plan?.version ?? 0 };
  });
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const [conflict, setConflict] = useState<ConflictInfo | null>(null);
  const [pending, setPending] = useState<"save" | "calculate" | null>(null);

  // A newer server version with no local edits (another tab, the job finishing): show it.
  if (plan && plan.version !== state.version && dirtyParts(state.base, state.form).length === 0 && !conflict) {
    const base = formOf(plan);
    setState({ base, form: base, version: plan.version });
  }

  const dirty = plan ? dirtyParts(state.base, state.form).length > 0 : true;
  const setForm = (next: (form: EditorForm) => EditorForm) => setState((s) => ({ ...s, form: next(s.form) }));

  const save = async (): Promise<PlanDetail | null> => {
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
      setErrors(NO_ERRORS);
      if (plan) {
        const base = formOf(saved);
        setState({ base, form: base, version: saved.version });
        toast.success("Plan saved");
      } else {
        toast.success(`Cut plan ${saved.plan_number} created`);
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
        toast.error(plan ? "The plan was not saved" : "The plan was not created", { description: problemDescription(error) });
      }
      return null;
    } finally {
      setPending(null);
    }
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
      if (result.calculation.status === "idle") toast.success("Layout calculated");
    } catch (error) {
      commandKeys.settle(signature, error);
      const info = conflictFromError(error);
      if (info) setConflict(info);
      else toast.error("The layout was not calculated", { description: problemDescription(error) });
    } finally {
      setPending(null);
    }
  };

  const loadTheirs = async () => {
    if (!plan) return;
    const fresh = await fetchPlan(plan.id);
    queryClient.setQueryData(queryKeys.cutting.plan(plan.id), fresh);
    const base = formOf(fresh);
    setConflict(null);
    setErrors(NO_ERRORS);
    setState({ base, form: base, version: fresh.version });
  };

  const keepMine = async () => {
    if (!plan) return;
    const fresh = await fetchPlan(plan.id);
    setConflict(null);
    setState((s) => ({ base: formOf(fresh), form: s.form, version: fresh.version }));
  };

  return {
    form: state.form,
    errors,
    conflict,
    pending,
    dirty,
    offline: !online,
    setName: (name) => setForm((form) => ({ ...form, name })),
    setRow: (key, change) => setForm((form) => ({ ...form, rows: form.rows.map((row) => (row.key === key ? { ...row, ...change } : row)) })),
    setSetting: (key, value) => setForm((form) => ({ ...form, settings: { ...form.settings, [key]: value } })),
    addRow: () => {
      const row = blankRow();
      setForm((form) => ({ ...form, rows: [...form.rows, row] }));
      return row.key;
    },
    removeRow: (key) => setForm((form) => ({ ...form, rows: form.rows.filter((row) => row.key !== key) })),
    pickProduct: (product) =>
      setForm((form) => {
        const blank = form.rows.find(isBlankRow);
        const rows = blank ? form.rows.map((row) => (row.key === blank.key ? applyProduct(row, product) : row)) : [...form.rows, applyProduct(blankRow(), product)];
        return { ...form, rows };
      }),
    check: () => {
      const local = validateForm(state.form);
      setErrors(local);
      return local;
    },
    save,
    calculate,
    discard: () => {
      setErrors(NO_ERRORS);
      setState((s) => ({ ...s, form: s.base }));
    },
    loadTheirs,
    keepMine,
  };
}

// ---------------------------------------------------------------------------------------------
// Plan commands: duplicate, archive, verify the boards, choose offcuts

/** The selection after toggling one lot, keeping the order the planner chose (the layout fills in this order). */
export function toggledSelection(current: readonly string[], lotId: string, on: boolean): string[] {
  const without = current.filter((id) => id !== lotId);
  return on ? [...without, lotId] : without;
}

export function usePlanCommands(plan: PlanDetail) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [keys] = useState(() => createCommandKeys());
  const [pending, setPending] = useState<"duplicate" | "archive" | "verify" | "offcuts" | null>(null);
  const planKey = queryKeys.cutting.plan(plan.id);

  const run = async (name: NonNullable<typeof pending>, signature: string, call: (key: string) => Promise<PlanDetail>, failed: string): Promise<PlanDetail | null> => {
    const attempt = keys.attempt(signature, () => null);
    setPending(name);
    try {
      const result = await call(attempt.key);
      keys.settle(signature);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.allPlans() });
      return result;
    } catch (error) {
      keys.settle(signature, error);
      if (conflictFromError(error)) void queryClient.invalidateQueries({ queryKey: planKey });
      toast.error(failed, { description: problemDescription(error) });
      return null;
    } finally {
      setPending(null);
    }
  };

  return {
    pending,
    offline: !online,
    /** Saves a copy as a new draft and returns it (the screen opens it). */
    duplicate: async () => {
      const copy = await run("duplicate", commandSignature(plan.id, "duplicate", plan.version), (key) => duplicatePlan(plan, key), "The plan was not duplicated");
      if (copy) {
        queryClient.setQueryData(queryKeys.cutting.plan(copy.id), copy);
        toast.success(`Copy saved as ${copy.plan_number}`);
      }
      return copy;
    },
    archive: async () => {
      const saved = await run("archive", commandSignature(plan.id, "archive", plan.version), (key) => archivePlan(plan, key), "The plan was not archived");
      if (saved) {
        queryClient.setQueryData(planKey, saved);
        toast.success("Plan archived");
      }
      return saved;
    },
    verify: async (measured: { length_mm: string; width_mm: string; note: string }) => {
      const saved = await run(
        "verify",
        commandSignature(plan.id, "verify", plan.version, measured.length_mm, measured.width_mm),
        (key) => verifyBoards(plan, measured, key),
        "The measurement was not recorded",
      );
      if (saved) {
        queryClient.setQueryData(planKey, saved);
        toast.success("Measurement recorded");
      }
      return saved;
    },
    /** Replaces the plan's offcut choice; a calculated plan becomes stale and the server checks every lot again. */
    chooseOffcuts: async (lotIds: string[]) => {
      const saved = await run("offcuts", commandSignature(plan.id, "offcuts", plan.version, lotIds.join(",")), (key) => saveOffcuts(plan, lotIds, key), "The offcut choice was not saved");
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.offcutCandidates(plan.id) });
      if (saved) {
        queryClient.setQueryData(planKey, saved);
        toast.success("Offcut choice saved", { description: "Calculate the layout again to use it." });
      }
      return saved;
    },
  };
}

// ---------------------------------------------------------------------------------------------
// Grain locks

export function useGrainLocks() {
  return useQuery({ queryKey: queryKeys.cutting.grainLocks(), queryFn: ({ signal }) => fetchGrainLocks(signal) });
}

export function useGrainLockCommands() {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [keys] = useState(() => createCommandKeys());
  /** "add", or the decor key being removed. */
  const [pending, setPending] = useState<string | null>(null);

  const apply = (next: GrainLockList, message: string) => {
    queryClient.setQueryData(queryKeys.cutting.grainLocks(), next);
    void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.allPlanDetails() });
    toast.success(message, next.warnings.length ? { description: next.warnings.join(" ") } : {});
  };

  return {
    pending,
    offline: !online,
    /** On failure, `fieldError` is the message to show under the decor field (409 and 422); otherwise a toast was raised. */
    add: async (decor: string, label: string): Promise<{ ok: true } | { ok: false; fieldError: string | null }> => {
      const signature = commandSignature("grain-lock", "add", decor.trim(), label.trim());
      const attempt = keys.attempt(signature, () => null);
      setPending("add");
      try {
        const next = await addGrainLock({ decor, label }, attempt.key);
        keys.settle(signature);
        const stored = next.items.find((lock) => lock.decor_source === decor.trim())?.decor_key ?? decor.trim();
        apply(next, `Decor ${stored} is grain-locked`);
        return { ok: true };
      } catch (error) {
        keys.settle(signature, error);
        if (error instanceof ProblemError && (error.status === 409 || error.status === 422)) {
          return { ok: false, fieldError: error.validationIssues[0]?.msg ?? error.detail ?? error.title };
        }
        toast.error("The grain lock was not added", { description: problemDescription(error) });
        return { ok: false, fieldError: null };
      } finally {
        setPending(null);
      }
    },
    remove: async (lock: GrainLock): Promise<boolean> => {
      const signature = commandSignature("grain-lock", "remove", lock.decor_key);
      const attempt = keys.attempt(signature, () => null);
      setPending(lock.decor_key);
      try {
        const next = await removeGrainLock(lock.decor_key, attempt.key);
        keys.settle(signature);
        apply(next, `Decor ${lock.decor_key} may rotate again`);
        return true;
      } catch (error) {
        keys.settle(signature, error);
        void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.grainLocks() });
        toast.error("The grain lock was not removed", { description: problemDescription(error) });
        return false;
      } finally {
        setPending(null);
      }
    },
  };
}

// ---------------------------------------------------------------------------------------------
// The board drawing: zoom steps and what a piece says about itself

/** Zoom steps of the drawing (its width as a share of the frame); 1 fits the board to the frame. */
export const ZOOM_STEPS = [1, 1.5, 2, 3, 4, 6] as const;

export function nextZoom(current: number, direction: 1 | -1): number {
  const index = ZOOM_STEPS.findIndex((step) => step === current);
  const next = Math.min(Math.max((index < 0 ? 0 : index) + direction, 0), ZOOM_STEPS.length - 1);
  return ZOOM_STEPS[next]!;
}

/** Labels only where they fit: at least 250 mm along the length and 80 mm across (the table lists every piece). */
export function pieceShowsLabel(piece: { along_length_mm: string; along_width_mm: string }): boolean {
  return compareDecimalStr(piece.along_length_mm, "250") >= 0 && compareDecimalStr(piece.along_width_mm, "80") >= 0;
}
