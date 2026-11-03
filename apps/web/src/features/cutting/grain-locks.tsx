"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { RelativeTime } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { EmptyState, Loading } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { addGrainLock, fetchGrainLocks, removeGrainLock } from "./api";
import { cuttingMessages as m } from "./messages";
import { QueryFailure } from "./query-failure";
import type { GrainLock, GrainLockList } from "./types";

function columns(canManage: boolean, onRemove: (lock: GrainLock) => void, pending: string | null): DataTableColumn<GrainLock>[] {
  const out: DataTableColumn<GrainLock>[] = [
    {
      id: "decor",
      header: m.grain.columns.decor,
      isRowHeader: true,
      mobile: "title",
      cell: (lock) => (
        <span className="font-mono">
          {lock.decor_key}
          {lock.decor_source ? <span className="ms-2 text-xs text-ink-muted">({lock.decor_source})</span> : null}
        </span>
      ),
    },
    { id: "label", header: m.grain.columns.label, mobile: "key", cell: (lock) => lock.label ?? "—" },
    { id: "updated", header: m.grain.columns.updated, mobile: "meta", cell: (lock) => <RelativeTime value={lock.updated_at} className="text-ink-muted" /> },
    { id: "by", header: m.grain.columns.by, cell: (lock) => lock.updated_by?.display_name ?? "—" },
  ];
  if (canManage) {
    out.push({
      id: "remove",
      header: "",
      cell: (lock) => (
        <Button size="sm" variant="quiet" isPending={pending === lock.decor_key} onPress={() => onRemove(lock)} aria-label={m.grain.remove(lock.decor_key)}>
          Remove
        </Button>
      ),
    });
  }
  return out;
}

/** Grain-locked decors: readable by every optimiser user; changed only with ``cutting.grain_lock.manage``. */
export function GrainLocks() {
  const query = useQuery({ queryKey: queryKeys.cutting.grainLocks(), queryFn: ({ signal }) => fetchGrainLocks(signal) });
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <Link href="/operations/cutting" className="text-sm">
          {m.editor.back}
        </Link>
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.grain.title}</h1>
        <p className="text-ink-muted">{m.grain.intro}</p>
      </header>
      {query.isPending ? (
        <Loading label={m.grain.loading} />
      ) : query.isError ? (
        <QueryFailure error={query.error} what={`the ${m.grain.loading}`} onRetry={() => void query.refetch()} />
      ) : (
        <GrainLockBody list={query.data} />
      )}
    </div>
  );
}

function GrainLockBody({ list }: { list: GrainLockList }) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [keys] = useState(() => createCommandKeys());
  const [decor, setDecor] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const offline = online ? null : "You're offline";

  const apply = (next: GrainLockList, message: string) => {
    queryClient.setQueryData(queryKeys.cutting.grainLocks(), next);
    void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.allPlanDetails() });
    toast.success(message, next.warnings.length ? { description: next.warnings.join(" ") } : {});
  };

  const add = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!decor.trim()) {
      setError(m.grain.decorRequired);
      return;
    }
    const signature = commandSignature("grain-lock", "add", decor.trim(), label.trim());
    const attempt = keys.attempt(signature, () => null);
    setPending("add");
    try {
      const next = await addGrainLock({ decor, label }, attempt.key);
      keys.settle(signature);
      setDecor("");
      setLabel("");
      setError(null);
      apply(next, m.grain.added(next.items.find((l) => l.decor_source === decor.trim())?.decor_key ?? decor.trim()));
    } catch (caught) {
      keys.settle(signature, caught);
      if (caught instanceof ProblemError && (caught.status === 409 || caught.status === 422)) setError(caught.validationIssues[0]?.msg ?? caught.detail ?? caught.title);
      else toast.error(m.grain.failed, { description: caught instanceof ProblemError ? (caught.detail ?? undefined) : undefined });
    } finally {
      setPending(null);
    }
  };

  const remove = async (lock: GrainLock) => {
    const signature = commandSignature("grain-lock", "remove", lock.decor_key);
    const attempt = keys.attempt(signature, () => null);
    setPending(lock.decor_key);
    try {
      const next = await removeGrainLock(lock.decor_key, attempt.key);
      keys.settle(signature);
      apply(next, m.grain.removed(lock.decor_key));
    } catch (caught) {
      keys.settle(signature, caught);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.grainLocks() });
      toast.error(m.grain.failed, { description: caught instanceof ProblemError ? (caught.detail ?? undefined) : undefined });
    } finally {
      setPending(null);
    }
  };

  return (
    <>
      {list.can_manage ? (
        <form onSubmit={(event) => void add(event)} noValidate className="grid grid-cols-1 items-start gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]" aria-label={m.grain.add}>
          <TextField label={m.grain.decor} description={m.grain.decorHint} value={decor} onChange={setDecor} maxLength={80} isRequired errorMessage={error ?? undefined} />
          <TextField label={m.grain.label} value={label} onChange={setLabel} maxLength={200} />
          <Button type="submit" variant="primary" className="sm:mt-7" isPending={pending === "add"} {...unavailableWhen(offline)}>
            {m.grain.submit}
          </Button>
        </form>
      ) : (
        <p className="text-sm text-ink-muted">{m.grain.readOnly}</p>
      )}
      <DataTable
        caption={m.grain.caption}
        columns={columns(list.can_manage, (lock) => void remove(lock), pending)}
        rows={list.items}
        rowId={(lock) => lock.id}
        empty={<EmptyState title={m.grain.emptyTitle}>{m.grain.empty}</EmptyState>}
      />
    </>
  );
}
