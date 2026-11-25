"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useResourceCommand } from "@/features/sales/resource-command";
import { fetchChallansForSample, fetchSampleLineage, linkSampleChallan, type LineageNode, type Sample, type SampleLineage } from "@/features/samples/api";
import { queryKeys } from "@/lib/api/query-keys";
import { safeAppPath } from "@/lib/safe-path";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Button, DateText, EmptyState, GlassPanel, KeyValue, Modal, Select, TextLink, Timeline } from "~/ui";
import { humanise, stagger } from "../customers/labels";

const ORDER = ["custom_product", "spec_revision", "quote", "challan", "product"] as const;
type Kind = (typeof ORDER)[number];

const KIND_LABEL: Record<Kind, string> = {
  custom_product: "Custom product",
  spec_revision: "Specification",
  quote: "Quotation",
  challan: "Delivery challan",
  product: "Catalogue product",
};

/** The links in reading order: what the sample was made from, then how it travelled. */
function lineageRows(view: SampleLineage): { kind: Kind; node: LineageNode | null }[] {
  const missing = new Set<string>(view.missing);
  return ORDER.flatMap((kind) => {
    const node = view[kind] ?? null;
    if (node === null && !missing.has(kind)) return [];
    return [{ kind, node }];
  });
}

function NodeValue({ node }: { node: LineageNode | null }) {
  if (node === null) return <span className="text-ink-3">Not linked yet</span>;
  if (node.state === "not_visible") return <span className="text-ink-3">Linked, but outside what your role can see</span>;
  const label = node.label ?? "";
  const path = safeAppPath(node.path);
  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-2">
      {path ? (
        <TextLink href={path as Route} className="lk-mono">
          {label}
        </TextLink>
      ) : (
        <span className="lk-mono">{label}</span>
      )}
      {node.title ? <span className="text-ink-3">{node.title}</span> : null}
      {node.status ? (
        <Badge size="sm" outline>
          {humanise(node.status)}
        </Badge>
      ) : null}
      {node.facts?.origin === "promoted" ? <span className="t-caption text-ink-3">promoted from the custom product</span> : null}
    </span>
  );
}

/**
 * Where a sample came from and how it travelled (`GET /sales/samples/{id}/lineage`): the custom
 * product and its specification, the quotation, the delivery challan and the catalogue product,
 * each through its own read scope. The owner of a requested sample links the challan that carries it.
 */
