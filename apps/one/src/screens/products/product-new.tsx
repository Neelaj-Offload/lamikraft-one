"use client";

import { useMutation } from "@tanstack/react-query";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { createProduct, fieldErrors } from "@/features/catalogue/api";
import {
  createBody,
  DECOR_FIELDS,
  MASTER_FIELDS,
  PACKAGING_FIELDS,
  PROVENANCE_FIELDS,
  SPEC_FIELDS,
  type FieldDef,
  type FormValues,
} from "@/features/catalogue/form-model";
import { PRODUCT_STATUSES } from "@/features/catalogue/types";
import { uuidv7 } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { useSession } from "@/lib/session/context";
import { PRODUCTS_CREATE, useCatalogueRefresh, useCategories } from "~/data/products";
import { Page, PageHeader } from "~/shell/page";
import { NotPermitted } from "~/shell/states";
import { Banner, Button, ButtonLink, FormActions, FormSection, Icon, Select, TextField, toast } from "~/ui";
import { PRODUCT_STATUS_LABEL } from "./format";
import { GroupFields, saveProblemText } from "./product-editor";

/**
 * Add a product in three steps: what it is, what it measures, how it sells. Only the code and the
 * category are needed to create it; the server checks everything else and its messages land on
 * the fields they are about, on whichever step holds them.
 */

const NONE = "none";

const master = (...names: string[]): FieldDef[] => names.map((name) => MASTER_FIELDS.find((field) => field.name === name)).filter((field): field is FieldDef => field !== undefined);

const IDENTITY_FIELDS = master("product_name", "display_sku", "brand", "product_type", "variant_group", "description");
const SIZE_FIELDS = master("size_mm", "finish", "shape");
const SELLING_FIELDS = master("unit_of_sale", "hsn_sac", "internal_remarks");

const STEPS = [
  { id: "identity", title: "Identity", lead: "What it is and where it sits in the catalogue." },
  { id: "specification", title: "Specification", lead: "Its decor, its size and how it is built." },
  { id: "selling", title: "Selling", lead: "How it is sold, packed and traced back." },
] as const;

/** The step that holds the input a server message is about. */
function stepOfError(key: string): number {
  if (key === "specification" || key.startsWith("specification.")) return 1;
  if (key === "packaging" || key.startsWith("packaging.")) return 2;
  if (["product_key", "category_id", "subcategory_id", "status"].includes(key) || IDENTITY_FIELDS.some((field) => field.name === key)) return 0;
  if (SIZE_FIELDS.some((field) => field.name === key) || DECOR_FIELDS.some((field) => field.name === key)) return 1;
  return 2;
}

