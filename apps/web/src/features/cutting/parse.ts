/**
 * Runtime readers for the cutting API (see types.ts). Required fields are checked, DecimalStr values are
 * validated and never converted, and links must stay inside the app or under /api/v1/cutting.
 */

import { isDecimalStr } from "@/lib/format/decimal";
import { safeAppPath } from "@/lib/safe-path";
import {
  GRAIN_RULES,
  MODES,
  PLAN_STATUSES,
  type Areas,
  type Board,
  type CalcState,
  type Calculation,
  type Capability,
  type CuttingProduct,
  type GrainLock,
  type GrainLockList,
  type GrainRule,
  type Group,
  type ItemResult,
  type Mode,
  type Page,
  type PlanDetail,
  type PlanItem,
  type PlanSettings,
  type PlanStatus,
  type PlanSummary,
  type Totals,
  type UnfitReason,
  type UserRef,
} from "./types";

export class CuttingShapeError extends Error {
  override readonly name = "CuttingShapeError";
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);
const dec = (value: unknown): string | null => (isDecimalStr(value) ? value : null);
const bool = (value: unknown): boolean => value === true;

function need<T>(value: T | null, what: string): T {
  if (value === null) throw new CuttingShapeError(`The cutting response has no valid ${what}.`);
  return value;
}

function obj(value: unknown, what: string): Json {
  if (!isObject(value)) throw new CuttingShapeError(`The cutting response has no ${what}.`);
  return value;
}

const API_LINK = /^\/api\/v1\/cutting\/[A-Za-z0-9/_.?=-]+$/;
function apiLink(value: unknown): string | null {
  const s = str(value);
  return s && API_LINK.test(s) && !s.includes("..") ? s : null;
}

function oneOf<T extends string>(values: readonly T[], value: unknown, what: string): T {
  const found = values.find((candidate) => candidate === value);
  if (!found) throw new CuttingShapeError(`The cutting response has an unknown ${what}.`);
  return found;
}

function user(value: unknown): UserRef | null {
  return isObject(value) && str(value.id) ? { id: str(value.id)!, display_name: str(value.display_name) } : null;
}

function areas(raw: Json, what: string): Areas {
  const d = (key: keyof Areas) => need(dec(raw[key]), `${what} ${key}`);
  return {
    raw_area_mm2: d("raw_area_mm2"),
    usable_area_mm2: d("usable_area_mm2"),
    placed_area_mm2: d("placed_area_mm2"),
    scrap_area_mm2: d("scrap_area_mm2"),
    efficiency_usable_pct: d("efficiency_usable_pct"),
    efficiency_raw_pct: d("efficiency_raw_pct"),
    scrap_pct: d("scrap_pct"),
    raw_area_m2: d("raw_area_m2"),
    placed_area_m2: d("placed_area_m2"),
    scrap_area_m2: d("scrap_area_m2"),
  };
}

export function parseSettings(value: unknown): PlanSettings {
  const raw = obj(value, "settings");
  const d = (key: string) => need(dec(raw[key]), `setting ${key}`);
  return {
    board_length_mm: d("board_length_mm"),
    board_width_mm: d("board_width_mm"),
    margin_mm: d("margin_mm"),
    gap_mm: d("gap_mm"),
    oversize_enabled: bool(raw.oversize_enabled),
    oversize_mm: d("oversize_mm"),
    mode: oneOf(MODES, raw.mode, "mode") as Mode,
    machine_profile_id: str(raw.machine_profile_id),
    overproduction_enabled: bool(raw.overproduction_enabled),
    max_extra_qty: int(raw.max_extra_qty) ?? 0,
    max_extra_pct: d("max_extra_pct"),
    min_offcut_mm: d("min_offcut_mm"),
    max_boards_per_group: int(raw.max_boards_per_group) ?? 500,
    raw_length_mm: d("raw_length_mm"),
    raw_width_mm: d("raw_width_mm"),
    usable_length_mm: d("usable_length_mm"),
    usable_width_mm: d("usable_width_mm"),
  };
}

function parseItem(value: unknown): PlanItem {
  const raw = obj(value, "item");
  return {
    id: str(raw.id),
    line_no: need(int(raw.line_no), "line number"),
    product_id: str(raw.product_id),
    sku: text(raw.sku),
    decor: str(raw.decor),
    decor_key: text(raw.decor_key),
    thickness_mm: need(dec(raw.thickness_mm), "thickness"),
    length_mm: need(dec(raw.length_mm), "length"),
    width_mm: need(dec(raw.width_mm), "width"),
    quantity: need(int(raw.quantity), "quantity"),
    grain_rule: oneOf(GRAIN_RULES, raw.grain_rule, "grain rule") as GrainRule,
    label: str(raw.label),
  };
}

function parseItemResult(value: unknown): ItemResult {
  const raw = obj(value, "item result");
  const n = (key: string) => need(int(raw[key]), key);
  return {
    line_no: n("line_no"),
    sku: text(raw.sku),
    length_mm: need(dec(raw.length_mm), "length"),
    width_mm: need(dec(raw.width_mm), "width"),
    rotation_allowed: bool(raw.rotation_allowed),
    required: n("required"),
    placed_required: n("placed_required"),
    extra: n("extra"),
    produced: n("produced"),
    unfit: n("unfit"),
    unfit_reason: (str(raw.unfit_reason) as UnfitReason | null) ?? null,
  };
}

