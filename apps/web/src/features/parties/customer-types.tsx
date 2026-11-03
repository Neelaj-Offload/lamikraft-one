"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { fieldErrors } from "@/features/catalogue/api";
import { SettingsAreaNav } from "@/features/settings/settings-hub";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { createCustomerType, fetchCustomerTypes, updateCustomerType, type CustomerTypeRead } from "./customer-types-api";

export function useCustomerTypes(enabled = true) {
  return useQuery({ queryKey: queryKeys.parties.customerTypes(), queryFn: ({ signal }) => fetchCustomerTypes(signal), enabled });
}

/** Customer types (SC-13): built-in standard/dealer/distributor plus company types; add, activate and deactivate. */
export function CustomerTypesManager() {
  const queryClient = useQueryClient();
  const { permissionKeys } = useSession();
  const readable = permissionKeys.has("parties.party.read");
  const types = useCustomerTypes(readable);
  const [draft, setDraft] = useState({ code: "", label: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const canManage = permissionKeys.has("parties.customer_type.manage");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.parties.all() });
  const create = useMutation({
    mutationFn: () => createCustomerType({ code: draft.code, label: draft.label }),
    onSuccess: () => {
      setDraft({ code: "", label: "" });
      setErrors({});
      refresh();
    },
    onError: (error) =>
      setErrors(error instanceof ProblemError && error.code === "customer_type_exists" ? { code: "This code already exists" } : fieldErrors(error)),
  });
  const toggle = useMutation({
    mutationFn: (t: CustomerTypeRead) => updateCustomerType(t.id, { expected_version: t.version, is_active: !t.is_active }),
    onSuccess: refresh,
    onError: () => toast.error("Changed by someone else; reload and try again"),
  });
  if (!readable) return <PermissionDenied area="customer types" />;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Customer types" intro="The types a customer can have; price lists and reports group by them." nav={<SettingsAreaNav currentId="settings-customer-types" />} />
      {types.isPending ? (
        <Loading label="customer types" />
      ) : types.isError ? (
        <ErrorState error={types.error} what="the customer types" onRetry={() => void types.refetch()} />
      ) : (
        <ul className="flex flex-col divide-y rounded-md border">
          {types.data.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <span className="font-semibold">{t.label}</span>
              <span className="font-mono text-ink-muted">{t.code}</span>
              {t.is_system ? <StatusPill tone="info">Built in</StatusPill> : null}
              {t.is_active ? null : <StatusPill tone="neutral">Inactive</StatusPill>}
              <span className="text-ink-muted tabular">{t.party_count} parties</span>
              {canManage ? (
                <Button size="sm" className="ms-auto" onPress={() => toggle.mutate(t)} isPending={toggle.isPending}>
                  {t.is_active ? "Deactivate" : "Activate"}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canManage ? (
        <form
          className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_2fr_auto] md:items-end"
          aria-label="New customer type"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <TextField label="Code" description="Lower case, e.g. wholesale" value={draft.code} onChange={(v) => setDraft((d) => ({ ...d, code: v }))} isInvalid={Boolean(errors.code)} errorMessage={errors.code} />
          <TextField label="Label" value={draft.label} onChange={(v) => setDraft((d) => ({ ...d, label: v }))} isInvalid={Boolean(errors.label)} errorMessage={errors.label} />
          <Button type="submit" variant="primary" isPending={create.isPending}>
            Add type
          </Button>
        </form>
      ) : null}
    </div>
  );
}
