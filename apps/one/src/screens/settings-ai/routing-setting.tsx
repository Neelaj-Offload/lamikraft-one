"use client";

import { useId, useState, type FormEvent } from "react";
import {
  draftFrom,
  emptyItem,
  flattenValue,
  formFor,
  labelFor,
  valueFrom,
  visibleForm,
  type DraftRecord,
  type DraftScalar,
  type FieldDef,
  type FlatValue,
  type SettingDraft,
} from "@/features/settings/setting-model";
import type { SettingRead } from "@/features/settings/types";
import { AI_ROUTING_SETTING, OFFLINE_NOTE, useSaveSetting, useSetting, useSettingRevisions } from "~/data/settings-ai";
import { PageSection } from "~/shell/page";
import { LoadingBlock, QueryView } from "~/shell/states";
import { Badge, Banner, Button, DateText, Drawer, EmptyState, GlassPanel, KeyValue, Select, Switch, Textarea, TextField, Timeline, type KeyValueItem } from "~/ui";

/**
 * The saved `ai_routing` setting: its values, its history, and the editor. Shown only to people
 * the server says may manage routing; the Edit button also waits for the setting's own
 * `capabilities.update`.
 */
export function SavedRouting() {
  const query = useSetting(AI_ROUTING_SETTING);
  return (
    <PageSection
      title="Saved routing"
      description="The setting behind the values above. A model left empty uses the server's own default for that task."
      index={4}
    >
      <QueryView query={query} what="The saved routing" loading={<LoadingBlock lines={5} label="Loading the saved routing" />}>
        {(setting) => <SettingPanel setting={setting} />}
      </QueryView>
    </PageSection>
  );
}

// ---- reading the value ----

interface ValueGroup {
  key: string;
  title: string;
  items: KeyValueItem[];
}

