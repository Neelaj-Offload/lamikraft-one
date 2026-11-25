"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  archiveCustomProduct,
  decideSpecRevision,
  duplicateCustomProduct,
  executePromotion,
  fetchCosting,
  fetchCustomHistory,
  fetchCustomProduct,
  recordCosting,
  recordSpecRevision,
  requestPromotion,
  transitionCustomProduct,
  updateCustomProduct,
  type CustomProductDetail,
} from "@/features/custom-products/api";
import { useResourceCommand } from "@/features/sales/resource-command";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { asRoute, CUSTOM_TYPE_LABEL, customBody, customFormOf, customProductStatus, humanise, quotationStatus, useCanOpen, type CustomForm } from "~/data/sales-deals";
import { Page, RecordHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Code,
  DateText,
  DecimalField,
  EmptyState,
  FactStrip,
  FormActions,
  FormSection,
  GlassPanel,
  KeyValue,
  Menu,
  Modal,
  Money,
  Select,
  Skeleton,
  SkeletonText,
  Tabs,
  Textarea,
  TextField,
  TextLink,
  Timeline,
  type IconName,
  type MenuItem,
  type TimelineItem,
  type Tone,
} from "~/ui";
import { ReasonModal, stagger, StatusBadge, Steps, type StepItem } from "../quotations/parts";
import { viewHref, type CustomProductView } from "../quotations/views";
import { CommercialFields, IdentityFields, PackagingFields, SpecificationFields, validateCustom } from "./custom-product-fields";

type Commands = ReturnType<typeof useResourceCommand>;

const TRANSITION: Record<string, string> = {
  develop: "Start development",
  sample: "Move to sample stage",
  quote: "Mark as quoted",
  approve: "Approve",
  reject: "Reject",
  park: "Make dormant",
  reopen: "Reopen",
  reactivate: "Reactivate",
};
const TRANSITION_ICON: Record<string, IconName> = { develop: "hammer", sample: "packageOpen", quote: "fileText", approve: "badgeCheck", reject: "xCircle", park: "pause", reopen: "undo", reactivate: "play" };
const DONE: Record<string, string> = {
  develop: "Development started",
  sample: "Moved to the sample stage",
  quote: "Marked as quoted",
  approve: "Custom product approved",
  reject: "Custom product rejected",
  park: "Made dormant",
  reopen: "Reopened",
  reactivate: "Reactivated",
  __archive: "Archived",
  __unarchive: "Restored from the archive",
};
const BACKWARD = new Set(["reject", "park"]);
const CONFLICT = "Someone else changed this custom product. The latest version is shown; check it and try again.";
const SPEC_OUTCOME: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Waiting for feedback", tone: "amber" },
  approved: { label: "Customer approved", tone: "leaf" },
  rejected: { label: "Customer rejected", tone: "ember" },
  superseded: { label: "Superseded", tone: "neutral" },
};
const PROMOTION: Record<string, { label: string; tone: Tone }> = {
  pending_approval: { label: "Waiting for approval", tone: "amber" },
  approved: { label: "Approved", tone: "leaf" },
  executed: { label: "Catalogue product created", tone: "leaf" },
  rejected: { label: "Rejected", tone: "ember" },
  withdrawn: { label: "Withdrawn", tone: "neutral" },
  failed: { label: "Failed", tone: "ember" },
};

/** A custom product: where it stands, its specification, its sample rounds, its costing and its history. */
export function CustomProductRecord({ customProductId, view }: { customProductId: string; view: CustomProductView }) {
  const query = useQuery({ queryKey: queryKeys.sales.customProduct(customProductId), queryFn: ({ signal }) => fetchCustomProduct(customProductId, signal) });
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the custom product">
          <Skeleton width="120px" height={14} />
          <Skeleton width="45%" height={32} />
          <SkeletonText lines={2} />
        </div>
        <LoadingBlock lines={6} label="Loading the custom product" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <ErrorBlock error={query.error} what="This custom product" onRetry={() => void query.refetch()} />
        <div>
          <ButtonLink href="/sales/custom-products" variant="secondary" iconLeft="arrowLeft">
            All custom products
          </ButtonLink>
        </div>
      </Page>
    );
  }
  return <Loaded product={query.data} view={view} />;
}

interface Asking {
  action: string;
  label: string;
  reason: "required" | "optional";
  danger: boolean;
  description: string;
}

