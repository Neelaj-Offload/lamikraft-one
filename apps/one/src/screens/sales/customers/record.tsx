"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useState } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { fetchParty } from "@/features/parties/api";
import { setPartyArchived } from "@/features/parties/customer-types-api";
import type { PartyDetail } from "@/features/parties/types";
import { conflictFromError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useRecentRecord } from "@/lib/recent/recent-records";
import { useSession } from "@/lib/session/context";
import { useCustomerOrders, useCustomerQuoteCounts, useCustomerQuotes, useCustomerSamples, useSampleStatusCounts } from "~/data/sales-crm";
import { Page, PageHeader, RecordHeader, type Crumb } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Button, ButtonLink, ConfirmDialog, FactStrip, IconButton, Menu, Skeleton, SkeletonText, Tabs, toast, type MenuItem, type TabItem } from "~/ui";
import { SampleCreateDialog } from "../samples/create-dialog";
import { countryName, customerHref, ROLE_LABEL, STAGE_LABEL, STAGE_TONE, TYPE_LABEL, type CustomerView } from "./labels";
import { RecordActivity, RecordFiles, RecordNote } from "./record-collab";
import { AddContactModal, EditCustomerDrawer } from "./record-forms";
import { SuppliesView } from "./record-supplies";
import { ContactsView, OrdersView, OverviewView, QuotationsView, SamplesView } from "./record-views";

const listCrumb = (party: Pick<PartyDetail, "status"> | null): Crumb =>
  party?.status === "prospect" ? { label: "Leads", href: "/sales/parties?status=prospect" as Route } : { label: "Customers", href: "/sales/parties?status=active" as Route };

/** One customer's profile: who they are, how to reach them, what they were offered, sent and sold. */
export function CustomerRecord({ partyId, view }: { partyId: string; view: CustomerView }) {
  const query = useQuery({ queryKey: queryKeys.parties.party(partyId), queryFn: ({ signal }) => fetchParty(partyId, signal) });
  useRecentRecord("parties.party", query.data?.id, query.isSuccess);

  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the customer">
          <Skeleton width={90} height={10} />
          <Skeleton width="40%" height={28} />
          <SkeletonText lines={2} />
        </div>
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <PageHeader breadcrumb={[{ label: "Sales", href: "/sales" }, listCrumb(null)]} title="Customer" />
        <ErrorBlock error={query.error} what="This customer" onRetry={() => void query.refetch()} />
      </Page>
    );
  }
  return <Loaded party={query.data} view={view} />;
}

