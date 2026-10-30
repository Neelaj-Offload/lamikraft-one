"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { Dialog } from "@/components/ui/dialog";
import { LocalDateTime } from "@/components/ui/format";
import { Link, LinkButton } from "@/components/ui/link";
import { Select } from "@/components/ui/select";
import { Conflict, EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { ProblemError, conflictFromError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import {
  IMPORT_TYPES,
  STATUS_LABEL,
  fetchIssues,
  fetchJob,
  fetchJobs,
  fetchPreview,
  fetchRollbackPlan,
  fetchRows,
  fetchTypes,
  isBusy,
  jobCommand,
  recheck,
  rollback,
  saveMapping,
  startImport,
  stepOf,
  type ImportType,
  type IssueRead,
  type JobDetail,
  type JobSummary,
  type RowRead,
} from "./api";

const TONE: Record<string, Tone> = {
  committed: "success",
  commit_failed: "danger",
  validated: "info",
  rolled_back: "neutral",
  partially_rolled_back: "warning",
  cancelled: "neutral",
};

export function JobStatus({ status }: { status: string }) {
  return <StatusPill tone={TONE[status] ?? "neutral"}>{STATUS_LABEL[status] ?? status}</StatusPill>;
}

const TYPE_LABEL: Record<ImportType, string> = {
  category_taxonomy: "Category taxonomy",
  products_master: "Products master",
  pricing: "Pricing",
  packaging: "Packaging",
  specifications: "Specifications",
  media: "Media",
  lookup_reference: "Lookup reference",
};

const historyColumns: DataTableColumn<JobSummary>[] = [
  { id: "file", header: "File", isRowHeader: true, mobile: "title", mobileCell: (j) => j.file_name, cell: (j) => <Link href={j.path}>{j.file_name}</Link> },
  { id: "type", header: "Type", mobile: "key", cell: (j) => TYPE_LABEL[j.import_type] ?? j.import_type },
  { id: "status", header: "Status", mobile: "status", cell: (j) => <JobStatus status={j.status} /> },
  { id: "rows", header: "Rows", numeric: true, cell: (j) => String(j.row_count) },
  { id: "committed", header: "Written", numeric: true, cell: (j) => String(j.counts.committed ?? 0) },
  { id: "issues", header: "Excluded", numeric: true, cell: (j) => String((j.counts.rejected ?? 0) + (j.counts.quarantined ?? 0)) },
  { id: "by", header: "By", mobile: "meta", cell: (j) => j.created_by_name ?? "—" },
  { id: "when", header: "Started", cell: (j) => <LocalDateTime value={j.created_at} /> },
];

/** Import history (UI-24/87): durable jobs with their files' hashes, filtered by type and status. */
export function ImportHistory({ importType, offset }: { importType: string | null; offset: number }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const jobs = useQuery({
    queryKey: queryKeys.imports.jobs({ import_type: importType, offset }),
    queryFn: ({ signal }) => fetchJobs({ importType, status: null, offset }, signal),
  });
  if (!permissionKeys.has("imports.job.read")) return <PermissionDenied area="Imports" />;
  const href = (next: { importType?: string | null; offset?: number }) => {
    const q = new URLSearchParams();
    const t = next.importType === undefined ? importType : next.importType;
    if (t) q.set("type", t);
    if (next.offset) q.set("offset", String(next.offset));
    return q.toString() ? `/settings/imports?${q}` : "/settings/imports";
  };
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">Imports</h1>
        <div className="flex flex-wrap gap-2">
          <LinkButton href="/settings/lookups" variant="quiet">
            Lookup reference
          </LinkButton>
          {permissionKeys.has("imports.job.run") ? (
            <LinkButton href="/settings/imports/new" variant="primary">
              New import
            </LinkButton>
          ) : null}
        </div>
      </header>
      <Select
        label="Type"
        className="max-w-xs"
        options={[{ id: "", label: "All types" }, ...IMPORT_TYPES.map((t) => ({ id: t, label: TYPE_LABEL[t] }))]}
        value={importType ?? ""}
        onChange={(v) => router.push(href({ importType: v || null, offset: 0 }) as Parameters<typeof router.push>[0])}
      />
      {jobs.isPending ? (
        <Loading label="imports" />
      ) : jobs.isError ? (
        <ErrorState error={jobs.error} what="the import history" onRetry={() => void jobs.refetch()} />
      ) : (
        <DataTable
          caption="Import history"
          hideCaption
          columns={historyColumns}
          rows={jobs.data.items}
          rowId={(j) => j.id}
          rowHref={(j) => j.path}
          empty={<EmptyState title="No imports yet">Start with the category taxonomy, then products.</EmptyState>}
          footer={
            <OffsetPagination
              label="Import pages"
              total={jobs.data.total}
              limit={jobs.data.limit || 25}
              offset={jobs.data.offset}
              shown={jobs.data.items.length}
              control={(o) => ({ href: href({ offset: o }) })}
            />
          }
        />
      )}
    </div>
  );
}

/** Step 1-2 (UI-86/89): choose the type (with dependency status and a template), then upload by button or drop. */
export function NewImport() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { permissionKeys } = useSession();
  const inputId = useId();
  const [importType, setImportType] = useState<ImportType>("category_taxonomy");
  const [file, setFile] = useState<File | null>(null);
  const types = useQuery({ queryKey: queryKeys.imports.types(), queryFn: ({ signal }) => fetchTypes(signal) });
  const start = useMutation({
    mutationFn: () => startImport(importType, file!),
    onSuccess: (detail) => {
      for (const key of invalidationMap["imports.changed"]) void queryClient.invalidateQueries({ queryKey: key });
      router.push(detail.path as Parameters<typeof router.push>[0]);
    },
    onError: (error) =>
      toast.error(
        error instanceof ProblemError && error.status === 415
          ? "Only CSV or XLSX files can be imported"
          : error instanceof ProblemError && error.status === 413
            ? "The file is larger than 50 MB"
            : error instanceof ProblemError
              ? (error.detail ?? error.title)
              : "The upload failed",
      ),
  });
  if (!permissionKeys.has("imports.job.run")) return <PermissionDenied area="Imports" />;
  const selected = types.data?.find((t) => t.import_type === importType);
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">New import</h1>
      <ol className="grid grid-cols-1 gap-2 md:grid-cols-2" aria-label="Import types in recommended order">
        {(types.data ?? []).map((t, index) => (
          <li key={t.import_type}>
            <label className="flex cursor-pointer gap-3 rounded-md border p-3 has-[:checked]:border-forest has-[:checked]:bg-forest-tint">
              <input type="radio" name="import_type" value={t.import_type} checked={importType === t.import_type} onChange={() => setImportType(t.import_type)} />
              <span className="flex flex-col gap-0.5 text-sm">
                <span className="font-semibold">
                  {index + 1}. {t.label}
                </span>
                <span className="text-ink-muted">{t.description}</span>
                <span className="text-ink-muted">
                  {t.depends_on.length ? `Needs: ${t.depends_on.map((d) => TYPE_LABEL[d]).join(", ")}. ` : ""}
                  {Object.entries(t.dependency_status)
                    .map(([k, v]) => `${v} ${k} now`)
                    .join(", ")}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ol>
      {selected ? (
        <p className="text-sm">
          Columns: {selected.fields.map((f) => (f.required ? `${f.name}*` : f.name)).join(", ")}.{" "}
          <a href={selected.template_path} className="underline" download>
            Download the template
          </a>
        </p>
      ) : null}
      <div
        className="flex flex-col gap-2 rounded-md border border-dashed p-4"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const dropped = e.dataTransfer.files[0];
          if (dropped) setFile(dropped);
        }}
      >
        <label htmlFor={inputId} className="text-sm font-semibold">
          CSV or XLSX file
        </label>
        <input id={inputId} type="file" accept=".csv,.xlsx" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <p className="text-sm text-ink-muted">{file ? `Selected: ${file.name}` : "Choose a file or drop it here."}</p>
      </div>
      <div className="flex justify-end gap-2">
        <LinkButton href="/settings/imports">Cancel</LinkButton>
        <Button variant="primary" onPress={() => start.mutate()} {...unavailableWhen((!file) ? "Choose a file" : null)} isPending={start.isPending} pendingLabel="Uploading…">
          Upload and preview
        </Button>
      </div>
    </div>
  );
}

