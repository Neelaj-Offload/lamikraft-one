/**
 * The challan header form: state, the choices the movement policy allows, the create body, the dirty-field PATCH
 * and the mapping of 422 field errors. Plain module (no React), unit-tested; the server stays the authority.
 */

import { ProblemError } from "@/lib/api/errors";
import { TYPE_POLICY, type ChallanCreateRequest, type ChallanDetail, type ChallanHeaderFields, type ChallanType, type DestinationType, type ReturnType } from "./types";

export interface PartyChoice {
  id: string;
  party_number: string;
  display_name: string;
}

export interface HeaderForm {
  challan_date: string | null;
  challan_type: ChallanType;
  return_type: ReturnType;
  destination_type: DestinationType;
  party: PartyChoice | null;
  destination_party: string;
  source_location: string;
  shipping_name: string;
  gstin: string;
  phone: string;
  email: string;
  address: string;
  reference_no: string;
  remarks: string;
  expected_return_date: string | null;
}

export const EMPTY_HEADER: HeaderForm = {
  challan_date: null,
  challan_type: "outward",
  return_type: "non_returnable",
  destination_type: "customer",
  party: null,
  destination_party: "",
  source_location: "",
  shipping_name: "",
  gstin: "",
  phone: "",
  email: "",
  address: "",
  reference_no: "",
  remarks: "",
  expected_return_date: null,
};

/** Party roles searched for a destination type (null: the destination has no party, e.g. a warehouse). */
export const PARTY_ROLE_FOR: Record<DestinationType, string | null | "any"> = {
  customer: "customer",
  fabricator: "fabricator",
  vendor: "vendor",
  transporter: "any",
  warehouse: null,
  office: null,
};

/** Changing the type keeps the return type and destination when the policy allows them, otherwise the defaults. */
export function withType(form: HeaderForm, challanType: ChallanType): HeaderForm {
  const rule = TYPE_POLICY[challanType];
  const returnType = rule.returnTypes.includes(form.return_type) ? form.return_type : rule.defaultReturn;
  const destination = rule.destinations.includes(form.destination_type) ? form.destination_type : rule.destinations[0]!;
  const keepParty = destination === form.destination_type;
  return { ...form, challan_type: challanType, return_type: returnType, destination_type: destination, party: keepParty ? form.party : null };
}

export function withDestination(form: HeaderForm, destination: DestinationType): HeaderForm {
  return { ...form, destination_type: destination, party: PARTY_ROLE_FOR[destination] === null ? null : destination === form.destination_type ? form.party : null };
}

const trimmed = (value: string) => value.trim() || null;

/** Client check before sending: only the destination is required (legacy UI-78). */
export function headerProblems(form: HeaderForm): Partial<Record<keyof HeaderForm, "destination_required">> {
  return form.party || form.destination_party.trim() ? {} : { destination_party: "destination_required" };
}

export function createBody(form: HeaderForm): ChallanCreateRequest {
  const body: ChallanCreateRequest = {
    challan_type: form.challan_type,
    return_type: form.return_type,
    destination_type: form.destination_type,
  };
  if (form.challan_date) body.challan_date = form.challan_date;
  if (form.party) body.party_id = form.party.id;
  const text: [keyof ChallanHeaderFields, string][] = [
    ["destination_party", form.destination_party],
    ["source_location", form.source_location],
    ["shipping_name", form.shipping_name],
    ["gstin", form.gstin],
    ["phone", form.phone],
    ["email", form.email],
    ["address", form.address],
    ["reference_no", form.reference_no],
    ["remarks", form.remarks],
  ];
  for (const [field, value] of text) {
    const v = trimmed(value);
    if (v) (body as Record<string, unknown>)[field] = v;
  }
  if (form.expected_return_date && form.return_type === "returnable") body.expected_return_date = form.expected_return_date;
  return body;
}

export function headerFormOf(c: ChallanDetail): HeaderForm {
  return {
    challan_date: c.challan_date,
    challan_type: c.challan_type,
    return_type: c.return_type,
    destination_type: c.destination_type,
    party: c.party ? { id: c.party.id, party_number: c.party.party_number ?? "", display_name: c.party.display_name ?? c.destination_party } : null,
    destination_party: c.destination_party,
    source_location: c.source_location,
    shipping_name: c.shipping_name ?? "",
    gstin: c.gstin ?? "",
    phone: c.phone ?? "",
    email: c.email ?? "",
    address: c.address ?? "",
    reference_no: c.reference_no ?? "",
    remarks: c.remarks ?? "",
    expected_return_date: c.expected_return_date,
  };
}

/** The dirty fields of an edit as a PATCH body (empty text clears optional fields). */
export function headerChanges(base: HeaderForm, form: HeaderForm): Partial<ChallanHeaderFields> {
  const out: Partial<ChallanHeaderFields> = {};
  const put = (field: keyof ChallanHeaderFields, value: unknown) => ((out as Record<string, unknown>)[field] = value);
  if (form.challan_date !== base.challan_date && form.challan_date) put("challan_date", form.challan_date);
  if (form.challan_type !== base.challan_type) put("challan_type", form.challan_type);
  if (form.return_type !== base.return_type) put("return_type", form.return_type);
  if (form.destination_type !== base.destination_type) put("destination_type", form.destination_type);
  if ((form.party?.id ?? null) !== (base.party?.id ?? null)) put("party_id", form.party?.id ?? null);
  for (const field of ["destination_party", "source_location"] as const) {
    if (form[field].trim() !== base[field].trim() && form[field].trim()) put(field, form[field].trim());
  }
  for (const field of ["shipping_name", "gstin", "phone", "email", "address", "reference_no", "remarks"] as const) {
    if (form[field].trim() !== base[field].trim()) put(field, trimmed(form[field]));
  }
  if (form.expected_return_date !== base.expected_return_date) put("expected_return_date", form.expected_return_date);
  return out;
}

/** 422 field errors by field name (`loc: ["body", "gstin"]`; `["body", "lines", 0, "quantity"]` -> `lines.0.quantity`). */
export function fieldErrorsFrom(error: unknown): Record<string, string> {
  if (!(error instanceof ProblemError) || error.status !== 422) return {};
  const out: Record<string, string> = {};
  for (const issue of error.validationIssues) {
    const path = issue.loc.filter((part) => part !== "body" && part !== "query" && part !== "header").join(".");
    if (path && !out[path]) out[path] = issue.msg;
  }
  return out;
}
