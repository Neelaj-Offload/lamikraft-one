"use client";

import { useMemo, useState, type ReactNode } from "react";
import type { Delivery, PermissionInfo, RoleSummary } from "@/app/(app)/settings/_lib/types";
import { PEOPLE_SEARCH_MIN_CHARS, usePeopleSearch } from "~/data/settings-access";
import { Badge, Banner, Button, CheckboxGroup, ComboBox, GlassPanel, Skeleton, TextField, toast } from "~/ui";
import { humanise, MEMBER_LABEL, MEMBER_TONE, REQUEST_LABEL, REQUEST_TONE } from "./labels";

/** Small pieces the people-and-access screens share. */

export function MemberStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={MEMBER_TONE[status] ?? "neutral"} dot>
      {MEMBER_LABEL[status] ?? humanise(status)}
    </Badge>
  );
}

export function RequestStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={REQUEST_TONE[status] ?? "neutral"} dot>
      {REQUEST_LABEL[status] ?? humanise(status)}
    </Badge>
  );
}

/** A failed command, said once above the form or the list it belongs to. */
export function Failure({ title, children, onClose }: { title: string; children: ReactNode; onClose?: () => void }) {
  return (
    <Banner tone="ember" title={title} onClose={onClose}>
      {children}
    </Banner>
  );
}

/**
 * What happened to an invitation or reset link. While email delivery is simulated the server
 * returns the one-time link itself, shown here once so an admin can hand it over.
 */
export function DeliveryNote({ delivery, what }: { delivery: Delivery; what: "invitation" | "reset" }) {
  const copy = async () => {
    if (!delivery.manual_link) return;
    try {
      await navigator.clipboard.writeText(delivery.manual_link);
      toast.success("Link copied");
    } catch {
      toast.error("Could not copy", { description: "Select the link and copy it by hand." });
    }
  };
  return (
    <GlassPanel variant="solid" padding="md" role="status" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {delivery.mode === "demo_outbox" ? <Badge tone="amber">Demo</Badge> : null}
        <p className="t-label text-ink">{delivery.label}</p>
      </div>
      {delivery.manual_link ? (
        <>
          <p className="t-body-sm text-ink-2">Copy this {what} link now and hand it over. It is shown only this once.</p>
          <div className="flex min-w-0 flex-wrap items-end gap-2">
            <TextField
              className="min-w-0 flex-1 basis-64"
              label={what === "invitation" ? "Invitation link" : "Reset link"}
              value={delivery.manual_link}
              isReadOnly
            />
            <Button variant="secondary" iconLeft="copy" onPress={() => void copy()}>
              Copy link
            </Button>
          </div>
        </>
      ) : null}
      {delivery.outbox_file ? (
        <p className="t-caption text-ink-3">
          Written to the demo outbox as <span className="lk-mono break-all">{delivery.outbox_file}</span>.
        </p>
      ) : null}
    </GlassPanel>
  );
}

/** A colleague picker over the people directory: names and job titles only, never contact details. */
export function PeoplePicker({
  label,
  optional,
  value,
  onChange,
  help,
  error,
}: {
  label: string;
  optional?: boolean;
  value: string | null;
  onChange: (userId: string | null) => void;
  help?: ReactNode;
  error?: ReactNode;
}) {
  const [text, setText] = useState("");
  const { hits, isSearching, ready } = usePeopleSearch(text);
  return (
    <ComboBox
      label={label}
      optional={optional}
      placeholder="Type at least two letters of a name"
      items={hits.map((hit) => ({ id: hit.id, label: hit.name, description: hit.detail ?? undefined }))}
      inputValue={text}
      onInputChange={(next) => {
        setText(next);
        if (value && next.trim() === "") onChange(null);
      }}
      selectedKey={value}
      onSelectionChange={(id) => {
        onChange(id);
        const hit = hits.find((candidate) => candidate.id === id);
        if (hit) setText(hit.name);
      }}
      isLoading={isSearching}
      emptyText={ready ? "No one by that name. Check the spelling." : `Type at least ${PEOPLE_SEARCH_MIN_CHARS} letters.`}
      help={help}
      error={error}
    />
  );
}

const MAX_PERMISSION_MATCHES = 40;

/** Pick one permission from the catalogue by typing part of its key or of what it allows. */
export function PermissionPicker({
  label = "Permission",
  permissions,
  value,
  onChange,
  isLoading = false,
  isRequired,
  help,
  error,
  className,
}: {
  label?: string;
  permissions: readonly Pick<PermissionInfo, "key" | "description">[];
  value: string | null;
  onChange: (key: string | null) => void;
  isLoading?: boolean;
  isRequired?: boolean;
  help?: ReactNode;
  error?: ReactNode;
  className?: string;
}) {
  const [text, setText] = useState(value ?? "");
  const matches = useMemo(() => {
    const needle = text.trim().toLowerCase();
    // With a permission chosen the field shows its key; keep the whole list on offer for a change of mind.
    const all = needle === "" || needle === value?.toLowerCase();
    return permissions
      .filter((permission) => all || permission.key.includes(needle) || permission.description.toLowerCase().includes(needle))
      .slice(0, MAX_PERMISSION_MATCHES)
      .map((permission) => ({ id: permission.key, label: permission.key, description: permission.description || undefined }));
  }, [permissions, text, value]);
  return (
    <ComboBox
      className={className}
      label={label}
      placeholder="For example sales.quote"
      items={matches}
      inputValue={text}
      onInputChange={(next) => {
        setText(next);
        if (value && next.trim() === "") onChange(null);
      }}
      selectedKey={value}
      onSelectionChange={(key) => {
        onChange(key);
        if (key) setText(key);
      }}
      isLoading={isLoading}
      isRequired={isRequired}
      emptyText="No permission matches. Try part of a key, such as quote or stock."
      help={help}
      error={error}
    />
  );
}

/** Tick the roles a person holds. Only roles that can be assigned and are not archived are offered. */
export function RoleChecklist({
  roles,
  isLoading,
  value,
  onChange,
  label = "Roles",
  help,
  error,
  className,
}: {
  roles: readonly RoleSummary[] | undefined;
  isLoading: boolean;
  value: string[];
  onChange: (keys: string[]) => void;
  label?: string;
  help?: ReactNode;
  error?: ReactNode;
  className?: string;
}) {
  const assignable = (roles ?? []).filter((role) => role.is_assignable && !role.archived);
  if (isLoading) {
    return (
      <div className={className} role="status" aria-label="Loading roles">
        <div className="flex flex-col gap-3">
          <Skeleton width={72} height={12} />
          <Skeleton width="60%" height={16} />
          <Skeleton width="48%" height={16} />
          <Skeleton width="54%" height={16} />
        </div>
      </div>
    );
  }
  return (
    <CheckboxGroup
      className={className}
      label={label}
      options={assignable.map((role) => ({
        value: role.key,
        label: role.kind === "custom" ? `${role.name} (custom)` : role.name,
        description: role.description ?? undefined,
      }))}
      value={value}
      onChange={onChange}
      help={help}
      error={error}
    />
  );
}

/** Buttons at the end of a table row; they wrap instead of forcing the table wider. */
export function RowActions({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center justify-start gap-2">{children}</div>;
}
