"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { fieldErrors, putSection, updateProduct } from "@/features/catalogue/api";
import { masterPatch, sectionBody, type FieldDef, type FormValues } from "@/features/catalogue/form-model";
import { conflictFromError, isNetworkError, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useCatalogueRefresh, type ProductRecord } from "~/data/products";
import { PageSection } from "~/shell/page";
import { Banner, Button, FormActions, FormSection, Textarea, TextField, toast } from "~/ui";

/**
 * Editing one part of a product in place. The read view shows first; "Edit" swaps it for the
 * form. Saving follows the old app exactly: a PATCH of only the changed master fields, or a PUT
 * of the whole specification or packaging section, each carrying the record's version.
 */

export type EditorMode = "master" | "specification" | "packaging";

export interface FieldGroup {
  title: string;
  description?: string;
  fields: readonly FieldDef[];
}

/** New words for the old form model's fields. Anything not listed keeps the model's own label. */
const FIELD_COPY: Record<string, { label?: string; help?: string }> = {
  product_name: { label: "Name" },
  display_sku: { label: "SKU shown to customers", help: "Two products may share one." },
  variant_group: { label: "Family", help: "Groups the sizes and decors of one design." },
  unit_of_sale: { label: "Sold by", help: "For example pcs, set, sheets or kg." },
  size_mm: { label: "Size", help: "For example 450 x 300. Millimetres unless you add a unit." },
  hsn_sac: { label: "HSN or SAC code", help: "Four to eight digits." },
  internal_remarks: { label: "Internal remarks", help: "For the team only. Never printed." },
  decor_no: { label: "Decor number", help: "Kept as text: 0120 and 120 are different decors." },
  decor_primary: { label: "Main decor" },
  decor_options: { label: "Other decors offered", help: "Decor numbers, separated by commas." },
  decor_options_text: { label: "Notes on decor options" },
  source_design_no: { label: "Design number" },
  source_shape_no: { label: "Shape number" },
  source_sheet: { label: "Sheet" },
  source_row: { label: "Row" },
  source_catalog_page: { label: "Catalogue page" },
  source_notes: { label: "Notes on the source" },
  length_mm: { label: "Length", help: "Millimetres unless you add a unit, for example 45 cm." },
  width_mm: { label: "Width" },
  height_mm: { label: "Height" },
  thickness_mm: { label: "Thickness, mm" },
  thickness_text: { label: "Thickness as described" },
  size_label: { label: "Size name", help: "For example Small, Medium, Large or XL." },
  material_type: { label: "Material" },
  groove_count: { label: "Grooves" },
  bowl_count: { label: "Bowls" },
  no_of_boards: { label: "Boards" },
  carton_qty: { label: "Units per carton" },
  inner_qty: { label: "Units per inner pack" },
  unit_weight_g: { label: "Unit weight, g", help: "Or give kilograms beside it. If you give both they must agree." },
  unit_weight_kg: { label: "Unit weight, kg" },
  carton_length_cm: { label: "Carton length, cm" },
  carton_width_cm: { label: "Carton width, cm" },
  carton_height_cm: { label: "Carton height, cm" },
  net_weight_kg: { label: "Net weight, kg" },
  gross_weight_kg: { label: "Gross weight, kg" },
  cbm: { label: "Carton volume, CBM" },
  packaging_notes: { label: "Packing notes" },
  fragile_notes: { label: "Handling notes for fragile goods" },
  notes: { label: "Other notes" },
};

export function fieldLabel(field: FieldDef): string {
  return FIELD_COPY[field.name]?.label ?? field.label;
}

/** The inputs of one group. Every value is text; the server reads lengths, weights and decors. */
export function GroupFields({
  fields,
  values,
  errors,
  onChange,
  valuePrefix = "",
  errorPrefix = "",
}: {
  fields: readonly FieldDef[];
  values: FormValues;
  errors: Record<string, string>;
  onChange: (name: string, value: string) => void;
  valuePrefix?: string;
  errorPrefix?: string;
}) {
  return (
    <>
      {fields.map((field) => {
        const key = `${valuePrefix}${field.name}`;
        const copy = FIELD_COPY[field.name];
        const common = {
          label: copy?.label ?? field.label,
          help: copy?.help,
          value: values[key] ?? "",
          onChange: (value: string) => onChange(key, value),
          error: errors[`${errorPrefix}${field.name}`] || undefined,
          name: key,
          className: field.wide ? "col-span-full" : undefined,
        };
        return field.kind === "textarea" ? (
          <Textarea key={key} {...common} rows={3} />
        ) : (
          <TextField key={key} {...common} inputMode={field.kind === "integer" ? "numeric" : undefined} />
        );
      })}
    </>
  );
}

