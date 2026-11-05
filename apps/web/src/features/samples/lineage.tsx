"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Badge, StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { LocalDate } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { Select } from "@/components/ui/select";
import { ErrorState, Loading } from "@/components/ui/states";
import { useResourceCommand } from "@/features/sales/resource-command";
import { queryKeys } from "@/lib/api/query-keys";
import { commercialMessages as c } from "@/messages/commercial";
import { fetchChallansForSample, fetchSampleLineage, linkSampleChallan, type LineageNode, type Sample, type SampleLineage } from "./api";

const l = c.samples.lineage;
const ch = c.samples.challan;

const ORDER = ["custom_product", "spec_revision", "quote", "challan", "product"] as const;

/** The lineage rows in reading order: what the sample was made from, then how it travelled. Pure (unit-tested). */
export function lineageRows(view: SampleLineage): { kind: (typeof ORDER)[number]; node: LineageNode | null; missing: boolean }[] {
  const missing = new Set<string>(view.missing);
  return ORDER.flatMap((kind) => {
    const node = view[kind] ?? null;
    if (node === null && !missing.has(kind)) return [];
    return [{ kind, node, missing: node === null }];
  });
}

function NodeValue({ node }: { node: LineageNode | null }) {
  if (node === null) return <span className="text-ink-muted">{l.notLinked}</span>;
  if (node.state === "not_visible") return <span className="text-ink-muted">{l.notVisible}</span>;
  const label = node.label ?? "";
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {node.path ? <Link href={node.path}>{label}</Link> : <span>{label}</span>}
      {node.title ? <span className="text-ink-muted">{node.title}</span> : null}
      {node.status ? <Badge>{c.human(node.status)}</Badge> : null}
      {node.facts?.origin === "promoted" ? <span className="text-sm text-ink-muted">{l.promoted}</span> : null}
    </span>
  );
}

/**
 * The sample's lineage (`GET /sales/samples/{id}/lineage`): custom product and spec revision, quote, delivery challan
 * and catalogue product, each through its own read scope (a link the viewer cannot see says so instead of naming it),
 * sibling samples and a dated timeline. A requested sample's owner links the challan that will carry it.
 */
export function SampleLineageSection({ sample }: { sample: Sample }) {
  const query = useQuery({ queryKey: queryKeys.sales.sampleLineage(sample.id), queryFn: ({ signal }) => fetchSampleLineage(sample.id, signal) });
  const canLink = sample.capabilities.link_challan?.allowed === true;
  const [open, setOpen] = useState(false);
  return (
    <section aria-label={l.title} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-[650] text-ink">{l.title}</h2>
          <p className="text-sm text-ink-muted">{l.intro}</p>
        </div>
        {canLink ? <Button onPress={() => setOpen(true)}>{sample.challan_id ? ch.change : ch.link}</Button> : null}
      </div>
      {query.isPending ? (
        <Loading label={l.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={l.loading} onRetry={() => void query.refetch()} />
      ) : (
        <LineageView view={query.data} />
      )}
      {canLink ? <ChallanLinkDialog sample={sample} isOpen={open} onOpenChange={setOpen} /> : null}
    </section>
  );
}

function LineageView({ view }: { view: SampleLineage }) {
  const rows = lineageRows(view);
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-[12rem_1fr]">
        {rows.map((r) => (
          <div key={r.kind} className="contents">
            <dt className="text-sm text-ink-muted">{l.kinds[r.kind]}</dt>
            <dd>
              <NodeValue node={r.node} />
            </dd>
          </div>
        ))}
      </dl>
      {view.related_samples.length ? (
        <div className="flex flex-col gap-1">
          <h3 className="font-[650] text-ink">{l.related}</h3>
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            {view.related_samples.map((s) => (
              <li key={s.id ?? s.label}>{s.path ? <Link href={s.path}>{s.label}</Link> : s.label}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="flex flex-col gap-1">
        <h3 className="font-[650] text-ink">{l.timeline}</h3>
        {view.timeline.length ? (
          <ol className="flex flex-col gap-1">
            {view.timeline.map((e, i) => (
              <li key={`${e.kind}-${i}`} className="flex flex-wrap gap-3">
                <LocalDate value={e.on} className="tabular text-ink-muted" />
                <span className="text-ink">{e.label}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-ink-muted">{l.noTimeline}</p>
        )}
      </div>
    </div>
  );
}

function ChallanLinkDialog({ sample, isOpen, onOpenChange }: { sample: Sample; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const keys = useMemo(() => [queryKeys.sales.sample(sample.id), queryKeys.sales.sampleLineage(sample.id), ["sales", "samples"]], [sample.id]);
  const commands = useResourceCommand(`sample-challan:${sample.id}`, keys);
  const options = useQuery({
    queryKey: queryKeys.sales.sampleChallans(sample.party.id),
    queryFn: ({ signal }) => fetchChallansForSample(sample.party.id, signal),
    enabled: isOpen,
  });
  const [chosen, setChosen] = useState<string | null>(sample.challan_id);
  const [error, setError] = useState<string | undefined>();
  const save = async (challanId: string | null) => {
    const label = challanId ? ch.save : ch.unlink;
    const outcome = await commands.run(challanId ? "link" : "unlink", [sample.version, challanId], (key) => linkSampleChallan(sample, challanId, key), {
      done: challanId ? ch.linked : ch.unlinked,
      failed: ch.failed,
      conflictMessage: c.common.conflict,
    });
    if (outcome.ok) onOpenChange(false);
    else setError(outcome.fieldErrors.challan_id ?? (outcome.conflict ? undefined : label));
  };
  return (
    <Dialog
      title={ch.title}
      description={ch.intro}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {c.common.cancel}
          </Button>
          {sample.challan_id ? (
            <Button variant="secondary" isPending={commands.pending === "unlink"} {...unavailableWhen(commands.offline)} onPress={() => void save(null)}>
              {ch.unlink}
            </Button>
          ) : null}
          <Button variant="primary" isPending={commands.pending === "link"} {...unavailableWhen(commands.offline ?? (!chosen || chosen === sample.challan_id ? ch.pickerPlaceholder : null))} onPress={() => void save(chosen)}>
            {ch.save}
          </Button>
        </>
      )}
    >
      {options.isPending ? (
        <Loading label={ch.loading} />
      ) : options.isError ? (
        <ErrorState error={options.error} what={ch.loading} onRetry={() => void options.refetch()} />
      ) : options.data.length === 0 ? (
        <p className="text-ink-muted">{ch.none}</p>
      ) : (
        <div className="flex flex-col gap-3">
          <Select
            label={ch.picker}
            placeholder={ch.pickerPlaceholder}
            options={options.data.map((x) => ({ id: x.id, label: ch.option(x.challan_number, c.human(x.status), x.challan_date) }))}
            value={chosen}
            onChange={(v) => {
              setChosen(v);
              setError(undefined);
            }}
            errorMessage={error}
          />
          {chosen ? (
            <p className="text-sm text-ink-muted">
              <StatusPill tone="info">{c.human(options.data.find((x) => x.id === chosen)?.challan_type ?? "")}</StatusPill>
            </p>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}