function MappingStep({ detail, fields }: { detail: JobDetail; fields: string[] }) {
  const queryClient = useQueryClient();
  const preview = useQuery({ queryKey: queryKeys.imports.preview(detail.id), queryFn: ({ signal }) => fetchPreview(detail.id, signal) });
  const [mapping, setMapping] = useState(detail.mapping);
  const [blankClear, setBlankClear] = useState(detail.options.blank_cells === "clear");
  const save = useMutation({
    mutationFn: async () => {
      const saved = await saveMapping(detail, mapping, { ...detail.options, blank_cells: blankClear ? "clear" : "ignore" });
      return jobCommand(saved, "validate");
    },
    onSuccess: (next) => queryClient.setQueryData(queryKeys.imports.job(detail.id), next),
    onError: (error) => toast.error(error instanceof ProblemError ? (error.detail ?? error.title) : "Not saved"),
  });
  if (preview.isPending) return <Loading label="preview" />;
  if (preview.isError) return <ErrorState error={preview.error} what="the preview" compact backToToday={false} />;
  const p = preview.data;
  return (
    <div className="flex flex-col gap-6">
      {p.same_file_jobs.length ? <p role="status" className="rounded-sm bg-warning-bg px-3 py-2 text-sm text-warning-text">This file was imported before ({p.same_file_jobs.length} earlier job). Re-importing is safe: unchanged rows are skipped.</p> : null}
      {p.duplicate_keys.length ? (
        <section aria-label="Repeated keys" className="text-sm">
          <h2 className="font-semibold">Keys repeated in the file</h2>
          <ul className="list-disc ps-5">
            {p.duplicate_keys.slice(0, 20).map((d) => (
              <li key={d.key}>
                <span className="font-mono">{d.key}</span>: rows {d.row_numbers.join(", ")} {d.identical ? "(identical; extra copies skipped)" : "(different values; quarantined)"}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-label="Column mapping" className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Map the columns</h2>
        {p.unmapped_required.length ? <p className="text-sm text-danger">Required: {p.unmapped_required.join(", ")}</p> : null}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {p.headers.map((h) => (
            <Select
              key={h.original}
              label={h.original}
              description={h.normalised !== h.original ? `Normalised: ${h.normalised}` : undefined}
              options={[{ id: "", label: "Ignore (kept as source data)" }, ...fields.map((f) => ({ id: f, label: f }))]}
              value={mapping[h.original] ?? ""}
              onChange={(v) => setMapping((cur) => ({ ...cur, [h.original]: v || null }))}
            />
          ))}
        </div>
        <Checkbox isSelected={blankClear} onChange={setBlankClear}>
          Blank cells clear existing values (default: keep them)
        </Checkbox>
      </section>
      <section aria-label="First rows" className="overflow-x-auto">
        <h2 className="mb-2 text-base font-semibold">
          First rows <span className="text-sm font-normal text-ink-muted">of {p.total_rows}</span>
        </h2>
        <table className="text-sm">
          <thead>
            <tr>
              <th scope="col" className="px-2 py-1 text-start">
                Row
              </th>
              {p.headers.map((h) => (
                <th key={h.original} scope="col" className="px-2 py-1 text-start">
                  {h.original}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {p.rows.map((row) => (
              <tr key={String(row.row_number)} className="border-t">
                <td className="px-2 py-1 tabular">{row.row_number}</td>
                {p.headers.map((h) => (
                  <td key={h.original} className="px-2 py-1">
                    {String(row[h.original] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <div className="flex justify-end">
        <Button variant="primary" onPress={() => save.mutate()} isPending={save.isPending} {...unavailableWhen((!detail.capabilities.validate?.allowed) ? "This import can no longer be changed" : null)}>
          Save mapping and validate
        </Button>
      </div>
    </div>
  );
}

const issueColumns: DataTableColumn<IssueRead>[] = [
  { id: "row", header: "Row", numeric: true, mobile: "meta", cell: (i) => (i.row_number === null ? "—" : String(i.row_number)) },
  { id: "column", header: "Column", cell: (i) => i.column ?? "—" },
  { id: "code", header: "Code", isRowHeader: true, mobile: "title", cell: (i) => <span className="font-mono">{i.code}</span> },
  { id: "severity", header: "Severity", mobile: "status", cell: (i) => i.severity },
  { id: "message", header: "Message", mobile: "key", cell: (i) => i.message },
  { id: "value", header: "Value", cell: (i) => i.raw_value ?? "—" },
];

const rowColumns: DataTableColumn<RowRead>[] = [
  { id: "row", header: "Row", numeric: true, mobile: "meta", cell: (r) => String(r.row_number) },
  { id: "key", header: "Key", isRowHeader: true, mobile: "title", cell: (r) => <span className="font-mono">{r.natural_key ?? "—"}</span> },
  { id: "status", header: "Status", mobile: "status", cell: (r) => r.status.replace(/_/g, " ") },
  { id: "action", header: "Action", cell: (r) => r.action ?? "—" },
  {
    id: "diff",
    header: "Before → after",
    mobile: "key",
    cell: (r) =>
      r.diff
        ? Object.entries(r.diff)
            .map(([field, [before, after]]) => `${field}: ${before ?? "∅"} → ${after ?? "∅"}`)
            .join("; ")
        : "—",
  },
];

function Review({ detail }: { detail: JobDetail }) {
  const queryClient = useQueryClient();
  const [severity, setSeverity] = useState<string | null>(null);
  const [rowStatus, setRowStatus] = useState<string | null>(null);
  const [issueOffset, setIssueOffset] = useState(0);
  const [rowOffset, setRowOffset] = useState(0);
  const [ack, setAck] = useState(false);
  const issues = useQuery({ queryKey: queryKeys.imports.issues(detail.id, { severity, offset: issueOffset }), queryFn: ({ signal }) => fetchIssues(detail.id, { severity, offset: issueOffset }, signal) });
  const rows = useQuery({ queryKey: queryKeys.imports.rows(detail.id, { status: rowStatus, offset: rowOffset }), queryFn: ({ signal }) => fetchRows(detail.id, { status: rowStatus, offset: rowOffset }, signal) });
  const excluded = (detail.counts.rejected ?? 0) + (detail.counts.quarantined ?? 0);
  const commit = useMutation({
    mutationFn: () => jobCommand(detail, "commit", { acknowledge_excluded: ack }),
    onSuccess: (next) => queryClient.setQueryData(queryKeys.imports.job(detail.id), next),
  });
  const conflict = commit.error ? conflictFromError(commit.error) : null;
  return (
    <div className="flex flex-col gap-6">
      <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-6" aria-label="Validation counts">
        {[
          ["To insert", detail.counts.to_insert ?? 0],
          ["To update", detail.counts.to_update ?? 0],
          ["Unchanged", (detail.counts.unchanged ?? 0) + (detail.counts.duplicate_identical ?? 0)],
          ["Warnings", detail.counts.warning ?? 0],
          ["Rejected", detail.counts.rejected ?? 0],
          ["Quarantined", detail.counts.quarantined ?? 0],
        ].map(([label, n]) => (
          <div key={String(label)} className="rounded-md border p-3">
            <dt className="text-ink-muted">{label}</dt>
            <dd className="text-lg font-semibold tabular">{n}</dd>
          </div>
        ))}
      </dl>
      <section aria-label="Issues" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-base font-semibold">Issues</h2>
          <div className="flex flex-wrap items-end gap-2">
            <Select
              label="Severity"
              options={[{ id: "", label: "All" }, ...["error", "quarantine", "warning", "info"].map((s) => ({ id: s, label: s }))]}
              value={severity ?? ""}
              onChange={(v) => {
                setSeverity(v || null);
                setIssueOffset(0);
              }}
            />
            <a href={detail.report_url} className="text-sm underline" download>
              Download full report
            </a>
          </div>
        </div>
        {issues.isPending ? (
          <Loading label="issues" />
        ) : issues.isError ? (
          <ErrorState error={issues.error} what="the issues" compact backToToday={false} />
        ) : (
          <DataTable caption="Issues" hideCaption columns={issueColumns} rows={issues.data.items} rowId={(i) => i.id}
            empty={<EmptyState title="No issues" />}
            footer={<OffsetPagination label="Issue pages" total={issues.data.total} limit={50} offset={issues.data.offset} shown={issues.data.items.length} control={(o) => ({ onPress: () => setIssueOffset(o) })} />}
          />
        )}
      </section>
      <section aria-label="Rows" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-base font-semibold">Rows (before and after)</h2>
          <Select
            label="Row status"
            options={[{ id: "", label: "All" }, ...["valid", "warning", "rejected", "quarantined", "duplicate_identical", "committed", "unchanged"].map((s) => ({ id: s, label: s.replace(/_/g, " ") }))]}
            value={rowStatus ?? ""}
            onChange={(v) => {
              setRowStatus(v || null);
              setRowOffset(0);
            }}
          />
        </div>
        {rows.isPending ? (
          <Loading label="rows" />
        ) : rows.isError ? (
          <ErrorState error={rows.error} what="the rows" compact backToToday={false} />
        ) : (
          <DataTable caption="Rows" hideCaption columns={rowColumns} rows={rows.data.items} rowId={(r) => r.id}
            empty={<EmptyState title="No rows" />}
            footer={<OffsetPagination label="Row pages" total={rows.data.total} limit={50} offset={rows.data.offset} shown={rows.data.items.length} control={(o) => ({ onPress: () => setRowOffset(o) })} />}
          />
        )}
      </section>
      {stepOf(detail) === "review" ? (
        <section aria-label="Commit" className="flex flex-col gap-3 rounded-md border p-4">
          {conflict ? <Conflict conflict={conflict} onReview={() => void queryClient.invalidateQueries({ queryKey: queryKeys.imports.job(detail.id) })} /> : null}
          {detail.status === "commit_failed" ? <p className="text-sm text-danger">The last commit stopped: {detail.error_detail}. Committing again resumes where it stopped.</p> : null}
          {excluded ? (
            <Checkbox isSelected={ack} onChange={setAck}>
              {excluded} rejected or quarantined rows will not be imported
            </Checkbox>
          ) : null}
          <div className="flex justify-end">
            <Button variant="primary" onPress={() => commit.mutate()} isPending={commit.isPending} {...unavailableWhen((!detail.capabilities.commit?.allowed || (excluded > 0 && !ack)) ? excluded > 0 && !ack ? "Acknowledge the excluded rows" : "Not ready to commit" : null)}>
              Commit in batches of 500
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function RollbackDialog({ detail, onClose }: { detail: JobDetail; onClose: () => void }) {
  const queryClient = useQueryClient();
  const plan = useQuery({ queryKey: ["imports", "rollback-plan", detail.id], queryFn: () => fetchRollbackPlan(detail.id) });
  const run = useMutation({
    mutationFn: (mode: "all" | "reversible_only") => rollback(detail.id, mode, plan.data!.plan_hash),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKeys.imports.job(detail.id), next);
      for (const key of invalidationMap["imports.changed"]) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(next.status === "rolled_back" ? "Import rolled back" : "Reversible changes rolled back");
      onClose();
    },
    onError: (error) => toast.error(error instanceof ProblemError && error.code === "reauth_required" ? "Sign in again to confirm" : error instanceof ProblemError ? (error.detail ?? error.title) : "Not rolled back"),
  });
  return (
    <Dialog
      role="alertdialog"
      title="Roll back this import"
      description="Later edits and records used elsewhere are never undone."
      isOpen
      size="lg"
      onOpenChange={(open) => (open ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button onPress={close}>Cancel</Button>
          {plan.data && plan.data.blocked ? (
            <Button variant="danger" onPress={() => run.mutate("reversible_only")} isPending={run.isPending} {...unavailableWhen((!plan.data.reversible) ? "Nothing is reversible" : null)}>
              Roll back {plan.data.reversible} reversible changes
            </Button>
          ) : (
            <Button variant="danger" onPress={() => run.mutate("all")} isPending={run.isPending} {...unavailableWhen((!plan.data) ? "Loading the plan" : null)}>
              Roll back everything
            </Button>
          )}
        </>
      )}
    >
      {plan.isPending ? (
        <Loading label="rollback plan" />
      ) : plan.isError ? (
        <ErrorState error={plan.error} what="the rollback plan" compact backToToday={false} />
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <p className="tabular">
            {plan.data.reversible} reversible · {plan.data.blocked} blocked · {plan.data.already_removed} already removed
          </p>
          {plan.data.blocked ? (
            <ul className="list-disc ps-5">
              {plan.data.items.filter((i) => i.status === "blocked").slice(0, 30).map((i) => (
                <li key={i.seq}>
                  {i.entity_table} {i.entity_id.slice(0, 8)}: {i.reason_code} {i.detail ? `(${i.detail})` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

/** One import job (UI-86): mapping -> validation -> review with before/after and issues -> commit -> result,
 * with quarantine recheck and the rollback plan. Polls while the server works. */
export function ImportJobView({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [rollbackOpen, setRollbackOpen] = useState(false);
  const job = useQuery({
    queryKey: queryKeys.imports.job(jobId),
    queryFn: ({ signal }) => fetchJob(jobId, signal),
    refetchInterval: (q) => (q.state.data && isBusy(q.state.data) ? 1000 : false),
  });
  const types = useQuery({ queryKey: queryKeys.imports.types(), queryFn: ({ signal }) => fetchTypes(signal) });
  const child = useMutation({
    mutationFn: () => recheck(jobId),
    onSuccess: (next) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.imports.all() });
      router.push(next.path as Parameters<typeof router.push>[0]);
    },
    onError: () => toast.error("Nothing to recheck"),
  });
  if (job.isPending) return <Loading label="import" />;
  if (job.isError) return <ErrorState error={job.error} what="this import" onRetry={() => void job.refetch()} />;
  const detail = job.data;
  const step = stepOf(detail);
  const fields = types.data?.find((t) => t.import_type === detail.import_type)?.fields.map((f) => f.name) ?? [];
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-ink-muted">
            <Link href="/settings/imports">Imports</Link> · {TYPE_LABEL[detail.import_type]}
          </p>
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{detail.file_name}</h1>
          <p className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
            <JobStatus status={detail.status} /> {detail.row_count} rows · sha256 <span className="font-mono">{detail.file_sha256.slice(0, 12)}</span> ·{" "}
            <a href={detail.source_url} className="underline">
              source file
            </a>
            {detail.parent_job_id ? (
              <>
                {" "}· recheck of <Link href={`/settings/imports/${detail.parent_job_id}`}>an earlier import</Link>
              </>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {detail.capabilities.recheck?.allowed ? (
            <Button onPress={() => child.mutate()} isPending={child.isPending}>
              Recheck quarantined rows
            </Button>
          ) : null}
          {detail.capabilities.rollback?.allowed ? (
            <Button variant="danger" onPress={() => setRollbackOpen(true)}>
              Roll back
            </Button>
          ) : null}
        </div>
      </header>
      <ol className="flex flex-wrap gap-2 text-sm" aria-label="Steps">
        {(["mapping", "validating", "review", "committing", "result"] as const).map((s) => (
          <li key={s} aria-current={s === step ? "step" : undefined} className={s === step ? "font-semibold text-ink" : "text-ink-muted"}>
            {s === "mapping" ? "Map" : s === "validating" ? "Validate" : s === "review" ? "Review" : s === "committing" ? "Commit" : "Result"}
          </li>
        ))}
      </ol>
      {detail.error_code && step !== "review" ? <p role="alert" className="text-sm text-danger">{detail.error_code}: {detail.error_detail}</p> : null}
      {step === "mapping" ? <MappingStep key={detail.version} detail={detail} fields={fields} /> : null}
      {step === "validating" || step === "committing" ? (
        <p role="status" className="text-sm">
          {step === "validating" ? "Validating every row…" : `Committing… ${detail.progress.done ?? 0} rows done`}
        </p>
      ) : null}
      {step === "review" || step === "result" ? <Review detail={detail} /> : null}
      {rollbackOpen ? <RollbackDialog detail={detail} onClose={() => setRollbackOpen(false)} /> : null}
    </div>
  );
}
