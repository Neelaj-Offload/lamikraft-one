"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { updateSetting } from "@/features/settings/api";
import {
  draftFrom,
  emptyItem,
  fieldPathFromLoc,
  formFor,
  valueFrom,
  visibleForm,
  type DraftRecord,
  type DraftScalar,
  type FieldDef,
  type SettingDraft,
} from "@/features/settings/setting-model";
import type { SettingRead } from "@/features/settings/types";
import { createIdempotencyKey } from "@/lib/api/client";
import { conflictFromError, ProblemError, type ConflictInfo } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { Banner, Button, DateText, Drawer, Select, Switch, Textarea, TextField, toast } from "~/ui";
import { sayQuotation } from "./shared";

const FIELD_ERROR: Record<string, string> = {
  "Enter a value.": "This cannot be empty. Enter a value.",
  "Enter a whole number.": "Enter a whole number, without decimals.",
};

/** One control per field kind. Text stays text: whole numbers convert on save, decimals never. */
function Field({ field, value, error, onChange }: { field: FieldDef; value: DraftScalar | undefined; error?: string; onChange: (value: DraftScalar) => void }) {
  const text = typeof value === "string" ? value : "";
  const label = sayQuotation(field.label);
  const help = field.description ? sayQuotation(field.description) : undefined;
  const shown = error ? (FIELD_ERROR[error] ?? error) : undefined;
  const optional = !field.required;
  switch (field.kind) {
    case "switch":
      return <Switch label={label} isSelected={value === true} onChange={onChange} className="col-span-full" />;
    case "select":
      return (
        <Select
          label={label}
          options={(field.options ?? []).map((option) => ({ value: option.id, label: option.label }))}
          value={text || null}
          onChange={onChange}
          help={help}
          error={shown}
          isRequired={field.required}
          optional={optional}
        />
      );
    case "textarea":
    case "lines":
      return (
        <Textarea
          className="col-span-full"
          label={label}
          value={text}
          onChange={onChange}
          rows={field.kind === "lines" ? 4 : 6}
          help={help}
          error={shown}
          maxLength={field.maxLength}
          isRequired={field.required}
          optional={optional}
        />
      );
    default:
      return (
        <TextField
          label={label}
          value={text}
          onChange={onChange}
          inputMode={field.kind === "integer" ? "numeric" : field.kind === "decimal" ? "decimal" : undefined}
          help={help ?? (field.kind === "csv" ? "Separate the entries with commas." : undefined)}
          error={shown}
          maxLength={field.maxLength}
          isRequired={field.required}
          optional={optional}
        />
      );
  }
}

function FieldGrid({ fields, record, prefix, errors, onChange }: { fields: readonly FieldDef[]; record: DraftRecord; prefix: string; errors: Record<string, string>; onChange: (name: string, value: DraftScalar) => void }) {
  return (
    <div className="lk-form-grid">
      {fields.map((field) => (
        <Field key={field.name} field={field} value={record[field.name]} error={errors[`${prefix}${field.name}`] || undefined} onChange={(value) => onChange(field.name, value)} />
      ))}
    </div>
  );
}

/**
 * Edits one company setting in a drawer, with a form built from the setting's own shape. It saves
 * against the version on screen: if someone else saved first nothing is overwritten and the
 * person is asked to reload; messages the server sends for a field land on that field.
 */
