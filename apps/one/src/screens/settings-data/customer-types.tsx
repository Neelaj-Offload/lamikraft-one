"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { fieldErrors } from "@/features/catalogue/api";
import { createCustomerType, updateCustomerType, type CustomerTypeRead } from "@/features/parties/customer-types-api";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { CUSTOMER_TYPE_MANAGE, CUSTOMERS_READ, useCustomerTypes } from "~/data/settings-data";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import { Badge, Banner, Button, Code, DataTable, EmptyState, GlassPanel, Modal, TextField, toast, type Column } from "~/ui";
import { SETTINGS_CRUMBS } from "./shared";

/** The kinds of customer you sell to. Customers carry one; price lists and reports group by it. */

function AddTypeDialog({ isOpen, onOpenChange, onCreated }: { isOpen: boolean; onOpenChange: (open: boolean) => void; onCreated: () => void }) {
  const [draft, setDraft] = useState({ code: "", label: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => createCustomerType({ code: draft.code, label: draft.label }),
    onSuccess: (created) => {
      toast.success(`${created.label} added`, { description: "You can now give it to customers and price lists." });
      setDraft({ code: "", label: "" });
      setErrors({});
      setFailure(null);
      onCreated();
      onOpenChange(false);
    },
    onError: (error) => {
      if (error instanceof ProblemError && error.code === "customer_type_exists") {
        setErrors({ code: "A customer type with this code already exists. Choose another code." });
        setFailure(null);
        return;
      }
      const found = fieldErrors(error);
      setErrors(found);
      setFailure(Object.keys(found).length > 0 ? null : error instanceof ProblemError ? (error.detail ?? error.title) : "The connection dropped before the server answered. Check your network and try again.");
    },
  });

  const submit = () => {
    const local: Record<string, string> = {};
    if (!draft.code.trim()) local.code = "Give the type a short code, for example wholesale.";
    if (!draft.label.trim()) local.label = "Give the type the name people will see.";
    setErrors(local);
    setFailure(null);
    if (Object.keys(local).length === 0) create.mutate();
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submit();
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      title="Add a customer type"
      description="It is active as soon as you add it."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)} isDisabled={create.isPending}>
            Cancel
          </Button>
          <Button onPress={submit} loading={create.isPending}>
            Add customer type
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
        {failure ? (
          <Banner tone="ember" title="The type was not added.">
            {failure}
          </Banner>
        ) : null}
        <TextField label="Name" isRequired autoFocus value={draft.label} onChange={(label) => setDraft((current) => ({ ...current, label }))} error={errors.label || undefined} placeholder="Wholesale" />
        <TextField
          label="Code"
          isRequired
          value={draft.code}
          onChange={(code) => setDraft((current) => ({ ...current, code }))}
          help="Lower case, no spaces. It cannot be changed later."
          error={errors.code || undefined}
          placeholder="wholesale"
        />
        <button type="submit" hidden tabIndex={-1} aria-hidden="true" />
      </form>
    </Modal>
  );
}

export function CustomerTypes() {
  const queryClient = useQueryClient();
  const { permissionKeys, zone } = useSession();
  const readable = permissionKeys.has(CUSTOMERS_READ);
  const canManage = permissionKeys.has(CUSTOMER_TYPE_MANAGE);
  const types = useCustomerTypes(readable);
  const [adding, setAdding] = useState(false);
  const [changing, setChanging] = useState<string | null>(null);

  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.parties.all() });
  const toggle = useMutation({
    mutationFn: (type: CustomerTypeRead) => updateCustomerType(type.id, { expected_version: type.version, is_active: !type.is_active }),
    onMutate: (type) => setChanging(type.id),
    onSuccess: (next) => {
      toast.success(next.is_active ? `${next.label} is active again` : `${next.label} deactivated`, {
        description: next.is_active ? undefined : "Customers keep it; it is no longer offered for new ones.",
      });
      refresh();
    },
    onError: (error) => {
      if (conflictFromError(error)) {
        toast.warning("Someone else changed this type first", { description: "The latest version is on screen. Check it, then try again." });
        refresh();
      } else {
        toast.error("The customer type was not changed", { description: error instanceof ProblemError ? (error.detail ?? error.title) : "Check your connection and try again." });
      }
    },
    onSettled: () => setChanging(null),
  });

  const header = (
    <PageHeader
      breadcrumb={SETTINGS_CRUMBS}
      title="Customer types"
      lead="The kinds of customer you sell to. Each customer carries one; price lists and reports group by it."
      actions={
        readable && canManage ? (
          <Button iconLeft="plus" onPress={() => setAdding(true)}>
            Add customer type
          </Button>
        ) : undefined
      }
    />
  );

  if (!readable) {
    return (
      <Page width="reading">
        {header}
        <NotPermitted what="Customer types" icon="users" />
      </Page>
    );
  }

  const columns: Column<CustomerTypeRead>[] = [
    {
      key: "type",
      header: "Customer type",
      primary: true,
      cell: (type) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="t-label text-ink">{type.label}</span>
          <Code>{type.code}</Code>
        </span>
      ),
    },
    {
      key: "origin",
      header: "Origin",
      mobileLabel: "Origin",
      cell: (type) => (type.is_system ? <Badge tone="cobalt" size="sm">Built in</Badge> : <Badge size="sm">Added here</Badge>),
    },
    {
      key: "customers",
      header: "Customers",
      mobileLabel: "Customers",
      numeric: true,
      cell: (type) => <span className="lk-tnum">{formatCount(type.party_count, zone.locale)}</span>,
    },
    {
      key: "status",
      header: "Status",
      mobileLabel: "Status",
      cell: (type) => (
        <Badge tone={type.is_active ? "leaf" : "neutral"} dot size="sm">
          {type.is_active ? "Active" : "Inactive"}
        </Badge>
      ),
    },
  ];
  if (canManage) {
    columns.push({
      key: "action",
      header: <span className="lk-sr-only">Change</span>,
      width: "148px",
      cell: (type) => (
        <Button variant="secondary" size="sm" onPress={() => toggle.mutate(type)} loading={changing === type.id} isDisabled={toggle.isPending && changing !== type.id} aria-label={`${type.is_active ? "Deactivate" : "Activate"} ${type.label}`}>
          {type.is_active ? "Deactivate" : "Activate"}
        </Button>
      ),
    });
  }

  return (
    <Page width="reading">
      {header}
      {types.isError && !types.data ? (
        <ErrorBlock error={types.error} what="Customer types" onRetry={() => void types.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Customer types"
            columns={columns}
            rows={types.data ?? []}
            rowKey={(type) => type.id}
            loading={types.isPending}
            skeletonRows={4}
            empty={
              <EmptyState
                icon="users"
                title="Add your first customer type"
                text="Types such as dealer or distributor let one price list serve a whole group of customers."
                actions={
                  canManage ? (
                    <Button variant="secondary" iconLeft="plus" onPress={() => setAdding(true)}>
                      Add customer type
                    </Button>
                  ) : undefined
                }
              />
            }
          />
        </GlassPanel>
      )}
      {canManage ? <AddTypeDialog isOpen={adding} onOpenChange={setAdding} onCreated={refresh} /> : null}
    </Page>
  );
}
