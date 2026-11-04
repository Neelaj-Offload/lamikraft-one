/**
 * The cutting API as the screens use it (INTERIM(api-generate): hand-written beside parse.ts until the
 * integrator regenerates schema.d.ts with the cutting routes). Dimensions, areas and percentages are
 * DecimalStr strings in millimetres, mm², m² and percent; piece counts are integers.
 */

export const PLAN_STATUSES = ["draft", "calculated", "released", "archived"] as const;
export type PlanStatus = (typeof PLAN_STATUSES)[number];
export const MODES = ["nested", "guillotine"] as const;
export type Mode = (typeof MODES)[number];
export const GRAIN_RULES = ["inherit", "locked", "free"] as const;
export type GrainRule = (typeof GRAIN_RULES)[number];
export type CalcStatus = "idle" | "queued" | "running" | "failed";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface UserRef {
  id: string;
  display_name: string | null;
}

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface PlanItem {
  id: string | null;
  line_no: number;
  product_id: string | null;
  sku: string;
  decor: string | null;
  decor_key: string;
  thickness_mm: string;
  length_mm: string;
  width_mm: string;
  quantity: number;
  grain_rule: GrainRule;
  label: string | null;
}

export interface PlanSettings {
  board_length_mm: string;
  board_width_mm: string;
  margin_mm: string;
  gap_mm: string;
  oversize_enabled: boolean;
  oversize_mm: string;
  mode: Mode;
  machine_profile_id: string | null;
  overproduction_enabled: boolean;
  max_extra_qty: number;
  max_extra_pct: string;
  min_offcut_mm: string;
  max_boards_per_group: number;
  raw_length_mm: string;
  raw_width_mm: string;
  usable_length_mm: string;
  usable_width_mm: string;
}

export interface Areas {
  raw_area_mm2: string;
  usable_area_mm2: string;
  placed_area_mm2: string;
  scrap_area_mm2: string;
  efficiency_usable_pct: string;
  efficiency_raw_pct: string;
  scrap_pct: string;
  raw_area_m2: string;
  placed_area_m2: string;
  scrap_area_m2: string;
}

export interface Placement {
  seq: number;
  line_no: number;
  sku: string;
  piece_no: number;
  x_mm: string;
  y_mm: string;
  along_length_mm: string;
  along_width_mm: string;
  rotated: boolean;
  is_extra: boolean;
}

export interface Offcut {
  seq: number;
  x_mm: string;
  y_mm: string;
  length_mm: string;
  width_mm: string;
}

export interface Board {
  index: number;
  board_no: number;
  /** standard sheet, or an offcut lot the plan chose (Slice 5 offcut reuse) */
  source: "standard" | "board_lot" | "offcut";
  lot_id: string | null;
  lot_code: string | null;
  raw_length_mm: string;
  raw_width_mm: string;
  margin_mm: string;
  usable_length_mm: string;
  usable_width_mm: string;
  placed_area_mm2: string;
  efficiency_pct: string;
  placements: Placement[];
  offcuts: Offcut[];
  cut_count: number;
  svg_path: string | null;
}

export type UnfitReason = "exceeds_usable_board" | "grain_lock_prevents_rotation" | "board_supply_exhausted" | "max_boards_limit";

export interface ItemResult {
  line_no: number;
  sku: string;
  length_mm: string;
  width_mm: string;
  rotation_allowed: boolean;
  required: number;
  placed_required: number;
  extra: number;
  produced: number;
  unfit: number;
  unfit_reason: UnfitReason | null;
}

export interface Group extends Areas {
  group_no: number;
  decor_key: string;
  thickness_mm: string;
  mode: Mode;
  board_count: number;
  lower_bound_boards: number;
  warnings: string[];
  items: ItemResult[];
  boards: Board[];
  offcut_boards: number;
}

export interface Totals extends Areas {
  boards: number;
  required: number;
  placed_required: number;
  extra: number;
  produced: number;
  unfit: number;
  lower_bound_boards: number;
  /** of `boards`, those cut from offcut lots */
  offcut_boards: number;
}

export interface Calculation {
  id: string | null;
  calc_no: number | null;
  created_at: string | null;
  created_by: UserRef | null;
  origin: "sync" | "job" | null;
  mode: Mode;
  requires_physical_verification: boolean;
  note: string;
  result_hash: string;
  totals: Totals;
  groups: Group[];
  grain_locked_decors: string[];
}

export interface CalcState {
  status: CalcStatus;
  requested_at: string | null;
  error: { code: string; detail: string } | null;
  pieces: number;
  sync_piece_limit: number;
  max_pieces: number;
}

export interface Verification {
  required: boolean;
  verified: boolean;
  verified_at: string | null;
  verified_by: UserRef | null;
  assumed_length_mm: string | null;
  assumed_width_mm: string | null;
  outcome: string | null;
}

export interface Transition {
  action: string;
  to_status: string;
}

export interface PlanDetail {
  id: string;
  plan_number: string;
  name: string;
  notes: string | null;
  status: PlanStatus;
  owner: UserRef;
  updated_at: string;
  version: number;
  duplicated_from: string | null;
  items: PlanItem[];
  settings: PlanSettings;
  stale: boolean;
  calculation: CalcState;
  verification: Verification;
  latest_calculation: Calculation | null;
  calculations: { calc_no: number; created_at: string; boards: number; efficiency_usable_pct: string; unfit: number }[];
  capabilities: Record<string, Capability>;
  allowed_transitions: Transition[];
  exports: { csv?: string; summary_csv?: string; pdf?: string };
  path: string;
  warnings: string[];
  offcuts: PlanOffcut[];
}

/** An offcut lot the plan may cut from, with its size pinned when chosen (grain along the length). */
export interface PlanOffcut {
  seq: number;
  lot_id: string;
  lot_code: string;
  thickness_mm: string;
  decor_key: string;
  length_mm: string;
  width_mm: string;
  /** null: the viewer cannot read stock */
  on_hand: boolean | null;
  used: boolean;
  matches_group: boolean;
}

export interface PlanSummary {
  id: string;
  plan_number: string;
  name: string;
  status: PlanStatus;
  owner: UserRef;
  item_count: number;
  piece_count: number;
  boards: number | null;
  efficiency_usable_pct: string | null;
  requires_physical_verification: boolean;
  verified: boolean;
  stale: boolean;
  calc_status: CalcStatus;
  updated_at: string;
  version: number;
  path: string;
}

export interface GrainLock {
  id: string;
  decor_key: string;
  decor_source: string | null;
  label: string | null;
  updated_at: string;
  updated_by: UserRef | null;
}

export interface GrainLockList {
  items: GrainLock[];
  can_manage: boolean;
  warnings: string[];
}

export interface CuttingProduct {
  product_id: string;
  product_key: string;
  display_sku: string;
  product_name: string;
  decor: string | null;
  decor_key: string;
  decor_name: string | null;
  thickness_mm: string | null;
  length_mm: string | null;
  width_mm: string | null;
  grain_locked: boolean;
}

/** One cut-list row in the request: quantity travels as an integer string (the server accepts "12"). */
export interface PlanItemRequest {
  product_id: string | null;
  sku: string;
  decor: string | null;
  thickness_mm: string;
  length_mm: string;
  width_mm: string;
  quantity: string;
  grain_rule: GrainRule;
}

export interface PlanSettingsRequest {
  board_length_mm?: string;
  board_width_mm?: string;
  margin_mm?: string;
  gap_mm?: string;
  oversize_enabled?: boolean;
  mode?: Mode;
  overproduction_enabled?: boolean;
  max_extra_qty?: string;
  max_extra_pct?: string;
}
