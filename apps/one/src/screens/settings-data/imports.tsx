"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { IMPORT_TYPES, runDemoReset, type JobSummary } from "@/features/imports/api";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { DEMO_DATA_DELETE, IMPORTS_READ, IMPORTS_RUN, useDemoReset, useImportJobs } from "~/data/settings-data";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import { Badge, Button, ButtonLink, ChipGroup, ChipLink, DataTable, DateText, EmptyState, GlassPanel, TextField, toast, type Column } from "~/ui";
import { IMPORT_PAGE_SIZE, IMPORT_TYPE_LABEL, importHref, importsHref, ImportStatus, importTypeLabel } from "./imports-shared";
import { OffsetPager, Quiet, SETTINGS_CRUMBS } from "./shared";

/**
 * Every spreadsheet brought into Lamikraft One, newest first, filtered by type in the URL. Below
 * the list, for demo companies only, the reset that clears the demo catalogue.
 */

function excludedOf(job: Pick<JobSummary, "counts">): number {
  return (job.counts.rejected ?? 0) + (job.counts.quarantined ?? 0);
}

function columns(locale: string): Column<JobSummary>[] {
  const count = (value: number) => <span className="lk-tnum">{formatCount(value, locale)}</span>;
  return [
    {
      key: "file",
      header: "File",
      primary: true,
      cell: (job) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="t-label text-ink [overflow-wrap:anywhere]" title={job.file_name}>
            {job.file_name}
          </span>
          <span className="t-caption text-ink-3">{importTypeLabel(job.import_type)}</span>
        </span>
      ),
    },
    { key: "status", header: "Status", mobileLabel: "Status", cell: (job) => <ImportStatus status={job.status} size="sm" /> },
    { key: "rows", header: "Rows", mobileLabel: "Rows", numeric: true, cell: (job) => count(job.row_count) },
    { key: "written", header: "Written", mobileLabel: "Written", numeric: true, cell: (job) => count(job.counts.committed ?? 0) },
    {
      key: "excluded",
      header: "Left out",
      mobileLabel: "Left out",
      numeric: true,
      cell: (job) => {
        const excluded = excludedOf(job);
        return excluded > 0 ? <span className="lk-tnum text-amber-text">{formatCount(excluded, locale)}</span> : count(0);
      },
    },
    {
      key: "started",
      header: "Started",
      mobileLabel: "Started",
      cell: (job) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <DateText value={job.created_at} style="dayTime" />
          <span className="t-caption text-ink-3">{job.created_by_name ?? <Quiet>Unknown</Quiet>}</span>
        </span>
      ),
    },
  ];
}

const RESET_REASON: Record<string, string> = {
  not_a_demo_company: "This is not a demo company, so its catalogue can never be cleared from here.",
  demo_data_referenced: "Price lists, quotations or other records still use the demo products. Clear those first.",
};

