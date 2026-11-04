/**
 * Quality API (backend/app/modules/quality/router.py), typed from the generated schema: inspections of stock in QC
 * hold (list by status, detail with capabilities and the suggested checklist, decide). Deciding posts the accepted
 * quantity to stock and the rejected quantity to the rejected location once; scope is enforced by the server.
 */

import { api, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type InspectionSummary = Schemas["InspectionSummary"];
export type InspectionDetail = Schemas["InspectionDetail"];
export type ChecklistItem = Schemas["ChecklistItem"];
export type CheckResult = ChecklistItem["result"];

export const PAGE_SIZE = 25;
export const INSPECTION_STATUSES = ["pending", "passed", "failed", "cancelled"] as const;

export function fetchInspections(params: { status?: string | null; offset?: number }, signal?: AbortSignal, client: ApiClient = api) {
  const status = INSPECTION_STATUSES.find((s) => s === params.status);
  return unwrap(
    client.GET("/api/v1/quality/inspections", {
      params: { query: { status: status ? [status] : undefined, limit: PAGE_SIZE, offset: params.offset ?? 0 } },
      signal,
    }),
  );
}

export function fetchInspection(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<InspectionDetail> {
  return unwrap(client.GET("/api/v1/quality/inspections/{inspection_id}", { params: { path: { inspection_id: id } }, signal }));
}

export interface InspectionDecisionDraft {
  qty_accepted: string;
  qty_rejected: string;
  checklist: ChecklistItem[];
  findings: string;
  reject_reason_code: string | null;
}

export function decideInspection(insp: Pick<InspectionDetail, "id" | "version">, draft: InspectionDecisionDraft, key: string, client: ApiClient = api): Promise<InspectionDetail> {
  return unwrap(
    client.POST("/api/v1/quality/inspections/{inspection_id}/decide", {
      params: { path: { inspection_id: insp.id } },
      body: {
        expected_version: insp.version,
        qty_accepted: draft.qty_accepted,
        qty_rejected: draft.qty_rejected,
        checklist: draft.checklist,
        findings: draft.findings.trim() || null,
        reject_reason_code: draft.reject_reason_code,
      },
      headers: idempotencyHeaders(key),
    }),
  );
}

/** Whether a + b equals total exactly (scaled BigInt arithmetic on DecimalStr values; never a float). */
export function addsUpTo(a: string, b: string, total: string): boolean {
  const re = /^\d+(\.\d+)?$/;
  if (![a, b, total].every((v) => re.test(v))) return false;
  const scale = Math.max(...[a, b, total].map((v) => (v.split(".")[1] ?? "").length));
  const scaled = (v: string) => {
    const [int = "0", frac = ""] = v.split(".");
    return BigInt(int + frac.padEnd(scale, "0"));
  };
  return scaled(a) + scaled(b) === scaled(total);
}
