"use client";

import type { Route } from "next";
import type { RoleSummary } from "@/app/(app)/settings/_lib/types";
import { useSession } from "@/lib/session/context";
import { useRoles } from "~/data/settings-access";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, ButtonLink, DataTable, EmptyState, GlassPanel, PageSummary, TableFooter, type Column } from "~/ui";
import { roleHref, SETTINGS_CRUMB } from "./labels";

function ownRules(role: RoleSummary): string {
  if (role.grant_count === 0 && role.deny_count === 0) return "None of its own";
  const grants = `${role.grant_count} ${role.grant_count === 1 ? "grant" : "grants"}`;
  return role.deny_count ? `${grants}, ${role.deny_count} ${role.deny_count === 1 ? "deny" : "denies"}` : grants;
}

const COLUMNS: Column<RoleSummary>[] = [
  {
    key: "name",
    header: "Role",
    primary: true,
    cell: (role) => (
      <span className="flex min-w-0 flex-col">
        <span className="t-label text-ink">{role.name}</span>
        {role.description ? (
          <span className="t-caption line-clamp-1 text-ink-3" title={role.description}>
            {role.description}
          </span>
        ) : null}
      </span>
    ),
  },
  {
    key: "kind",
    header: "Kind",
    cell: (role) => (
      <span className="flex flex-wrap items-center gap-1">
        {role.kind === "custom" ? <Badge tone="cobalt">Custom</Badge> : <Badge icon="lock">Built in</Badge>}
        {role.archived ? (
          <Badge outline size="sm" icon="archive">
            Archived
          </Badge>
        ) : null}
      </span>
    ),
  },
  { key: "inherits", header: "Builds on", cell: (role) => role.inherits?.name ?? <span className="text-ink-3">Nothing</span> },
  { key: "members", header: "People", numeric: true, cell: (role) => role.member_count },
  { key: "entries", header: "Own rules", hideOnMobile: true, cell: (role) => <span className="text-ink-2">{ownRules(role)}</span> },
];

/** Every role in the workspace: the built-in ones and the custom ones made from them. */
export function RolesList() {
  const { permissionKeys } = useSession();
  const query = useRoles();
  const canManage = permissionKeys.has("identity.role.manage");

  return (
    <Page>
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, { label: "Roles" }]}
        title="Roles"
        lead="A role is a set of permissions for one kind of job. Built-in roles cannot be edited: make a custom role that builds on one, then add or deny permissions."
        actions={
          <>
            {canManage ? (
              <ButtonLink href={"/settings/roles/new" as Route} iconLeft="plus">
                Create role
              </ButtonLink>
            ) : null}
            <ButtonLink variant="secondary" href={"/settings/roles/simulate" as Route} iconLeft="scan">
              Check someone&apos;s access
            </ButtonLink>
          </>
        }
      />

      {query.isError ? (
        <ErrorBlock error={query.error} what="Roles" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise" style={{ "--i": 1 } as React.CSSProperties}>
          <DataTable
            label="Roles"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(role) => role.id}
            rowHref={(role) => roleHref(role.id)}
            loading={query.isPending}
            skeletonRows={8}
            empty={<EmptyState icon="badgeCheck" title="No roles yet" text="The built-in roles appear once the workspace is set up." />}
            footer={query.data && query.data.items.length > 0 ? <TableFooter left={<PageSummary from={1} to={query.data.items.length} total={query.data.items.length} noun="roles" />} /> : undefined}
          />
        </GlassPanel>
      )}
    </Page>
  );
}
