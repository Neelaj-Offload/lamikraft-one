"use client";

import { productsAreaNav } from "@/features/products/product-list";
import { PageHeader } from "@/components/ui/page-header";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { ErrorState, PermissionDenied } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { uuidv7 } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { createProduct, fetchCategories, fieldErrors } from "./api";
import { FieldGrid } from "./field-grid";
import { DECOR_FIELDS, MASTER_FIELDS, PACKAGING_FIELDS, PROVENANCE_FIELDS, SPEC_FIELDS, createBody, type FormValues } from "./form-model";
import { PRODUCT_STATUSES, type CategoryRead, type ProductStatus } from "./types";

const STATUS_LABEL: Record<ProductStatus, string> = { active: "Active", inactive: "Inactive", under_development: "Under development" };

/** Active categories and subcategories only (UI-48: taxonomy pickers never offer inactive entries). */
export function taxonomyOptions(categories: readonly CategoryRead[], categoryId: string | null) {
  const active = categories.filter((c) => c.is_active);
  const category = active.find((c) => c.id === categoryId);
  return {
    categories: active.map((c) => ({ id: c.id, label: c.name })),
    subcategories: (category?.subcategories ?? []).filter((s) => s.effective_active).map((s) => ({ id: s.id, label: s.name })),
  };
}

/** New product (LM-16, UI-15/45/49): every section on one page; 422 errors land on their fields. */
export function NewProductForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { permissionKeys } = useSession();
  const [values, setValues] = useState<FormValues>({ status: "active" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [idempotencyKey] = useState(() => uuidv7());
  const categories = useQuery({ queryKey: queryKeys.catalogue.categories(false), queryFn: ({ signal }) => fetchCategories(false, signal) });
  const options = useMemo(() => taxonomyOptions(categories.data ?? [], values.category_id ?? null), [categories.data, values.category_id]);
  const set = (name: string, value: string) => setValues((cur) => ({ ...cur, [name]: value }));
  const create = useMutation({
    mutationFn: () => createProduct(createBody(values), idempotencyKey),
    onSuccess: (result) => {
      for (const key of invalidationMap["catalogue.changed"]) void queryClient.invalidateQueries({ queryKey: key });
      if (result.warnings.length) toast.warning("Created with warnings", { description: result.warnings.slice(0, 3).join("; ") });
      else toast.success("Product created");
      router.push(result.product.path as Parameters<typeof router.push>[0]);
    },
    onError: (error) => setErrors(fieldErrors(error)),
  });

  if (!permissionKeys.has("catalogue.product.create")) return <PermissionDenied area="Add products" />;
  const generalError =
    create.error && !Object.keys(fieldErrors(create.error)).length ? create.error : null;
  const keyTaken = create.error instanceof ProblemError && create.error.code === "product_key_exists";

  return (
    <form
      className="flex flex-col gap-8"
      aria-label="New product"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <PageHeader title="New product" intro="Key and taxonomy first; every other section can be completed later." nav={productsAreaNav()} />
      {generalError && !keyTaken ? <ErrorState error={generalError} what="the product" compact backToToday={false} /> : null}
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-base font-semibold">Identity and taxonomy</legend>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <TextField
            label="Product key"
            description="Permanent; cannot be changed later"
            isRequired
            value={values.product_key ?? ""}
            onChange={(v) => set("product_key", v)}
            isInvalid={Boolean(errors.product_key) || keyTaken}
            errorMessage={keyTaken ? "A product with this key already exists" : errors.product_key}
          />
          <Select
            label="Status"
            options={PRODUCT_STATUSES.map((s) => ({ id: s, label: STATUS_LABEL[s] }))}
            value={values.status ?? "active"}
            onChange={(v) => set("status", v ?? "active")}
          />
          <Select
            label="Category"
            isRequired
            placeholder={categories.isPending ? "Loading…" : "Choose a category"}
            options={options.categories}
            value={values.category_id ?? null}
            onChange={(v) => setValues((cur) => ({ ...cur, category_id: v ?? "", subcategory_id: "" }))}
            isInvalid={Boolean(errors.category_id)}
            errorMessage={errors.category_id}
          />
          <Select
            label="Subcategory"
            placeholder="None"
            options={[{ id: "", label: "None" }, ...options.subcategories]}
            value={values.subcategory_id ?? ""}
            onChange={(v) => set("subcategory_id", v ?? "")}
            isInvalid={Boolean(errors.subcategory_id)}
            errorMessage={errors.subcategory_id}
            isDisabled={!values.category_id}
          />
        </div>
      </fieldset>
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-base font-semibold">Master data</legend>
        <FieldGrid fields={MASTER_FIELDS} values={values} errors={errors} onChange={set} />
      </fieldset>
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-base font-semibold">Decor</legend>
        <FieldGrid fields={DECOR_FIELDS} values={values} errors={errors} onChange={set} />
      </fieldset>
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-base font-semibold">Specifications</legend>
        <FieldGrid fields={SPEC_FIELDS} values={values} errors={errors} valuePrefix="spec." errorPrefix="specification." onChange={set} />
      </fieldset>
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-base font-semibold">Packaging</legend>
        <FieldGrid fields={PACKAGING_FIELDS} values={values} errors={errors} valuePrefix="pack." errorPrefix="packaging." onChange={set} />
      </fieldset>
      <details className="flex flex-col gap-4">
        <summary className="text-base font-semibold">Source and provenance</summary>
        <div className="mt-4">
          <FieldGrid fields={PROVENANCE_FIELDS} values={values} errors={errors} onChange={set} />
        </div>
      </details>
      <div className="flex flex-wrap justify-end gap-2">
        <Button onPress={() => router.push("/products")}>Cancel</Button>
        <Button type="submit" variant="primary" isPending={create.isPending} pendingLabel="Creating…">
          Create product
        </Button>
      </div>
    </form>
  );
}
