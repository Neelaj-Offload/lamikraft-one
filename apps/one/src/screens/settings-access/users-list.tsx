"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { USERS_PAGE_SIZE } from "@/app/(app)/settings/_lib/api";
import type { UserListItem } from "@/app/(app)/settings/_lib/types";
import { userListHref, type UserListState } from "@/app/(app)/settings/_lib/user-list-state";
import { useRoles, useUsers } from "~/data/settings-access";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Avatar,
  Badge,
  Button,
  ButtonLink,
  ChipGroup,
  ChipLink,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  Menu,
  PageSummary,
  Pagination,
  SearchField,
  SegmentedLinks,
  TableFooter,
  type Column,
  type MenuItem,
} from "~/ui";
import { SETTINGS_CRUMB, userHref } from "./labels";
import { MemberStatusBadge } from "./parts";

const href = (state: UserListState) => userListHref(state) as Route;

const COLUMNS: Column<UserListItem>[] = [
  {
    key: "name",
    header: "Name",
    primary: true,
    cell: (person) => (
      <span className="flex min-w-0 items-center gap-3">
        <Avatar name={person.display_name} size="sm" />
        <span className="flex min-w-0 flex-col">
          <span className="t-label truncate text-ink" title={person.display_name}>
            {person.display_name}
          </span>
          <span className="t-caption truncate text-ink-3" title={person.email ?? undefined}>
            {[person.job_title, person.email].filter(Boolean).join(" · ") || "No email on file"}
          </span>
        </span>
      </span>
    ),
  },
  {
    key: "roles",
    header: "Roles",
    cell: (person) =>
      person.roles.length > 0 ? (
        <span className="flex flex-wrap gap-1">
          {person.roles.map((role) => (
            <Badge key={role.key} outline size="sm">
              {role.name}
            </Badge>
          ))}
        </span>
      ) : (
        <span className="text-ink-3">No role</span>
      ),
  },
  { key: "status", header: "Status", cell: (person) => <MemberStatusBadge status={person.status} /> },
  {
    key: "two-step",
    header: "Two-step sign-in",
    mobileLabel: "Two-step",
    hideOnMobile: true,
    cell: (person) =>
      person.mfa_enrolled ? (
        <Badge tone="leaf" icon="shield" size="sm">
          On
        </Badge>
      ) : (
        <span className="text-ink-3">Off</span>
      ),
  },
  {
    key: "last",
    header: "Last sign-in",
    cell: (person) => (person.last_login_at ? <DateText value={person.last_login_at} style="relative" className="text-ink-3" /> : <span className="text-ink-3">Never</span>),
  },
];

/** Everyone with access to the workspace. Search, status, role and page all live in the URL. */
export function UsersList({ state }: { state: UserListState }) {
  const router = useRouter();
  const query = useUsers(state);
  const roles = useRoles();
  const go = (next: Partial<UserListState>) => router.push(href({ ...state, offset: 0, ...next }));
  const filtered = Boolean(state.q || state.status || state.role);
  const roleName = state.role ? (roles.data?.items.find((role) => role.key === state.role)?.name ?? state.role) : null;

  const roleMenu: MenuItem[] = [
    { id: "any", label: "Any role", icon: state.role ? undefined : "check", href: href({ ...state, role: null, offset: 0 }) },
    ...(roles.data?.items ?? []).map((role) => ({
      id: role.key,
      label: role.name,
      icon: state.role === role.key ? ("check" as const) : undefined,
      href: href({ ...state, role: role.key, offset: 0 }),
    })),
  ];

  const limit = query.data?.limit || USERS_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor((query.data?.offset ?? state.offset) / limit) + 1;

  return (
    <Page>
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, { label: "People" }]}
        title="People"
        lead="Everyone who can sign in to this workspace. Nobody is ever deleted: a person you deactivate keeps their name on past work."
        actions={
          <ButtonLink href={"/settings/users/invite" as Route} iconLeft="userPlus">
            Invite someone
          </ButtonLink>
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={{ "--i": 1 } as React.CSSProperties}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SegmentedLinks
            label="Show"
            glass
            value={state.status ?? "all"}
            options={[
              { value: "all", label: "Everyone", href: href({ ...state, status: null, offset: 0 }) },
              { value: "active", label: "Active", href: href({ ...state, status: "active", offset: 0 }) },
              { value: "invited", label: "Invited", href: href({ ...state, status: "invited", offset: 0 }) },
              { value: "deactivated", label: "Inactive", href: href({ ...state, status: "deactivated", offset: 0 }) },
            ]}
          />
          <SearchField
            key={state.q ?? ""}
            className="min-w-0 flex-1 basis-64"
            label="Search people"
            placeholder="Name, email or job title"
            defaultValue={state.q ?? ""}
            onSubmit={(q) => go({ q: q.trim() || null })}
            onChange={(q) => {
              if (q === "" && state.q) go({ q: null });
            }}
          />
          <Menu
            label="Filter by role"
            items={roleMenu}
            placement="bottom end"
            trigger={
              <Button variant="secondary" iconLeft="filter">
                Role
              </Button>
            }
          />
        </div>
        {roleName ? (
          <ChipGroup label="Filters in use">
            <ChipLink href={href({ ...state, role: null, offset: 0 })} selected icon="x">
              {roleName}
            </ChipLink>
          </ChipGroup>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="People" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise" style={{ "--i": 2 } as React.CSSProperties}>
          <DataTable
            label="People"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(person) => person.user_id}
            rowHref={(person) => userHref(person.user_id)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No one matches"
                  text="Nobody fits this search and these filters. Clear them to see everyone."
                  actions={
                    <ButtonLink variant="secondary" size="sm" href={"/settings/users" as Route}>
                      Clear search and filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="users"
                  title="No one here yet"
                  text="Invite the first person. They get a link to choose a password and start with the roles you pick."
                  actions={
                    <ButtonLink href={"/settings/users/invite" as Route} iconLeft="userPlus">
                      Invite someone
                    </ButtonLink>
                  }
                />
              )
            }
            footer={
              query.data && total > 0 ? (
                <TableFooter
                  left={<PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="people" />}
                  right={pages > 1 ? <Pagination label="People pages" page={page} pages={pages} hrefFor={(target) => href({ ...state, offset: (target - 1) * limit })} /> : null}
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
    </Page>
  );
}
