"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import type { AccessCheck as AccessCheckResult, EffectiveAccess, Scope } from "@/app/(app)/settings/_lib/types";
import { useAccessCheck, useActiveUsers, useEffectiveAccess, useRoles } from "~/data/settings-access";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import {
  Avatar,
  Badge,
  Banner,
  ComboBox,
  EmptyState,
  FactStrip,
  GlassPanel,
  Select,
  SkeletonText,
  TabPanel,
  Tabs,
  TextLink,
  type TabItem,
} from "~/ui";
import { humanise, keyLabel, roleHref, ROLES_CRUMB, scopeFrom, scopeOptions, SETTINGS_CRUMB, simulateHref, userHref } from "./labels";
import { PermissionPicker } from "./parts";
import { PermissionTable } from "./permission-table";

const NO_ROLE = "none";

/**
 * "What can they do, and why not?" for one person or one role. It explains access and never
 * changes it. The subject lives in the URL (`?user=` wins over `?role=`).
 */
export function AccessCheck({ userId, roleId }: { userId: string | null; roleId: string | null }) {
  const subject = { userId, roleId: userId ? null : roleId };
  const effective = useEffectiveAccess(subject);
  const chosen = Boolean(subject.userId || subject.roleId);

  return (
    <Page>
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, ROLES_CRUMB, { label: "Check access" }]}
        title="Check access"
        lead="Pick a person or a role to see every permission they hold, where each one comes from, and what was taken away. Nothing here changes anyone's access."
      />

      <SubjectPicker userId={subject.userId} roleId={subject.roleId} />

      {!chosen ? (
        <GlassPanel padding="lg" className="rise" style={{ "--i": 2 } as React.CSSProperties}>
          <EmptyState
            icon="scan"
            title="Choose someone to explain"
            text="Pick a colleague to find out why they can, or cannot, do something. Pick a role to see what it gives before you hand it out."
          />
        </GlassPanel>
      ) : effective.isPending ? (
        <LoadingBlock label="Working out their access" lines={6} />
      ) : effective.isError ? (
        <ErrorBlock error={effective.error} what="Their access" onRetry={() => void effective.refetch()} />
      ) : (
        <Result access={effective.data} userId={subject.userId} roleId={subject.roleId} />
      )}
    </Page>
  );
}

/** Who to explain: a colleague from the active list, or a role on its own. Each choice is a new URL. */
function SubjectPicker({ userId, roleId }: { userId: string | null; roleId: string | null }) {
  const router = useRouter();
  const users = useActiveUsers();
  const roles = useRoles();
  const people = useMemo(() => users.data?.items ?? [], [users.data]);
  const selected = people.find((person) => person.user_id === userId) ?? null;
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? selected?.display_name ?? "";
  const needle = shown.trim().toLowerCase();
  const matches = people
    .filter((person) => !needle || needle === selected?.display_name.toLowerCase() || person.display_name.toLowerCase().includes(needle))
    .map((person) => ({ id: person.user_id, label: person.display_name, description: person.roles.map((role) => role.name).join(", ") || undefined }));

  const go = (next: { user?: string | null; role?: string | null }) => router.push(simulateHref(next));

  return (
    <GlassPanel as="section" padding="lg" className="rise" style={{ "--i": 1 } as React.CSSProperties} aria-label="Who to check">
      <div className="grid min-w-0 grid-cols-1 items-start gap-5 md:grid-cols-[minmax(0,3fr)_auto_minmax(0,2fr)]">
        <ComboBox
          label="A person"
          placeholder="Type a name"
          items={matches}
          inputValue={shown}
          onInputChange={setText}
          selectedKey={userId}
          onSelectionChange={(id) => {
            setText(null);
            if (id && id !== userId) go({ user: id });
          }}
          isLoading={users.isPending}
          emptyText={users.isError ? "The list of people could not load." : "No active person by that name."}
          help="Active people only."
        />
        <p className="t-overline hidden pt-9 text-ink-3 md:block" aria-hidden>
          or
        </p>
        <Select
          label="A role on its own"
          options={[
            { value: NO_ROLE, label: "No role chosen" },
            ...(roles.data?.items ?? []).map((role) => ({ value: role.id, label: role.name, description: role.kind === "custom" ? "Custom" : "Built in" })),
          ]}
          value={userId ? NO_ROLE : (roleId ?? NO_ROLE)}
          onChange={(value) => go({ role: value === NO_ROLE ? null : value })}
          help={roles.isError ? "The roles could not load. Reload the page to try again." : "What the role gives, before you hand it out."}
        />
      </div>
    </GlassPanel>
  );
}

