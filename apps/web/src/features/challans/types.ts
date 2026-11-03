/**
 * Hand types mirroring the challans read models (backend/app/modules/challans/schemas.py). Quantities are
 * DecimalStr strings everywhere and are never added in the browser: the server returns totals per unit.
 * INTERIM(api-generate): the generated `schema.d.ts` has these shapes too; parse.ts is the runtime reader.
 */

export const CHALLAN_TYPES = ["outward", "inward", "return", "job_work", "transfer", "sample"] as const;
export type ChallanType = (typeof CHALLAN_TYPES)[number];

export const RETURN_TYPES = ["returnable", "non_returnable"] as const;
export type ReturnType = (typeof RETURN_TYPES)[number];

export const DESTINATION_TYPES = ["fabricator", "customer", "warehouse", "vendor", "office", "transporter"] as const;
export type DestinationType = (typeof DESTINATION_TYPES)[number];

export const CHALLAN_STATUSES = ["draft", "issued", "closed", "cancelled"] as const;
export type ChallanStatus = (typeof CHALLAN_STATUSES)[number];

export const LINE_TYPES = ["catalog", "custom", "manual"] as const;
export type LineType = (typeof LINE_TYPES)[number];

export const PERIODS = ["this_week", "this_month"] as const;
export type Period = (typeof PERIODS)[number];

/** The legacy unit list of the line dialog (all seeded in the company's UOM master). */
export const LEGACY_UNITS = ["pcs", "nos", "sheets", "kg", "m", "sqm", "sqft", "box", "set", "roll", "bundle"] as const;

/**
 * Which return types and destinations each type accepts (movement_policy.POLICY). The server checks this on
 * every save; the form uses it only to offer valid choices first.
 */
export const TYPE_POLICY: Record<ChallanType, { returnTypes: readonly ReturnType[]; destinations: readonly DestinationType[]; defaultReturn: ReturnType }> = {
  outward: { returnTypes: RETURN_TYPES, destinations: ["customer", "fabricator", "vendor", "transporter"], defaultReturn: "non_returnable" },
  inward: { returnTypes: ["non_returnable"], destinations: ["fabricator", "customer", "vendor", "office", "transporter"], defaultReturn: "non_returnable" },
  return: { returnTypes: RETURN_TYPES, destinations: ["customer", "fabricator", "vendor", "transporter", "office"], defaultReturn: "non_returnable" },
  job_work: { returnTypes: ["returnable"], destinations: ["fabricator", "vendor"], defaultReturn: "returnable" },
  transfer: { returnTypes: ["non_returnable"], destinations: ["warehouse", "office"], defaultReturn: "non_returnable" },
  sample: { returnTypes: RETURN_TYPES, destinations: ["fabricator", "customer", "vendor", "office", "transporter"], defaultReturn: "returnable" },
};

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

export interface PartyLink {
  id: string;
  party_number: string | null;
  display_name: string | null;
}

export interface BranchLink {
  id: string;
  branch_code: string;
  name: string;
}

export interface ChallanLink {
  id: string;
  challan_number: string;
  status: ChallanStatus;
  path: string;
}

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface TransitionOption {
  action: string;
  to_status: string;
  requires_reason: boolean;
}

/** `{unit: DecimalStr}` in unit order; mixed units are never added together. */
export type QuantityByUnit = Record<string, string>;

export interface ChallanSummaryRow {
  id: string;
  challan_number: string;
  revision_no: number;
  challan_date: string;
  challan_type: ChallanType;
  return_type: ReturnType;
  destination_type: DestinationType;
  destination_party: string;
  party: PartyLink | null;
  reference_no: string | null;
  status: ChallanStatus;
  line_count: number;
  quantity_by_unit: QuantityByUnit;
  outstanding_by_unit: QuantityByUnit;
  expected_return_date: string | null;
  owner: UserRef;
  updated_at: string;
  deleted_at: string | null;
  version: number;
  path: string;
}

