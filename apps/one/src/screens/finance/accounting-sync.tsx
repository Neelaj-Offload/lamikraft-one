"use client";

import { useEffect, useMemo, useRef } from "react";
import { journalHref, reconcileExport, runExport, verifyTaxProfile, type ExportRead, type TaxProfile } from "@/features/finance/api";
import { useFinanceCommand } from "@/features/finance/use-finance-command";
import { queryKeys } from "@/lib/api/query-keys";
import { ADAPTER_LABEL, exceptionCodeText, humanise, RECONCILIATION, useAccountingExports, useAccountingStatus, useFinanceSummary, useTaxProfiles } from "~/data/finance";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, Code, CountUp, DataTable, DateText, EmptyState, GlassPanel, Skeleton, StatTile, toast, type Column } from "~/ui";
import { DemoBadge, Percent, stagger, StatusBadge } from "./parts";

const FAILED = "That did not go through";
const plural = (count: number, one: string, many: string) => (count === 1 ? `1 ${one}` : `${count} ${many}`);

/**
 * The hand-off to accounting: what is waiting, the exports so far (download the journal, reconcile a
 * simulated one) and the tax profiles every invoice depends on. No accounting system is connected:
 * the CSV adapter writes a journal file and the Demo adapter only simulates an acknowledgement.
 */
export function AccountingSync({ exportId }: { exportId: string | null }) {
  const summary = useFinanceSummary();
  const status = useAccountingStatus();
  const exports = useAccountingExports();
  const key = useMemo(() => queryKeys.finance.exports(), []);
  const { run, pending, offline } = useFinanceCommand<null>(key);
  const canRun = Boolean(summary.data?.capabilities?.run_export?.allowed);
  const canVerify = Boolean(summary.data?.capabilities?.verify_tax_profile?.allowed);

  const start = (adapter: "csv" | "demo") =>
    void run(adapter, (k) => runExport(adapter, k), {
      failed: FAILED,
      write: (result) => {
        if (result.status === "completed") toast.success(`Export ${result.export_number} is done`, { description: plural(result.document_count, "document handed over.", "documents handed over.") });
        else toast.error(`Export ${result.export_number} failed`, { description: exceptionCodeText(result.error_code ?? "") });
        return null;
      },
    });

  return (
    <Page>
      <PageHeader
        eyebrow={
          <span className="inline-flex items-center gap-2">
            Finance <DemoBadge />
          </span>
        }
        title="Accounting sync"
        lead="Hand issued invoices and credit notes to accounting as a journal, then reconcile what came back."
        actions={
          canRun ? (
            <>
              <Button iconLeft="download" loading={pending === "csv"} isDisabled={Boolean(offline)} onPress={() => start("csv")}>
                Export CSV journal
              </Button>
              <Button variant="secondary" iconLeft="refresh" loading={pending === "demo"} isDisabled={Boolean(offline)} onPress={() => start("demo")}>
                Run a Demo export
              </Button>
            </>
          ) : null
        }
      />

      <Banner tone="cobalt" icon="info" title="No accounting system is connected.">
        The CSV export writes a journal your accountant imports. The Demo export records a simulated acknowledgement and posts nothing anywhere.
      </Banner>
      {offline ? (
        <Banner tone="amber" title="You are offline.">
          Exports and verifications work again once the connection is back.
        </Banner>
      ) : null}

      {status.isError ? (
        <ErrorBlock error={status.error} what="The accounting status" onRetry={() => void status.refetch()} />
      ) : (
        <>
          <div className="tiles" role="group" aria-label="Accounting at a glance">
            <GlassPanel className="rise" style={stagger(1)}>
              <StatTile
                label="Waiting to export"
                value={status.data ? <CountUp value={status.data.pending_documents} /> : <Skeleton width={44} height={32} />}
                foot={status.data ? "Issued documents not yet handed over" : undefined}
                dot={Boolean(status.data?.pending_documents)}
              />
            </GlassPanel>
            <GlassPanel className="rise" style={stagger(2)}>
              <StatTile
                label="Account codes"
                value={status.data ? (status.data.mapping_complete ? "All set" : `${status.data.missing_mapping.length} missing`) : <Skeleton width={96} height={32} />}
                foot={status.data ? (status.data.mapping_complete ? "Every document can be posted" : "Documents stay blocked until they are set") : undefined}
                dot={status.data ? !status.data.mapping_complete : false}
              />
            </GlassPanel>
            <GlassPanel className="rise" style={stagger(3)}>
              <StatTile
                label="Connection"
                value={status.data ? <span className="t-h3">{status.data.label}</span> : <Skeleton width={120} height={28} />}
                foot={status.data ? "Simulated. Nothing is posted anywhere." : undefined}
              />
            </GlassPanel>
          </div>
          {status.data && !status.data.mapping_complete ? (
            <Banner tone="amber" title="Some account codes are not set.">
              Documents that need them are blocked from every export until they are: {status.data.missing_mapping.map((code) => humanise(code).toLowerCase()).join(", ")}.
            </Banner>
          ) : null}
        </>
      )}

      <PageSection title="Exports" description="The latest 20, newest first. Download a journal to import it, or reconcile a simulated one." index={1}>
        {exports.isError ? (
          <ErrorBlock error={exports.error} what="The exports" onRetry={() => void exports.refetch()} />
        ) : (
          <GlassPanel padding="none" className="min-w-0">
            <DataTable
              label="Accounting exports"
              columns={exportColumns({ canRun, pending, offline, onReconcile: (x) => void run(`rec:${x.id}`, (k) => reconcileExport(x.id, k), { done: "Reconciliation recorded", failed: FAILED }) })}
              rows={exports.data?.items ?? []}
              rowKey={(x) => x.id}
              selectedKey={exportId ?? undefined}
              loading={exports.isPending}
              skeletonRows={4}
              empty={
                <EmptyState
                  compact
                  icon="send"
                  title="Nothing has been exported yet"
                  text={canRun ? "Export the CSV journal to hand every issued document to your accountant in one file." : "Once someone in finance runs an export, it is listed here."}
                  actions={
                    canRun ? (
                      <Button variant="secondary" size="sm" iconLeft="download" loading={pending === "csv"} isDisabled={Boolean(offline)} onPress={() => start("csv")}>
                        Export CSV journal
                      </Button>
                    ) : undefined
                  }
                />
              }
            />
          </GlassPanel>
        )}
      </PageSection>

      <TaxProfiles canVerify={canVerify} />
    </Page>
  );
}