function Result({ access, userId, roleId }: { access: EffectiveAccess; userId: string | null; roleId: string | null }) {
  const roles = useRoles();
  const roleNames = access.role_keys.map((key) => roles.data?.items.find((role) => role.key === key)?.name ?? key);
  const inactive = access.membership_status !== null && access.membership_status !== "active";
  const name = access.display_name ?? (access.subject === "role" ? "This role" : "This person");
  const tabs: TabItem[] = [
    { id: "granted", label: "Allowed", count: access.granted.length },
    ...(access.removed.length > 0 ? [{ id: "removed", label: "Taken away", count: access.removed.length }] : []),
    ...(access.delegated.length > 0 ? [{ id: "delegated", label: "Delegated reach", count: access.delegated.length }] : []),
  ];

  return (
    <div className="stack">
      <GlassPanel as="section" padding="lg" className="rise flex min-w-0 flex-col gap-5" style={{ "--i": 2 } as React.CSSProperties} aria-label="Who is being checked">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            {access.subject === "member" ? <Avatar name={name} /> : null}
            <div className="flex min-w-0 flex-col gap-1">
              <h2 className="t-h3 truncate" title={name}>
                {name}
              </h2>
              <p className="t-body-sm text-ink-3">
                {access.subject === "role" ? "A role on its own" : roleNames.length > 0 ? roleNames.join(", ") : "No role"}
              </p>
            </div>
          </div>
          {userId ? (
            <TextLink href={userHref(userId, "access")} className="t-body-sm">
              Open their roles and permissions
            </TextLink>
          ) : roleId ? (
            <TextLink href={roleHref(roleId)} className="t-body-sm">
              Open the role
            </TextLink>
          ) : null}
        </div>
        <FactStrip
          items={[
            { label: "Allowed", value: access.granted.length, icon: "check" },
            { label: "Taken away", value: access.removed.length, icon: "x" },
            { label: "Delegated reach", value: access.delegated.length, icon: "users" },
          ]}
        />
      </GlassPanel>

      {inactive ? (
        <Banner tone="amber" icon="lock" title={`${humanise(access.membership_status ?? "")}, so no permission applies.`}>
          The list below is what their roles would give if they were active again.
        </Banner>
      ) : null}

      {userId ? <WhyCheck userId={userId} access={access} /> : null}

      <Tabs label="Permissions" tabs={tabs} variant="underline">
        <TabPanel id="granted">
          <PermissionTable rows={access.granted} label="Allowed permissions" emptyText={`${name} cannot do anything yet. Give them a role to start.`} />
        </TabPanel>
        {access.removed.length > 0 ? (
          <TabPanel id="removed" className="stack">
            <p className="t-body-sm text-ink-3">A role deny or a personal revoke removed these. A removal always wins over a grant.</p>
            <PermissionTable rows={access.removed} label="Permissions taken away" emptyText="Nothing was taken away." />
          </TabPanel>
        ) : null}
        {access.delegated.length > 0 ? (
          <TabPanel id="delegated" className="stack">
            <p className="t-body-sm text-ink-3">Delegation lets them reach other people&apos;s records. It never adds a permission they do not hold.</p>
            <PermissionTable rows={access.delegated} label="Delegated reach" emptyText="No delegated reach." />
          </TabPanel>
        ) : null}
      </Tabs>
    </div>
  );
}

/** One permission at one reach: yes or no, and the reasons the server gives. */
function WhyCheck({ userId, access }: { userId: string; access: EffectiveAccess }) {
  const [key, setKey] = useState<string | null>(null);
  const [scope, setScope] = useState<Scope>("own");
  const check = useAccessCheck(userId, key, scope);
  const candidates = useMemo(() => {
    const seen = new Set<string>();
    return [...access.granted, ...access.removed]
      .filter((row) => (seen.has(row.key) ? false : (seen.add(row.key), true)))
      .map((row) => ({ key: row.key, description: keyLabel(row.key) }));
  }, [access]);

  return (
    <GlassPanel
      as="section"
      title="Why, or why not?"
      titleAs="h2"
      padding="lg"
      className="rise flex min-w-0 flex-col gap-5"
      style={{ "--i": 3 } as React.CSSProperties}
    >
      <p className="t-body-sm text-ink-3">Ask about one permission at the reach the work needs. The answer lists every rule that decided it.</p>
      <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <PermissionPicker permissions={candidates} value={key} onChange={setKey} help="Any permission they hold or lost." />
        <Select label="Reach needed" options={scopeOptions()} value={scope} onChange={(value) => setScope(scopeFrom(value, scope))} />
      </div>
      {key === null ? null : check.isPending ? (
        <div role="status" aria-label="Checking">
          <SkeletonText lines={2} />
        </div>
      ) : check.isError ? (
        <ErrorBlock error={check.error} what="The answer" onRetry={() => void check.refetch()} />
      ) : (
        <Answer result={check.data} />
      )}
    </GlassPanel>
  );
}

function Answer({ result }: { result: AccessCheckResult }) {
  return (
    <div role="status" className="flex min-w-0 flex-col gap-3">
      <Banner tone={result.allowed ? "leaf" : "ember"} icon={result.allowed ? "checkCircle" : "xCircle"} title={result.allowed ? "Yes, allowed." : "No, not allowed."}>
        {keyLabel(result.permission_key)}
        {result.scope ? ` · they reach ${scopeLabelLower(result.scope)}` : ""}
      </Banner>
      {result.reasons.length > 0 ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {result.reasons.map((reason) => (
            <li key={reason} className="t-body-sm flex items-start gap-2 text-ink-2">
              <Badge size="sm" outline>
                Rule
              </Badge>
              <span className="min-w-0">{reason}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

const scopeLabelLower = (scope: Scope): string => ({ own: "their own records", team: "their team", branch: "their branch", company: "the whole company" })[scope];
