/**
 * Product form model (UI-45/46/49): every legacy field has an input, grouped as on the detail tabs. Pure functions, so
 * the dirty-field and body rules are unit tested; values stay strings (the server parses lengths, weights, decor).
 */

import type { ProductDetail } from "./types";

export interface FieldDef {
  name: string;
  label: string;
  kind?: "text" | "textarea" | "integer";
  description?: string;
  /** Wider input on desktop. */
  wide?: boolean;
}

export const MASTER_FIELDS: readonly FieldDef[] = [
  { name: "product_name", label: "Product name", wide: true },
  { name: "display_sku", label: "Display SKU", description: "Need not be unique" },
  { name: "brand", label: "Brand" },
  { name: "product_type", label: "Product type" },
  { name: "variant_group", label: "Family (variant group)" },
  { name: "unit_of_sale", label: "Unit of sale", description: "pcs, nos, sheets, kg, set…" },
  { name: "size_mm", label: "Size", description: "e.g. 450 x 300 (mm unless a unit is given)" },
  { name: "finish", label: "Finish" },
  { name: "shape", label: "Shape" },
  { name: "hsn_sac", label: "HSN/SAC", description: "4 to 8 digits" },
  { name: "description", label: "Description", kind: "textarea", wide: true },
  { name: "internal_remarks", label: "Internal remarks", kind: "textarea", wide: true, description: "Never printed" },
];

export const DECOR_FIELDS: readonly FieldDef[] = [
  { name: "decor_no", label: "Decor number", description: "Text: 0120 and 120 are different decors" },
  { name: "decor_name", label: "Decor name" },
  { name: "decor_primary", label: "Primary decor" },
  { name: "decor_options", label: "Decor options", description: "Comma-separated decor numbers" },
  { name: "decor_options_text", label: "Decor options (notes)", kind: "textarea", wide: true },
];

export const PROVENANCE_FIELDS: readonly FieldDef[] = [
  { name: "source_design_no", label: "Source design no." },
  { name: "source_shape_no", label: "Source shape no." },
  { name: "source_sheet", label: "Source sheet" },
  { name: "source_row", label: "Source row" },
  { name: "source_catalog_page", label: "Catalogue page" },
  { name: "source_notes", label: "Source notes", kind: "textarea", wide: true },
];

export const SPEC_FIELDS: readonly FieldDef[] = [
  { name: "length_mm", label: "Length", description: "mm unless stated, e.g. 45 cm" },
  { name: "width_mm", label: "Width" },
  { name: "height_mm", label: "Height" },
  { name: "thickness_mm", label: "Thickness (mm)" },
  { name: "thickness_text", label: "Thickness (text)" },
  { name: "size_mm", label: "Size" },
  { name: "size_label", label: "Size label" },
  { name: "finish", label: "Finish" },
  { name: "material_type", label: "Material" },
  { name: "type", label: "Type" },
  { name: "top_sheet", label: "Top sheet" },
  { name: "groove_count", label: "Grooves", kind: "integer" },
  { name: "bowl_count", label: "Bowls", kind: "integer" },
  { name: "bowl_type", label: "Bowl type" },
  { name: "handle_type", label: "Handle type" },
  { name: "no_of_boards", label: "Boards", kind: "integer" },
  { name: "stand_material", label: "Stand material" },
  { name: "stand_size_mm", label: "Stand size" },
  { name: "board_size_mm", label: "Board size" },
  { name: "working_size_mm", label: "Working size" },
  { name: "plate1_size_mm", label: "Plate 1 size" },
  { name: "plate2_size_mm", label: "Plate 2 size" },
  { name: "plate3_size_mm", label: "Plate 3 size" },
  { name: "special_features", label: "Special features", kind: "textarea", wide: true },
  { name: "care_instructions", label: "Care instructions", kind: "textarea", wide: true },
  { name: "usage_notes", label: "Usage notes", kind: "textarea", wide: true },
];

export const PACKAGING_FIELDS: readonly FieldDef[] = [
  { name: "carton_qty", label: "Carton quantity", kind: "integer" },
  { name: "inner_qty", label: "Inner pack quantity", kind: "integer" },
  { name: "unit_weight_g", label: "Unit weight (g)", description: "Or enter kilograms below; both must agree" },
  { name: "unit_weight_kg", label: "Unit weight (kg)" },
  { name: "packing_type", label: "Packing type" },
  { name: "carton_length_cm", label: "Carton length (cm)" },
  { name: "carton_width_cm", label: "Carton width (cm)" },
  { name: "carton_height_cm", label: "Carton height (cm)" },
  { name: "net_weight_kg", label: "Net weight (kg)" },
  { name: "gross_weight_kg", label: "Gross weight (kg)" },
  { name: "cbm", label: "CBM" },
  { name: "packaging_status", label: "Packaging status" },
  { name: "packaging_notes", label: "Packaging notes", kind: "textarea", wide: true },
  { name: "fragile_notes", label: "Fragile notes", kind: "textarea", wide: true },
  { name: "notes", label: "Notes", kind: "textarea", wide: true },
];

export type FormValues = Record<string, string>;

const text = (value: unknown): string => (value === null || value === undefined ? "" : String(value));

