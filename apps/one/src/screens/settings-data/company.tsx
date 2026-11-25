"use client";

import { useState } from "react";
import { flattenValue, type FlatValue } from "@/features/settings/setting-model";
import type { SettingRead } from "@/features/settings/types";
import { useSession } from "@/lib/session/context";
import { hasOrgPermission, useCompanySettings, useSettingRevisions } from "~/data/settings-data";
import { Page, PageHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted, QueryView } from "~/shell/states";
import { Badge, Button, DateText, EmptyState, GlassPanel, KeyValue, SkeletonText, Tabs, Timeline, type KeyValueItem } from "~/ui";
import { SettingEditor } from "./company-editor";
import { asRoute, Block, entityLabel, Mono, Quiet, sayQuotation, SETTINGS_CRUMBS } from "./shared";

/**
 * Company settings: what is printed on documents and assumed for new quotations. One view per
 * setting (`?view=<key>`), its values on the left and its versions on the right.
 */

const LABEL: Record<string, string> = {
  company_identity: "Identity",
  bank_details: "Bank accounts",
  document_terms: "Document terms",
  quote_defaults: "Quotation defaults",
  brands: "Brands",
  security_policy: "Sign-in policy",
  challan_defaults: "Challan defaults",
  e_invoice: "E-invoice",
  finance_account_mapping: "Account mapping",
  finance_policy: "Finance policy",
  inventory_policy: "Stock policy",
  procurement_policy: "Purchasing policy",
  ai_routing: "AI routing",
};

/** The settings people open most come first; the rest follow in the order the server lists them. */
const ORDER = ["company_identity", "bank_details", "document_terms", "quote_defaults", "brands", "challan_defaults", "security_policy"];
const rank = (key: string) => {
  const index = ORDER.indexOf(key);
  return index === -1 ? ORDER.length : index;
};

const LEAD: Record<string, string> = {
  company_identity: "The names, address, tax numbers and contacts printed at the top of every document.",
  bank_details: "The accounts printed on documents so customers know where to pay.",
  document_terms: "The terms printed on quotations and challans, and the footer under every document.",
  quote_defaults: "What a new quotation starts with before anyone changes it.",
  brands: "The brand letters that appear in document numbers and headers.",
  security_policy: "Who must use two-step sign-in.",
};

/** Bank details are restricted values: the wrapper is marked so masked screenshots black them out. */
const RESTRICTED: ReadonlySet<string> = new Set(["bank_details"]);

const labelOf = (setting: Pick<SettingRead, "key">) => LABEL[setting.key] ?? entityLabel(setting.key);
/** A branch-scoped setting shares its key with the company one, so the branch is part of its view id. */
const idOf = (setting: Pick<SettingRead, "key" | "branch_id">) => (setting.branch_id ? `${setting.key}@${setting.branch_id}` : setting.key);
const viewHref = (id: string) => asRoute(`/settings/company?view=${encodeURIComponent(id)}`);

interface ValueGroup {
  title: string | null;
  rows: FlatValue[];
}

/** "Account 1 · IFSC" rows gather under "Account 1"; top-level rows stay in an untitled first group. */
function groupRows(rows: FlatValue[]): ValueGroup[] {
  const groups: ValueGroup[] = [];
  for (const row of rows) {
    const cut = row.term.indexOf(" · ");
    const title = cut === -1 ? null : row.term.slice(0, cut);
    const term = cut === -1 ? row.term : row.term.slice(cut + 3);
    let group = groups.find((candidate) => candidate.title === title);
    if (!group) {
      group = { title, rows: [] };
      groups.push(group);
    }
    group.rows.push({ ...row, term });
  }
  return groups;
}

function valueItems(rows: FlatValue[], missing: ReadonlySet<string>): KeyValueItem[] {
  return rows.map((row) => {
    const absent = row.value === null || missing.has(row.path);
    return {
      label: sayQuotation(row.term),
      value: absent ? (
        <Quiet>Not set</Quiet>
      ) : typeof row.value === "boolean" ? (
        row.value ? "Yes" : "No"
      ) : row.mono ? (
        <Mono>{row.value}</Mono>
      ) : (
        <span className="whitespace-pre-line [overflow-wrap:anywhere]">{row.value}</span>
      ),
    };
  });
}

function Versions({ setting }: { setting: SettingRead }) {
  const query = useSettingRevisions(setting.key);
  return (
    <GlassPanel title="Versions" titleAs="h2" eyebrow={setting.version === 0 ? "Default values" : `Now on version ${setting.version}`}>
      <QueryView
        query={query}
        what="The change history"
        loading={<SkeletonText lines={4} />}
        isEmpty={(revisions) => revisions.length === 0}
        empty={<p className="t-body-sm text-ink-3">No change has been saved yet. The default values apply.</p>}
      >
        {(revisions) => (
          <Timeline
            label={`Versions of ${labelOf(setting).toLowerCase()}`}
            items={revisions.map((revision) => ({
              id: String(revision.version),
              title: `Version ${revision.version}`,
              meta: (
                <>
                  <DateText value={revision.changed_at} style="dayTime" />
                  {revision.changed_by ? (
                    <>
                      {" · "}
                      <Mono>{revision.changed_by}</Mono>
                    </>
                  ) : null}
                </>
              ),
              body: revision.change_reason ?? <Quiet>No reason given</Quiet>,
              icon: "history" as const,
            }))}
          />
        )}
      </QueryView>
    </GlassPanel>
  );
}