function parseBoard(value: unknown): Board {
  const raw = obj(value, "board");
  const d = (key: string) => need(dec(raw[key]), `board ${key}`);
  return {
    index: need(int(raw.index), "board index"),
    board_no: need(int(raw.board_no), "board number"),
    raw_length_mm: d("raw_length_mm"),
    raw_width_mm: d("raw_width_mm"),
    margin_mm: d("margin_mm"),
    usable_length_mm: d("usable_length_mm"),
    usable_width_mm: d("usable_width_mm"),
    placed_area_mm2: d("placed_area_mm2"),
    efficiency_pct: d("efficiency_pct"),
    placements: arr(raw.placements).map((entry) => {
      const p = obj(entry, "placement");
      const pd = (key: string) => need(dec(p[key]), `placement ${key}`);
      return {
        seq: need(int(p.seq), "placement number"),
        line_no: need(int(p.line_no), "placement line"),
        sku: text(p.sku),
        piece_no: int(p.piece_no) ?? 0,
        x_mm: pd("x_mm"),
        y_mm: pd("y_mm"),
        along_length_mm: pd("along_length_mm"),
        along_width_mm: pd("along_width_mm"),
        rotated: bool(p.rotated),
        is_extra: bool(p.is_extra),
      };
    }),
    offcuts: arr(raw.offcuts).map((entry) => {
      const o = obj(entry, "offcut");
      const od = (key: string) => need(dec(o[key]), `offcut ${key}`);
      return { seq: int(o.seq) ?? 0, x_mm: od("x_mm"), y_mm: od("y_mm"), length_mm: od("length_mm"), width_mm: od("width_mm") };
    }),
    cut_count: arr(raw.cuts).length,
    svg_path: apiLink(raw.svg_path),
  };
}

function parseGroup(value: unknown): Group {
  const raw = obj(value, "group");
  return {
    ...areas(raw, "group"),
    group_no: need(int(raw.group_no), "group number"),
    decor_key: text(raw.decor_key),
    thickness_mm: text(raw.thickness_mm),
    mode: oneOf(MODES, raw.mode, "mode") as Mode,
    board_count: need(int(raw.board_count), "board count"),
    lower_bound_boards: int(raw.lower_bound_boards) ?? 0,
    warnings: arr(raw.warnings).flatMap((w) => (typeof w === "string" ? [w] : [])),
    items: arr(raw.items).map(parseItemResult),
    boards: arr(raw.boards).map(parseBoard),
  };
}

export function parseCalculation(value: unknown): Calculation {
  const raw = obj(value, "calculation");
  const t = obj(raw.totals, "totals");
  const n = (key: string) => need(int(t[key]), `total ${key}`);
  const totals: Totals = {
    ...areas(t, "totals"),
    boards: n("boards"),
    required: n("required"),
    placed_required: n("placed_required"),
    extra: n("extra"),
    produced: n("produced"),
    unfit: n("unfit"),
    lower_bound_boards: n("lower_bound_boards"),
  };
  return {
    id: str(raw.id),
    calc_no: int(raw.calc_no),
    created_at: str(raw.created_at),
    created_by: user(raw.created_by),
    origin: raw.origin === "sync" || raw.origin === "job" ? raw.origin : null,
    mode: oneOf(MODES, raw.mode, "mode") as Mode,
    requires_physical_verification: bool(raw.requires_physical_verification),
    note: text(raw.note),
    result_hash: text(raw.result_hash),
    totals,
    groups: arr(raw.groups).map(parseGroup),
    grain_locked_decors: arr(raw.grain_locked_decors).flatMap((d) => (typeof d === "string" ? [d] : [])),
  };
}

function capabilities(value: unknown): Record<string, Capability> {
  if (!isObject(value)) return {};
  const out: Record<string, Capability> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (isObject(entry)) out[key] = { allowed: entry.allowed === true, reason_code: str(entry.reason_code) };
  }
  return out;
}

function calcState(value: unknown): CalcState {
  const raw = obj(value, "calculation state");
  const status = raw.status === "queued" || raw.status === "running" || raw.status === "failed" ? raw.status : "idle";
  const error = isObject(raw.error) ? { code: text(raw.error.code), detail: text(raw.error.detail) } : null;
  return {
    status,
    requested_at: str(raw.requested_at),
    error,
    pieces: int(raw.pieces) ?? 0,
    sync_piece_limit: int(raw.sync_piece_limit) ?? 300,
    max_pieces: int(raw.max_pieces) ?? 5000,
  };
}