function exportColumns({
  canRun,
  pending,
  offline,
  onReconcile,
}: {
  canRun: boolean;
  pending: string | null;
  offline: string | null;
  onReconcile: (x: ExportRead) => void;
}): Column<ExportRead>[] {
  return [
    {
      key: "batch",
      header: "Batch",
      primary: true,
      cell: (x) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{x.export_number}</Code>
          <span className="t-caption text-ink-3">
            <DateText value={x.created_at} style="dayTime" />
            {x.actor?.display_name ? ` · ${x.actor.display_name}` : ""}
          </span>
        </span>
      ),
    },
    {
      key: "adapter",
      header: "Adapter",
      cell: (x) => (
        <span className="inline-flex flex-wrap items-center gap-2">
          {x.simulated ? "Demo" : (ADAPTER_LABEL[x.adapter] ?? x.adapter)}
          {x.simulated ? <DemoBadge /> : null}
        </span>
      ),
    },
    {
      key: "status",
      header: "Result",
      cell: (x) =>
        x.status === "completed" ? (
          <Badge tone="leaf" icon="check">
            Completed
          </Badge>
        ) : (
          <span className="flex min-w-0 flex-col items-start gap-1">
            <Badge tone="ember" icon="xCircle">
              Failed
            </Badge>
            {x.error_code ? <span className="t-caption text-ink-3">{exceptionCodeText(x.error_code)}</span> : null}
          </span>
        ),
    },
    {
      key: "documents",
      header: "Documents",
      numeric: true,
      cell: (x) => (
        <span className="flex flex-col items-end gap-0.5">
          <span className="lk-tnum t-label text-ink">{x.document_count}</span>
          {x.blocked_count > 0 ? <span className="t-caption text-amber-text">{x.blocked_count} blocked</span> : null}
        </span>
      ),
    },
    { key: "reconciliation", header: "Reconciliation", cell: (x) => <StatusBadge look={RECONCILIATION[x.reconciliation_status] ?? { label: x.reconciliation_status, tone: "neutral" }} /> },
    {
      key: "actions",
      header: <span className="lk-sr-only">Actions</span>,
      mobileLabel: "Actions",
      cell: (x) =>
        x.status === "completed" && canRun ? (
          <span className="flex flex-wrap items-center gap-2">
            <ButtonLink external href={journalHref(x.id)} download variant="ghost" size="sm" iconLeft="download">
              Journal
            </ButtonLink>
            {x.simulated ? (
              <Button variant="secondary" size="sm" loading={pending === `rec:${x.id}`} isDisabled={Boolean(offline)} onPress={() => onReconcile(x)}>
                Reconcile
              </Button>
            ) : (
              <span className="t-caption text-ink-3">Reconciled on the accounting side</span>
            )}
          </span>
        ) : null,
    },
  ];
}