function SettingView({ setting }: { setting: SettingRead }) {
  const [editing, setEditing] = useState(false);
  const title = labelOf(setting);
  const rows = flattenValue(setting.value, setting.redacted_fields);
  const missing = new Set(setting.not_configured_fields);
  const groups = groupRows(rows);
  const canUpdate = setting.capabilities.update?.allowed === true;

  return (
    <Split
      main={
        <GlassPanel
          padding="lg"
          className="rise"
          title={title}
          titleAs="h2"
          action={
            canUpdate ? (
              <Button iconLeft="edit" onPress={() => setEditing(true)}>
                Edit {title.toLowerCase()}
              </Button>
            ) : undefined
          }
        >
          <div className="flex min-w-0 flex-col gap-6">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <p className="t-body text-ink-2">{LEAD[setting.key] ?? sayQuotation(setting.description)}</p>
              {setting.configured ? null : (
                <Badge tone="amber" icon="alert" size="sm">
                  Not filled in yet
                </Badge>
              )}
            </div>
            {rows.length === 0 ? (
              <EmptyState
                compact
                icon="building"
                title="Nothing set here yet"
                text={canUpdate ? "Fill it in so documents carry the right details." : "Ask a workspace admin to fill it in."}
                actions={
                  canUpdate ? (
                    <Button variant="secondary" size="sm" iconLeft="edit" onPress={() => setEditing(true)}>
                      Fill in {title.toLowerCase()}
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <div data-restricted={RESTRICTED.has(setting.key) ? "true" : undefined} className="flex min-w-0 flex-col gap-6">
                {groups.map((group) =>
                  group.title ? (
                    <Block key={group.title} title={sayQuotation(group.title)}>
                      <KeyValue items={valueItems(group.rows, missing)} />
                    </Block>
                  ) : (
                    <KeyValue key="top" items={valueItems(group.rows, missing)} />
                  ),
                )}
              </div>
            )}
            {setting.redacted_fields.length > 0 ? (
              <p className="t-body-sm text-ink-3">
                {setting.redacted_fields.length === 1 ? "1 restricted value is hidden from your role." : `${setting.redacted_fields.length} restricted values are hidden from your role.`}
              </p>
            ) : null}
            {setting.updated_at ? (
              <p className="t-caption text-ink-3">
                Last changed <DateText value={setting.updated_at} style="dayTime" />
              </p>
            ) : null}
          </div>
          {editing ? <SettingEditor key={setting.version} setting={setting} title={title} isOpen={editing} onClose={() => setEditing(false)} /> : null}
        </GlassPanel>
      }
      aside={<Versions key={setting.key} setting={setting} />}
    />
  );
}

export function CompanySettings({ view }: { view: string | null }) {
  const { permissionKeys } = useSession();
  const allowed = hasOrgPermission(permissionKeys);
  const query = useCompanySettings(allowed);

  const header = (
    <PageHeader breadcrumb={SETTINGS_CRUMBS} title="Company" lead="What Lamikraft One prints on your documents and assumes for new quotations. Every change is kept as a version." />
  );

  if (!allowed) {
    return (
      <Page>
        {header}
        <NotPermitted what="Company settings" icon="building" />
      </Page>
    );
  }
  if (query.isPending) {
    return (
      <Page>
        {header}
        <LoadingBlock lines={8} label="Loading the company settings" />
      </Page>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Page>
        {header}
        <ErrorBlock error={query.error} what="Company settings" onRetry={() => void query.refetch()} />
      </Page>
    );
  }
  const settings = [...query.data].sort((a, b) => rank(a.key) - rank(b.key));
  if (settings.length === 0) {
    return (
      <Page>
        {header}
        <GlassPanel>
          <EmptyState icon="lock" title="No company setting is open to your role" text="Ask a workspace admin if you need to see or change one." />
        </GlassPanel>
      </Page>
    );
  }
  const selected = settings.find((setting) => idOf(setting) === view) ?? settings[0]!;

  return (
    <Page>
      {header}
      <Tabs label="Company settings" selectedKey={idOf(selected)} tabs={settings.map((setting) => ({ id: idOf(setting), label: labelOf(setting), href: viewHref(idOf(setting)) }))} />
      <SettingView key={idOf(selected)} setting={selected} />
    </Page>
  );
}