/** Demo companies only, for holders of the demo-data permission. The typed phrase and a fresh preview token are both required; the server checks again. */
function DemoReset() {
  const { permissionKeys, zone } = useSession();
  const queryClient = useQueryClient();
  const allowed = permissionKeys.has(DEMO_DATA_DELETE);
  const preview = useDemoReset(allowed);
  const [phrase, setPhrase] = useState("");
  const reset = useMutation({
    mutationFn: () => runDemoReset(preview.data?.token ?? "", phrase),
    onSuccess: (result) => {
      for (const key of invalidationMap["imports.changed"]) void queryClient.invalidateQueries({ queryKey: key });
      const total = Object.values(result.deleted).reduce((sum, value) => sum + value, 0);
      toast.success("Demo catalogue cleared", { description: `${formatCount(total, zone.locale)} rows removed.` });
      setPhrase("");
    },
    onError: (error) =>
      toast.error("The demo catalogue was not cleared", {
        description:
          error instanceof ProblemError && error.code === "reauth_required"
            ? "Sign in again, then clear it."
            : error instanceof ProblemError
              ? (error.detail ?? error.title)
              : "Check your connection and try again.",
      }),
  });

  if (!allowed || !preview.data) return null;
  const data = preview.data;
  const matches = phrase.trim() === data.phrase;
  const counts = Object.entries(data.counts);

  return (
    <GlassPanel
      as="section"
      padding="lg"
      className="rise"
      eyebrow="Demo data"
      title="Clear the demo catalogue"
      titleAs="h2"
      action={<Badge tone="amber" size="sm">Demo</Badge>}
    >
      <div className="flex min-w-0 flex-col gap-5">
        <p className="t-body text-ink-2">Removes the demo catalogue counted below from {data.company_name}, so you can start again from your own sheets. It cannot be undone.</p>
        {counts.length > 0 ? (
          <ul className="flex list-none flex-wrap gap-2" aria-label="What would be removed">
            {counts.map(([table, count]) => (
              <li key={table}>
                <Badge size="sm">
                  <span className="lk-tnum">{formatCount(count, zone.locale)}</span> {table.replace(/^catalogue_|^imports_/, "").replace(/_/g, " ")}
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}
        {data.allowed ? (
          <form
            className="flex min-w-0 flex-wrap items-end gap-3"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              if (matches && !reset.isPending) reset.mutate();
            }}
          >
            <TextField
              className="min-w-0 flex-1 basis-64"
              label={`Type “${data.phrase}” to confirm`}
              value={phrase}
              onChange={setPhrase}
              autoComplete="off"
              help={phrase && !matches ? "Type the phrase exactly as shown." : undefined}
            />
            <Button type="submit" variant="danger" iconLeft="trash" loading={reset.isPending} isDisabled={!matches}>
              Clear demo catalogue
            </Button>
          </form>
        ) : (
          <p className="t-body-sm text-ink-2">{RESET_REASON[data.reason_code ?? ""] ?? "Clearing is not available right now."}</p>
        )}
      </div>
    </GlassPanel>
  );
}

export function Imports({ importType, offset }: { importType: string | null; offset: number }) {
  const { permissionKeys, zone } = useSession();
  const canRead = permissionKeys.has(IMPORTS_READ);
  const canRun = permissionKeys.has(IMPORTS_RUN);
  const jobs = useImportJobs(importType, offset, canRead);
  const data = jobs.data;

  const header = (
    <PageHeader
      breadcrumb={SETTINGS_CRUMBS}
      title="Imports"
      lead="Bring products, prices, packaging, specifications and media in from spreadsheets. Nothing is written until you review it and commit."
      actions={
        canRead ? (
          <>
            {canRun ? (
              <ButtonLink href="/settings/imports/new" iconLeft="upload">
                Start an import
              </ButtonLink>
            ) : null}
            <ButtonLink href="/settings/lookups" variant="secondary" iconLeft="database">
              Lookup reference
            </ButtonLink>
          </>
        ) : undefined
      }
    />
  );

  if (!canRead) {
    return (
      <Page>
        {header}
        <NotPermitted what="Imports" icon="upload" />
      </Page>
    );
  }

  return (
    <Page>
      {header}
      <ChipGroup label="Filter by type">
        <ChipLink href={importsHref(null)} selected={!importType} scroll={false}>
          All types
        </ChipLink>
        {IMPORT_TYPES.map((type) => (
          <ChipLink key={type} href={importsHref(type)} selected={importType === type} scroll={false}>
            {IMPORT_TYPE_LABEL[type]}
          </ChipLink>
        ))}
      </ChipGroup>

      {jobs.isError && !data ? (
        <ErrorBlock error={jobs.error} what="The import history" onRetry={() => void jobs.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Import history"
            columns={columns(zone.locale)}
            rows={data?.items ?? []}
            rowKey={(job) => job.id}
            rowHref={(job) => importHref(job.id)}
            loading={jobs.isPending}
            skeletonRows={6}
            empty={
              importType ? (
                <EmptyState
                  compact
                  icon="search"
                  title={`No ${importTypeLabel(importType).toLowerCase()} import yet`}
                  text="Choose all types to see every import."
                  actions={
                    <ButtonLink href={importsHref(null)} variant="secondary" size="sm">
                      Show all types
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="spreadsheet"
                  title="Bring in your first spreadsheet"
                  text="Start with the categories, then the products. Prices, packaging, specifications and media follow."
                  actions={
                    canRun ? (
                      <ButtonLink href="/settings/imports/new" variant="secondary" iconLeft="upload">
                        Start an import
                      </ButtonLink>
                    ) : undefined
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      {data ? <OffsetPager data={data} noun="imports" label="Import pages" fallbackLimit={IMPORT_PAGE_SIZE} hrefFor={(next) => importsHref(importType, next)} /> : null}

      <DemoReset />
    </Page>
  );
}
