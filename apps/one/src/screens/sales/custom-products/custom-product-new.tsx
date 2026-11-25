"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { createCustomProduct } from "@/features/custom-products/api";
import { useResourceCommand } from "@/features/sales/resource-command";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { asRoute, customBody, EMPTY_CUSTOM, type CustomForm } from "~/data/sales-deals";
import { Page, PageHeader } from "~/shell/page";
import { NotPermitted } from "~/shell/states";
import { Banner, Button, ButtonLink, FormActions, FormSection, GlassPanel } from "~/ui";
import { Steps, stagger, type StepState } from "../quotations/parts";
import { CommercialFields, FIELD_STEP, IdentityFields, PackagingFields, SpecificationFields, validateCustom } from "./custom-product-fields";

const INVALIDATE = [queryKeys.sales.all()];
type Stage = 0 | 1 | 2;

/** Record a custom product in three steps: what it is, how it is made, how it is packed and priced. */
export function CustomProductNew() {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const commands = useResourceCommand("custom_product:new", INVALIDATE);
  const [stage, setStage] = useState<Stage>(0);
  const [form, setForm] = useState<CustomForm>(EMPTY_CUSTOM);
  const [errors, setErrors] = useState<Record<string, string>>({});

  if (!permissionKeys.has("sales.custom_product.create")) {
    return (
      <Page width="narrow">
        <PageHeader breadcrumb={[{ label: "Sales", href: "/sales" }, { label: "Custom products", href: "/sales/custom-products" }, { label: "New" }]} title="New custom product" />
        <GlassPanel>
          <NotPermitted what="Creating custom products" />
        </GlassPanel>
      </Page>
    );
  }

  const set = <K extends keyof CustomForm>(field: K, value: CustomForm[K]) => {
    setForm((current) => ({ ...current, [field]: value }));
    if (errors[field]) setErrors((current) => ({ ...current, [field]: "" }));
  };
  const stepOf = (found: Record<string, string>): Stage | null => {
    const fields = Object.keys(found).filter((field) => found[field]);
    if (fields.length === 0) return null;
    return Math.min(...fields.map((field) => FIELD_STEP[field] ?? 1)) as Stage;
  };

  const next = () => {
    const found = validateCustom(form);
    if (stage === 0 && found.product_name) {
      setErrors({ product_name: found.product_name });
      return;
    }
    setStage((current) => (current === 0 ? 1 : 2));
  };

  const create = async () => {
    const found = validateCustom(form);
    const at = stepOf(found);
    if (at !== null) {
      setErrors(found);
      setStage(at);
      return;
    }
    const body = customBody(form, null);
    const outcome = await commands.run("create", [JSON.stringify(body)], (key) => createCustomProduct(body, key), { failed: "The custom product was not created" });
    if (outcome.ok) {
      router.push(asRoute(outcome.value.path));
      return;
    }
    setErrors(outcome.fieldErrors);
    const back = stepOf(outcome.fieldErrors);
    if (back !== null) setStage(back);
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (stage < 2) next();
    else void create();
  };
  const stateOf = (index: number): StepState => (index < stage ? "done" : index === stage ? "current" : "todo");
  const group = { form, set, errors };
  const errorCount = Object.values(errors).filter(Boolean).length;

  return (
    <Page width="reading">
      <PageHeader
        breadcrumb={[{ label: "Sales", href: "/sales" }, { label: "Custom products", href: "/sales/custom-products" }, { label: "New" }]}
        title="New custom product"
        lead="Only the name is needed to start. Add what you know now; the rest can follow as the customer decides."
      />

      <GlassPanel padding="md" className="rise" style={stagger(1)}>
        <Steps
          label="Steps to record a custom product"
          steps={[
            { id: "product", label: "The product", hint: stage > 0 && form.product_name ? form.product_name : "Name, kind, customer", state: stateOf(0) },
            { id: "spec", label: "Specification", hint: "Size, decor, finish", state: stateOf(1) },
            { id: "price", label: "Packaging and price", hint: "Cartons, quoted price", state: stateOf(2) },
          ]}
        />
      </GlassPanel>

      {commands.offline ? (
        <Banner tone="amber" title="You are offline.">
          The custom product can be created once the connection is back.
        </Banner>
      ) : null}
      {errorCount > 0 && stage === 2 ? (
        <Banner tone="ember" title={errorCount === 1 ? "One field needs another look." : `${errorCount} fields need another look.`}>
          They are marked below and on the earlier steps.
        </Banner>
      ) : null}

      <form onSubmit={onSubmit} className="stack" noValidate>
        {stage === 0 ? (
          <FormSection title="What is it?" description="A custom product is its own item beside the catalogue: a changed catalogue product, or something entirely new.">
            <IdentityFields {...group} />
          </FormSection>
        ) : null}
        {stage === 1 ? (
          <FormSection title="How is it made?" description="Everything here is optional. Record what the customer has specified so far; a sample round can refine it.">
            <SpecificationFields {...group} />
          </FormSection>
        ) : null}
        {stage === 2 ? (
          <>
            <FormSection title="How is it packed?" description="Used when the product is quoted and, later, shipped.">
              <PackagingFields {...group} />
            </FormSection>
            <FormSection title="What does it cost the customer?" description="The quoted price, if you have one. Costing is recorded separately, by people with cost access.">
              <CommercialFields {...group} />
            </FormSection>
          </>
        ) : null}

        <FormActions note={`Step ${stage + 1} of 3`}>
          {stage === 0 ? (
            <ButtonLink href="/sales/custom-products" variant="ghost">
              Cancel
            </ButtonLink>
          ) : (
            <Button variant="ghost" iconLeft="arrowLeft" onPress={() => setStage((current) => (current === 2 ? 1 : 0))} isDisabled={commands.pending !== null}>
              Back
            </Button>
          )}
          {stage < 2 ? (
            <Button type="submit" variant="inverse" iconRight="arrowRight">
              {stage === 0 ? "Continue to specification" : "Continue to packaging and price"}
            </Button>
          ) : (
            <Button type="submit" loading={commands.pending === "create"} isDisabled={Boolean(commands.offline)}>
              Create custom product
            </Button>
          )}
        </FormActions>
      </form>
    </Page>
  );
}
