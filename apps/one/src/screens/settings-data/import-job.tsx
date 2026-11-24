"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  jobCommand,
  recheck,
  rollback,
  saveMapping,
  stepOf,
  type IssueRead,
  type JobDetail,
  type PreviewRead,
  type RowRead,
  type Step,
} from "@/features/imports/api";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { useImportIssues, useImportJob, useImportPreview, useImportRows, useImportTypes, useRollbackPlan } from "~/data/settings-data";
import { Page, RecordHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import {
  Banner,
  Button,
  ButtonLink,
  Checkbox,
  DataTable,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  Icon,
  IconButton,
  Menu,
  Modal,
  ProgressBar,
  Select,
  SkeletonText,
  StatRow,
  StatTile,
  TabPanel,
  Tabs,
  TextLink,
  toast,
  type Column,
} from "~/ui";
import { IMPORTS_CRUMBS, importHref, ImportStatus, importTypeLabel } from "./imports-shared";
import { asRoute, Mono, OffsetPager, Quiet, shortSha } from "./shared";

/**
 * One import, as the steps it moves through: map the columns, let the server check every row,
 * review what would change, commit, see the result. The job is polled while the server works.
 */

const STEPS: readonly { id: Step; title: string }[] = [
  { id: "mapping", title: "Map" },
  { id: "validating", title: "Check" },
  { id: "review", title: "Review" },
  { id: "committing", title: "Commit" },
  { id: "result", title: "Result" },
];

const ROW_PAGE = 50;
const none = <Quiet>None</Quiet>;
const problemText = (error: unknown, fallback: string) => (error instanceof ProblemError ? (error.detail ?? error.title) : fallback);

function StepIndicator({ step }: { step: Step }) {
  const at = STEPS.findIndex((entry) => entry.id === step);
  return (
    <ol className="m-0 grid list-none grid-cols-5 gap-2 p-0" aria-label="Steps">
      {STEPS.map((entry, index) => {
        const current = index === at;
        const done = index < at || (step === "result" && current);
        return (
          <li
            key={entry.id}
            aria-current={current ? "step" : undefined}
            className={`flex min-w-0 flex-col items-center gap-2 rounded-lg border px-2 py-3 sm:flex-row sm:px-4 ${current ? "border-line-strong bg-surface shadow-panel" : "border-line"}`}
          >
            <span
              className={`t-label lk-tnum flex size-8 flex-none items-center justify-center rounded-pill ${
                done ? "bg-leaf-soft text-leaf-text" : current ? "bg-inverse text-on-inverse" : "bg-sand-soft text-ink-2"
              }`}
              aria-hidden="true"
            >
              {done ? <Icon name="check" size={16} /> : index + 1}
            </span>
            <span className="flex min-w-0 flex-col items-center sm:items-start">
              <span className="t-caption hidden text-ink-3 sm:block">Step {index + 1}</span>
              <span className={`t-label truncate ${current ? "text-ink" : "text-ink-2"}`}>
                {entry.title}
                <span className="lk-sr-only">{done ? ", done" : current ? ", current" : ""}</span>
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

// ---- step 1: mapping ----

const IGNORE = "__ignore__";

function previewColumns(preview: PreviewRead): Column<Record<string, string | number>>[] {
  return [
    { key: "__row", header: "Row", numeric: true, width: "72px", cell: (row) => <span className="lk-tnum">{row.row_number}</span> },
    ...preview.headers.map((header) => ({
      key: header.original,
      header: header.original,
      cell: (row: Record<string, string | number>) => {
        const value = row[header.original];
        return value === undefined || value === "" ? none : <span className="[overflow-wrap:anywhere]">{String(value)}</span>;
      },
    })),
  ];
}

function MappingStep({ detail, fields }: { detail: JobDetail; fields: string[] }) {
  const queryClient = useQueryClient();
  const preview = useImportPreview(detail.id);
  const [mapping, setMapping] = useState(detail.mapping);
  const [blankClear, setBlankClear] = useState(detail.options.blank_cells === "clear");
  const canValidate = detail.capabilities.validate?.allowed === true;
  const save = useMutation({
    mutationFn: async () => {
      const saved = await saveMapping(detail, mapping, { ...detail.options, blank_cells: blankClear ? "clear" : "ignore" });
      return jobCommand(saved, "validate");
    },
    onSuccess: (next) => queryClient.setQueryData(queryKeys.imports.job(detail.id), next),
    onError: (error) => toast.error("The mapping was not saved", { description: problemText(error, "Check your connection and try again.") }),
  });

  if (preview.isPending) return <LoadingBlock lines={8} label="Reading the file" />;
  if (preview.isError) return <ErrorBlock error={preview.error} what="The preview" onRetry={() => void preview.refetch()} />;
  const data = preview.data;

  return (
    <div className="stack">
      {data.same_file_jobs.length ? (
        <Banner tone="cobalt" title="You have imported this file before.">
          {data.same_file_jobs.length === 1 ? "There is 1 earlier import of it." : `There are ${data.same_file_jobs.length} earlier imports of it.`} Importing it again is safe: unchanged rows are skipped.
        </Banner>
      ) : null}
      {data.duplicate_keys.length ? (
        <Banner tone="amber" title="Some keys appear more than once in the file.">
          <ul className="mt-2 flex list-none flex-col gap-1">
            {data.duplicate_keys.slice(0, 20).map((duplicate) => (
              <li key={duplicate.key}>
                <Mono>{duplicate.key}</Mono> on rows {duplicate.row_numbers.join(", ")}:{" "}
                {duplicate.identical ? "identical, so the extra copies are skipped." : "different values, so they are held back for a look."}
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}

      <GlassPanel
        as="section"
        padding="lg"
        className="rise"
        title="Match the columns"
        titleAs="h2"
        eyebrow={`${data.headers.length} columns in the file`}
      >
        <div className="flex min-w-0 flex-col gap-5">
          <p className="t-body text-ink-2">Tell Lamikraft One what each column holds. A column you ignore stays in the source file and is not imported.</p>
          {data.unmapped_required.length ? (
            <Banner tone="ember" title="Still needed:">
              {data.unmapped_required.join(", ")}. Match a column to each before you check the rows.
            </Banner>
          ) : null}
          <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.headers.map((header) => (
              <Select
                key={header.original}
                label={header.original}
                help={header.normalised !== header.original ? `Read as ${header.normalised}` : undefined}
                options={[{ value: IGNORE, label: "Ignore this column" }, ...fields.map((field) => ({ value: field, label: field }))]}
                value={mapping[header.original] ?? IGNORE}
                onChange={(value) => setMapping((current) => ({ ...current, [header.original]: value === IGNORE ? null : value }))}
              />
            ))}
          </div>
          <Checkbox
            label="Blank cells clear the value already saved"
            description="Off: a blank cell leaves the saved value as it is."
            isSelected={blankClear}
            onChange={setBlankClear}
          />
          <div className="flex flex-wrap items-center justify-end gap-3">
            {canValidate ? null : <span className="t-body-sm text-ink-3">This import can no longer be changed.</span>}
            <Button onPress={() => save.mutate()} loading={save.isPending} isDisabled={!canValidate} iconRight="arrowRight">
              Save mapping and check rows
            </Button>
          </div>
        </div>
      </GlassPanel>

      <GlassPanel as="section" padding="none" className="rise" title="First rows" titleAs="h2" eyebrow={`Of ${data.total_rows} in the file`}>
        <DataTable
          label="First rows of the file"
          columns={previewColumns(data)}
          rows={data.rows}
          rowKey={(row) => String(row.row_number)}
          dense
          mobile="scroll"
          empty={<EmptyState compact icon="spreadsheet" title="The file has no rows" text="Check that the sheet holds data under its header row, then upload it again." />}
        />
      </GlassPanel>
    </div>
  );
}

// ---- steps 2 and 4: the server is working ----

function Working({ detail, step }: { detail: JobDetail; step: "validating" | "committing" }) {
  const { zone } = useSession();
  const done = detail.progress.done ?? 0;
  const percent = detail.row_count > 0 ? Math.min(100, Math.round((done / detail.row_count) * 100)) : 0;
  return (
    <GlassPanel padding="lg" className="rise" role="status">
      <div className="flex min-w-0 flex-col gap-4">
        <p className="t-h3">{step === "validating" ? "Checking every row" : "Writing to the catalogue"}</p>
        <p className="t-body text-ink-2">
          {step === "validating" ? "Each row is checked against your catalogue. This page updates by itself." : "Rows are written in batches of 500. You can leave this page; the import carries on."}
        </p>
        {step === "committing" ? (
          <ProgressBar label="Rows written" value={percent} detail={`${formatCount(done, zone.locale)} of ${formatCount(detail.row_count, zone.locale)} rows`} />
        ) : (
          <SkeletonText lines={2} />
        )}
      </div>
    </GlassPanel>
  );
}

// ---- steps 3 and 5: review and result ----

const SEVERITY: Record<string, string> = { error: "Rejected", quarantine: "Held back", warning: "Warning", info: "Note" };
const SEVERITY_TONE: Record<string, string> = { error: "text-ember-text", quarantine: "text-amber-text", warning: "text-amber-text", info: "text-ink-2" };
const ROW_STATUSES = ["valid", "warning", "rejected", "quarantined", "duplicate_identical", "committed", "unchanged"] as const;
const ROW_STATUS: Record<string, string> = {
  valid: "Valid",
  warning: "Warning",
  rejected: "Rejected",
  quarantined: "Held back",
  duplicate_identical: "Identical copy",
  committed: "Written",
  unchanged: "Unchanged",
};
const ANY = "any";

const issueColumns: Column<IssueRead>[] = [
  { key: "row", header: "Row", numeric: true, width: "72px", mobileLabel: "Row", cell: (issue) => (issue.row_number === null ? none : <span className="lk-tnum">{issue.row_number}</span>) },
  {
    key: "message",
    header: "What is wrong",
    primary: true,
    cell: (issue) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="t-body-sm text-ink">{issue.message}</span>
        <Mono className="text-ink-3">{issue.code}</Mono>
      </span>
    ),
  },
  { key: "severity", header: "Kind", mobileLabel: "Kind", cell: (issue) => <span className={`t-label ${SEVERITY_TONE[issue.severity] ?? ""}`}>{SEVERITY[issue.severity] ?? issue.severity}</span> },
  { key: "column", header: "Column", mobileLabel: "Column", cell: (issue) => issue.column ?? none },
  { key: "value", header: "Value in the file", mobileLabel: "Value", cell: (issue) => (issue.raw_value ? <span className="[overflow-wrap:anywhere]">{issue.raw_value}</span> : none) },
];

function diffText(row: RowRead): string[] {
  if (!row.diff) return [];
  return Object.entries(row.diff).map(([field, [before, after]]) => `${field}: ${before ?? "empty"} → ${after ?? "empty"}`);
}

const rowColumns: Column<RowRead>[] = [
  { key: "row", header: "Row", numeric: true, width: "72px", mobileLabel: "Row", cell: (row) => <span className="lk-tnum">{row.row_number}</span> },
  { key: "key", header: "Key", primary: true, cell: (row) => (row.natural_key ? <Mono>{row.natural_key}</Mono> : none) },
  { key: "status", header: "Status", mobileLabel: "Status", cell: (row) => ROW_STATUS[row.status] ?? row.status.replace(/_/g, " ") },
  { key: "action", header: "Change", mobileLabel: "Change", cell: (row) => (row.action ? row.action.replace(/_/g, " ") : none) },
  {
    key: "diff",
    header: "Before and after",
    mobileLabel: "Before and after",
    cell: (row) => {
      const lines = diffText(row);
      return lines.length ? (
        <ul className="flex list-none flex-col gap-0.5">
          {lines.map((line) => (
            <li key={line} className="t-body-sm [overflow-wrap:anywhere]">
              {line}
            </li>
          ))}
        </ul>
      ) : (
        none
      );
    },
  },
];

function Issues({ detail }: { detail: JobDetail }) {
  const [severity, setSeverity] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const issues = useImportIssues(detail.id, severity, offset);
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-3">
        <Select
          label="Kind of issue"
          className="w-64 max-w-full"
          options={[{ value: ANY, label: "Every kind" }, ...Object.entries(SEVERITY).map(([value, label]) => ({ value, label }))]}
          value={severity ?? ANY}
          onChange={(value) => {
            setSeverity(value === ANY ? null : value);
            setOffset(0);
          }}
        />
        <ButtonLink external href={detail.report_url} download variant="secondary" iconLeft="download">
          Download the full report
        </ButtonLink>
      </div>
      {issues.isError && !issues.data ? (
        <ErrorBlock error={issues.error} what="The issues" onRetry={() => void issues.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Issues"
            columns={issueColumns}
            rows={issues.data?.items ?? []}
            rowKey={(issue) => issue.id}
            loading={issues.isPending}
            skeletonRows={5}
            empty={<EmptyState compact icon="checkCircle" title={severity ? "No issue of this kind" : "Every row passed"} text={severity ? "Choose every kind to see the rest." : "Nothing in the file needs a correction."} />}
          />
        </GlassPanel>
      )}
      {issues.data ? <OffsetPager data={issues.data} noun="issues" label="Issue pages" fallbackLimit={ROW_PAGE} onOffset={setOffset} /> : null}
    </div>
  );
}

function Rows({ detail }: { detail: JobDetail }) {
  const [status, setStatus] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const rows = useImportRows(detail.id, status, offset);
  return (
    <div className="stack">
      <Select
        label="Row status"
        className="w-64 max-w-full"
        options={[{ value: ANY, label: "Every status" }, ...ROW_STATUSES.map((value) => ({ value, label: ROW_STATUS[value] ?? value }))]}
        value={status ?? ANY}
        onChange={(value) => {
          setStatus(value === ANY ? null : value);
          setOffset(0);
        }}
      />
      {rows.isError && !rows.data ? (
        <ErrorBlock error={rows.error} what="The rows" onRetry={() => void rows.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Rows, before and after"
            columns={rowColumns}
            rows={rows.data?.items ?? []}
            rowKey={(row) => row.id}
            loading={rows.isPending}
            skeletonRows={5}
            empty={<EmptyState compact icon="list" title={status ? "No row has this status" : "No rows to show"} text={status ? "Choose every status to see the rest." : "The file had no rows to check."} />}
          />
        </GlassPanel>
      )}
      {rows.data ? <OffsetPager data={rows.data} noun="rows" label="Row pages" fallbackLimit={ROW_PAGE} onOffset={setOffset} /> : null}
    </div>
  );
}

function CommitPanel({ detail }: { detail: JobDetail }) {
  const queryClient = useQueryClient();
  const { zone } = useSession();
  const [acknowledged, setAcknowledged] = useState(false);
  const excluded = (detail.counts.rejected ?? 0) + (detail.counts.quarantined ?? 0);
  const commit = useMutation({
    mutationFn: () => jobCommand(detail, "commit", { acknowledge_excluded: acknowledged }),
    onSuccess: (next) => queryClient.setQueryData(queryKeys.imports.job(detail.id), next),
  });
  const conflict = commit.error ? conflictFromError(commit.error) : null;
  const canCommit = detail.capabilities.commit?.allowed === true;
  const blocked = !canCommit || (excluded > 0 && !acknowledged);
  const writes = (detail.counts.to_insert ?? 0) + (detail.counts.to_update ?? 0);

  return (
    <GlassPanel as="section" padding="lg" className="rise" title="Write it to the catalogue" titleAs="h2" eyebrow="Commit">
      <div className="flex min-w-0 flex-col gap-4">
        {conflict ? (
          <Banner
            tone="amber"
            title="This import changed while you were reviewing it."
            action={
              <Button
                variant="secondary"
                size="sm"
                iconLeft="refresh"
                onPress={() => {
                  commit.reset();
                  void queryClient.invalidateQueries({ queryKey: queryKeys.imports.job(detail.id) });
                }}
              >
                Reload
              </Button>
            }
          >
            Nothing was written. Reload to see the latest state, then commit again.
          </Banner>
        ) : commit.error ? (
          <Banner tone="ember" title="The commit did not start.">
            {problemText(commit.error, "Check your connection and try again.")}
          </Banner>
        ) : null}
        {detail.status === "commit_failed" ? (
          <Banner tone="ember" title="The last commit stopped part way.">
            {detail.error_detail ? `${detail.error_detail}. ` : ""}Committing again carries on where it stopped.
          </Banner>
        ) : null}
        <p className="t-body text-ink-2">
          {formatCount(writes, zone.locale)} {writes === 1 ? "row is" : "rows are"} written in batches of 500. Unchanged rows are skipped.
        </p>
        {excluded > 0 ? (
          <Checkbox
            label={`Leave out ${formatCount(excluded, zone.locale)} rejected or held-back ${excluded === 1 ? "row" : "rows"}`}
            description="They are not imported. Fix them in the sheet and import it again, or recheck the held-back rows later."
            isSelected={acknowledged}
            onChange={setAcknowledged}
          />
        ) : null}
        <div className="flex flex-wrap items-center justify-end gap-3">
          {!canCommit ? <span className="t-body-sm text-ink-3">This import is not ready to commit.</span> : excluded > 0 && !acknowledged ? <span className="t-body-sm text-ink-3">Tick the box above to carry on.</span> : null}
          <Button onPress={() => commit.mutate()} loading={commit.isPending} isDisabled={blocked} iconLeft="check">
            Commit import
          </Button>
        </div>
      </div>
    </GlassPanel>
  );
}

function Review({ detail, step }: { detail: JobDetail; step: Step }) {
  const { zone } = useSession();
  const counts = detail.counts;
  const tile = (label: string, value: number, foot?: string) => <StatTile label={label} value={<span className="lk-tnum">{formatCount(value, zone.locale)}</span>} foot={foot} />;
  return (
    <div className="stack">
      <StatRow>
        {step === "result" ? tile("Written", counts.committed ?? 0) : tile("To add", counts.to_insert ?? 0)}
        {step === "result" ? tile("Rows in the file", detail.row_count) : tile("To update", counts.to_update ?? 0)}
        {tile("Unchanged", (counts.unchanged ?? 0) + (counts.duplicate_identical ?? 0), "Skipped")}
        {tile("Rejected or held back", (counts.rejected ?? 0) + (counts.quarantined ?? 0), `${formatCount(counts.warning ?? 0, zone.locale)} with a warning`)}
      </StatRow>
      {step === "review" ? <CommitPanel key={detail.version} detail={detail} /> : null}
      <Tabs label="Review views" defaultSelectedKey="issues" tabs={[{ id: "issues", label: "Issues" }, { id: "rows", label: "Rows, before and after" }]}>
        <TabPanel id="issues">
          <Issues detail={detail} />
        </TabPanel>
        <TabPanel id="rows">
          <Rows detail={detail} />
        </TabPanel>
      </Tabs>
    </div>
  );
}

// ---- rollback ----

function RollbackDialog({ detail, onClose }: { detail: JobDetail; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { zone } = useSession();
  const plan = useRollbackPlan(detail.id);
  const run = useMutation({
    mutationFn: (mode: "all" | "reversible_only") => rollback(detail.id, mode, plan.data!.plan_hash),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKeys.imports.job(detail.id), next);
      for (const key of invalidationMap["imports.changed"]) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(next.status === "rolled_back" ? "Import rolled back" : "The reversible changes were rolled back");
      onClose();
    },
    onError: (error) =>
      toast.error("Nothing was rolled back", {
        description: error instanceof ProblemError && error.code === "reauth_required" ? "Sign in again, then roll back." : problemText(error, "Check your connection and try again."),
      }),
  });
  const data = plan.data;
  const count = (value: number) => formatCount(value, zone.locale);

  return (
    <Modal
      isOpen
      onOpenChange={(open) => {
        if (!open && !run.isPending) onClose();
      }}
      size="lg"
      isDismissable={!run.isPending}
      title="Roll back this import"
      description="Removes what this import wrote. Later edits, and records used elsewhere, are never undone."
      actions={
        <>
          <Button variant="ghost" onPress={onClose} isDisabled={run.isPending}>
            Cancel
          </Button>
          {data && data.blocked ? (
            <Button variant="danger" onPress={() => run.mutate("reversible_only")} loading={run.isPending} isDisabled={!data.reversible}>
              Roll back {count(data.reversible)} reversible {data.reversible === 1 ? "change" : "changes"}
            </Button>
          ) : (
            <Button variant="danger" onPress={() => run.mutate("all")} loading={run.isPending} isDisabled={!data}>
              Roll back everything
            </Button>
          )}
        </>
      }
    >
      {plan.isPending ? (
        <SkeletonText lines={3} />
      ) : plan.isError || !data ? (
        <ErrorBlock error={plan.error} what="The rollback plan" onRetry={() => void plan.refetch()} />
      ) : (
        <div className="flex min-w-0 flex-col gap-4">
          <FactStrip
            items={[
              { label: "Can be undone", value: <span className="lk-tnum">{count(data.reversible)}</span> },
              { label: "Blocked", value: <span className="lk-tnum">{count(data.blocked)}</span> },
              { label: "Already removed", value: <span className="lk-tnum">{count(data.already_removed)}</span> },
            ]}
          />
          {data.blocked ? (
            <div className="flex min-w-0 flex-col gap-2">
              <p className="t-label text-ink">Blocked, and why</p>
              <ul className="flex list-none flex-col gap-1">
                {data.items
                  .filter((item) => item.status === "blocked")
                  .slice(0, 30)
                  .map((item) => (
                    <li key={item.seq} className="t-body-sm text-ink-2 [overflow-wrap:anywhere]">
                      <Mono>
                        {item.entity_table} {item.entity_id.slice(0, 8)}
                      </Mono>
                      : {item.reason_code ?? "blocked"}
                      {item.detail ? ` (${item.detail})` : ""}
                    </li>
                  ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

// ---- the screen ----

export function ImportJob({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { zone } = useSession();
  const job = useImportJob(jobId);
  const types = useImportTypes();
  const [rollingBack, setRollingBack] = useState(false);
  const child = useMutation({
    mutationFn: () => recheck(jobId),
    onSuccess: (next) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.imports.all() });
      router.push(asRoute(next.path));
    },
    onError: () => toast.error("Nothing to recheck", { description: "No held-back row can be checked again yet." }),
  });

  if (job.isPending) {
    return (
      <Page>
        <LoadingBlock lines={10} label="Loading the import" />
      </Page>
    );
  }
  if (job.isError) {
    return (
      <Page>
        <ErrorBlock error={job.error} what="This import" onRetry={() => void job.refetch()} />
      </Page>
    );
  }

  const detail = job.data;
  const step = stepOf(detail);
  const fields = types.data?.find((type) => type.import_type === detail.import_type)?.fields.map((field) => field.name) ?? [];
  const excluded = (detail.counts.rejected ?? 0) + (detail.counts.quarantined ?? 0);
  const canRollback = detail.capabilities.rollback?.allowed === true;
  const canRecheck = detail.capabilities.recheck?.allowed === true;
  const sha = shortSha(detail.file_sha256);

  return (
    <Page>
      <RecordHeader
        breadcrumb={IMPORTS_CRUMBS}
        code={`${importTypeLabel(detail.import_type)} import`}
        title={<span className="[overflow-wrap:anywhere]">{detail.file_name}</span>}
        status={<ImportStatus status={detail.status} />}
        lead={
          detail.parent_job_id ? (
            <>
              A recheck of the held-back rows from{" "}
              <TextLink href={importHref(detail.parent_job_id)}>an earlier import</TextLink>
              .
            </>
          ) : undefined
        }
        facts={
          <FactStrip
            items={[
              { label: "Rows", value: <span className="lk-tnum">{formatCount(detail.row_count, zone.locale)}</span> },
              { label: "Left out", value: <span className="lk-tnum">{formatCount(excluded, zone.locale)}</span> },
              {
                label: "Started",
                value: (
                  <span className="flex min-w-0 flex-col">
                    <DateText value={detail.created_at} style="dayTime" />
                    {detail.created_by_name ? <span className="t-caption text-ink-3">{detail.created_by_name}</span> : null}
                  </span>
                ),
              },
              { label: "File check", value: sha ? <Mono title={detail.file_sha256}>{sha}</Mono> : null },
            ]}
          />
        }
        actions={
          <>
            {canRecheck ? (
              <Button variant="secondary" iconLeft="refresh" onPress={() => child.mutate()} loading={child.isPending}>
                Recheck held-back rows
              </Button>
            ) : null}
            <ButtonLink external href={detail.source_url} variant="secondary" iconLeft="download">
              Source file
            </ButtonLink>
            {canRollback ? (
              <Menu
                label="More actions for this import"
                placement="bottom end"
                items={[{ id: "rollback", label: "Roll back import", icon: "undo", tone: "danger", description: "Removes what it wrote", onAction: () => setRollingBack(true) }]}
                trigger={<IconButton icon="more" label="More actions" />}
              />
            ) : null}
          </>
        }
      />

      <StepIndicator step={step} />

      {detail.error_code && step !== "review" ? (
        <Banner tone="ember" title="The import stopped.">
          {detail.error_detail ?? detail.error_code} <Mono className="text-ink-3">({detail.error_code})</Mono>
        </Banner>
      ) : null}

      {step === "mapping" ? <MappingStep key={detail.version} detail={detail} fields={fields} /> : null}
      {step === "validating" || step === "committing" ? <Working detail={detail} step={step} /> : null}
      {step === "review" || step === "result" ? <Review detail={detail} step={step} /> : null}

      {rollingBack ? <RollbackDialog detail={detail} onClose={() => setRollingBack(false)} /> : null}
    </Page>
  );
}
