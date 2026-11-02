"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Switch } from "@/components/ui/choice";
import { Drawer } from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { Conflict } from "@/components/ui/states";
import { sectionLabelClasses } from "@/components/ui/styles";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { createIdempotencyKey } from "@/lib/api/client";
import { conflictFromError, ProblemError, type ConflictInfo } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { formatDayTime } from "@/lib/format/time";
import { useOnline } from "@/lib/hooks";
import { useNow, useSession } from "@/lib/session/context";
import { settingsMessages } from "@/messages/settings";
import { updateSetting } from "./api";
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
} from "./setting-model";
import type { SettingRead } from "./types";

const m = settingsMessages.company.editor;

/** One control per field kind; strings stay strings (integers convert on save, decimals never). */
function Field({
  field,
  value,
  onChange,
  errorMessage,
}: {
  field: FieldDef;
  value: DraftScalar | undefined;
  onChange: (value: DraftScalar) => void;
  errorMessage?: string;
}) {
  const text = typeof value === "string" ? value : "";
  switch (field.kind) {
    case "switch":
      return (
        <Switch isSelected={value === true} onChange={onChange}>
          {field.label}
        </Switch>
      );
    case "select":
      return (
        <Select
          label={field.label}
          options={field.options ?? []}
          value={text || null}
          onChange={(next) => onChange(next ?? "")}
          description={field.description}
          errorMessage={errorMessage}
          isRequired={field.required}
        />
      );
    case "textarea":
    case "lines":
      return (
        <TextArea
          label={field.label}
          value={text}
          onChange={onChange}
          rows={field.kind === "lines" ? 4 : 6}
          description={field.description}
          errorMessage={errorMessage}
          maxLength={field.maxLength}
          isRequired={field.required}
        />
      );
    case "integer":
    case "decimal":
      return (
        <TextField
          label={field.label}
          value={text}
          onChange={onChange}
          inputMode={field.kind === "integer" ? "numeric" : "decimal"}
          inputClassName="tabular"
          description={field.description}
          errorMessage={errorMessage}
          isRequired={field.required}
        />
      );
    case "code":
      return (
        <TextField
          label={field.label}
          value={text}
          onChange={onChange}
          inputClassName="font-mono uppercase"
          spellCheck="false"
          description={field.description}
          errorMessage={errorMessage}
          maxLength={field.maxLength}
          isRequired={field.required}
        />
      );
    default:
      return (
        <TextField
          label={field.label}
          value={text}
          onChange={onChange}
          description={field.description}
          errorMessage={errorMessage}
          maxLength={field.maxLength}
          isRequired={field.required}
        />
      );
  }
}

function FieldSet({
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
          <Field field={field} value={record[field.name]} onChange={(value) => onChange(field.name, value)} errorMessage={errors[`${prefix}${field.name}`]} />
        </div>
      ))}
    </div>
  );
}

/**
 * Edits one setting in a drawer with a form generated from its schema. Saves with
 * `expected_version`; a 409 shows the Conflict state whose "Review latest version" reloads the
 * setting (nothing is overwritten); 422 messages land on their fields.
 */
export function SettingEditor({ setting, isOpen, onClose }: { setting: SettingRead; isOpen: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { zone } = useSession();
  const now = useNow();
  const online = useOnline();
  const form = visibleForm(formFor(setting), setting.redacted_fields);
  const [draft, setDraft] = useState<SettingDraft>(() => draftFrom(form, setting.value));
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState<ConflictInfo | null>(null);
  const [pending, setPending] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => createIdempotencyKey());
  const offline = online ? null : m.offline;
  const editable = form.fields.length + form.groups.length + form.lists.length > 0;

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

  const reload = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.org.settings() });
    await queryClient.invalidateQueries({ queryKey: queryKeys.org.setting(setting.key) });
    onClose();
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || offline) return;
    const result = valueFrom(form, draft, setting.value, setting.redacted_fields);
    setErrors(result.errors);
    if (Object.keys(result.errors).length > 0) return;
    setPending(true);
    setConflict(null);
    try {
      await updateSetting(setting.key, { value: result.value, expected_version: setting.version, change_reason: reason }, idempotencyKey);
      await Promise.all(invalidationMap["org.setting_changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      toast.success(m.saved);
      onClose();
    } catch (error) {
      // The attempt is over: a retry after a 409/422 is a new command with the corrected value.
      setIdempotencyKey(createIdempotencyKey());
      const conflictInfo = conflictFromError(error);
      if (conflictInfo) setConflict(conflictInfo);
      else if (error instanceof ProblemError && error.status === 422) {
        const fieldErrors: Record<string, string> = {};
        for (const issue of error.validationIssues) fieldErrors[fieldPathFromLoc(issue.loc)] = issue.msg;
        setErrors(fieldErrors);
        toast.error(m.failed, { description: error.detail ?? error.title });
      } else toast.error(m.failed, { description: error instanceof ProblemError ? (error.detail ?? error.title) : undefined });
    } finally {
      setPending(false);
    }
  };

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={m.title(setting.description)}
      description={<span className="font-mono">{setting.key}</span>}
      width="lg"
    >
      <Form onSubmit={submit} validationBehavior="aria" className="flex flex-col gap-6">
        {conflict ? <Conflict conflict={conflict} changedAtLabel={conflict.changedAt && now ? formatDayTime(conflict.changedAt, now, zone) : null} onReview={() => void reload()} /> : null}
        {errors["body.change_reason"] || errors.change_reason ? <p className="text-sm font-medium text-danger">{errors["body.change_reason"] ?? errors.change_reason}</p> : null}
        {form.fields.length > 0 ? <FieldSet fields={form.fields} record={draft.fields} prefix="" errors={errors} onChange={setField} /> : null}
        {form.groups.map((group) => (
          <fieldset key={group.name} className="flex flex-col gap-3">
            <legend className={sectionLabelClasses}>{group.label}</legend>
            <FieldSet fields={group.fields} record={draft.groups[group.name] ?? {}} prefix={`${group.name}.`} errors={errors} onChange={(name, value) => setGroupField(group.name, name, value)} />
          </fieldset>
        ))}
        {form.lists.map((list) => {
          const items = draft.lists[list.name] ?? [];
          return (
            <fieldset key={list.name} className="flex flex-col gap-4">
              <legend className={sectionLabelClasses}>{list.label}</legend>
              {errors[list.name] ? <p className="text-sm font-medium text-danger">{errors[list.name]}</p> : null}
              {items.map((item, index) => (
                <div key={index} className="flex flex-col gap-3 rounded-lg border p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-ink">
                      {list.label} {index + 1}
                    </span>
                    <Button size="sm" variant="quiet" onPress={() => removeItem(list.name, index)}>
                      {m.remove(list.itemLabel)}
                    </Button>
                  </div>
                  <FieldSet fields={list.fields} record={item} prefix={`${list.name}[${index}].`} errors={errors} onChange={(name, value) => setListField(list.name, index, name, value)} />
                </div>
              ))}
              {list.max === undefined || items.length < list.max ? (
                <div>
                  <Button onPress={() => addItem(list.name, emptyItem(list))}>{m.add(list.itemLabel)}</Button>
                </div>
              ) : null}
            </fieldset>
          );
        })}
        <TextArea label={m.reason} value={reason} onChange={setReason} description={m.reasonHint} maxLength={500} rows={2} />
        <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
          <Button onPress={onClose}>{m.cancel}</Button>
          <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.saving} {...unavailableWhen(offline ?? (editable ? null : m.unavailable))}>
            {m.save}
          </Button>
        </div>
      </Form>
    </Drawer>
  );
}
