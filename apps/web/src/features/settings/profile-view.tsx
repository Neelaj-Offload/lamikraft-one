"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { ErrorState, Loading } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { settingsMessages } from "@/messages/settings";
import { fetchMe } from "./api";
import { PasswordSection } from "./password-section";
import { PreferencesSection } from "./preferences-section";
import { SettingsAreaNav } from "./settings-hub";
import type { Me } from "./types";

const m = settingsMessages.profile;

/** The read-only account facts MeRead carries; empty values are dropped. */
export function accountItems(me: Me): KeyValue[] {
  const f = m.fields;
  const items: (KeyValue | null)[] = [
    { term: f.displayName, description: me.user.display_name },
    me.user.full_name && me.user.full_name !== me.user.display_name ? { term: f.fullName, description: me.user.full_name } : null,
    me.user.email ? { term: f.email, description: me.user.email } : null,
    me.membership.job_title ? { term: f.jobTitle, description: me.membership.job_title } : null,
    { term: f.roles, description: me.membership.roles.map((role) => role.name).join(", ") || m.none },
    me.membership.company ? { term: f.company, description: me.membership.company.display_name } : null,
    me.membership.branches.length ? { term: f.branches, description: me.membership.branches.map((branch) => `${branch.name} (${branch.code})`).join(", ") } : null,
    me.membership.teams.length ? { term: f.teams, description: me.membership.teams.map((team) => team.name).join(", ") } : null,
    me.membership.manager ? { term: f.manager, description: me.membership.manager.display_name } : null,
    me.membership.joined_on ? { term: f.joinedOn, description: <LocalDate value={me.membership.joined_on} /> } : null,
    me.time_zone ? { term: f.timeZone, description: me.time_zone, mono: true } : null,
    me.locale ? { term: f.locale, description: me.locale, mono: true } : null,
    me.membership.status ? { term: f.status, description: me.membership.status } : null,
  ];
  return items.filter((item): item is KeyValue => item !== null);
}

function SessionSection({ me }: { me: Me }) {
  if (!me.session) return null;
  const s = m.session;
  return (
    <SectionCard title={s.title} description={s.intro} actions={<Badge tone="success">{s.current}</Badge>}>
      <KeyValueGrid
        items={[
          { term: s.authMethod, description: me.session.auth_method || m.none, mono: true },
          { term: s.createdAt, description: <LocalDateTime value={me.session.created_at} /> },
          { term: s.idleExpires, description: <LocalDateTime value={me.session.idle_expires_at} /> },
          { term: s.absoluteExpires, description: <LocalDateTime value={me.session.absolute_expires_at} /> },
        ]}
        columns={2}
      />
    </SectionCard>
  );
}

export function ProfileView() {
  const query = useQuery({ queryKey: queryKeys.identity.me(), queryFn: ({ signal }) => fetchMe(signal) });

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav />} />
      {query.isPending ? (
        <Loading label={m.what} variant="detail" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.what} onRetry={() => void query.refetch()} />
      ) : (
        <SectionCard title={m.account} description={m.accountIntro}>
          <KeyValueGrid items={accountItems(query.data)} />
        </SectionCard>
      )}
      <PreferencesSection />
      <PasswordSection />
      {query.data ? <SessionSection me={query.data} /> : null}
    </div>
  );
}
