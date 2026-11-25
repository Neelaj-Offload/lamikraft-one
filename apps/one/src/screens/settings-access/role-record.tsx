"use client";

import type { Route } from "next";
import { Fragment, useState } from "react";
import { archiveRole } from "@/app/(app)/settings/_lib/api";
import type { RoleDetail } from "@/app/(app)/settings/_lib/types";
import { useRefreshIdentity, useRole } from "~/data/settings-access";
import { Page, PageHeader, RecordHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Banner, ButtonLink, ConfirmDialog, FactStrip, GlassPanel, Icon, IconButton, Menu, Skeleton, SkeletonText, Tabs, TextLink, toast, type MenuItem, type TabItem } from "~/ui";

/** Overview lists every deny and the first grants; the full list lives in the permissions view. */
const RULES_SHOWN = 10;
import { keyLabel, problemText, roleHref, ROLES_CRUMB, SCOPE_LABEL, SETTINGS_CRUMB, simulateHref, type RoleView } from "./labels";
import { PermissionTable } from "./permission-table";
import { useStepUp } from "./step-up";

/** One role: what it builds on, the rules it adds, and everything it ends up allowing. */
export function RoleRecord({ roleId, view }: { roleId: string; view: RoleView }) {
  const query = useRole(roleId);
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading this role">
          <Skeleton width={90} height={10} />
          <Skeleton width="36%" height={28} />
          <SkeletonText lines={2} />
        </div>
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <PageHeader breadcrumb={[SETTINGS_CRUMB, ROLES_CRUMB]} title="Role" />
        <ErrorBlock error={query.error} what="This role" onRetry={() => void query.refetch()} />
      </Page>
    );
  }
  return <Loaded detail={query.data} view={view} />;
}