const topKey = (path: string) => path.split(/[.[]/, 1)[0] ?? path;

/** Section names the generic labeller cannot spell (an acronym). */
const GROUP_TITLE: Record<string, string> = { dpdp: "Data protection (DPDP)" };

/** Rows grouped by the setting's top-level sections, so thirty values read as five short lists. */
function groupValues(setting: SettingRead): ValueGroup[] {
  const missing = new Set(setting.not_configured_fields);
  const groups = new Map<string, ValueGroup>();
  const general: ValueGroup = { key: "", title: "General", items: [] };
  for (const row of flattenValue(setting.value, setting.redacted_fields)) {
    const key = topKey(row.path);
    const nested = row.path !== key;
    const group = nested ? (groups.get(key) ?? { key, title: GROUP_TITLE[key] ?? labelFor(key), items: [] }) : general;
    if (nested) groups.set(key, group);
    group.items.push({ label: nested ? termWithin(row, labelFor(key)) : row.term, value: valueText(row, missing), mono: row.mono && row.value !== null });
  }
  return [...(general.items.length > 0 ? [general] : []), ...groups.values()];
}

/** "Models · Phrasing" inside the Models group is just "Phrasing"; "Prices 2 · Input" is "2 · Input". */
function termWithin(row: FlatValue, groupTitle: string): string {
  if (!row.term.startsWith(groupTitle)) return row.term;
  const rest = row.term.slice(groupTitle.length).replace(/^\s*·?\s*/, "");
  return rest || row.term;
}

function valueText(row: FlatValue, missing: ReadonlySet<string>) {
  if (row.value === null || missing.has(row.path)) return <span className="text-ink-3">Not set</span>;
  if (typeof row.value === "boolean") return row.value ? "Yes" : "No";
  return row.value;
}

function SettingPanel({ setting }: { setting: SettingRead }) {
  const [editing, setEditing] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const groups = groupValues(setting);
  const canUpdate = setting.capabilities.update?.allowed === true;
  const hidden = setting.redacted_fields.length;

  return (
    <GlassPanel padding="lg" className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="t-body text-ink">{setting.description}</p>
          <p className="t-caption flex flex-wrap items-center gap-x-2 gap-y-1 text-ink-3">
            <span className="lk-mono">{setting.key}</span>
            <span aria-hidden="true">·</span>
            <span>{setting.version === 0 ? "Default values, never changed" : `Version ${setting.version}`}</span>
            {setting.updated_at ? (
              <>
                <span aria-hidden="true">·</span>
                <span>
                  Updated <DateText value={setting.updated_at} style="dayTime" />
                </span>
              </>
            ) : null}
            {setting.configured ? null : (
              <Badge size="sm" tone="amber">
                Not configured
              </Badge>
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" iconLeft="history" onPress={() => setHistoryOpen(true)}>
            See history
          </Button>
          {canUpdate ? (
            <Button variant="primary" iconLeft="edit" onPress={() => setEditing(true)}>
              Edit routing
            </Button>
          ) : null}
        </div>
      </div>

      {groups.length === 0 ? (
        <EmptyState compact icon="sliders" title="This setting has no values yet" text={canUpdate ? "Edit routing to choose models, quotas and prices." : undefined} />
      ) : (
        <div className="grid gap-x-10 gap-y-6 md:grid-cols-2">
          {groups.map((group) => (
            <section key={group.key} className="flex min-w-0 flex-col gap-2">
              <h3 className="t-h4">{group.title}</h3>
              <KeyValue rows items={group.items} />
            </section>
          ))}
        </div>
      )}
      {hidden > 0 ? (
        <p className="t-body-sm text-ink-3">{hidden === 1 ? "1 restricted value is hidden from you." : `${hidden} restricted values are hidden from you.`}</p>
      ) : null}

      <HistoryDrawer settingKey={setting.key} isOpen={historyOpen} onOpenChange={setHistoryOpen} />
      {editing ? <RoutingEditor key={setting.version} setting={setting} onClose={() => setEditing(false)} /> : null}
    </GlassPanel>
  );
}

// ---- history ----

function HistoryDrawer({ settingKey, isOpen, onOpenChange }: { settingKey: string; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const query = useSettingRevisions(settingKey, isOpen);
  return (
    <Drawer isOpen={isOpen} onOpenChange={onOpenChange} title="Routing history" description="Every saved version, newest first, with who changed it and why.">
      <QueryView
        query={query}
        what="The change history"
        isEmpty={(revisions) => revisions.length === 0}
        empty={<EmptyState compact icon="history" title="Nothing has been changed yet" text="The default values apply until someone saves a version." />}
      >
        {(revisions) => (
          <Timeline
            label="Routing history"
            items={revisions.map((revision) => ({
              id: String(revision.version),
              title: `Version ${revision.version}`,
              meta: <DateText value={revision.changed_at} style="dayTime" />,
              icon: "edit" as const,
              body: (
                <span className="flex flex-col gap-1">
                  <span>{revision.change_reason ?? <span className="text-ink-3">No reason given</span>}</span>
                  {revision.changed_by ? <span className="t-code-sm lk-mono break-all text-ink-3">Changed by {revision.changed_by}</span> : null}
                </span>
              ),
            }))}
          />
        )}
      </QueryView>
    </Drawer>
  );
}

// ---- editor ----

/** One control per field kind. Values stay strings; only declared integers are converted on save. */
function Field({ field, value, error, onChange }: { field: FieldDef; value: DraftScalar | undefined; error?: string; onChange: (value: DraftScalar) => void }) {
  const text = typeof value === "string" ? value : "";
  const optional = field.kind !== "switch" && !field.required;
  switch (field.kind) {
    case "switch":
      return <Switch label={field.label} isSelected={value === true} onChange={onChange} />;
    case "select":
      return (
        <Select
          label={field.label}
          optional={optional}
          options={(field.options ?? []).map((option) => ({ value: option.id, label: option.label }))}
          value={text || null}
          onChange={onChange}
          help={field.description}
          error={error}
          isRequired={field.required}
        />
      );
    case "textarea":
    case "lines":
      return (
        <Textarea
          label={field.label}
          optional={optional}
          value={text}
          onChange={onChange}
          rows={field.kind === "lines" ? 4 : 6}
          help={field.description}
          error={error}
          maxLength={field.maxLength}
          isRequired={field.required}
        />
      );
    default:
      return (
        <TextField
          label={field.label}
          optional={optional}
          value={text}
          onChange={onChange}
          inputMode={field.kind === "integer" ? "numeric" : field.kind === "decimal" ? "decimal" : undefined}
          help={field.kind === "csv" ? (field.description ?? "Separate values with commas.") : field.description}
          error={error}
          maxLength={field.maxLength}
          isRequired={field.required}
        />
      );
  }
}

function FieldGrid({
  fields,
  record,
  prefix,
  errors,
  onChange,
}: {
  fields: readonly FieldDef[];
  record: DraftRecord;
  prefix: string;
  errors: Record<string, string>;
  onChange: (name: string, value: DraftScalar) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {fields.map((field) => (
        <div key={field.name} className={field.kind === "textarea" || field.kind === "lines" || field.kind === "switch" ? "sm:col-span-2" : undefined}>
          <Field field={field} value={record[field.name]} error={errors[`${prefix}${field.name}`]} onChange={(value) => onChange(field.name, value)} />
        </div>
      ))}
    </div>
  );
}

/**
 * Edits the setting in a drawer, with a form built from its shape. Saved with the version on
 * screen: if someone else saved first, nothing is overwritten and the drawer offers the latest
 * version instead. Server validation lands on the field it is about.
 */
function RoutingEditor({ setting, onClose }: { setting: SettingRead; onClose: () => void }) {
  const formId = useId();
  const command = useSaveSetting(setting);
  const form = visibleForm(formFor(setting), setting.redacted_fields);
  const [draft, setDraft] = useState<SettingDraft>(() => draftFrom(form, setting.value));
  const [reason, setReason] = useState("");
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});
  const errors = { ...command.fieldErrors, ...localErrors };
  const editable = form.fields.length + form.groups.length + form.lists.length > 0;
  const reasonError = errors["body.change_reason"] ?? errors.change_reason;

  const setField = (name: string, value: DraftScalar) => setDraft((current) => ({ ...current, fields: { ...current.fields, [name]: value } }));
  const setGroupField = (group: string, name: string, value: DraftScalar) =>
    setDraft((current) => ({ ...current, groups: { ...current.groups, [group]: { ...current.groups[group], [name]: value } } }));
  const setListField = (list: string, index: number, name: string, value: DraftScalar) =>
    setDraft((current) => ({
      ...current,
      lists: { ...current.lists, [list]: (current.lists[list] ?? []).map((item, i) => (i === index ? { ...item, [name]: value } : item)) },
    }));
  const addItem = (list: string, item: DraftRecord) => setDraft((current) => ({ ...current, lists: { ...current.lists, [list]: [...(current.lists[list] ?? []), item] } }));
  const removeItem = (list: string, index: number) =>
    setDraft((current) => ({ ...current, lists: { ...current.lists, [list]: (current.lists[list] ?? []).filter((_, i) => i !== index) } }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (command.pending || command.offline || !editable) return;
    const result = valueFrom(form, draft, setting.value, setting.redacted_fields);
    setLocalErrors(result.errors);
    if (Object.keys(result.errors).length > 0) return;
    if ((await command.save(result.value, reason)) === "saved") onClose();
  };

  const conflict = command.conflict;

  return (
    <Drawer
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Edit routing"
      description="Saved as a new version. Assistant requests that start after you save use it."
      width="lg"
      footer={
        <>
          <Button variant="ghost" onPress={onClose} isDisabled={command.pending}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={command.pending} isDisabled={command.offline || !editable}>
            Save routing
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-6">
        {command.offline ? <Banner tone="amber">{OFFLINE_NOTE}</Banner> : null}
        {conflict ? (
          <Banner
            tone="amber"
            title="Someone saved this setting while you were editing."
            action={
              <Button variant="secondary" size="sm" onPress={() => void command.reload().then(onClose)}>
                Load latest version
              </Button>
            }
          >
            Nothing was overwritten.{conflict.changedBy ? ` Last changed by ${conflict.changedBy}.` : ""} Load the latest version, then make your change again.
          </Banner>
        ) : null}
        {!editable ? <Banner tone="neutral">Nothing in this setting can be edited from here yet.</Banner> : null}

        {form.fields.length > 0 ? (
          <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
            <legend className="t-h4 mb-3 p-0">General</legend>
            <FieldGrid fields={form.fields} record={draft.fields} prefix="" errors={errors} onChange={setField} />
          </fieldset>
        ) : null}

        {form.groups.map((group) => (
          <fieldset key={group.name} className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
            <legend className="t-h4 mb-3 p-0">{group.label}</legend>
            <FieldGrid
              fields={group.fields}
              record={draft.groups[group.name] ?? {}}
              prefix={`${group.name}.`}
              errors={errors}
              onChange={(name, value) => setGroupField(group.name, name, value)}
            />
          </fieldset>
        ))}

        {form.lists.map((list) => {
          const items = draft.lists[list.name] ?? [];
          return (
            <fieldset key={list.name} className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0">
              <legend className="t-h4 mb-3 p-0">{list.label}</legend>
              {errors[list.name] ? (
                <p className="t-body-sm text-ember-text" role="alert">
                  {errors[list.name]}
                </p>
              ) : null}
              {items.map((item, index) => (
                <GlassPanel key={index} variant="outline" padding="sm" className="flex flex-col gap-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="t-label text-ink">
                      {list.label} {index + 1}
                    </span>
                    <Button size="sm" variant="ghost" iconLeft="trash" onPress={() => removeItem(list.name, index)}>
                      Remove {list.itemLabel}
                    </Button>
                  </div>
                  <FieldGrid
                    fields={list.fields}
                    record={item}
                    prefix={`${list.name}[${index}].`}
                    errors={errors}
                    onChange={(name, value) => setListField(list.name, index, name, value)}
                  />
                </GlassPanel>
              ))}
              {list.max === undefined || items.length < list.max ? (
                <div>
                  <Button variant="secondary" size="sm" iconLeft="plus" onPress={() => addItem(list.name, emptyItem(list))}>
                    Add {list.itemLabel}
                  </Button>
                </div>
              ) : null}
            </fieldset>
          );
        })}

        <Textarea
          label="Reason for the change"
          optional
          value={reason}
          onChange={setReason}
          help="Kept with this version in the history."
          error={reasonError}
          maxLength={500}
          rows={2}
        />
      </form>
    </Drawer>
  );
}
