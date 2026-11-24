"use client";

import { useId, useState, type FormEvent } from "react";
import { setUserRoles, updateUser } from "@/app/(app)/settings/_lib/api";
import type { UserDetail } from "@/app/(app)/settings/_lib/types";
import { conflictFromError } from "@/lib/api/errors";
import { useRefreshIdentity, useRoles } from "~/data/settings-access";
import { Banner, Button, Modal, TextField, toast } from "~/ui";
import { fieldErrors, formFailure } from "./labels";
import { RoleChecklist } from "./parts";

type Run = <T>(command: () => Promise<T>) => Promise<T>;

interface DialogProps {
  user: UserDetail;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** The screen's step-up runner, so a refused change asks for the password or a code and retries. */
  run: Run;
}

/** Name, job title and department. Saved against the version the form opened with. */
export function EditDetailsModal({ user, isOpen, onOpenChange, run }: DialogProps) {
  const formId = useId();
  const refresh = useRefreshIdentity();
  const [name, setName] = useState(user.display_name.replace(/ \(inactive\)$/, ""));
  const [jobTitle, setJobTitle] = useState(user.job_title ?? "");
  const [department, setDepartment] = useState(user.department ?? "");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const server = fieldErrors(error);
  const conflict = conflictFromError(error);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await run(() => updateUser(user.user_id, { expected_version: user.version, display_name: name.trim(), job_title: jobTitle, department }));
      await refresh();
      toast.success("Details saved");
      onOpenChange(false);
    } catch (err) {
      setError(err);
      if (conflictFromError(err)) await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      title="Edit details"
      description="How this person appears to the team."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy}>
            Save details
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        {conflict ? (
          <Banner tone="amber" title="This profile changed while you were editing.">
            {conflict.changedBy ? `${conflict.changedBy} saved a change first. ` : "Someone saved a change first. "}The latest version is loaded now. Save again to put your name, job title and department on top of it.
          </Banner>
        ) : formFailure(error) ? (
          <Banner tone="ember" title="The details were not saved.">
            {formFailure(error)}
          </Banner>
        ) : null}
        <TextField
          label="Name"
          isRequired
          autoFocus
          maxLength={200}
          value={name}
          onChange={setName}
          error={server.display_name ?? (submitted && !name.trim() ? "Enter the name the team will see." : undefined)}
        />
        <TextField label="Job title" optional maxLength={120} value={jobTitle} onChange={setJobTitle} error={server.job_title} />
        <TextField label="Department" optional maxLength={120} value={department} onChange={setDepartment} error={server.department} />
      </form>
    </Modal>
  );
}

/** Replace the person's roles. At least one; the server refuses roles the admin does not hold. */
export function ChangeRolesModal({ user, isOpen, onOpenChange, run }: DialogProps) {
  const formId = useId();
  const refresh = useRefreshIdentity();
  const roles = useRoles();
  const [draft, setDraft] = useState<string[]>(() => user.roles.map((role) => role.key));
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const server = fieldErrors(error);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy || draft.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await run(() => setUserRoles(user.user_id, draft));
      await refresh();
      toast.success("Roles updated", { description: "The change applies on their next request." });
      onOpenChange(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Change roles"
      description={`What ${user.display_name} can see and do. You can only give access you hold yourself.`}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy}>
            Save roles
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        {formFailure(error) ? (
          <Banner tone="ember" title="The roles were not changed.">
            {formFailure(error)}
          </Banner>
        ) : null}
        <RoleChecklist
          roles={roles.data?.items}
          isLoading={roles.isPending}
          value={draft}
          onChange={setDraft}
          error={roles.isError ? "The roles could not load. Close this and try again." : (server.role_keys ?? (submitted && draft.length === 0 ? "Choose at least one role." : undefined))}
        />
      </form>
    </Modal>
  );
}