export function SettingEditor({ setting, title, isOpen, onClose }: { setting: SettingRead; title: string; isOpen: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const form = visibleForm(formFor(setting), setting.redacted_fields);
  const [draft, setDraft] = useState<SettingDraft>(() => draftFrom(form, setting.value));
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState<ConflictInfo | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => createIdempotencyKey());
  const editable = form.fields.length + form.groups.length + form.lists.length > 0;

  const setField = (name: string, value: DraftScalar) => setDraft((current) => ({ ...current, fields: { ...current.fields, [name]: value } }));
  const setGroupField = (group: string, name: string, value: DraftScalar) =>
    setDraft((current) => ({ ...current, groups: { ...current.groups, [group]: { ...current.groups[group], [name]: value } } }));
  const setListField = (list: string, index: number, name: string, value: DraftScalar) =>
    setDraft((current) => ({
      ...current,
      lists: { ...current.lists, [list]: (current.lists[list] ?? []).map((item, position) => (position === index ? { ...item, [name]: value } : item)) },
    }));
  const addItem = (list: string, item: DraftRecord) => setDraft((current) => ({ ...current, lists: { ...current.lists, [list]: [...(current.lists[list] ?? []), item] } }));
  const removeItem = (list: string, index: number) =>
    setDraft((current) => ({ ...current, lists: { ...current.lists, [list]: (current.lists[list] ?? []).filter((_, position) => position !== index) } }));

  const reload = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.org.settings() });
    await queryClient.invalidateQueries({ queryKey: queryKeys.org.setting(setting.key) });
    onClose();
  };

  const save = async () => {
    if (pending || !online || !editable) return;
    const result = valueFrom(form, draft, setting.value, setting.redacted_fields);
    setErrors(result.errors);
    setFailure(null);
    if (Object.keys(result.errors).length > 0) return;
    setPending(true);
    setConflict(null);
    try {
      await updateSetting(setting.key, { value: result.value, expected_version: setting.version, change_reason: reason }, idempotencyKey);
      await Promise.all(invalidationMap["org.setting_changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      toast.success(`${title} saved`, { description: "The change is kept as a new version." });
      onClose();
    } catch (error) {
      // The attempt is over: a retry after a 409 or 422 is a new command with the corrected value.
      setIdempotencyKey(createIdempotencyKey());
      const found = conflictFromError(error);
      if (found) setConflict(found);
      else if (error instanceof ProblemError && error.status === 422) {
        const fieldErrors: Record<string, string> = {};
        for (const issue of error.validationIssues) fieldErrors[fieldPathFromLoc(issue.loc)] = issue.msg;
        setErrors(fieldErrors);
        setFailure(error.detail ?? "Some values were not accepted. Check the marked fields and save again.");
      } else {
        setFailure(error instanceof ProblemError ? (error.detail ?? error.title) : "The connection dropped before the server answered. Check your network and save again.");
      }
    } finally {
      setPending(false);
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void save();
  };

  const reasonError = errors["body.change_reason"] ?? errors.change_reason;

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Edit ${title.toLowerCase()}`}
      description="Saving keeps the old values as a version you can look back at."
      width="lg"
      footer={
        <>
          <Button variant="ghost" onPress={onClose} isDisabled={pending}>
            Cancel
          </Button>
          <Button onPress={() => void save()} loading={pending} isDisabled={!online || !editable || conflict !== null}>
            Save changes
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-6">
        {conflict ? (
          <Banner
            tone="amber"
            title="Someone else saved this setting while you were editing."
            action={
              <Button variant="secondary" size="sm" iconLeft="refresh" onPress={() => void reload()}>
                Reload latest
              </Button>
            }
          >
            Nothing was overwritten{conflict.changedBy ? `. ${conflict.changedBy} made the last change` : ""}
            {conflict.changedAt ? (
              <>
                {" "}
                (<DateText value={conflict.changedAt} style="dayTime" />)
              </>
            ) : null}
            . Reload to see it, then make your change again.
          </Banner>
        ) : null}
        {!online ? (
          <Banner tone="amber" title="You are offline.">
            Changes can be saved once the connection is back.
          </Banner>
        ) : null}
        {failure ? (
          <Banner tone="ember" title="The setting was not saved.">
            {failure}
          </Banner>
        ) : null}
        {!editable ? <Banner tone="neutral">Nothing in this setting can be edited from here.</Banner> : null}

        {form.fields.length > 0 ? <FieldGrid fields={form.fields} record={draft.fields} prefix="" errors={errors} onChange={setField} /> : null}

        {form.groups.map((group) => (
          <fieldset key={group.name} className="flex min-w-0 flex-col gap-4">
            <legend className="t-overline mb-3 text-ink-3">{sayQuotation(group.label)}</legend>
            <FieldGrid fields={group.fields} record={draft.groups[group.name] ?? {}} prefix={`${group.name}.`} errors={errors} onChange={(name, value) => setGroupField(group.name, name, value)} />
          </fieldset>
        ))}

        {form.lists.map((list) => {
          const items = draft.lists[list.name] ?? [];
          return (
            <fieldset key={list.name} className="flex min-w-0 flex-col gap-4">
              <legend className="t-overline mb-3 text-ink-3">{sayQuotation(list.label)}</legend>
              {errors[list.name] ? (
                <Banner tone="ember">{errors[list.name]}</Banner>
              ) : null}
              {items.length === 0 ? <p className="t-body-sm text-ink-3">None yet. Add the first {list.itemLabel} below.</p> : null}
              {items.map((item, index) => (
                <div key={index} className="flex min-w-0 flex-col gap-4 rounded-md border border-line bg-surface p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="t-label text-ink">
                      {list.itemLabel.charAt(0).toUpperCase() + list.itemLabel.slice(1)} {index + 1}
                    </span>
                    <Button size="sm" variant="ghost" iconLeft="trash" onPress={() => removeItem(list.name, index)}>
                      Remove {list.itemLabel}
                    </Button>
                  </div>
                  <FieldGrid fields={list.fields} record={item} prefix={`${list.name}[${index}].`} errors={errors} onChange={(name, value) => setListField(list.name, index, name, value)} />
                </div>
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

        <Textarea label="Reason for the change" optional value={reason} onChange={setReason} help="Kept with this version, for whoever looks back at it." maxLength={500} rows={2} error={reasonError || undefined} />
        {/* Enter in a single-line field saves, as in any form. */}
        <button type="submit" hidden tabIndex={-1} aria-hidden="true" />
      </form>
    </Drawer>
  );
}