function Loaded({ party, view }: { party: PartyDetail; view: CustomerView }) {
  const { permissionKeys } = useSession();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState({ open: false, round: 0 });
  const [addingContact, setAddingContact] = useState({ open: false, round: 0 });
  const [addingSample, setAddingSample] = useState({ open: false, round: 0 });
  const [confirmArchive, setConfirmArchive] = useState<"archive" | "restore" | null>(null);

  const canUpdate = party.capabilities.update?.allowed === true;
  const canArchive = party.capabilities.archive?.allowed === true;
  const canRestore = party.capabilities.restore?.allowed === true;
  const isCustomer = party.roles.includes("customer");
  const isVendor = party.roles.includes("vendor");
  const canQuotes = isCustomer && permissionKeys.has("sales.quote.read");
  const canSamples = isCustomer && permissionKeys.has("sales.sample.read");
  const canOrders = isCustomer && permissionKeys.has("orders.sales_order.read");
  const canSupplies = isVendor && permissionKeys.has("procurement.vendor_item.read");
  const tradable = isCustomer && !party.archived_at && party.status !== "blocked";
  const canCreateQuote = tradable && permissionKeys.has("sales.quote.create");
  const canCreateSample = tradable && permissionKeys.has("sales.sample.create");

  const quotes = useCustomerQuotes(party.id, canQuotes);
  const quoteCounts = useCustomerQuoteCounts(party.id, canQuotes);
  const samples = useCustomerSamples(party.id, canSamples);
  const sampleCounts = useSampleStatusCounts(canSamples, party.id);
  const orders = useCustomerOrders(party.id, canOrders);

  useScreenContribution({ focus: { type: "parties.party", id: party.id, version: party.version } });

  // A view this record does not have (a vendor's "samples", say) falls back to the overview.
  const available: Record<CustomerView, boolean> = {
    overview: true,
    contacts: true,
    quotations: canQuotes,
    samples: canSamples,
    orders: canOrders,
    supplies: canSupplies,
    notes: true,
    activity: true,
  };
  const current: CustomerView = available[view] ? view : "overview";
  const tab = (id: CustomerView, label: string, count?: number): TabItem => ({ id, label, count, href: customerHref(party.id, id) as Route });
  const tabs: TabItem[] = [
    tab("overview", "Overview"),
    tab("contacts", "Contacts and addresses", party.contacts.length || undefined),
    ...(canQuotes ? [tab("quotations", "Quotations", quotes.data?.total || undefined)] : []),
    ...(canSamples ? [tab("samples", "Samples", samples.data?.total || undefined)] : []),
    ...(canOrders ? [tab("orders", "Orders", orders.data?.total || undefined)] : []),
    ...(canSupplies ? [tab("supplies", "What they supply")] : []),
    tab("notes", "Notes and files"),
    tab("activity", "Activity"),
  ];

  const open = (set: typeof setEditing) => () => set((state) => ({ open: true, round: state.round + 1 }));
  const close = (set: typeof setEditing) => (isOpen: boolean) => set((state) => ({ ...state, open: isOpen }));

  const createQuote = canCreateQuote ? (
    <ButtonLink href={`/sales/quotes/new?party=${encodeURIComponent(party.id)}` as Route} iconLeft="plus">
      Create quotation
    </ButtonLink>
  ) : null;
  const addSample = canCreateSample ? (
    <Button variant="secondary" size="sm" iconLeft="plus" onPress={open(setAddingSample)}>
      Add sample
    </Button>
  ) : undefined;

  const menu: MenuItem[] = [
    ...(canUpdate ? [{ id: "contact", label: "Add contact", icon: "userPlus" as const, onAction: open(setAddingContact) }] : []),
    ...(canCreateSample ? [{ id: "sample", label: "Add sample", icon: "packageOpen" as const, onAction: open(setAddingSample) }] : []),
    ...(canArchive
      ? [
          ...(canUpdate || canCreateSample ? [{ id: "sep", separator: true as const }] : []),
          { id: "archive", label: "Archive", icon: "archive" as const, tone: "danger" as const, onAction: () => setConfirmArchive("archive") },
        ]
      : []),
  ];

  const archive = async (archived: boolean) => {
    try {
      await setPartyArchived(party.id, archived, party.version);
      await Promise.all(invalidationMap["parties.party_changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      toast.success(archived ? `${party.display_name} archived` : `${party.display_name} restored`);
    } catch (error) {
      if (conflictFromError(error)) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.parties.party(party.id) });
        toast.warning("This customer changed since you opened it", { description: "The latest version is showing. Try again." });
      } else {
        toast.error(archived ? "The customer was not archived" : "The customer was not restored", { description: "Check your connection, then try again." });
      }
      throw error;
    }
  };

  const otherRoles = party.roles.filter((role) => role !== "customer");

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Sales", href: "/sales" }, listCrumb(party), { label: party.display_name }]}
        code={party.party_number}
        title={party.display_name}
        status={
          <>
            <Badge tone={STAGE_TONE[party.status]} dot>
              {STAGE_LABEL[party.status]}
            </Badge>
            {otherRoles.map((role) => (
              <Badge key={role} outline>
                {ROLE_LABEL[role]}
              </Badge>
            ))}
            {party.archived_at ? <Badge icon="archive">Archived</Badge> : null}
          </>
        }
        lead={party.legal_name !== party.display_name ? party.legal_name : undefined}
        facts={
          <FactStrip
            items={[
              { label: "Country", value: countryName(party.country_code), icon: "globe" },
              { label: "Quoted in", value: party.default_currency, icon: "banknote" },
              { label: "Type", value: party.customer_type ? (TYPE_LABEL[party.customer_type] ?? party.customer_type) : null, icon: "tag" },
              { label: "Looked after by", value: party.owner.display_name, icon: "user" },
              { label: "Main contact", value: party.contacts.find((contact) => contact.is_primary)?.name ?? party.primary_contact, icon: "phone" },
            ]}
          />
        }
        actions={
          <>
            {createQuote}
            {canRestore ? (
              <Button variant="inverse" iconLeft="undo" onPress={() => setConfirmArchive("restore")}>
                Restore
              </Button>
            ) : null}
            {canUpdate ? (
              <Button variant="secondary" iconLeft="edit" onPress={open(setEditing)}>
                Edit
              </Button>
            ) : null}
            {menu.length > 0 ? <Menu label="More actions" items={menu} placement="bottom end" trigger={<IconButton icon="more" label="More actions" />} /> : null}
          </>
        }
      >
        <Tabs label={`${party.display_name}: views`} tabs={tabs} selectedKey={current} />
      </RecordHeader>

      {current === "overview" ? (
        <OverviewView
          party={party}
          quotes={canQuotes ? quotes : null}
          samples={canSamples ? samples : null}
          orders={canOrders ? orders : null}
          quoteCounts={quoteCounts.data}
          sampleCounts={sampleCounts.data}
          can={{ createQuote: canCreateQuote }}
          createQuote={
            canCreateQuote ? (
              <ButtonLink variant="inverse" href={`/sales/quotes/new?party=${encodeURIComponent(party.id)}` as Route} iconRight="arrowRight">
                Create quotation
              </ButtonLink>
            ) : undefined
          }
        />
      ) : null}
      {current === "contacts" ? <ContactsView party={party} onAddContact={canUpdate ? open(setAddingContact) : undefined} /> : null}
      {current === "quotations" ? (
        <QuotationsView
          party={party}
          query={quotes}
          create={
            canCreateQuote ? (
              <ButtonLink variant="secondary" size="sm" href={`/sales/quotes/new?party=${encodeURIComponent(party.id)}` as Route} iconLeft="plus">
                Create quotation
              </ButtonLink>
            ) : undefined
          }
        />
      ) : null}
      {current === "samples" ? <SamplesView party={party} query={samples} create={addSample} /> : null}
      {current === "orders" ? <OrdersView party={party} query={orders} /> : null}
      {current === "supplies" ? <SuppliesView vendorId={party.id} vendorName={party.display_name} defaultCurrency={party.default_currency || null} /> : null}
      {current === "notes" ? (
        <div className="grid min-w-0 grid-cols-1 items-start gap-5 lg:grid-cols-2">
          <RecordNote resourceType="parties.party" resourceId={party.id} subject={party.display_name} />
          <RecordFiles resourceType="parties.party" resourceId={party.id} />
        </div>
      ) : null}
      {current === "activity" ? <RecordActivity resourceType="parties.party" resourceId={party.id} /> : null}

      {canUpdate ? <EditCustomerDrawer key={`edit-${editing.round}`} party={party} isOpen={editing.open} onOpenChange={close(setEditing)} /> : null}
      {canUpdate ? <AddContactModal key={`contact-${addingContact.round}`} party={party} isOpen={addingContact.open} onOpenChange={close(setAddingContact)} /> : null}
      {canCreateSample ? (
        <SampleCreateDialog
          key={`sample-${addingSample.round}`}
          isOpen={addingSample.open}
          onOpenChange={close(setAddingSample)}
          customer={{ id: party.id, name: party.display_name }}
        />
      ) : null}
      <ConfirmDialog
        isOpen={confirmArchive !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setConfirmArchive(null);
        }}
        tone={confirmArchive === "archive" ? "danger" : "default"}
        title={confirmArchive === "restore" ? `Restore ${party.display_name}` : `Archive ${party.display_name}`}
        description={
          confirmArchive === "restore"
            ? "They return to the customer list and can be quoted again."
            : "They leave the customer list and the pickers. Their quotations, samples and orders stay, and you can restore them later."
        }
        confirmLabel={confirmArchive === "restore" ? "Restore customer" : "Archive customer"}
        onConfirm={() => archive(confirmArchive !== "restore")}
      />
    </Page>
  );
}