function Loaded({ product, view }: { product: CustomProductDetail; view: CustomProductView }) {
  const router = useRouter();
  const keys = useMemo(() => [queryKeys.sales.customProduct(product.id), ["sales", "custom-products"], queryKeys.sales.customProductHistory(product.id)], [product.id]);
  const commands = useResourceCommand(`custom_product:${product.id}`, keys);
  const [asking, setAsking] = useState<Asking | null>(null);
  const [promoting, setPromoting] = useState(false);
  const caps = product.capabilities;
  const can = (name: string) => caps[name]?.allowed === true;
  const offline = Boolean(commands.offline);
  const path = `/sales/custom-products/${product.id}`;
  const canReadCosting = can("read_costing");
  const customer = product.party?.display_name ?? product.legacy_customer_name;

  const perform = async (action: string, label: string, reason: string | null): Promise<boolean> => {
    const options = { done: DONE[action] ?? label, failed: `${label} did not go through`, conflictMessage: CONFLICT };
    const outcome =
      action === "__archive" || action === "__unarchive"
        ? await commands.run(action, [product.version, reason], () => archiveCustomProduct(product, action === "__archive", reason), options)
        : await commands.run(action, [product.version, reason], () => transitionCustomProduct(product, action, reason), options);
    return outcome.ok;
  };
  const start = (action: string, requiresReason: boolean) => {
    const label = TRANSITION[action] ?? humanise(action);
    if (requiresReason || BACKWARD.has(action)) {
      setAsking({
        action,
        label,
        reason: requiresReason ? "required" : "optional",
        danger: action === "reject",
        description: action === "reject" ? "The product will not go ahead. It stays on record and can be reopened." : `${product.custom_code} · ${product.product_name}`,
      });
    } else void perform(action, label, null);
  };
  const duplicate = async () => {
    const outcome = await commands.run("duplicate", [product.version], (key) => duplicateCustomProduct(product.id, key), { failed: "The custom product was not duplicated" });
    if (outcome.ok) router.push(asRoute(outcome.value.path));
  };

  const forward = product.allowed_transitions.find((t) => !BACKWARD.has(t.action)) ?? null;
  const promoteLeads = can("promote");
  const rest = product.allowed_transitions.filter((t) => t !== forward || promoteLeads);
  const menu: MenuItem[] = rest
    .filter((t) => !BACKWARD.has(t.action))
    .map((t) => ({ id: t.action, label: TRANSITION[t.action] ?? humanise(t.action), icon: TRANSITION_ICON[t.action], isDisabled: offline, onAction: () => start(t.action, t.requires_reason) }));
  if (can("duplicate")) menu.push({ id: "duplicate", label: "Duplicate", icon: "copy", description: "A new custom product with the same specification", isDisabled: offline, onAction: () => void duplicate() });
  if (product.archived_at && caps.archive?.reason_code === "custom_product_archived") {
    menu.push({ id: "unarchive", label: "Restore from archive", icon: "undo", isDisabled: offline, onAction: () => void perform("__unarchive", "Restored from the archive", null) });
  }
  const backward = rest.filter((t) => BACKWARD.has(t.action));
  if (backward.length > 0 || can("archive")) {
    if (menu.length > 0) menu.push({ id: "sep", separator: true });
    for (const t of backward) {
      menu.push({ id: t.action, label: TRANSITION[t.action] ?? humanise(t.action), icon: TRANSITION_ICON[t.action], tone: t.action === "reject" ? "danger" : undefined, isDisabled: offline, onAction: () => start(t.action, t.requires_reason) });
    }
    if (can("archive")) {
      menu.push({
        id: "archive",
        label: "Archive",
        icon: "archive",
        tone: "danger",
        isDisabled: offline,
        onAction: () => setAsking({ action: "__archive", label: "Archive", reason: "optional", danger: true, description: "An archived custom product is read-only until it is restored." }),
      });
    }
  }

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Sales", href: "/sales" }, { label: "Custom products", href: "/sales/custom-products" }, { label: product.custom_code }]}
        code={product.custom_code}
        title={product.product_name}
        status={
          <>
            <StatusBadge look={customProductStatus(product.status)} />
            {product.archived_at ? (
              <Badge tone="neutral" icon="archive">
                Archived
              </Badge>
            ) : null}
            {product.customer_specific_flag ? <Badge outline>Only for this customer</Badge> : null}
          </>
        }
        lead={[CUSTOM_TYPE_LABEL[product.custom_type] ?? humanise(product.custom_type), product.dimensions_text, product.decor_no ? `decor ${product.decor_no}` : null, product.finish].filter(Boolean).join(" · ")}
        facts={
          <FactStrip
            items={[
              { label: "Quoted price", icon: "banknote", value: product.quoted_price ? <Money value={product.quoted_price} className="t-stat-sm" /> : null },
              {
                label: "Customer",
                icon: "building",
                value: product.party ? <TextLink href={asRoute(`/sales/parties/${product.party.id}`)}>{product.party.display_name}</TextLink> : customer,
              },
              { label: "Based on", icon: "box", value: product.base_product_key ? <Code>{product.base_product_key}</Code> : null },
              { label: "Owner", icon: "user", value: product.owner.display_name },
            ]}
          />
        }
        actions={
          <>
            {promoteLeads ? (
              <Button iconLeft="star" isDisabled={offline} onPress={() => setPromoting(true)}>
                Request promotion
              </Button>
            ) : forward ? (
              <Button iconLeft={TRANSITION_ICON[forward.action]} loading={commands.pending === forward.action} isDisabled={offline} onPress={() => start(forward.action, forward.requires_reason)}>
                {TRANSITION[forward.action] ?? humanise(forward.action)}
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More custom product actions"
                items={menu}
                placement="bottom end"
                trigger={
                  <Button variant="secondary" iconRight="chevronDown">
                    More
                  </Button>
                }
              />
            ) : null}
          </>
        }
      >
        <Tabs
          label="Views of this custom product"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "specification", label: "Specification", href: asRoute(viewHref(path, "specification")) },
            { id: "samples", label: "Samples and revisions", count: product.spec_revisions.length || undefined, href: asRoute(viewHref(path, "samples")) },
            ...(canReadCosting || view === "costing" ? [{ id: "costing", label: "Costing", href: asRoute(viewHref(path, "costing")) }] : []),
            { id: "activity", label: "Activity", href: asRoute(viewHref(path, "activity")) },
          ]}
        />
      </RecordHeader>

      {commands.offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this custom product. Changes can be saved once the connection is back.
        </Banner>
      ) : null}
      {product.archived_at ? (
        <Banner tone="neutral" icon="archive" title="Archived.">
          This custom product is read-only. Restore it from the archive to work on it again.
        </Banner>
      ) : null}

      {view === "overview" ? <Overview product={product} commands={commands} onPromote={() => setPromoting(true)} /> : null}
      {view === "specification" ? <SpecificationView product={product} commands={commands} /> : null}
      {view === "samples" ? <SamplesView product={product} commands={commands} /> : null}
      {view === "costing" ? canReadCosting ? <CostingView product={product} /> : <GlassPanel><NotPermitted what="Costing" /></GlassPanel> : null}
      {view === "activity" ? <ActivityView product={product} /> : null}

      <ReasonModal
        isOpen={asking !== null}
        onOpenChange={(open) => (open ? undefined : setAsking(null))}
        title={asking ? `${asking.label}: ${product.custom_code}` : ""}
        description={asking?.description}
        confirmLabel={asking?.label ?? ""}
        tone={asking?.danger ? "danger" : "default"}
        reason={asking?.reason ?? "optional"}
        reasonHelp="Kept in the custom product's history."
        onConfirm={async (reason) => {
          if (asking && (await perform(asking.action, asking.label, reason))) setAsking(null);
        }}
      />
      <PromotionDialog product={product} commands={commands} isOpen={promoting} onOpenChange={setPromoting} />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview

const STAGES = ["inquiry", "under_development", "sample_stage", "quoted", "approved", "converted_to_standard"] as const;
const STAGE_LABEL: Record<string, string> = { inquiry: "Enquiry", under_development: "Development", sample_stage: "Samples", quoted: "Quoted", approved: "Approved", converted_to_standard: "Catalogue" };

function stagesOf(product: CustomProductDetail): StepItem[] | null {
  const at = STAGES.findIndex((stage) => stage === product.status);
  if (at === -1) return null;
  const finished = product.status === "converted_to_standard";
  return STAGES.map((stage, index) => ({ id: stage, label: STAGE_LABEL[stage] ?? stage, state: finished || index < at ? "done" : index === at ? "current" : "todo" }));
}

function standingOf(product: CustomProductDetail): { headline: ReactNode; body: string } {
  const pending = product.spec_revisions.filter((rev) => rev.outcome === "pending").length;
  switch (product.status) {
    case "inquiry":
      return { headline: <>An enquiry, not yet in <em>development</em></>, body: "Record what the customer asked for under Specification. Start development when the team takes it on." };
    case "under_development":
      return { headline: <>In <em>development</em></>, body: "Refine the specification as it firms up. When a sample is ready to go out, move it to the sample stage." };
    case "sample_stage":
      return {
        headline: pending > 0 ? <>Waiting for the customer&apos;s <em>feedback</em></> : <>At the <em>sample</em> stage</>,
        body: pending > 0 ? "A specification revision is out with the customer. Record their answer under Samples and revisions." : "Record each specification you send with its sample, then the customer's answer.",
      };
    case "quoted":
      return { headline: <>Quoted. Waiting for a <em>decision</em></>, body: "The quotations that carry it are listed here. Approve it once the customer accepts the product." };
    case "approved":
      return {
        headline: <>Approved. Ready for the <em>catalogue</em></>,
        body: product.capabilities.promote?.allowed
          ? "Request promotion to make it a catalogue product. A catalogue approver decides."
          : "Promotion to the catalogue needs an approved specification revision as well.",
      };
    case "converted_to_standard":
      return { headline: <>Now a <em>catalogue</em> product</>, body: "The custom record is kept as history. New quotations use the catalogue product." };
    case "rejected":
      return { headline: "Rejected", body: product.status_reason ?? "It will not go ahead. Reopen it if the customer comes back." };
    case "dormant":
      return {
        headline: "Dormant",
        body: product.status_reason ?? `Set aside${product.dormant_from_status ? ` from ${customProductStatus(product.dormant_from_status).label.toLowerCase()}` : ""}. Reactivate it to carry on.`,
      };
    default:
      return { headline: customProductStatus(product.status).label, body: product.status_reason ?? "" };
  }
}

