"use client";

/**
 * Data helpers for the Production screens (work orders, bills of materials, routings, work
 * centres, capacity, what-if).
 *
 * The API calls, types and URL state come from the old app's non-visual modules
 * (`@/features/production/api`, `@/features/production/list-state`). This file holds only what
 * lived inside old *view* files and so could not be imported: the command runner, the simulation
 * request builder and the status vocabulary. Endpoints, bodies, idempotency keys, conflict
 * handling and cache keys are the same as before.
 */

import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import type { Route } from "next";
import { useCallback, useState } from "react";
import type { SimulationRequest } from "@/features/production/api";
import type { ProductOption } from "@/features/sales/pickers";
import { problemDescription } from "@/features/sales/use-quote-command";
import { createIdempotencyKey } from "@/lib/api/client";
import { conflictFromError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { toast, type Tone } from "~/ui";

/** `router.push` and `Link` want typed routes; API paths and built URLs are plain strings. */
export const asRoute = (path: string) => path as Route;

// ---------------------------------------------------------------------------------------------
// Vocabulary: one word and one tone per status, shared by lists and records

export interface StatusLook {
  label: string;
  tone: Tone;
}

export function humanise(code: string): string {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const WORK_ORDER_STATUSES = ["draft", "released", "in_progress", "completed", "closed", "cancelled"] as const;

const WORK_ORDER_STATUS: Record<string, StatusLook> = {
  draft: { label: "Planned", tone: "neutral" },
  released: { label: "Released", tone: "cobalt" },
  in_progress: { label: "In progress", tone: "cobalt" },
  completed: { label: "Completed", tone: "leaf" },
  closed: { label: "Closed", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const VERSION_STATUS: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "amber" },
  approved: { label: "Approved", tone: "leaf" },
  retired: { label: "Retired", tone: "neutral" },
};

const look = (table: Record<string, StatusLook>, status: string): StatusLook => table[status] ?? { label: humanise(status), tone: "neutral" };

export const workOrderStatus = (status: string) => look(WORK_ORDER_STATUS, status);
export const versionStatus = (status: string) => look(VERSION_STATUS, status);

export const CANCEL_REASONS = [
  { id: "not_needed", label: "No longer needed" },
  { id: "order_cancelled", label: "The order was cancelled" },
  { id: "replanned", label: "Replanned" },
  { id: "data_error", label: "Entered by mistake" },
  { id: "other", label: "Something else" },
] as const;

export const POSTING_KIND: Record<string, string> = {
  issue: "Issued to the floor",
  consume: "Consumed",
  return: "Returned to stock",
  output: "Output received",
  offcut: "Offcut recorded",
};

export const WORK_CENTRE_KIND: Record<string, string> = { internal: "In-house", external: "Outside vendor" };
export const CALENDAR_SOURCE: Record<string, string> = { work_centre: "its own calendar", company_default: "the company calendar", built_in: "the built-in office day" };

export const FEASIBILITY_OUTCOME: Record<string, StatusLook> = {
  feasible: { label: "Can be done", tone: "leaf" },
  at_risk: { label: "At risk", tone: "amber" },
  not_feasible: { label: "Cannot be done", tone: "ember" },
  estimate: { label: "Estimate only", tone: "cobalt" },
};

export const EVIDENCE_KIND: Record<string, string> = {
  stock: "Stock",
  purchase_supply: "On order",
  components: "Components",
  capacity: "Capacity",
  routing: "Routing",
  bom: "Bill of materials",
  lead_time: "Lead time",
};

export const EVIDENCE_TONE: Record<string, Tone> = { ok: "leaf", short: "ember", missing: "cobalt", late: "amber", info: "neutral" };

// ---------------------------------------------------------------------------------------------
// One production command at a time

const OFFLINE = "You are offline. Changes can be saved once the connection is back.";

/**
 * Runs one production command at a time: a fresh Idempotency-Key per attempt, the answer written
 * into the record's cache, everything a stock or reservation change touches refreshed
 * (`invalidationMap["production.changed"]`), failures shown with the server's own detail (never
 * silent) and a 409 reloading the record instead of overwriting it.
 */
export function useProductionCommand<T>(recordKey: QueryKey) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [pending, setPending] = useState<string | null>(null);
  const offline = online ? null : OFFLINE;
  const run = useCallback(
    async <R,>(name: string, call: (key: string) => Promise<R>, options: { done?: string; failed: string; write?: (result: R) => T | null }): Promise<R | null> => {
      if (offline) {
        toast.error(options.failed, { description: offline });
        return null;
      }
      setPending(name);
      try {
        const result = await call(createIdempotencyKey());
        const record = options.write ? options.write(result) : null;
        if (record) queryClient.setQueryData(recordKey, record);
        await Promise.all(invalidationMap["production.changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey, refetchType: "active" })));
        if (options.done) toast.success(options.done);
        return result;
      } catch (error) {
        if (conflictFromError(error)) await queryClient.invalidateQueries({ queryKey: recordKey });
        toast.error(options.failed, { description: problemDescription(error) });
        return null;
      } finally {
        setPending(null);
      }
    },
    [offline, queryClient, recordKey],
  );
  return { run, pending, offline };
}

export type ProductionRun<T> = ReturnType<typeof useProductionCommand<T>>["run"];

// ---------------------------------------------------------------------------------------------
// What-if: the rows of the form and the request they make

export interface CheckRow {
  key: number;
  product: string | null;
  quantity: string;
  needBy: string | null;
  warehouse: string | null;
}

export interface StockRow {
  key: number;
  product: ProductOption | null;
  text: string;
  warehouse: string | null;
  delta: string;
}

export interface CapacityRow {
  key: number;
  workCentre: string | null;
  machines: number | null;
  extraMinutes: number | null;
}

export const MAX_CHECKS = 5;
export const MAX_CHANGES = 10;

/** The request the server sees: complete rows only, in the order shown. */
export function simulationBody(checks: readonly CheckRow[], stock: readonly StockRow[], capacity: readonly CapacityRow[]): SimulationRequest | null {
  const complete = checks.filter((check) => check.product && check.quantity && check.needBy);
  if (complete.length === 0) return null;
  return {
    checks: complete.map((check) => ({ product_id: check.product!, quantity: check.quantity, need_by: check.needBy!, warehouse_id: check.warehouse })),
    stock_changes: stock
      .filter((change) => change.product && change.delta && change.delta !== "0")
      .map((change) => ({ product_id: change.product!.id, warehouse_id: change.warehouse, delta: change.delta })),
    capacity_changes: capacity
      .filter((change) => change.workCentre && (change.machines !== null || change.extraMinutes !== null))
      .map((change) => ({ work_center_id: change.workCentre!, machine_count: change.machines, extra_minutes_per_day: change.extraMinutes })),
  };
}
