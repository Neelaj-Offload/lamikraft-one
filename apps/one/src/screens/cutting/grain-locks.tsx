"use client";

import { useState, type FormEvent } from "react";
import type { GrainLock, GrainLockList } from "@/features/cutting/types";
import { useGrainLockCommands, useGrainLocks } from "~/data/cutting";
import { Page, PageHeader, Split } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Banner, Button, Code, DataTable, Dash, DateText, EmptyState, GlassPanel, TextField, type Column } from "~/ui";
import { stagger } from "./parts";

/**
 * Decors whose grain must run along the board: their pieces are never rotated. Everyone who plans
 * cuts reads the list; people who manage grain settings add and remove locks.
 */
export function GrainLocks() {
  const query = useGrainLocks();
  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Cut plans", href: "/operations/cutting" }, { label: "Grain locks" }]}
        title="Grain locks"
        lead="Pieces in these decors are never rotated, so the grain always runs along the length of the board."
      />
      {query.isError ? (
        <ErrorBlock error={query.error} what="Grain locks" onRetry={() => void query.refetch()} />
      ) : (
        <Body list={query.data ?? null} loading={query.isPending} />
      )}
    </Page>
  );
}

function Body({ list, loading }: { list: GrainLockList | null; loading: boolean }) {
  const commands = useGrainLockCommands();
  const canManage = list?.can_manage === true;

  const columns: Column<GrainLock>[] = [
    {
      key: "decor",
      header: "Decor",
      primary: true,
      cell: (lock) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{lock.decor_key}</Code>
          {lock.decor_source && lock.decor_source !== lock.decor_key ? <span className="t-caption text-ink-3">entered as {lock.decor_source}</span> : null}
        </span>
      ),
    },
    { key: "label", header: "What it is", cell: (lock) => (lock.label ? <span className="text-ink">{lock.label}</span> : <Dash />) },
    {
      key: "updated",
      header: "Locked",
      hideOnMobile: true,
      cell: (lock) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <DateText value={lock.updated_at} style="relative" className="text-ink-2" />
          {lock.updated_by?.display_name ? <span className="t-caption text-ink-3">by {lock.updated_by.display_name}</span> : null}
        </span>
      ),
    },
    ...(canManage
      ? [
          {
            key: "remove",
            header: <span className="sr-only">Remove</span>,
            mobileLabel: "Remove",
            numeric: true,
            cell: (lock: GrainLock) => (
              <Button
                variant="ghost"
                size="sm"
                iconLeft="x"
                loading={commands.pending === lock.decor_key}
                isDisabled={commands.offline || (commands.pending !== null && commands.pending !== lock.decor_key)}
                onPress={() => void commands.remove(lock)}
                aria-label={`Remove the lock on decor ${lock.decor_key}`}
              >
                Unlock
              </Button>
            ),
          } satisfies Column<GrainLock>,
        ]
      : []),
  ];

  const table = (
    <GlassPanel padding="none" className="rise min-w-0" style={stagger(1)}>
      <DataTable
        label="Grain-locked decors"
        columns={columns}
        rows={list?.items ?? []}
        rowKey={(lock) => lock.id}
        loading={loading}
        skeletonRows={5}
        empty={
          <EmptyState
            icon="lock"
            title="Every decor may rotate"
            text={canManage ? "Lock a decor whose grain must run along the board, such as a wood grain or a directional pattern." : "No decor is grain-locked yet."}
          />
        }
      />
    </GlassPanel>
  );

  if (loading || !list) return table;
  if (!canManage) {
    return (
      <div className="stack">
        <Banner tone="neutral" icon="lock" title="Read only.">
          Only people who manage grain settings can change this list.
        </Banner>
        {table}
      </div>
    );
  }
  return <Split main={table} aside={<AddLock commands={commands} />} />;
}

function AddLock({ commands }: { commands: ReturnType<typeof useGrainLockCommands> }) {
  const [decor, setDecor] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!decor.trim()) {
      setError("Enter the decor number to lock.");
      return;
    }
    const result = await commands.add(decor, label);
    if (result.ok) {
      setDecor("");
      setLabel("");
      setError(null);
    } else if (result.fieldError) {
      setError(result.fieldError);
    }
  };

  return (
    <GlassPanel padding="lg" className="rise" style={stagger(2)} title="Lock a decor" titleAs="h2">
      <form onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
      <p className="t-body-sm text-ink-3">Plans that use it treat its pieces as never rotated from their next calculation.</p>
      <TextField
        label="Decor"
        placeholder="892"
        value={decor}
        onChange={(value) => {
          setDecor(value);
          if (error) setError(null);
        }}
        maxLength={80}
        isRequired
        error={error ?? undefined}
        help="120.0 is stored as 120; 0120 keeps its leading zero."
      />
      <TextField label="What it is" optional placeholder="Walnut, vertical grain" value={label} onChange={setLabel} maxLength={200} />
      {commands.offline ? <p className="t-caption text-ink-3">You are offline. Locks can be added once the connection is back.</p> : null}
      <div>
        <Button type="submit" variant="primary" iconLeft="lock" loading={commands.pending === "add"} isDisabled={commands.offline}>
          Lock decor
        </Button>
      </div>
      </form>
    </GlassPanel>
  );
}