function Overview({ product, commands, onPromote }: { product: CustomProductDetail; commands: Commands; onPromote: () => void }) {
  const canOpen = useCanOpen();
  const standing = standingOf(product);
  const stages = stagesOf(product);
  const promote = product.capabilities.promote;
  const canExecute = product.capabilities.execute_promotion?.allowed === true;
  const showPromotion = product.promotions.length > 0 || promote?.allowed === true || product.status === "approved";
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            {stages ? <Steps label="Progress of this custom product" steps={stages} /> : null}
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
              {product.status_reason && product.status !== "rejected" && product.status !== "dormant" ? <p className="t-body-sm text-ink-3">Note on the status: {product.status_reason}</p> : null}
            </div>
            {product.promoted_product_id && canOpen(`/products/${product.promoted_product_id}`) ? (
              <div>
                <ButtonLink href={asRoute(`/products/${product.promoted_product_id}`)} variant="inverse" iconRight="arrowRight">
                  Open the catalogue product
                </ButtonLink>
              </div>
            ) : null}
          </GlassPanel>

          <GlassPanel padding="lg" className="rise" title="Quotations that carry it" titleAs="h2" style={stagger(1)}>
            {product.quotes.length === 0 ? (
              <EmptyState compact icon="fileText" title="Not on a quotation yet" text="Add it as a line from any draft quotation: Lines, Add line, Custom product." />
            ) : (
              <ul className="flex flex-col">
                {product.quotes.map((quote) => (
                  <li key={`${quote.quote_id}-${quote.line_no}`} className="hairline-top flex flex-wrap items-center justify-between gap-3 py-3 first:border-t-0 first:pt-0 last:pb-0">
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <TextLink href={asRoute(`/sales/quotes/${quote.quote_id}?view=lines`)} className="t-label">
                        <Code>{quote.quote_number}</Code>
                      </TextLink>
                      <span className="t-caption text-ink-3">Line {quote.line_no}</span>
                    </span>
                    <StatusBadge look={quotationStatus(quote.status)} size="sm" />
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>

          {showPromotion ? (
            <GlassPanel
              padding="lg"
              className="rise"
              title="Promotion to the catalogue"
              titleAs="h2"
              style={stagger(2)}
              action={
                promote?.allowed ? (
                  <Button variant="secondary" size="sm" iconLeft="star" onPress={onPromote} isDisabled={Boolean(commands.offline)}>
                    Request promotion
                  </Button>
                ) : undefined
              }
            >
              {product.promotions.length === 0 ? (
                <p className="t-body-sm text-ink-3">
                  {promote?.allowed
                    ? "Nothing requested yet. A promotion creates a catalogue product with its own key, once a catalogue approver agrees."
                    : "Promotion needs an approved product with an approved specification revision."}
                </p>
              ) : (
                <ul className="flex flex-col">
                  {product.promotions.map((promo) => {
                    const look = PROMOTION[promo.status] ?? { label: humanise(promo.status), tone: "neutral" as Tone };
                    return (
                      <li key={promo.id} className="hairline-top flex flex-wrap items-center justify-between gap-3 py-3 first:border-t-0 first:pt-0 last:pb-0">
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="t-label text-ink">
                            As <Code>{String(promo.payload.product_key ?? "")}</Code>
                          </span>
                          <span className="t-caption text-ink-3">
                            Requested <DateText value={promo.created_at} style="dayTime" />
                            {promo.requested_by?.display_name ? ` by ${promo.requested_by.display_name}` : ""}
                            {promo.failure_reason ? ` · ${promo.failure_reason}` : ""}
                            {promo.decision_reason ? ` · ${promo.decision_reason}` : ""}
                          </span>
                        </span>
                        <span className="flex flex-wrap items-center gap-2">
                          <Badge tone={look.tone} dot>
                            {look.label}
                          </Badge>
                          {promo.status === "failed" && canExecute ? (
                            <Button
                              size="sm"
                              variant="secondary"
                              loading={commands.pending === "execute"}
                              onPress={() => void commands.run("execute", [promo.id], () => executePromotion(product.id, promo.id), { done: "Catalogue product created", failed: "The catalogue product was not created" })}
                            >
                              Create the catalogue product
                            </Button>
                          ) : null}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </GlassPanel>
          ) : null}
        </>
      }
      aside={
        <GlassPanel padding="md" className="rise" title="At a glance" titleAs="h2" style={stagger(1)}>
          <KeyValue
            rows
            items={[
              { label: "Kind", value: CUSTOM_TYPE_LABEL[product.custom_type] ?? humanise(product.custom_type) },
              { label: "Category", value: [product.category_name, product.subcategory_name].filter(Boolean).join(" / ") },
              { label: "Enquiry reference", value: product.inquiry_reference },
              { label: "Sold by", value: product.unit_code },
              { label: "Sample rounds", value: String(product.spec_revisions.length) },
              { label: "Created by", value: product.created_by?.display_name },
              { label: "Updated", value: <DateText value={product.updated_at} style="relative" /> },
            ]}
          />
        </GlassPanel>
      }
    />
  );
}

function PromotionDialog({ product, commands, isOpen, onOpenChange }: { product: CustomProductDetail; commands: Commands; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const [productKey, setProductKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    const key = productKey.trim();
    if (!key) {
      setError("Enter the key the catalogue product will carry.");
      return;
    }
    const outcome = await commands.run("promote", [product.version, key], () => requestPromotion(product.id, { product_key: key, display_sku: key }), {
      done: "Promotion requested. A catalogue approver decides it.",
      failed: "The promotion was not requested",
    });
    if (outcome.ok) {
      setProductKey("");
      onOpenChange(false);
    } else setError(outcome.fieldErrors.product_key ?? outcome.fieldErrors.category_id ?? null);
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      title="Request promotion to the catalogue"
      description={`${product.custom_code} · ${product.product_name} becomes a catalogue product once a catalogue approver agrees.`}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Not now
          </Button>
          <Button variant="inverse" loading={commands.pending === "promote"} isDisabled={Boolean(commands.offline)} onPress={() => void submit()}>
            Request promotion
          </Button>
        </>
      }
    >
      <TextField
        label="Product key"
        value={productKey}
        onChange={(value) => {
          setProductKey(value);
          setError(null);
        }}
        maxLength={120}
        isRequired
        help="The key it will carry in the catalogue. It is also used as its display SKU."
        error={error ?? undefined}
      />
    </Modal>
  );
}

// ---------------------------------------------------------------------------------------------
// Specification: a form while it can be edited, a record otherwise

function SpecificationView({ product, commands }: { product: CustomProductDetail; commands: Commands }) {
  const editable = product.capabilities.update?.allowed === true;
  const [state, setState] = useState<{ base: CustomForm; form: CustomForm; version: number }>(() => {
    const base = customFormOf(product);
    return { base, form: base, version: product.version };
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const changes = customBody(state.form, state.base);
  const dirty = Object.keys(changes).length > 0;
  if (product.version !== state.version && !dirty) {
    const base = customFormOf(product);
    setState({ base, form: base, version: product.version });
  }
  const set = <K extends keyof CustomForm>(field: K, value: CustomForm[K]) => {
    setState((current) => ({ ...current, form: { ...current.form, [field]: value } }));
    if (errors[field]) setErrors((current) => ({ ...current, [field]: "" }));
  };
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!dirty) return;
    const found = validateCustom(state.form);
    if (Object.keys(found).length > 0) {
      setErrors(found);
      return;
    }
    const outcome = await commands.run("update", [state.version, JSON.stringify(changes)], () => updateCustomProduct({ id: product.id, version: state.version }, changes), {
      done: "Specification saved",
      failed: "The specification was not saved",
      conflictMessage: CONFLICT,
    });
    if (outcome.ok) {
      const base = customFormOf(outcome.value);
      setState({ base, form: base, version: outcome.value.version });
      setErrors({});
    } else setErrors(outcome.fieldErrors);
  };

  if (!editable) return <SpecificationRecord product={product} />;
  const group = { form: state.form, set, errors };
  const errorCount = Object.values(errors).filter(Boolean).length;
  return (
    <form onSubmit={(event) => void save(event)} className="stack" noValidate>
      {errorCount > 0 ? (
        <Banner tone="ember" title={errorCount === 1 ? "One field needs another look." : `${errorCount} fields need another look.`}>
          Nothing was saved. The fields are marked below.
        </Banner>
      ) : null}
      <FormSection title="The product" description="What it is and who asked for it.">
        <IdentityFields {...group} />
      </FormSection>
      <FormSection title="Specification" description="Change it here as it firms up. To put a version on record with a sample, use Samples and revisions.">
        <SpecificationFields {...group} />
      </FormSection>
      <FormSection title="Packaging">
        <PackagingFields {...group} />
      </FormSection>
      <FormSection title="Price" description="The price the customer is quoted. Costing lives in its own view, for people with cost access.">
        <CommercialFields {...group} />
      </FormSection>
      <FormActions note={commands.offline ?? (dirty ? "Unsaved changes" : "No unsaved changes")}>
        {dirty ? (
          <Button
            variant="ghost"
            onPress={() => {
              setState((current) => ({ ...current, form: current.base }));
              setErrors({});
            }}
          >
            Discard
          </Button>
        ) : null}
        <Button type="submit" variant="inverse" loading={commands.pending === "update"} isDisabled={!dirty || Boolean(commands.offline)}>
          Save specification
        </Button>
      </FormActions>
    </form>
  );
}

function SpecificationRecord({ product }: { product: CustomProductDetail }) {
  const pack = product.packaging ?? {};
  const mm = (value: string | null) => (value ? `${value} mm` : null);
  return (
    <div className="stack">
      <GlassPanel padding="lg" title="Specification" titleAs="h2" className="rise" action={<span className="t-caption text-ink-3">Read-only in its current state</span>}>
        <KeyValue
          columns={2}
          items={[
            { label: "Based on", value: product.base_product_key, mono: true },
            { label: "Enquiry reference", value: product.inquiry_reference },
            { label: "Category", value: [product.category_name, product.subcategory_name].filter(Boolean).join(" / ") },
            { label: "Dimensions", value: product.dimensions_text },
            { label: "Length", value: mm(product.length_mm) },
            { label: "Width", value: mm(product.width_mm) },
            { label: "Height", value: mm(product.height_mm) },
            { label: "Thickness", value: product.thickness_text ?? mm(product.thickness_mm) },
            { label: "Decor", value: [product.decor_no, product.decor_name].filter(Boolean).join(" · ") },
            { label: "Finish", value: product.finish },
            { label: "Shape", value: product.shape },
            { label: "Grooves", value: product.groove_count === null ? null : String(product.groove_count) },
            { label: "Bowls", value: product.bowl_count === null ? null : String(product.bowl_count) },
            { label: "Handle", value: product.handle_type },
            { label: "Description", value: product.description ? <span className="whitespace-pre-line">{product.description}</span> : null },
          ]}
        />
      </GlassPanel>
      <GlassPanel padding="lg" title="Packaging and price" titleAs="h2" className="rise" style={stagger(1)}>
        <KeyValue
          columns={2}
          items={[
            { label: "Units per carton", value: pack.carton_qty == null ? null : String(pack.carton_qty) },
            { label: "Units per inner pack", value: pack.inner_qty == null ? null : String(pack.inner_qty) },
            { label: "Packing type", value: pack.packing_type },
            { label: "Unit weight", value: pack.unit_weight_g ? `${pack.unit_weight_g} g` : null },
            { label: "Carton volume", value: pack.cbm ? `${pack.cbm} CBM` : null },
            { label: "Packaging notes", value: product.packaging_notes },
            { label: "Quoted price", value: product.quoted_price ? <Money value={product.quoted_price} /> : null },
            { label: "Sold by", value: product.unit_code },
            { label: "Remarks", value: product.remarks ? <span className="whitespace-pre-line">{product.remarks}</span> : null },
          ]}
        />
      </GlassPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Samples and specification revisions

function SamplesView({ product, commands }: { product: CustomProductDetail; commands: Commands }) {
  const canOpen = useCanOpen();
  const editable = product.capabilities.update?.allowed === true;
  const [reference, setReference] = useState("");
  const [feedback, setFeedback] = useState("");
  const record = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const outcome = await commands.run("spec", [product.version, reference, feedback], () => recordSpecRevision(product.id, { sample_reference: reference.trim() || null, feedback: feedback.trim() || null }), {
      done: "Specification put on record",
      failed: "The specification was not recorded",
    });
    if (outcome.ok) {
      setReference("");
      setFeedback("");
    }
  };
  const decide = (revision: CustomProductDetail["spec_revisions"][number], outcome: "approved" | "rejected") =>
    void commands.run(outcome === "approved" ? "spec_ok" : "spec_no", [revision.id], () => decideSpecRevision(product.id, revision, outcome), {
      done: outcome === "approved" ? "Recorded: the customer approved" : "Recorded: the customer rejected",
      failed: "The customer's answer was not recorded",
      conflictMessage: CONFLICT,
    });

  return (
    <div className="stack">
      <GlassPanel padding="lg" title="Specification revisions" titleAs="h2" className="rise">
        {product.spec_revisions.length === 0 ? (
          <EmptyState
            compact
            icon="packageOpen"
            title="No specification on record yet"
            text="Each time a sample goes out, put the specification it was made to on record. The customer's answer is recorded against it."
          />
        ) : (
          <ol className="flex flex-col">
            {product.spec_revisions.map((revision, index) => {
              const look = SPEC_OUTCOME[revision.outcome] ?? { label: humanise(revision.outcome), tone: "neutral" as Tone };
              return (
                <li key={revision.id} className="rise-plain hairline-top flex flex-wrap items-start justify-between gap-x-6 gap-y-3 py-4 first:border-t-0 first:pt-0 last:pb-0" style={stagger(index)}>
                  <div className="flex min-w-0 items-start gap-4">
                    <span className="t-stat-sm lk-tnum flex h-11 w-11 flex-none items-center justify-center rounded-md border border-line bg-surface text-ink" aria-hidden="true">
                      {revision.revision_no}
                    </span>
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="t-label flex flex-wrap items-center gap-2 text-ink">
                        Revision {revision.revision_no}
                        <Badge tone={look.tone} size="sm" dot>
                          {look.label}
                        </Badge>
                      </span>
                      <span className="t-caption text-ink-3">
                        Recorded <DateText value={revision.created_at} style="dayTime" />
                        {revision.sample_sent_on ? (
                          <>
                            {" · sample sent "}
                            <DateText value={revision.sample_sent_on} style="business" />
                          </>
                        ) : null}
                        {revision.sample_reference ? ` · ${revision.sample_reference}` : ""}
                        {revision.decided_by?.display_name ? ` · answer recorded by ${revision.decided_by.display_name}` : ""}
                      </span>
                      {revision.sample_id && revision.sample_number ? (
                        <span className="t-body-sm text-ink-2">
                          Sample{" "}
                          {canOpen(`/sales/samples/${revision.sample_id}`) ? (
                            <TextLink href={asRoute(`/sales/samples/${revision.sample_id}`)}>
                              <Code>{revision.sample_number}</Code>
                            </TextLink>
                          ) : (
                            <Code>{revision.sample_number}</Code>
                          )}
                        </span>
                      ) : null}
                      {revision.feedback ? <p className="t-body-sm text-ink-2">{revision.feedback}</p> : null}
                    </div>
                  </div>
                  {editable && revision.outcome === "pending" ? (
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="secondary" iconLeft="thumbsDown" isDisabled={Boolean(commands.offline) || commands.pending !== null} onPress={() => decide(revision, "rejected")}>
                        Customer rejected
                      </Button>
                      <Button size="sm" variant="inverse" iconLeft="thumbsUp" isDisabled={Boolean(commands.offline) || commands.pending !== null} onPress={() => decide(revision, "approved")}>
                        Customer approved
                      </Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
      </GlassPanel>

      {editable ? (
        <form onSubmit={(event) => void record(event)} noValidate>
          <FormSection title="Put the current specification on record" description="A snapshot of the specification as it stands now, tied to the sample you are sending. Earlier revisions are kept.">
            <TextField label="Sample reference" optional placeholder="Courier, tracking number or a note" value={reference} onChange={setReference} maxLength={120} />
            <TextField label="Feedback so far" optional value={feedback} onChange={setFeedback} maxLength={4000} />
            <div className="col-span-full flex justify-end">
              <Button type="submit" variant="inverse" iconLeft="save" loading={commands.pending === "spec"} isDisabled={Boolean(commands.offline)}>
                Record this specification
              </Button>
            </div>
          </FormSection>
        </form>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Costing (restricted)

function CostingView({ product }: { product: CustomProductDetail }) {
  const canWrite = product.capabilities.record_costing?.allowed === true;
  const costingKeys = useMemo(() => [queryKeys.sales.customProductCosting(product.id)], [product.id]);
  const query = useQuery({ queryKey: queryKeys.sales.customProductCosting(product.id), queryFn: ({ signal }) => fetchCosting(product.id, signal) });
  const commands = useResourceCommand(`costing:${product.id}`, costingKeys);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<string>("EUR");
  const [basis, setBasis] = useState("");
  const [error, setError] = useState(false);
  const record = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!amount) {
      setError(true);
      return;
    }
    const outcome = await commands.run("cost", [amount, currency], () => recordCosting(product.id, { cost_amount: amount, cost_currency: currency, basis_note: basis.trim() || null }), {
      done: "Costing recorded",
      failed: "The costing was not recorded",
    });
    if (outcome.ok) {
      setAmount("");
      setBasis("");
    }
  };
  const latest = query.data?.[0];
  return (
    <div className="stack">
      <GlassPanel
        padding="lg"
        title="Cost per unit"
        titleAs="h2"
        className="rise"
        action={
          <Badge tone="neutral" icon="lock" size="sm">
            Restricted
          </Badge>
        }
      >
        {query.isPending ? (
          <SkeletonText lines={3} />
        ) : query.isError ? (
          <ErrorBlock error={query.error} what="Costing" onRetry={() => void query.refetch()} />
        ) : query.data.length === 0 ? (
          <EmptyState compact icon="calculator" title="No costing recorded" text="Record what a unit costs to make, and what that figure is based on." />
        ) : (
          <div className="flex flex-col gap-5">
            {latest ? (
              <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
                <div className="flex flex-col gap-0.5">
                  <span className="t-overline text-ink-3">Latest, version {latest.cost_version}</span>
                  {latest.basis_note ? <span className="t-body-sm text-ink-2">{latest.basis_note}</span> : null}
                </div>
                <Money value={latest.cost} className="t-stat ml-auto text-right text-ink" />
              </div>
            ) : null}
            <ol className="flex flex-col">
              {query.data.map((row) => (
                <li key={row.id} className="hairline-top flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3 last:pb-0">
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="t-label text-ink">Version {row.cost_version}</span>
                    <span className="t-caption text-ink-3">
                      <DateText value={row.recorded_at} style="date" />
                      {row.recorded_by?.display_name ? ` · ${row.recorded_by.display_name}` : ""}
                      {row.basis_note ? ` · ${row.basis_note}` : ""}
                    </span>
                  </span>
                  <Money value={row.cost} className="t-label text-ink" />
                </li>
              ))}
            </ol>
          </div>
        )}
      </GlassPanel>
      {canWrite ? (
        <form onSubmit={(event) => void record(event)} noValidate>
          <FormSection title="Record a new costing" description="Each entry is a new version. Earlier versions stay on record.">
            <DecimalField
              label="Cost per unit"
              value={amount}
              onChange={(value) => {
                setAmount(value);
                setError(false);
              }}
              prefix={currency}
              maxFractionDigits={4}
              isRequired
              error={error ? "Enter the cost of one unit." : undefined}
            />
            <Select label="Currency" options={CURRENCIES.map((code) => ({ value: code, label: code }))} value={currency} onChange={setCurrency} />
            <Textarea className="col-span-full" label="What it is based on" optional rows={2} value={basis} onChange={setBasis} />
            <div className="col-span-full flex justify-end">
              <Button type="submit" variant="inverse" loading={commands.pending === "cost"} isDisabled={Boolean(commands.offline)}>
                Record costing
              </Button>
            </div>
          </FormSection>
        </form>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Activity

function ActivityView({ product }: { product: CustomProductDetail }) {
  const query = useQuery({ queryKey: queryKeys.sales.customProductHistory(product.id), queryFn: ({ signal }) => fetchCustomHistory(product.id, signal) });
  if (query.isPending) return <LoadingBlock label="Loading activity" lines={5} />;
  if (query.isError) return <ErrorBlock error={query.error} what="The activity" onRetry={() => void query.refetch()} />;
  const items: TimelineItem[] = query.data.map((entry) => {
    const from = customProductStatus(entry.from_status);
    const to = customProductStatus(entry.to_status);
    return {
      id: entry.id,
      title: `${entry.actor?.display_name ?? "Lamikraft One"}: ${(TRANSITION[entry.action] ?? humanise(entry.action)).toLowerCase()}`,
      meta: (
        <>
          <DateText value={entry.occurred_at} style="dayTime" />
          {entry.from_status !== entry.to_status ? ` · ${from.label} to ${to.label}` : ` · ${to.label}`}
        </>
      ),
      body:
        entry.reason || entry.quote_id ? (
          <>
            {entry.reason}
            {entry.quote_id ? (
              <>
                {entry.reason ? " " : ""}
                <TextLink href={asRoute(`/sales/quotes/${entry.quote_id}`)}>Open the quotation</TextLink>
              </>
            ) : null}
          </>
        ) : undefined,
      icon: TRANSITION_ICON[entry.action],
      tone: to.tone,
    };
  });
  return (
    <GlassPanel padding="lg" title="Activity" titleAs="h2" className="rise">
      {items.length === 0 ? <EmptyState compact icon="history" title="No history yet" text="Changes of status are listed here as they happen." /> : <Timeline label="Custom product activity" items={items} />}
    </GlassPanel>
  );
}