export interface ChallanLine {
  id: string;
  line_no: number;
  line_type: LineType;
  product_id: string | null;
  custom_product_id: string | null;
  item_code: string | null;
  item_name: string;
  hsn_sac: string | null;
  quantity: string;
  unit: string;
  remarks: string | null;
  original_line_id: string | null;
  returned_quantity: string;
  outstanding_quantity: string;
}

export interface ReturnLink {
  id: string;
  return_challan: ChallanLink;
  original_challan: ChallanLink;
  return_line_id: string;
  original_line_id: string;
  quantity: string;
  created_at: string;
  reversed_at: string | null;
}

export interface HistoryEntry {
  action: string;
  from_status: string;
  to_status: string;
  actor: UserRef | null;
  reason_code: string | null;
  reason: string | null;
  occurred_at: string;
}

export interface ChallanDetail extends ChallanSummaryRow {
  source_location: string;
  source_branch: BranchLink | null;
  consignee_party: PartyLink | null;
  office_branch: BranchLink | null;
  shipping_name: string | null;
  gstin: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  remarks: string | null;
  direction: "outward" | "inward";
  inventory_effect: "none" | "posting";
  original_challan: ChallanLink | null;
  duplicated_from: ChallanLink | null;
  issued_at: string | null;
  issued_by: UserRef | null;
  closed_at: string | null;
  close_reason: string | null;
  cancelled_at: string | null;
  cancel_reason_code: string | null;
  cancel_reason: string | null;
  created_at: string;
  origin: string;
  lines: ChallanLine[];
  return_links: ReturnLink[];
  history: HistoryEntry[];
  capabilities: Record<string, Capability>;
  allowed_transitions: TransitionOption[];
}

export interface CountBucket {
  key: string;
  label: string;
  count: number;
}

export interface ChallanSummary {
  total: number;
  this_week: number;
  this_month: number;
  pending_returnable: number;
  pending_returnable_quantity: QuantityByUnit;
  issued: number;
  by_type: CountBucket[];
  by_destination: CountBucket[];
  by_status: CountBucket[];
  today: string;
}

export interface PrintLine {
  line_no: number;
  item_code: string | null;
  item_name: string;
  hsn_sac: string | null;
  quantity: string;
  unit: string;
  remarks: string | null;
}

export interface PrintParty {
  title: string;
  lines: string[];
}

export interface ChallanPrint {
  challan_id: string;
  challan_number: string;
  challan_date: string;
  status: ChallanStatus;
  type_label: string;
  return_label: string;
  destination_label: string;
  reference_no: string | null;
  expected_return_date: string | null;
  company_name: string;
  company_lines: string[];
  not_configured: string[];
  from_block: PrintParty;
  to_block: PrintParty;
  lines: PrintLine[];
  total_quantity: QuantityByUnit;
  remarks: string | null;
  terms: string[];
  terms_are_demo: boolean;
  signatures: string[];
  watermark: string | null;
}

export interface InternalNote {
  body: string;
  version: number;
  updated_at: string | null;
  updated_by: UserRef | null;
  canUpdate: boolean;
}

/** Header fields a draft accepts (`ChallanUpdate` minus `expected_version`; dirty fields only). */
export interface ChallanHeaderFields {
  challan_date: string;
  challan_type: ChallanType;
  return_type: ReturnType;
  source_location: string;
  destination_type: DestinationType;
  destination_party: string;
  party_id: string | null;
  shipping_name: string | null;
  gstin: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  reference_no: string | null;
  remarks: string | null;
  expected_return_date: string | null;
  original_challan_id: string | null;
}

export interface ChallanCreateRequest extends Partial<ChallanHeaderFields> {
  lines?: LineCreateRequest[];
}

export interface LineCreateRequest {
  line_type: LineType;
  product_id?: string | null;
  item_code?: string | null;
  item_name?: string | null;
  hsn_sac?: string | null;
  quantity: string;
  unit?: string | null;
  remarks?: string | null;
  original_line_id?: string | null;
}

export interface LineUpdateRequest {
  item_code?: string | null;
  item_name?: string | null;
  hsn_sac?: string | null;
  quantity?: string;
  unit?: string;
  remarks?: string | null;
}
