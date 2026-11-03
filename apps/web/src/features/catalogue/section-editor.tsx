"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Conflict, ErrorState } from "@/components/ui/states";
import { conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { fieldErrors, putSection, updateProduct } from "./api";
import { FieldGrid } from "./field-grid";
import { masterPatch, sectionBody, type FieldDef, type FormValues } from "./form-model";
import type { ProductDetail } from "./types";

export type SectionMode = "master" | "specification" | "packaging";

/** Why Edit is unavailable, or null when it is allowed. Edit is hidden entirely when it can never be allowed. */
function editState(product: ProductDetail): { show: boolean; reason: string | null } {
  const update = product.capabilities.update;
  if (!update) return { show: false, reason: null };
  if (update.allowed) return { show: true, reason: null };
  if (update.reason_code === "product_archived") return { show: true, reason: "Restore the product to edit it" };
  return { show: false, reason: null };
}

/**
 * One editable product section (catalogue lane, merged into the product record at the Slice-2 merge): the record's
 * read view (`children`) with an Edit button, then the inline form with server field errors (422) and the
 * version-conflict view (409). Saving sends only dirty master fields, or the whole section for
 * specification/packaging (PUT). `product` is the raw server record, so every field the form edits round-trips.
 */
export function SectionEditor({
  product,
  mode,
  groups,
  initial,
  onSaved,
  children,
}: {
  product: ProductDetail;
  mode: SectionMode;
  groups: readonly { title: string; fields: readonly FieldDef[] }[];
  initial: FormValues;
  onSaved: (next: ProductDetail, warnings: string[]) => void;
  children: ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<FormValues>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();
  const edit = editState(product);
  const prefix = mode === "master" ? "" : `${mode}.`;
  const save = useMutation({
    mutationFn: () =>
      mode === "master"
        ? updateProduct(product.id, masterPatch(initial, values, product.version))
        : putSection(product.id, mode, product.version, sectionBody(groups.flatMap((g) => g.fields), values)),
    onSuccess: (result) => {
      setErrors({});
      setEditing(false);
      onSaved(result.product, result.warnings);
    },
    onError: (error) => setErrors(fieldErrors(error)),
  });
  const conflict = save.error ? conflictFromError(save.error) : null;
  const generalError = save.error && !conflict && !Object.keys(fieldErrors(save.error)).length ? save.error : null;
  const sectionTitle = groups[0]?.title ?? "section";

  if (!editing) {
    return (
      <div className="flex flex-col gap-4">
        {edit.show ? (
          <div className="flex justify-end">
            <Button
              onPress={() => {
                setValues(initial);
                setErrors({});
                save.reset();
                setEditing(true);
              }}
              {...unavailableWhen(edit.reason)}
            >
              {`Edit ${sectionTitle.toLowerCase()}`}
            </Button>
          </div>
        ) : null}
        {children}
      </div>
    );
  }
  return (
    <form
      className="flex flex-col gap-6"
      aria-label={`Edit ${sectionTitle}`}
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      {conflict ? (
        <Conflict
          conflict={conflict}
          onReview={() => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.catalogue.product(product.id) });
            setEditing(false);
          }}
        />
      ) : null}
      {generalError ? <ErrorState error={generalError} what="the change" compact backToToday={false} /> : null}
      {groups.map((group) => (
        <fieldset key={group.title} className="flex flex-col gap-3">
          <legend className="mb-2 text-base font-semibold">{group.title}</legend>
          <FieldGrid
            fields={group.fields}
            values={values}
            errors={errors}
            errorPrefix={prefix}
            onChange={(name, v) => {
              setValues((cur) => ({ ...cur, [name]: v }));
              // see NewProductForm: an edit clears its own message, or the section's for specification/packaging
              setErrors((cur) => (mode === "master" ? Object.fromEntries(Object.entries(cur).filter(([key]) => key !== name)) : {}));
            }}
          />
        </fieldset>
      ))}
      <div className="flex flex-wrap justify-end gap-2">
        <Button onPress={() => setEditing(false)}>Cancel</Button>
        <Button type="submit" variant="primary" isPending={save.isPending} pendingLabel="Saving…">
          Save
        </Button>
      </div>
    </form>
  );
}