/** Current master values of a product as form strings. */
export function masterValues(product: ProductDetail): FormValues {
  const size = product.dimensions.find((d) => d.kind === "master_size")?.source_text ?? "";
  const provenance = product.provenance as Record<string, unknown>;
  const out: FormValues = {};
  for (const field of MASTER_FIELDS) out[field.name] = text((product as unknown as Record<string, unknown>)[field.name]);
  out.size_mm = size;
  out.hsn_sac = text(product.stock_attributes.hsn_sac);
  out.decor_no = text(product.decor.decor_no);
  out.decor_name = text(product.decor.decor_name);
  out.decor_primary = text(product.decor.decor_primary);
  out.decor_options = product.decor.decor_options.join(", ");
  out.decor_options_text = text(product.decor.decor_options_text);
  for (const field of PROVENANCE_FIELDS) out[field.name] = text(provenance[field.name]);
  return out;
}

const SPEC_SOURCE: Record<string, string> = {
  length_mm: "length_mm_source",
  width_mm: "width_mm_source",
  height_mm: "height_mm_source",
  thickness_mm: "thickness_mm_source",
};
const SPEC_DIMENSION: Record<string, string> = {
  size_mm: "spec_size",
  board_size_mm: "board_size",
  working_size_mm: "working_size",
  stand_size_mm: "stand_size",
  plate1_size_mm: "plate_1_size",
  plate2_size_mm: "plate_2_size",
  plate3_size_mm: "plate_3_size",
};

/** The specification as entered (lengths from their source text, sizes from the dimension rows). */
export function specValues(product: ProductDetail): FormValues {
  const spec = (product.specification ?? {}) as Record<string, unknown>;
  const out: FormValues = {};
  for (const field of SPEC_FIELDS) {
    const source = SPEC_SOURCE[field.name];
    const dimension = SPEC_DIMENSION[field.name];
    if (source) out[field.name] = text(spec[source] ?? spec[field.name]);
    else if (dimension) out[field.name] = text(product.dimensions.find((d) => d.kind === dimension)?.source_text);
    else out[field.name] = text(spec[field.name]);
  }
  return out;
}

export function packagingValues(product: ProductDetail): FormValues {
  const pack = (product.packaging ?? {}) as Record<string, unknown>;
  const out: FormValues = {};
  for (const field of PACKAGING_FIELDS) out[field.name] = text(pack[field.name]);
  return out;
}

/** Field names whose value differs from the initial form (trimmed). */
export function dirtyFields(initial: FormValues, current: FormValues): string[] {
  return Object.keys(current).filter((name) => (current[name] ?? "").trim() !== (initial[name] ?? "").trim());
}

function value(field: FieldDef | undefined, raw: string): unknown {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (field?.kind === "integer" && /^\d+$/.test(trimmed)) return Number.parseInt(trimmed, 10);
  return trimmed;
}

/** PATCH body: only the dirty master fields (blank clears; decor options split on commas). */
export function masterPatch(initial: FormValues, current: FormValues, version: number): Record<string, unknown> {
  const fields = [...MASTER_FIELDS, ...DECOR_FIELDS, ...PROVENANCE_FIELDS];
  const body: Record<string, unknown> = { expected_version: version };
  for (const name of dirtyFields(initial, current)) {
    if (name === "decor_options") {
      const parts = (current[name] ?? "").split(",").map((p) => p.trim()).filter(Boolean);
      body[name] = parts.length ? parts : null;
    } else {
      body[name] = value(fields.find((f) => f.name === name), current[name] ?? "");
    }
  }
  return body;
}

/** A full section (specification or packaging) for PUT: blanks are omitted (cleared). */
export function sectionBody(fields: readonly FieldDef[], current: FormValues): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const field of fields) {
    const v = value(field, current[field.name] ?? "");
    if (v !== null) body[field.name] = v;
  }
  return body;
}

/** Create body: product key, taxonomy, master fields and the non-empty sections. */
export function createBody(values: FormValues): Record<string, unknown> {
  const body: Record<string, unknown> = { product_key: (values.product_key ?? "").trim(), category_id: values.category_id || null };
  if (values.subcategory_id) body.subcategory_id = values.subcategory_id;
  if (values.status) body.status = values.status;
  for (const field of [...MASTER_FIELDS, ...DECOR_FIELDS, ...PROVENANCE_FIELDS]) {
    const raw = values[field.name] ?? "";
    if (!raw.trim()) continue;
    body[field.name] =
      field.name === "decor_options" ? raw.split(",").map((p) => p.trim()).filter(Boolean) : value(field, raw);
  }
  const spec = sectionBody(SPEC_FIELDS, prefixed(values, "spec."));
  const pack = sectionBody(PACKAGING_FIELDS, prefixed(values, "pack."));
  if (Object.keys(spec).length) body.specification = spec;
  if (Object.keys(pack).length) body.packaging = pack;
  return body;
}

export function prefixed(values: FormValues, prefix: string): FormValues {
  const out: FormValues = {};
  for (const [key, v] of Object.entries(values)) if (key.startsWith(prefix)) out[key.slice(prefix.length)] = v;
  return out;
}
