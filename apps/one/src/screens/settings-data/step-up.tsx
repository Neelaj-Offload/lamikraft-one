"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { reauthenticate } from "@/app/(app)/settings/_lib/api";
import { isProblemError } from "@/lib/api/errors";
import { ErrorBlock } from "~/shell/states";
import { Button, EmptyState, GlassPanel, Modal, TextField } from "~/ui";

/**
 * Migration reports and backup facts are protected reads: the server may answer 401
 * `mfa_required` or `reauth_required`. The person then confirms with an authenticator code or
 * their password (`POST /identity/session/reauthentication`) and the read is tried once more.
 */

const STEP_UP_CODES = new Set(["reauth_required", "mfa_required"]);

/** Which proof the server asked for, or null when the failure is something else. */
export function needsStepUp(error: unknown): "password" | "code" | null {
  if (!isProblemError(error) || !STEP_UP_CODES.has(error.code)) return null;
  return error.code === "mfa_required" ? "code" : "password";
}

interface Pending {
  mode: "password" | "code";
  retry: () => Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
}

export function useStepUp(): { run: <T>(command: () => Promise<T>) => Promise<T>; dialog: ReactNode } {
  const [pending, setPending] = useState<Pending | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run<T>(command: () => Promise<T>): Promise<T> {
    try {
      return await command();
    } catch (failure) {
      const mode = needsStepUp(failure);
      if (!mode) throw failure;
      return new Promise<T>((resolve, reject) => {
        setError(null);
        setValue("");
        setPending({ mode, retry: command, resolve: resolve as (value: unknown) => void, reject });
      });
    }
  }

  const cancel = () => {
    if (!pending || busy) return;
    pending.reject(new Error("step_up_cancelled"));
    setPending(null);
    setValue("");
  };

  const confirm = async () => {
    if (!pending || busy) return;
    if (!value.trim()) {
      setError(pending.mode === "code" ? "Enter the 6-digit code from your authenticator app." : "Enter your password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await reauthenticate(pending.mode === "code" ? { code: value.trim() } : { password: value });
      const result = await pending.retry();
      pending.resolve(result);
      setPending(null);
    } catch (failure) {
      if (isProblemError(failure) && (failure.code === "invalid_code" || failure.status === 422)) {
        setError(pending.mode === "code" ? "That code did not work. Use the current code from your authenticator app." : "That password is not correct. Check it and try again.");
      } else if (needsStepUp(failure) === "code" && pending.mode === "password") {
        setPending({ ...pending, mode: "code" });
        setError("This also needs a code from your authenticator app.");
      } else {
        pending.reject(failure);
        setPending(null);
      }
    } finally {
      setBusy(false);
      setValue("");
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void confirm();
  };

  const dialog = (
    <Modal
      isOpen={pending !== null}
      onOpenChange={(open) => {
        if (!open) cancel();
      }}
      size="sm"
      isDismissable={!busy}
      title="Confirm it is you"
      description={
        pending?.mode === "code"
          ? "This is protected by two-step verification. Enter the 6-digit code from your authenticator app."
          : "This needs a recent sign-in. Enter your password to carry on."
      }
      actions={
        <>
          <Button variant="ghost" onPress={cancel} isDisabled={busy}>
            Cancel
          </Button>
          <Button onPress={() => void confirm()} loading={busy}>
            Confirm and continue
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        {pending?.mode === "code" ? (
          <TextField label="Authenticator code" inputMode="numeric" autoComplete="one-time-code" autoFocus isRequired value={value} onChange={setValue} error={error ?? undefined} />
        ) : (
          <TextField label="Password" type="password" autoComplete="current-password" autoFocus isRequired value={value} onChange={setValue} error={error ?? undefined} />
        )}
      </form>
    </Modal>
  );

  return { run, dialog };
}

/**
 * The error state of a protected read. When the server asked for a second factor it offers the
 * confirmation and then reads again; any other failure is the usual in-place error with a retry.
 * `retry` performs the read itself (so a 401 surfaces here) and then refreshes the query.
 */
export function ProtectedReadProblem({ error, what, reason, retry }: { error: unknown; what: string; reason: string; retry: () => Promise<unknown> }) {
  const stepUp = useStepUp();
  if (!needsStepUp(error)) return <ErrorBlock error={error} what={what} onRetry={() => void retry().catch(() => undefined)} />;
  return (
    <>
      <GlassPanel padding="lg" className="rise">
        <EmptyState
          icon="lock"
          title="Confirm it is you"
          text={reason}
          actions={
            <Button iconLeft="shield" onPress={() => void stepUp.run(retry).catch(() => undefined)}>
              Confirm and show
            </Button>
          }
        />
      </GlassPanel>
      {stepUp.dialog}
    </>
  );
}