/** What went wrong with a save, in words: what happened and what to do. */
export function saveProblemText(error: unknown): string {
  if (isNetworkError(error)) return "The connection dropped before the server answered. Check your network, then save again.";
  if (error instanceof ProblemError) return error.detail || error.title || "The server did not accept the change. Check the fields, then save again.";
  return "Something unexpected happened. Save again.";
}

function SectionForm({
  raw,
  mode,
  groups,
  initial,
  saveLabel,
  onClose,
}: {
  raw: ProductRecord;
  mode: EditorMode;
  groups: readonly FieldGroup[];
  initial: FormValues;
  saveLabel: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const refresh = useCatalogueRefresh();
  const [values, setValues] = useState<FormValues>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const prefix = mode === "master" ? "" : `${mode}.`;
  const allFields = groups.flatMap((group) => group.fields);

  const save = useMutation({
    mutationFn: () =>
      mode === "master" ? updateProduct(raw.id, masterPatch(initial, values, raw.version)) : putSection(raw.id, mode, raw.version, sectionBody(allFields, values)),
    onSuccess: (result) => {
      refresh(result.product);
      if (result.warnings.length > 0) {
        toast.warning("Saved, with something to check", { description: result.warnings.slice(0, 3).join(" ") });
      } else {
        toast.success("Changes saved");
      }
      onClose();
    },
    onError: (error) => setErrors(fieldErrors(error)),
  });

  const conflict = save.error ? conflictFromError(save.error) : null;
  const known = new Set(allFields.map((field) => `${prefix}${field.name}`));
  // Messages the server did not pin to one input (two fields that disagree) are shown together at the top.
  const loose = Object.entries(errors).filter(([key]) => !known.has(key));
  const general = save.error && !conflict && Object.keys(errors).length === 0 ? save.error : null;

  return (
    <form
      className="stack"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      {conflict ? (
        <Banner
          tone="amber"
          title="This product changed while you were editing."
          action={
            <Button
              size="sm"
              variant="secondary"
              iconLeft="refresh"
              onPress={() => {
                void queryClient.invalidateQueries({ queryKey: queryKeys.catalogue.product(raw.id) });
                onClose();
              }}
            >
              Reload the product
            </Button>
          }
        >
          Someone else saved first. Reload to see their version, then make your change again.
        </Banner>
      ) : null}
      {general ? (
        <Banner tone="ember" title="Your changes were not saved.">
          {saveProblemText(general)}
        </Banner>
      ) : null}
      {loose.length > 0 ? (
        <Banner tone="ember" title="Some of these values do not agree.">
          {loose.map(([key, message]) => (
            <span key={key} className="block">
              {message}
            </span>
          ))}
        </Banner>
      ) : null}
      {groups.map((group) => (
        <FormSection key={group.title} title={group.title} description={group.description}>
          <GroupFields
            fields={group.fields}
            values={values}
            errors={errors}
            errorPrefix={prefix}
            onChange={(name, value) => {
              setValues((current) => ({ ...current, [name]: value }));
              // An edited field drops its own message. Specification and packaging messages are
              // cross-field, so an edit there clears the section and the server checks again.
              setErrors((current) => (mode === "master" ? Object.fromEntries(Object.entries(current).filter(([key]) => key !== name)) : {}));
            }}
          />
        </FormSection>
      ))}
      <FormActions>
        <Button variant="ghost" onPress={onClose} isDisabled={save.isPending}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending}>
          {saveLabel}
        </Button>
      </FormActions>
    </form>
  );
}

/** Whether the person may edit, from the record's own `capabilities`. */
export function canEditProduct(raw: ProductRecord): boolean {
  return raw.capabilities.update?.allowed === true;
}

/**
 * A titled view of the record that can turn into its own form. `children` is the read view.
 * The Edit button exists only when the server allows the update.
 */
export function EditableView({
  raw,
  mode,
  title,
  description,
  editLabel,
  saveLabel,
  groups,
  initial,
  children,
}: {
  raw: ProductRecord;
  mode: EditorMode;
  title: string;
  description: string;
  editLabel: string;
  saveLabel: string;
  groups: readonly FieldGroup[];
  initial: FormValues;
  children: ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  if (editing) {
    return <SectionForm raw={raw} mode={mode} groups={groups} initial={initial} saveLabel={saveLabel} onClose={() => setEditing(false)} />;
  }
  return (
    <PageSection
      title={title}
      description={description}
      action={
        canEditProduct(raw) ? (
          <Button variant="secondary" iconLeft="edit" onPress={() => setEditing(true)}>
            {editLabel}
          </Button>
        ) : undefined
      }
    >
      {children}
    </PageSection>
  );
}