function StepIndicator({ step, errorSteps, onStep }: { step: number; errorSteps: ReadonlySet<number>; onStep: (index: number) => void }) {
  return (
    <ol className="m-0 grid list-none grid-cols-3 gap-2 p-0 sm:gap-3" aria-label="Steps">
      {STEPS.map((entry, index) => {
        const current = index === step;
        const done = index < step;
        const hasError = errorSteps.has(index);
        return (
          <li key={entry.id} className="min-w-0">
            <button
              type="button"
              onClick={() => onStep(index)}
              aria-current={current ? "step" : undefined}
              className={`press flex w-full min-w-0 cursor-pointer items-center gap-3 rounded-lg border px-3 py-3 text-start sm:px-4 ${
                current ? "border-line-strong bg-surface shadow-panel" : "border-line bg-transparent"
              }`}
            >
              <span
                className={`t-label lk-tnum flex size-8 flex-none items-center justify-center rounded-pill ${
                  hasError ? "bg-ember-soft text-ember-text" : current ? "bg-inverse text-on-inverse" : done ? "bg-leaf-soft text-leaf-text" : "bg-sand-soft text-ink-2"
                }`}
                aria-hidden="true"
              >
                {hasError ? <Icon name="alert" size={16} /> : done ? <Icon name="check" size={16} /> : index + 1}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="t-caption text-ink-3">
                  Step {index + 1}
                  {hasError ? ", needs a correction" : done ? ", done" : ""}
                </span>
                <span className={`t-label truncate ${current ? "text-ink" : "text-ink-2"}`}>{entry.title}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function ProductNew() {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_CREATE);
  const refresh = useCatalogueRefresh();
  const [step, setStep] = useState(0);
  const [values, setValues] = useState<FormValues>({ status: "active" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [idempotencyKey] = useState(() => uuidv7());
  const categories = useCategories(false, allowed);

  const options = useMemo(() => {
    const active = (categories.data ?? []).filter((category) => category.is_active);
    const category = active.find((entry) => entry.id === values.category_id);
    return {
      categories: active.map((entry) => ({ value: entry.id, label: entry.name })),
      subcategories: (category?.subcategories ?? []).filter((entry) => entry.effective_active).map((entry) => ({ value: entry.id, label: entry.name })),
    };
  }, [categories.data, values.category_id]);

  const create = useMutation({
    mutationFn: () => createProduct(createBody(values), idempotencyKey),
    onSuccess: (result) => {
      refresh();
      if (result.warnings.length > 0) toast.warning("Product added, with something to check", { description: result.warnings.slice(0, 3).join(" ") });
      else toast.success("Product added", { description: `${result.product.product_key} is in the catalogue.` });
      router.push(result.product.path as Route);
    },
    onError: (error) => {
      const fields = fieldErrors(error);
      if (error instanceof ProblemError && error.code === "product_key_exists") fields.product_key = "A product with this code already exists. Choose a different code.";
      setErrors(fields);
      const first = Object.keys(fields)[0];
      if (first) setStep(stepOfError(first));
    },
  });

  if (!allowed) {
    return (
      <Page width="reading">
        <PageHeader breadcrumb={[{ label: "Catalogue", href: "/products" }]} title="Add a product" />
        <NotPermitted what="Adding products" icon="box" />
      </Page>
    );
  }

  const set = (name: string, value: string) => {
    setValues((current) => ({ ...current, [name]: value }));
    // An edited field drops the server's message for it. Specification and packaging messages are
    // cross-field, so an edit in either section clears that section and the server checks again.
    const section = name.startsWith("pack.") ? "packaging" : name.startsWith("spec.") ? "specification" : null;
    setErrors((current) =>
      Object.fromEntries(Object.entries(current).filter(([key]) => (section ? key !== section && !key.startsWith(`${section}.`) : key !== name))),
    );
  };

  /** The two things the server cannot do without. Checked before leaving step one and before creating. */
  const requiredProblems = (): Record<string, string> => {
    const problems: Record<string, string> = {};
    if (!(values.product_key ?? "").trim()) problems.product_key = "Give the product a code. It is how everyone will find it.";
    if (!values.category_id) problems.category_id = "Choose the category this product belongs to.";
    return problems;
  };

  const goTo = (index: number) => {
    if (index > 0) {
      const problems = requiredProblems();
      if (Object.keys(problems).length > 0) {
        setErrors((current) => ({ ...current, ...problems }));
        setStep(0);
        return;
      }
    }
    setStep(index);
    window.scrollTo({ top: 0 });
  };

  const submit = () => {
    const problems = requiredProblems();
    if (Object.keys(problems).length > 0) {
      setErrors((current) => ({ ...current, ...problems }));
      setStep(0);
      return;
    }
    create.mutate();
  };

  const errorSteps = new Set(Object.keys(errors).map(stepOfError));
  const known = new Set<string>([
    "product_key",
    "category_id",
    "subcategory_id",
    "status",
    ...[...MASTER_FIELDS, ...DECOR_FIELDS, ...PROVENANCE_FIELDS].map((field) => field.name),
    ...SPEC_FIELDS.map((field) => `specification.${field.name}`),
    ...PACKAGING_FIELDS.map((field) => `packaging.${field.name}`),
  ]);
  const loose = Object.entries(errors).filter(([key]) => !known.has(key));
  const general = create.error && Object.keys(errors).length === 0 ? create.error : null;
  const last = step === STEPS.length - 1;

  return (
    <Page width="reading">
      <PageHeader
        breadcrumb={[{ label: "Catalogue", href: "/products" }]}
        title="Add a product"
        lead="One design in one decor and one size. Start with its code and category; everything else can be filled in now or later."
      />
      <StepIndicator step={step} errorSteps={errorSteps} onStep={goTo} />

      <form
        className="stack"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (last) submit();
          else goTo(step + 1);
        }}
      >
        {general ? (
          <Banner tone="ember" title="The product was not added.">
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

        {step === 0 ? (
          <>
            <FormSection title="Code and category" description="The code is permanent. Choose it the way the team already says it, for example CB01-892-M.">
              <TextField
                label="Product code"
                isRequired
                autoFocus
                value={values.product_key ?? ""}
                onChange={(value) => set("product_key", value)}
                onBlur={() => {
                  if (!(values.product_key ?? "").trim()) setErrors((current) => ({ ...current, product_key: "Give the product a code. It is how everyone will find it." }));
                }}
                help="It cannot be changed after the product is created."
                error={errors.product_key || undefined}
              />
              <Select
                label="Status"
                options={PRODUCT_STATUSES.map((status) => ({ value: status, label: PRODUCT_STATUS_LABEL[status] ?? status }))}
                value={values.status ?? "active"}
                onChange={(value) => set("status", value)}
                help="Active products can be quoted straight away."
                error={errors.status || undefined}
              />
              <Select
                label="Category"
                isRequired
                placeholder={categories.isPending ? "Loading categories" : "Choose a category"}
                options={options.categories}
                value={values.category_id || null}
                onChange={(value) => {
                  setValues((current) => ({ ...current, category_id: value, subcategory_id: "" }));
                  setErrors((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== "category_id" && key !== "subcategory_id")));
                }}
                isDisabled={categories.isPending}
                error={errors.category_id || (categories.isError ? "Categories could not load. Reload the page to try again." : undefined)}
              />
              <Select
                label="Subcategory"
                optional
                placeholder={values.category_id ? "No subcategory" : "Choose a category first"}
                options={[{ value: NONE, label: "No subcategory" }, ...options.subcategories]}
                value={values.subcategory_id || (values.category_id ? NONE : null)}
                onChange={(value) => set("subcategory_id", value === NONE ? "" : value)}
                isDisabled={!values.category_id}
                error={errors.subcategory_id || undefined}
              />
            </FormSection>
            <FormSection title="Name and family" description="What people read in lists, quotations and search.">
              <GroupFields fields={IDENTITY_FIELDS} values={values} errors={errors} onChange={set} />
            </FormSection>
          </>
        ) : null}

        {step === 1 ? (
          <>
            <FormSection title="Decor" description="A different decor is a different product. Options are the other decors this design is offered in.">
              <GroupFields fields={DECOR_FIELDS} values={values} errors={errors} onChange={set} />
            </FormSection>
            <FormSection title="Size and finish" description="The size people search and quote by.">
              <GroupFields fields={SIZE_FIELDS} values={values} errors={errors} onChange={set} />
            </FormSection>
            <FormSection title="Full specification" description="Measured detail for cutting and packing. Fill in what you know; the rest can wait.">
              <GroupFields fields={SPEC_FIELDS} values={values} errors={errors} valuePrefix="spec." errorPrefix="specification." onChange={set} />
            </FormSection>
          </>
        ) : null}

        {step === 2 ? (
          <>
            <FormSection title="Selling" description="How it is counted on a quotation and taxed on an invoice.">
              <GroupFields fields={SELLING_FIELDS} values={values} errors={errors} onChange={set} />
            </FormSection>
            <FormSection title="Packaging" description="What goes in a carton and what the carton weighs. Dispatch and freight are worked out from these.">
              <GroupFields fields={PACKAGING_FIELDS} values={values} errors={errors} valuePrefix="pack." errorPrefix="packaging." onChange={set} />
            </FormSection>
            <FormSection title="Source" description="Optional. Where this product came from in the old catalogue, so it can be traced back.">
              <GroupFields fields={PROVENANCE_FIELDS} values={values} errors={errors} onChange={set} />
            </FormSection>
          </>
        ) : null}

        <FormActions note={`Step ${step + 1} of ${STEPS.length}: ${STEPS[step]?.lead ?? ""}`}>
          {step === 0 ? (
            <ButtonLink href="/products" variant="ghost">
              Cancel
            </ButtonLink>
          ) : (
            <Button variant="ghost" iconLeft="arrowLeft" onPress={() => goTo(step - 1)} isDisabled={create.isPending}>
              Back
            </Button>
          )}
          {last ? (
            <Button type="submit" loading={create.isPending}>
              Create product
            </Button>
          ) : (
            <Button type="submit" variant="inverse" iconRight="arrowRight">
              Continue
            </Button>
          )}
        </FormActions>
      </form>
    </Page>
  );
}