// ---------------------------------------------------------------------------------------------
// Tax profiles: entered with a source, verified by a second person

function TaxProfiles({ canVerify }: { canVerify: boolean }) {
  const key = useMemo(() => queryKeys.finance.taxProfiles(), []);
  const query = useTaxProfiles();
  const { run, pending, offline } = useFinanceCommand<TaxProfile[]>(key);
  const anchor = useRef<HTMLDivElement>(null);
  const loaded = query.isSuccess;

  // Blockers link here (#tax-profiles); the list renders after load, so bring it into view once it is there.
  useEffect(() => {
    if (loaded && window.location.hash === "#tax-profiles") anchor.current?.scrollIntoView({ block: "start" });
  }, [loaded]);

  const columns: Column<TaxProfile>[] = [
    {
      key: "profile",
      header: "Profile",
      primary: true,
      cell: (p) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{p.code}</Code>
          <span className="t-caption text-ink-3">{p.name}</span>
        </span>
      ),
    },
    { key: "rate", header: "Rate", numeric: true, cell: (p) => <Percent value={p.rate_percent} className="t-label text-ink" /> },
    { key: "einvoice", header: "E-invoicing", cell: (p) => (p.requires_e_invoice ? "Needed" : "Not needed") },
    {
      key: "source",
      header: "Source",
      hideOnMobile: true,
      cell: (p) => (
        <span className="t-body-sm block max-w-xs truncate text-ink-2" title={p.source_reference}>
          {p.source_reference}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (p) =>
        p.status === "verified" ? (
          <span className="flex min-w-0 flex-col items-start gap-1">
            <Badge tone="leaf" icon="badgeCheck">
              Verified
            </Badge>
            {p.verified_by?.display_name ? <span className="t-caption text-ink-3">by {p.verified_by.display_name}</span> : null}
          </span>
        ) : canVerify && p.capabilities?.verify?.allowed ? (
          <Button
            variant="secondary"
            size="sm"
            iconLeft="check"
            loading={pending === p.id}
            isDisabled={Boolean(offline)}
            onPress={() => void run(p.id, (k) => verifyTaxProfile(p, k), { done: "Tax profile verified", failed: FAILED })}
          >
            Verify
          </Button>
        ) : (
          <span className="flex min-w-0 flex-col items-start gap-1">
            <Badge tone="amber" dot>
              Not yet verified
            </Badge>
            {p.author?.display_name ? <span className="t-caption text-ink-3">Entered by {p.author.display_name}</span> : null}
          </span>
        ),
    },
  ];

  return (
    <div id="tax-profiles" ref={anchor} className="scroll-mt-24">
      <PageSection
        title="Tax profiles"
        description="Rates your business entered, each with its source, and checked by a second person. Lamikraft One never invents a rate."
        index={2}
      >
        {query.isError ? (
          <ErrorBlock error={query.error} what="The tax profiles" onRetry={() => void query.refetch()} />
        ) : (
          <GlassPanel padding="none" className="min-w-0">
            <DataTable
              label="Tax profiles"
              columns={columns}
              rows={query.data ?? []}
              rowKey={(p) => p.id}
              loading={query.isPending}
              skeletonRows={3}
              empty={<EmptyState compact icon="percent" title="No tax profile has been entered" text="Invoices stay drafts until a profile is entered and verified by a second person." />}
            />
          </GlassPanel>
        )}
      </PageSection>
    </div>
  );
}
