"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { fetchWarehouses } from "@/features/inventory/api";
import { createWorkOrder, fetchBoms } from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute, useProductionCommand } from "~/data/production";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Banner, Button, ButtonLink, DatePicker, DecimalField, EmptyState, FormActions, FormSection, GlassPanel, Select, Textarea } from "~/ui";
import { OPERATIONS_CRUMB, PATHS, useCanOpen } from "./parts";

const NO_WAREHOUSE = "default";

/**
 * Plan a work order: the product and how many, then where and when. Only products with an
 * approved bill of materials are offered; the approved versions are pinned to the work order.
 */
export function WorkOrderNew() {
  const router = useRouter();
  const canOpen = useCanOpen();
  const boms = useQuery({ queryKey: queryKeys.production.boms({ status: "approved" }), queryFn: ({ signal }) => fetchBoms({}, signal) });
  const warehouses = useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal) });
  const listKey = useMemo(() => queryKeys.production.workOrders({}), []);
  const { run, pending, offline } = useProductionCommand<null>(listKey);

  const products = useMemo(() => {
    const seen = new Map<string, { id: string; key: string; name: string; uom: string | null }>();
    for (const bom of boms.data?.items ?? []) {
      if (bom.status === "approved") seen.set(bom.product.id, { id: bom.product.id, key: bom.product.product_key, name: bom.product.name, uom: bom.product.stock_uom_code });
    }
    return [...seen.values()];
  }, [boms.data]);

  const [product, setProduct] = useState<string | null>(null);
  const [quantity, setQuantity] = useState("");
  const [warehouse, setWarehouse] = useState<string | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const [due, setDue] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<{ product?: string; quantity?: string }>({});
  const chosen = products.find((candidate) => candidate.id === product) ?? null;

  const validate = () => {
    const found: typeof errors = {};
    if (!product) found.product = "Choose the product to make.";
    if (!quantity) found.quantity = "Say how many to make.";
    else if (!isPositiveDecimalStr(quantity)) found.quantity = "Enter a quantity above zero.";
    setErrors(found);
    return Object.keys(found).length === 0;
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!validate() || !product) return;
    void run("create", (key) => createWorkOrder({ product_id: product, quantity, warehouse_id: warehouse, planned_start_date: start, due_date: due, notes: notes.trim() || null }, key), {
      done: "Work order planned",
      failed: "The work order was not planned",
    }).then((created) => {
      if (created) router.push(asRoute(`${PATHS.workOrders}/${created.id}`));
    });
  };

  return (
    <Page width="narrow">
      <PageHeader
        breadcrumb={[OPERATIONS_CRUMB, { label: "Work orders", href: PATHS.workOrders }, { label: "New" }]}
        title="Plan a work order"
        lead="Say what to make and how many. The approved bill of materials and routing are pinned to it, so later changes to them leave this order alone."
      />

      {boms.isPending ? (
        <LoadingBlock lines={5} label="Loading the products that can be made" />
      ) : boms.isError ? (
        <ErrorBlock error={boms.error} what="The products that can be made" onRetry={() => void boms.refetch()} />
      ) : products.length === 0 ? (
        <GlassPanel padding="lg" className="rise">
          <EmptyState
            icon="layers"
            title="Nothing can be planned yet"
            text="A product needs an approved bill of materials and an approved routing before the floor can make it."
            actions={
              canOpen(PATHS.boms) ? (
                <ButtonLink href={PATHS.boms} variant="secondary" iconRight="arrowRight">
                  See bills of materials
                </ButtonLink>
              ) : undefined
            }
          />
        </GlassPanel>
      ) : (
        <form onSubmit={onSubmit} className="stack" noValidate>
          {offline ? (
            <Banner tone="amber" title="You are offline.">
              The work order can be planned once the connection is back.
            </Banner>
          ) : null}
          <FormSection title="What to make" description="Only products with an approved bill of materials are listed.">
            <Select
              label="Product"
              placeholder="Choose a product"
              options={products.map((candidate) => ({ value: candidate.id, label: candidate.name, description: candidate.key }))}
              value={product}
              onChange={(value) => {
                setProduct(value);
                setErrors((current) => ({ ...current, product: undefined }));
              }}
              isRequired
              error={errors.product}
            />
            <DecimalField
              label="Quantity to make"
              value={quantity}
              onChange={(value) => {
                setQuantity(value);
                setErrors((current) => ({ ...current, quantity: undefined }));
              }}
              maxFractionDigits={6}
              suffix={chosen?.uom ?? undefined}
              isRequired
              error={errors.quantity}
            />
          </FormSection>

          <FormSection title="Where and when" description="All optional. Materials are reserved in this warehouse when the order is released.">
            <Select
              className="col-span-full"
              label="Warehouse"
              optional
              options={[
                { value: NO_WAREHOUSE, label: "Default warehouse" },
                ...(warehouses.data ?? []).map((candidate) => ({ value: candidate.id, label: candidate.name, description: candidate.code })),
              ]}
              value={warehouse ?? NO_WAREHOUSE}
              onChange={(value) => setWarehouse(value === NO_WAREHOUSE ? null : value)}
              help={warehouses.isError ? "The warehouses could not load. The default warehouse will be used." : "Left on default, the workspace's own default warehouse is used."}
            />
            <DatePicker label="Planned start" optional value={start} onChange={setStart} />
            <DatePicker label="Due date" optional value={due} onChange={setDue} />
            <Textarea className="col-span-full" label="Notes" optional rows={3} value={notes} onChange={setNotes} placeholder="Anything the floor should know" />
          </FormSection>

          <FormActions note="Planning reserves nothing. Materials are reserved when you release the order.">
            <ButtonLink href={PATHS.workOrders} variant="ghost">
              Cancel
            </ButtonLink>
            <Button type="submit" loading={pending === "create"} isDisabled={Boolean(offline)}>
              Plan work order
            </Button>
          </FormActions>
        </form>
      )}
    </Page>
  );
}