export function SampleLineageView({ sample }: { sample: Sample }) {
  const query = useQuery({ queryKey: queryKeys.sales.sampleLineage(sample.id), queryFn: ({ signal }) => fetchSampleLineage(sample.id, signal) });
  const canLink = sample.capabilities.link_challan?.allowed === true;
  const [linking, setLinking] = useState({ open: false, round: 0 });

  if (query.isPending) return <LoadingBlock label="Loading where this sample came from" lines={6} />;
  if (query.isError) return <ErrorBlock error={query.error} what="This sample's history" onRetry={() => void query.refetch()} />;
  const view = query.data;
  const rows = lineageRows(view);

  return (
    <div className="grid min-w-0 grid-cols-1 items-start gap-5 lg:grid-cols-2">
      <GlassPanel
        as="section"
        padding="lg"
        title="Linked records"
        titleAs="h2"
        className="rise"
        action={
          canLink ? (
            <Button variant="secondary" size="sm" iconLeft="link" onPress={() => setLinking((current) => ({ open: true, round: current.round + 1 }))}>
              {sample.challan_id ? "Change challan" : "Link a challan"}
            </Button>
          ) : undefined
        }
      >
        {rows.length === 0 ? (
          <EmptyState compact icon="link" title="Nothing linked yet" text="A sample can be tied to a quotation, a custom product and the challan that carries it." />
        ) : (
          <KeyValue rows items={rows.map((row) => ({ label: KIND_LABEL[row.kind], value: <NodeValue node={row.node} /> }))} />
        )}
        {view.related_samples.length > 0 ? (
          <div className="hairline-top mt-5 flex flex-col gap-2 pt-4">
            <h3 className="t-overline text-ink-3">Other samples of this custom product</h3>
            <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0">
              {view.related_samples.map((related) => {
                const path = safeAppPath(related.path);
                return (
                  <li key={related.id ?? related.label} className="lk-mono t-code-sm">
                    {path ? <TextLink href={path as Route}>{related.label}</TextLink> : related.label}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </GlassPanel>

      <GlassPanel as="section" padding="lg" title="Dated history" titleAs="h2" className="rise" style={stagger(1)}>
        {view.timeline.length === 0 ? (
          <p className="t-body-sm text-ink-3">Nothing is dated yet. Entries appear as the sample is dispatched, delivered and answered.</p>
        ) : (
          <Timeline
            label="Sample history"
            items={view.timeline.map((event, index) => ({
              id: `${event.kind}-${index}`,
              title: event.label,
              meta: <DateText value={event.on} style="business" />,
            }))}
          />
        )}
      </GlassPanel>

      {canLink ? <ChallanLinkModal key={linking.round} sample={sample} isOpen={linking.open} onOpenChange={(open) => setLinking((current) => ({ ...current, open }))} /> : null}
    </div>
  );
}

function ChallanLinkModal({ sample, isOpen, onOpenChange }: { sample: Sample; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const keys = useMemo(() => [queryKeys.sales.sample(sample.id), queryKeys.sales.sampleLineage(sample.id), ["sales", "samples"], ["sales", "sample-status-counts"]], [sample.id]);
  const commands = useResourceCommand(`sample-challan:${sample.id}`, keys);
  const options = useQuery({
    queryKey: queryKeys.sales.sampleChallans(sample.party.id),
    queryFn: ({ signal }) => fetchChallansForSample(sample.party.id, signal),
    enabled: isOpen,
  });
  const [chosen, setChosen] = useState<string | null>(sample.challan_id);
  const [error, setError] = useState<string | undefined>();

  const save = async (challanId: string | null) => {
    const outcome = await commands.run(challanId ? "link" : "unlink", [sample.version, challanId], (key) => linkSampleChallan(sample, challanId, key), {
      done: challanId ? "Challan linked" : "Challan unlinked",
      failed: "The challan link did not change",
      conflictMessage: "This sample changed since you opened it. The latest version is showing.",
    });
    if (outcome.ok || outcome.conflict) onOpenChange(false);
    else setError(outcome.fieldErrors.challan_id);
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Delivery challan for this sample"
      description="Issuing the challan marks the sample as dispatched. Linking a challan that is already issued dispatches it now."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          {sample.challan_id ? (
            <Button variant="secondary" loading={commands.pending === "unlink"} isDisabled={Boolean(commands.offline)} onPress={() => void save(null)}>
              Unlink challan
            </Button>
          ) : null}
          <Button loading={commands.pending === "link"} isDisabled={Boolean(commands.offline) || !chosen || chosen === sample.challan_id} onPress={() => void save(chosen)}>
            Link challan
          </Button>
        </>
      }
    >
      {options.isPending ? (
        <LoadingBlock label="Loading challans for this customer" lines={2} />
      ) : options.isError ? (
        <ErrorBlock error={options.error} what="Challans for this customer" onRetry={() => void options.refetch()} />
      ) : options.data.length === 0 ? (
        <p className="t-body-sm text-ink-3">There is no draft or issued sample or outward challan for {sample.party.display_name} that you can see. Create one under Challans first.</p>
      ) : (
        <Select
          label="Challan"
          placeholder="Choose a draft or issued challan"
          options={options.data.map((challan) => ({
            value: challan.id,
            label: challan.challan_number,
            description: `${humanise(challan.challan_type)} · ${humanise(challan.status)} · ${challan.challan_date}`,
          }))}
          value={chosen}
          onChange={(value) => {
            setChosen(value);
            setError(undefined);
          }}
          error={error}
        />
      )}
    </Modal>
  );
}
