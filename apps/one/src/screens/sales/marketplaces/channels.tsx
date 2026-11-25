"use client";

import type { Route } from "next";
import { useChannels, type Channel } from "~/data/marketplaces";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, DateText, GlassPanel, Skeleton, TextLink } from "~/ui";

export const CHANNEL_HINT: Record<string, string> = {
  amazon: "Amazon Seller Central (Selling Partner API)",
  flipkart: "Flipkart Seller Hub",
  pepperfry: "Pepperfry",
  website: "The Lamikraft website",
};

export function ModeBadge({ channel }: { channel: Pick<Channel, "mode" | "is_active"> }) {
  if (!channel.is_active) return <Badge>Off</Badge>;
  return channel.mode === "live" ? (
    <Badge tone="leaf" dot>
      Live
    </Badge>
  ) : (
    <Badge tone="gold" icon="sparkles">
      Demo
    </Badge>
  );
}

/** Where online sales come from: each platform's orders take stock out, and stock is pushed back to it. */
export function MarketplaceChannels() {
  const query = useChannels();
  return (
    <Page>
      <PageHeader
        eyebrow="Sales"
        title="Marketplaces"
        lead="Orders on Amazon, Flipkart, Pepperfry and the website take their stock out here, and each platform gets the free quantity back."
      />
      {query.isError ? (
        <ErrorBlock error={query.error} what="Marketplaces" onRetry={() => void query.refetch()} />
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-5 md:grid-cols-2">
          {(query.data ?? [null, null, null, null]).map((channel, index) =>
            channel ? (
              <GlassPanel key={channel.id} padding="lg" interactive className="rise flex flex-col gap-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-col gap-1">
                    <TextLink href={`/sales/marketplaces/${channel.id}` as Route} className="t-h3 text-ink">
                      {channel.name}
                    </TextLink>
                    <p className="t-caption text-ink-3">{CHANNEL_HINT[channel.kind]}</p>
                  </div>
                  <ModeBadge channel={channel} />
                </div>
                <p className="t-body-sm text-ink-2">
                  {channel.listing_count} {channel.listing_count === 1 ? "product mapped" : "products mapped"} · ships from {channel.warehouse_code}
                </p>
                <p className="t-body-sm text-ink-3">
                  {channel.last_synced_at ? (
                    <>
                      Last synced <DateText value={channel.last_synced_at} style="relative" />
                    </>
                  ) : (
                    "Not synced yet"
                  )}
                </p>
                {channel.attention_count > 0 ? (
                  <Badge tone="amber" icon="alert">
                    {channel.attention_count} {channel.attention_count === 1 ? "order needs" : "orders need"} attention
                  </Badge>
                ) : null}
              </GlassPanel>
            ) : (
              <GlassPanel key={index} padding="lg">
                <Skeleton width="50%" height={24} />
              </GlassPanel>
            ),
          )}
        </div>
      )}
    </Page>
  );
}
