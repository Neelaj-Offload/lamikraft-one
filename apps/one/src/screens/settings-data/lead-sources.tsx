"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { fieldErrors } from "@/features/catalogue/api";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { createLeadSource, updateLeadSource, useLeadSources, type LeadSource } from "~/data/leads";
import { ErrorBlock } from "~/shell/states";
import { Badge, Banner, Button, Code, DataTable, EmptyState, GlassPanel, Modal, TextField, toast, type Column } from "~/ui";

export const LEAD_SOURCE_MANAGE = "parties.lead_source.manage";

/** "NRA Chicago 2026" → "nra_chicago_2026": the code the API accepts (20 characters, starts with a letter). */
export function codeFromLabel(label: string): string {
  const base = label
    .normalize("NFKD")
    .replace(/[^\x00-\x7f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const lettered = /^[a-z]/.test(base) ? base : `s_${base}`;
  return lettered.slice(0, 20).replace(/_+$/, "");
}

function AddSourceDialog({ isOpen, onOpenChange, onCreated }: { isOpen: boolean; onOpenChange: (open: boolean) => void; onCreated: () => void }) {
  const [label, setLabel] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const code = codeFromLabel(label);

  const create = useMutation({
    mutationFn: () => createLeadSource({ code, label: label.trim(), display_order: 50 }),
    onSuccess: (created) => {
      toast.success(`${created.label} added`, { description: "Pick it as the source on new leads." });
      setLabel("");
      setErrors({});
      setFailure(null);
      onCreated();
      onOpenChange(false);
    },
    onError: (error) => {
      if (error instanceof ProblemError && error.code === "lead_source_exists") {
        setErrors({ label: "A source with a name like this already exists. Add the year or the city to tell them apart." });
        setFailure(null);
        return;
      }
      const found = fieldErrors(error);
      setErrors(found);
      setFailure(Object.keys(found).length > 0 ? null : error instanceof ProblemError ? (error.detail ?? error.title) : "The connection dropped before the server answered. Check your network and try again.");
    },
  });

  const submit = () => {
    if (code.length < 2) {
      setErrors({ label: "Name the source, for example Ambiente 2026." });
      return;
    }
    setErrors({});
    create.mutate();
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      title="Add a lead source"
      description="A trade show, a campaign or any other place leads come from."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)} isDisabled={create.isPending}>
            Cancel
          </Button>
          <Button onPress={submit} loading={create.isPending}>
            Add source
          </Button>
        </>
      }
    >
      <form
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          submit();
        }}
        noValidate
        className="flex flex-col gap-5"
      >
        {failure ? (
          <Banner tone="ember" title="The source was not added.">
            {failure}
          </Banner>
        ) : null}
        <TextField
          label="Name"
          isRequired
          autoFocus
          value={label}
          onChange={setLabel}
          maxLength={80}
          placeholder="Ambiente 2026"
          help={code.length >= 2 ? <>Saved as <Code>{code}</Code></> : "Include the year for a trade show."}
          error={errors.label || errors.code || undefined}
        />
        <button type="submit" hidden tabIndex={-1} aria-hidden="true" />
      </form>
    </Modal>
  );
}

/** Where leads come from. Every lead can carry one; the leads list filters by it. */
export function LeadSourcesSection() {
  const queryClient = useQueryClient();
  const { permissionKeys, zone } = useSession();
  const canManage = permissionKeys.has(LEAD_SOURCE_MANAGE);
  const sources = useLeadSources();
  const [adding, setAdding] = useState(false);
  const [changing, setChanging] = useState<string | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.parties.all() });

  const toggle = useMutation({
    mutationFn: (source: LeadSource) => updateLeadSource(source.id, { expected_version: source.version, is_active: !source.is_active }),
    onMutate: (source) => setChanging(source.id),
    onSuccess: (next) => {
      toast.success(next.is_active ? `${next.label} is offered again` : `${next.label} switched off`, {
        description: next.is_active ? undefined : "Leads keep it; it is no longer offered for new ones.",
      });
      refresh();
    },
    onError: (error) => {
      if (conflictFromError(error)) {
        toast.warning("Someone else changed this source first", { description: "The latest version is on screen. Check it, then try again." });
        refresh();
      } else {
        toast.error("The source was not changed", { description: error instanceof ProblemError ? (error.detail ?? error.title) : "Check your connection and try again." });
      }
    },
    onSettled: () => setChanging(null),
  });

  const columns: Column<LeadSource>[] = [
    {
      key: "source",
      header: "Lead source",
      primary: true,
      cell: (source) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="t-label text-ink">{source.label}</span>
          <Code>{source.code}</Code>
        </span>
      ),
    },
    {
      key: "origin",
      header: "Origin",
      mobileLabel: "Origin",
      cell: (source) => (source.is_system ? <Badge tone="cobalt" size="sm">Built in</Badge> : <Badge size="sm">Added here</Badge>),
    },
    { key: "leads", header: "Leads", mobileLabel: "Leads", numeric: true, cell: (source) => <span className="lk-tnum">{formatCount(source.lead_count, zone.locale)}</span> },
    {
      key: "status",
      header: "Status",
      mobileLabel: "Status",
      cell: (source) => (
        <Badge tone={source.is_active ? "leaf" : "neutral"} dot size="sm">
          {source.is_active ? "Offered" : "Switched off"}
        </Badge>
      ),
    },
  ];
  if (canManage) {
    columns.push({
      key: "action",
      header: <span className="lk-sr-only">Change</span>,
      width: "148px",
      cell: (source) => (
        <Button
          variant="secondary"
          size="sm"
          onPress={() => toggle.mutate(source)}
          loading={changing === source.id}
          isDisabled={toggle.isPending && changing !== source.id}
          aria-label={`${source.is_active ? "Switch off" : "Offer"} ${source.label}`}
        >
          {source.is_active ? "Switch off" : "Offer again"}
        </Button>
      ),
    });
  }

  return (
    <section className="flex min-w-0 flex-col gap-4" aria-labelledby="lead-sources-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id="lead-sources-title" className="t-h3 text-ink">
            Lead sources
          </h2>
          <p className="t-body-sm text-ink-2">Where leads come from: the website, a visiting card, each trade show. The leads list filters by it.</p>
        </div>
        {canManage ? (
          <Button variant="secondary" iconLeft="plus" onPress={() => setAdding(true)}>
            Add source
          </Button>
        ) : null}
      </div>
      {sources.isError && !sources.data ? (
        <ErrorBlock error={sources.error} what="Lead sources" onRetry={() => void sources.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Lead sources"
            columns={columns}
            rows={sources.data ?? []}
            rowKey={(source) => source.id}
            loading={sources.isPending}
            skeletonRows={5}
            empty={<EmptyState icon="flag" title="No sources yet" text="Add the trade shows and campaigns your leads come from." />}
          />
        </GlassPanel>
      )}
      {canManage ? <AddSourceDialog isOpen={adding} onOpenChange={setAdding} onCreated={refresh} /> : null}
    </section>
  );
}