function Loaded({ detail, view }: { detail: RoleDetail; view: RoleView }) {
  const refresh = useRefreshIdentity();
  const stepUp = useStepUp();
  const [confirmArchive, setConfirmArchive] = useState(false);
  const { role, capabilities: caps } = detail;
  const isCustom = role.kind === "custom";
  const canArchive = isCustom && !role.archived && caps.archive.allowed;
  const archiveBlocked = isCustom && !role.archived && !caps.archive.allowed && caps.archive.reason_code === "role_in_use";
  const grants = detail.entries.filter((entry) => entry.effect === "grant");
  const denies = detail.entries.filter((entry) => entry.effect === "deny");

  const archive = async () => {
    try {
      await stepUp.run(() => archiveRole(role.id));
      await refresh();
      toast.success(`${role.name} archived`);
    } catch (error) {
      toast.error("The role was not archived", { description: problemText(error) });
      throw error;
    }
  };

  const tabs: TabItem[] = [
    { id: "overview", label: "Overview", href: roleHref(role.id) },
    { id: "permissions", label: "Everything it allows", count: detail.effective.length, href: roleHref(role.id, "permissions") },
  ];
  const menu: MenuItem[] = canArchive ? [{ id: "archive", label: "Archive role", icon: "archive", tone: "danger", onAction: () => setConfirmArchive(true) }] : [];

  return (
    <Page>
      <RecordHeader
        breadcrumb={[SETTINGS_CRUMB, ROLES_CRUMB, { label: role.name }]}
        code={role.key}
        title={role.name}
        status={
          <>
            {isCustom ? <Badge tone="cobalt">Custom</Badge> : <Badge icon="lock">Built in</Badge>}
            {role.archived ? <Badge icon="archive">Archived</Badge> : null}
          </>
        }
        lead={role.description ?? (isCustom ? undefined : "A built-in role. It mirrors a standard job and cannot be edited.")}
        facts={
          <FactStrip
            items={[
              { label: "People", value: role.member_count, icon: "users" },
              { label: "Builds on", value: role.inherits?.name ?? "Nothing", icon: "layers" },
              { label: "Own grants", value: role.grant_count, icon: "check" },
              { label: "Own denies", value: role.deny_count, icon: "x" },
              { label: "Allows in total", value: detail.effective.length, icon: "key" },
            ]}
          />
        }
        actions={
          <>
            {caps.update.allowed ? (
              <ButtonLink href={`/settings/roles/${encodeURIComponent(role.id)}/edit` as Route} iconLeft="edit">
                Edit role
              </ButtonLink>
            ) : null}
            <ButtonLink variant="secondary" href={simulateHref({ role: role.id })} iconLeft="scan">
              Check access
            </ButtonLink>
            {menu.length > 0 ? <Menu label="More actions" items={menu} placement="bottom end" trigger={<IconButton icon="more" label="More actions" />} /> : null}
          </>
        }
      >
        <Tabs label={`${role.name}: views`} tabs={tabs} selectedKey={view} />
      </RecordHeader>

      {view === "overview" ? (
        <div className="stack">
          {archiveBlocked ? (
            <Banner tone="neutral" icon="archive" title="This role is in use.">
              To archive it, first move its people to another role and change any role that builds on it.
            </Banner>
          ) : null}
          <div className="grid min-w-0 grid-cols-1 items-start gap-5 lg:grid-cols-2">
            <GlassPanel as="section" title="How it is built" titleAs="h2" padding="lg" className="flex flex-col gap-4">
              <p className="t-body-sm text-ink-3">Read from the left. Each role starts with everything before it, then adds or denies.</p>
              <ol className="m-0 flex list-none flex-wrap items-center gap-2 p-0">
                {detail.chain.map((step, index) => (
                  <Fragment key={step.key}>
                    {index > 0 ? (
                      <li aria-hidden className="text-ink-3">
                        <Icon name="arrowRight" size={16} />
                      </li>
                    ) : null}
                    <li>
                      <Badge tone={index === detail.chain.length - 1 ? "inverse" : "neutral"}>{step.name}</Badge>
                    </li>
                  </Fragment>
                ))}
              </ol>
              {detail.chain.length <= 1 ? <p className="t-body-sm text-ink-2">It builds on nothing: its own grants are all it allows.</p> : null}
            </GlassPanel>

            <GlassPanel as="section" title="Its own rules" titleAs="h2" padding="lg" className="flex flex-col gap-4">
              {detail.entries.length === 0 ? (
                <p className="t-body text-ink-2">No rules of its own. It allows exactly what it builds on.</p>
              ) : (
                <>
                  <p className="t-body-sm text-ink-3">What this role adds to, or takes away from, the role it builds on.</p>
                  <ul className="m-0 flex list-none flex-col p-0">
                    {[...denies, ...grants].slice(0, Math.max(RULES_SHOWN, denies.length)).map((entry, index) => (
                      <li key={entry.key} className={`flex flex-wrap items-center gap-2 py-2.5 ${index > 0 ? "hairline-top" : ""}`}>
                        <Badge tone={entry.effect === "grant" ? "leaf" : "ember"} icon={entry.effect === "grant" ? "check" : "x"} size="sm">
                          {entry.effect === "grant" ? "Grant" : "Deny"}
                        </Badge>
                        <span className="t-label min-w-0 flex-1 text-ink" title={entry.key}>
                          {keyLabel(entry.key)}
                        </span>
                        {entry.scope ? <span className="t-body-sm text-ink-3">{SCOPE_LABEL[entry.scope]}</span> : null}
                      </li>
                    ))}
                  </ul>
                  {detail.entries.length > Math.max(RULES_SHOWN, denies.length) ? (
                    <div className="hairline-top pt-4">
                      <TextLink href={roleHref(role.id, "permissions")} className="t-body-sm">
                        {`${detail.entries.length - Math.max(RULES_SHOWN, denies.length)} more rules. See everything it allows`}
                      </TextLink>
                    </div>
                  ) : null}
                </>
              )}
            </GlassPanel>
          </div>
        </div>
      ) : null}

      {view === "permissions" ? (
        <PermissionTable rows={detail.effective} label="Permissions this role allows" emptyText="This role allows nothing yet. Edit it to add grants or have it build on another role." />
      ) : null}

      <ConfirmDialog
        isOpen={confirmArchive}
        onOpenChange={setConfirmArchive}
        tone="danger"
        title={`Archive ${role.name}`}
        description="It leaves the lists and can no longer be given to anyone. Past records keep its name."
        confirmLabel="Archive role"
        onConfirm={archive}
      />
      {stepUp.dialog}
    </Page>
  );
}
