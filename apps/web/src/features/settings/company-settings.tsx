"use client";

import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { settingsMessages } from "@/messages/settings";
import { fetchSettings } from "./api";
import { SettingCard } from "./setting-card";
import { SettingsAreaNav } from "./settings-hub";

const m = settingsMessages.company;

export function hasOrgPermission(permissionKeys: ReadonlySet<string>): boolean {
  for (const key of permissionKeys) if (key.startsWith("org.")) return true;
  return false;
}

/** Company settings: one card per `SettingRead` the actor may read. */
export function CompanySettings() {
  const { permissionKeys } = useSession();
  const allowed = hasOrgPermission(permissionKeys);
  const query = useQuery({ queryKey: queryKeys.org.settings(), queryFn: ({ signal }) => fetchSettings(signal), enabled: allowed });

  if (!allowed) return <PermissionDenied area={m.area} />;

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav />} />
      {query.isPending ? (
        <Loading label={m.what} variant="detail" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.what} onRetry={() => void query.refetch()} />
      ) : query.data.length === 0 ? (
        <EmptyState title={m.emptyTitle}>{m.emptyBody}</EmptyState>
      ) : (
        query.data.map((setting) => <SettingCard key={`${setting.key}:${setting.branch_id ?? ""}`} setting={setting} />)
      )}
    </div>
  );
}