export function parsePlanDetail(value: unknown): PlanDetail {
  const raw = obj(value, "plan");
  const v = isObject(raw.verification) ? raw.verification : {};
  const exportsRaw = isObject(raw.exports) ? raw.exports : {};
  return {
    id: need(str(raw.id), "plan id"),
    plan_number: need(str(raw.plan_number), "plan number"),
    name: text(raw.name),
    notes: str(raw.notes),
    status: oneOf(PLAN_STATUSES, raw.status, "status") as PlanStatus,
    owner: need(user(raw.owner), "owner"),
    updated_at: text(raw.updated_at),
    version: need(int(raw.version), "version"),
    duplicated_from: str(raw.duplicated_from),
    items: arr(raw.items).map(parseItem),
    settings: parseSettings(raw.settings),
    stale: bool(raw.stale),
    calculation: calcState(raw.calculation),
    verification: {
      required: bool(v.required),
      verified: bool(v.verified),
      verified_at: str(v.verified_at),
      verified_by: user(v.verified_by),
      assumed_length_mm: dec(v.assumed_length_mm),
      assumed_width_mm: dec(v.assumed_width_mm),
      outcome: isObject(v.measured) ? str(v.measured.outcome) : null,
    },
    latest_calculation: raw.latest_calculation ? parseCalculation(raw.latest_calculation) : null,
    calculations: arr(raw.calculations).flatMap((entry) =>
      isObject(entry) && int(entry.calc_no) !== null
        ? [{ calc_no: int(entry.calc_no)!, created_at: text(entry.created_at), boards: int(entry.boards) ?? 0,
             efficiency_usable_pct: dec(entry.efficiency_usable_pct) ?? "0", unfit: int(entry.unfit) ?? 0 }]
        : [],
    ),
    capabilities: capabilities(raw.capabilities),
    allowed_transitions: arr(raw.allowed_transitions).flatMap((entry) =>
      isObject(entry) && str(entry.action) ? [{ action: str(entry.action)!, to_status: text(entry.to_status) }] : [],
    ),
    exports: {
      csv: apiLink(exportsRaw.csv) ?? undefined,
      summary_csv: apiLink(exportsRaw.summary_csv) ?? undefined,
      pdf: apiLink(exportsRaw.pdf) ?? undefined,
    },
    path: safeAppPath(str(raw.path)) ?? `/operations/cutting/${encodeURIComponent(need(str(raw.id), "plan id"))}`,
    warnings: arr(raw.warnings).flatMap((w) => (typeof w === "string" ? [w] : [])),
  };
}

export function parsePlanSummary(value: unknown): PlanSummary {
  const raw = obj(value, "plan");
  const id = need(str(raw.id), "plan id");
  return {
    id,
    plan_number: need(str(raw.plan_number), "plan number"),
    name: text(raw.name),
    status: oneOf(PLAN_STATUSES, raw.status, "status") as PlanStatus,
    owner: need(user(raw.owner), "owner"),
    item_count: int(raw.item_count) ?? 0,
    piece_count: int(raw.piece_count) ?? 0,
    boards: int(raw.boards),
    efficiency_usable_pct: dec(raw.efficiency_usable_pct),
    requires_physical_verification: bool(raw.requires_physical_verification),
    verified: bool(raw.verified),
    stale: bool(raw.stale),
    calc_status: raw.calc_status === "queued" || raw.calc_status === "running" || raw.calc_status === "failed" ? raw.calc_status : "idle",
    updated_at: text(raw.updated_at),
    version: int(raw.version) ?? 1,
    path: safeAppPath(str(raw.path)) ?? `/operations/cutting/${encodeURIComponent(id)}`,
  };
}

export function parsePage<T>(value: unknown, parse: (entry: unknown) => T): Page<T> {
  const raw = obj(value, "page");
  return {
    items: arr(raw.items).map(parse),
    total: int(raw.total) ?? 0,
    limit: int(raw.limit) ?? 25,
    offset: int(raw.offset) ?? 0,
  };
}

export function parseGrainLocks(value: unknown): GrainLockList {
  const raw = obj(value, "grain locks");
  return {
    items: arr(raw.items).flatMap((entry): GrainLock[] =>
      isObject(entry) && str(entry.id) && str(entry.decor_key)
        ? [{ id: str(entry.id)!, decor_key: str(entry.decor_key)!, decor_source: str(entry.decor_source), label: str(entry.label),
             updated_at: text(entry.updated_at), updated_by: user(entry.updated_by) }]
        : [],
    ),
    can_manage: bool(raw.can_manage),
    warnings: arr(raw.warnings).flatMap((w) => (typeof w === "string" ? [w] : [])),
  };
}

export function parseProducts(value: unknown): CuttingProduct[] {
  return arr(value).flatMap((entry): CuttingProduct[] =>
    isObject(entry) && str(entry.product_id) && str(entry.product_key)
      ? [{
          product_id: str(entry.product_id)!,
          product_key: str(entry.product_key)!,
          display_sku: text(entry.display_sku),
          product_name: text(entry.product_name),
          decor: str(entry.decor),
          decor_key: text(entry.decor_key),
          decor_name: str(entry.decor_name),
          thickness_mm: dec(entry.thickness_mm),
          length_mm: dec(entry.length_mm),
          width_mm: dec(entry.width_mm),
          grain_locked: bool(entry.grain_locked),
        }]
      : [],
  );
}
