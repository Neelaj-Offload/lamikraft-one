"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useState, type FormEvent } from "react";
import { useProductSearch } from "@/features/sales/pickers";
import { ProblemError } from "@/lib/api/errors";
import {
  createListing,
  MARKETPLACE_INVALIDATE,
  simulateOrder,
  syncChannel,
  updateChannel,
  updateListing,
  useChannel,
  type ChannelDetail,
  type Listing,
  type MarketplaceOrder,
} from "~/data/marketplaces";
import { Page, PageHeader, RecordHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ComboBox,
  DataTable,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  Modal,
  Select,
  Skeleton,
  Switch,
  TextField,
  toast,
  type Column,
} from "~/ui";
import { CHANNEL_HINT, ModeBadge } from "./channels";

const crumbs = [
  { label: "Sales", href: "/sales" as Route },
  { label: "Marketplaces", href: "/sales/marketplaces" as Route },
];

function useRefresh() {
  const queryClient = useQueryClient();
  return () => Promise.all(MARKETPLACE_INVALIDATE.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
}

const problem = (error: unknown) => (error instanceof ProblemError ? (error.detail ?? error.title) : "The connection dropped. Try again.");

export function MarketplaceChannel({ channelId }: { channelId: string }) {
  const query = useChannel(channelId);
  if (query.isPending) {
    return (
      <Page>
        <Skeleton width="40%" height={28} />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <PageHeader breadcrumb={crumbs} title="Marketplace" />
        <ErrorBlock error={query.error} what="This marketplace" onRetry={() => void query.refetch()} />
      </Page>
    );
  }
  return <Loaded channel={query.data} />;
}

function Loaded({ channel }: { channel: ChannelDetail }) {
  const refresh = useRefresh();
  const [mapping, setMapping] = useState(0);
  const [simulating, setSimulating] = useState(0);
  const canManage = channel.capabilities.manage?.allowed === true;
  const canSync = channel.capabilities.sync?.allowed === true;
  const canSimulate = channel.capabilities.simulate?.allowed === true;

  const sync = useMutation({
    mutationFn: () => syncChannel(channel.id),
    onSuccess: async (s) => {
      await refresh();
      if (s.error) toast.error("The sync stopped", { description: s.error });
      else toast.success("Synced", { description: `${s.orders_posted} orders posted, ${s.orders_held} held, ${s.listings_pushed} stock levels sent.` });
    },
    onError: (error) => toast.error("The sync did not run", { description: problem(error) }),
  });
  const toggle = useMutation({
    mutationFn: (patch: { mode?: "demo" | "live"; is_active?: boolean }) => updateChannel(channel.id, { expected_version: channel.version, ...patch }),
    onSuccess: async () => {
      await refresh();
      toast.success("Channel updated");
    },
    onError: (error) => toast.error("The channel was not changed", { description: problem(error) }),
  });
  const push = useMutation({
    mutationFn: (listing: Listing) => updateListing(listing.id, { expected_version: listing.version, push_stock: !listing.push_stock }),
    onSuccess: () => refresh(),
    onError: (error) => toast.error("Not changed", { description: problem(error) }),
  });

  const listingColumns: Column<Listing>[] = [
    {
      key: "sku",
      header: "Channel SKU",
      primary: true,
      cell: (l) => (
        <span className="flex min-w-0 flex-col">
          <span className="t-label lk-mono text-ink">{l.channel_sku}</span>
          <span className="t-caption text-ink-3">
            {l.product_key} · {l.product_name}
          </span>
        </span>
      ),
    },
    { key: "free", header: "Free to sell", numeric: true, cell: (l) => <span className="lk-tnum">{Number(l.free_quantity).toLocaleString()}</span> },
    {
      key: "pushed",
      header: "Last sent",
      hideOnMobile: true,
      cell: (l) =>
        l.last_push_error ? (
          <Badge tone="ember" icon="alert">
            {l.last_push_error}
          </Badge>
        ) : l.last_pushed_at ? (
          <span>
            {Number(l.last_pushed_qty ?? 0).toLocaleString()} · <DateText value={l.last_pushed_at} style="relative" />
          </span>
        ) : (
          <span className="text-ink-3">Not sent yet</span>
        ),
    },
    {
      key: "push",
      header: "Send stock",
      cell: (l) => (
        <Switch label={`Send stock for ${l.channel_sku}`} isSelected={l.push_stock} isDisabled={!canManage || push.isPending} onChange={() => push.mutate(l)} />
      ),
    },
  ];

  const orderColumns: Column<MarketplaceOrder>[] = [
    {
      key: "id",
      header: "Order",
      primary: true,
      cell: (o) => (
        <span className="flex flex-wrap items-center gap-2">
          <span className="lk-mono">{o.external_order_id}</span>
          {o.is_demo ? <Badge size="sm">Demo</Badge> : null}
        </span>
      ),
    },
    { key: "when", header: "Ordered", cell: (o) => <DateText value={o.ordered_at} style="relative" /> },
    { key: "items", header: "Items", hideOnMobile: true, cell: (o) => o.lines.map((l) => `${l.quantity} × ${l.sku}`).join(", ") },
    {
      key: "status",
      header: "Stock",
      cell: (o) =>
        o.status === "posted" ? (
          <Badge tone="leaf" dot>
            Taken out
          </Badge>
        ) : o.status === "cancelled" ? (
          <Badge>Cancelled</Badge>
        ) : (
          <span className="flex flex-col gap-1">
            <Badge tone="amber" icon="alert">
              Needs attention
            </Badge>
            <span className="t-caption text-ink-3">{o.attention_reason}</span>
          </span>
        ),
    },
  ];

  return (
    <Page>
      <RecordHeader
        breadcrumb={[...crumbs, { label: channel.name }]}
        code={channel.code}
        title={channel.name}
        status={<ModeBadge channel={channel} />}
        lead={CHANNEL_HINT[channel.kind]}
        facts={
          <FactStrip
            items={[
              { label: "Ships from", value: channel.warehouse_code, icon: "warehouse" },
              { label: "Products mapped", value: String(channel.listing_count), icon: "tag" },
              { label: "Last synced", value: channel.last_synced_at ? <DateText value={channel.last_synced_at} style="relative" /> : "Never", icon: "refresh" },
              { label: "Need attention", value: String(channel.attention_count), icon: "alert" },
            ]}
          />
        }
        actions={
          <>
            {canSync ? (
              <Button iconLeft="refresh" loading={sync.isPending} onPress={() => sync.mutate()}>
                Sync now
              </Button>
            ) : null}
            {canSimulate ? (
              <Button variant="secondary" iconLeft="sparkles" onPress={() => setSimulating((n) => n + 1)}>
                Simulate an order
              </Button>
            ) : null}
            {canManage ? (
              <Button variant="secondary" iconLeft="plus" onPress={() => setMapping((n) => n + 1)}>
                Map a product
              </Button>
            ) : null}
          </>
        }
      />

      {channel.mode === "demo" ? (
        <Banner tone="gold" title="Demo mode.">
          Nothing is sent to {channel.name}. Simulated orders take real stock out of {channel.warehouse_code} so you can try the flow.
          {channel.live_available
            ? " Credentials are configured: you can switch this channel to Live."
            : channel.kind === "amazon"
              ? " Live needs the Amazon Selling Partner credentials on the server, after Amazon approves the developer profile."
              : " Live for this platform comes after Amazon."}
        </Banner>
      ) : null}
      {canManage ? (
        <div className="flex flex-wrap gap-3">
          {channel.live_available ? (
            <Button variant="secondary" size="sm" loading={toggle.isPending} onPress={() => toggle.mutate({ mode: channel.mode === "live" ? "demo" : "live" })}>
              {channel.mode === "live" ? "Switch to Demo" : "Switch to Live"}
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" loading={toggle.isPending} onPress={() => toggle.mutate({ is_active: !channel.is_active })}>
            {channel.is_active ? "Turn this channel off" : "Turn this channel on"}
          </Button>
        </div>
      ) : null}

      <GlassPanel padding="none" className="rise">
        <DataTable
          label="Products on this channel"
          columns={listingColumns}
          rows={channel.listings}
          rowKey={(l) => l.id}
          empty={<EmptyState icon="tag" title="No products mapped yet" text="Map each product to its SKU on this platform. Orders for unmapped SKUs wait here for you." />}
        />
      </GlassPanel>
      <GlassPanel padding="none" className="rise">
        <DataTable
          label="Recent orders"
          columns={orderColumns}
          rows={channel.orders}
          rowKey={(o) => o.id}
          empty={<EmptyState icon="cart" title="No orders yet" text="Orders appear here after a sync, each taking its stock out once." />}
        />
      </GlassPanel>

      {mapping > 0 ? <MapProductDialog key={mapping} channel={channel} onClose={() => setMapping(0)} /> : null}
      {simulating > 0 ? <SimulateDialog key={simulating} channel={channel} onClose={() => setSimulating(0)} /> : null}
    </Page>
  );
}

function MapProductDialog({ channel, onClose }: { channel: ChannelDetail; onClose: () => void }) {
  const refresh = useRefresh();
  const [text, setText] = useState("");
  const [productId, setProductId] = useState<string | null>(null);
  const [sku, setSku] = useState("");
  const [externalId, setExternalId] = useState("");
  const [productType, setProductType] = useState("");
  const [error, setError] = useState<string | null>(null);
  const search = useProductSearch(text);
  const options = (search.data ?? []).map((p) => ({ id: p.id, label: p.product_key, description: p.product_name }));
  const save = useMutation({
    mutationFn: () =>
      createListing(channel.id, {
        product_id: productId!,
        channel_sku: sku.trim(),
        external_id: externalId.trim() || null,
        product_type: productType.trim() || null,
      }),
    onSuccess: async () => {
      await refresh();
      toast.success(`${sku.trim()} mapped`);
      onClose();
    },
    onError: (e) => setError(problem(e)),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!productId || !sku.trim()) return setError("Pick the product and enter its SKU on this platform.");
    save.mutate();
  };
  return (
    <Modal
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`Map a product on ${channel.name}`}
      description="The SKU is exactly what the platform shows for this product."
      actions={
        <>
          <Button variant="ghost" onPress={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="map-product" loading={save.isPending}>
            Map product
          </Button>
        </>
      }
    >
      <form id="map-product" onSubmit={submit} noValidate className="flex flex-col gap-4">
        {error ? (
          <Banner tone="ember" title="Not mapped.">
            {error}
          </Banner>
        ) : null}
        <ComboBox
          label="Product"
          placeholder="Type a product key or name"
          emptyText={text.trim().length < 2 ? "Type at least two letters" : "No product matches"}
          items={options}
          inputValue={text}
          onInputChange={setText}
          selectedKey={productId}
          onSelectionChange={(id) => {
            setProductId(id);
            const option = options.find((o) => o.id === id);
            if (option) setText(option.label);
          }}
          isLoading={search.isFetching}
          isRequired
        />
        <TextField label="SKU on the platform" isRequired value={sku} onChange={setSku} maxLength={80} />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField label={channel.kind === "amazon" ? "ASIN" : "Listing id"} optional value={externalId} onChange={setExternalId} maxLength={80} />
          {channel.kind === "amazon" ? (
            <TextField label="Amazon product type" optional value={productType} onChange={setProductType} maxLength={80} help="Needed to send stock, for example CUTTING_BOARD." />
          ) : null}
        </div>
      </form>
    </Modal>
  );
}

function SimulateDialog({ channel, onClose }: { channel: ChannelDetail; onClose: () => void }) {
  const refresh = useRefresh();
  const [sku, setSku] = useState<string | null>(channel.listings[0]?.channel_sku ?? null);
  const [quantity, setQuantity] = useState("1");
  const run = useMutation({
    mutationFn: () => simulateOrder(channel.id, { channel_sku: sku ?? "", quantity: Number(quantity) || 1 }),
    onSuccess: async (order) => {
      await refresh();
      if (order.status === "posted") toast.success(`${order.external_order_id}: stock taken out`);
      else toast.warning(`${order.external_order_id} needs attention`, { description: order.attention_reason ?? undefined });
      onClose();
    },
    onError: (e) => toast.error("No order was simulated", { description: problem(e) }),
  });
  return (
    <Modal
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      size="sm"
      title="Simulate an order"
      description={`Demo: an order arrives on ${channel.name} and takes real stock out, as a live order would.`}
      actions={
        <>
          <Button variant="ghost" onPress={onClose}>
            Cancel
          </Button>
          <Button isDisabled={!sku} loading={run.isPending} onPress={() => run.mutate()}>
            Simulate order
          </Button>
        </>
      }
    >
      {channel.listings.length === 0 ? (
        <p className="t-body text-ink-2">Map a product first.</p>
      ) : (
        <div className="flex flex-col gap-4">
          <Select label="SKU" options={channel.listings.map((l) => ({ value: l.channel_sku, label: l.channel_sku, description: l.product_name }))} value={sku} onChange={setSku} />
          <TextField label="Quantity" inputMode="numeric" value={quantity} onChange={setQuantity} maxLength={4} />
        </div>
      )}
    </Modal>
  );
}
