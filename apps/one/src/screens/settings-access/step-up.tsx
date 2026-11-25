"use client";

import { useId, useState, type ReactNode } from "react";
import { reauthenticate } from "@/app/(app)/settings/_lib/api";
import { isProblemError } from "@/lib/api/errors";
import { needsStepUp } from "~/data/settings-access";
import { PasswordField } from "~/screens/auth/parts";
import { Button, Modal, TextField } from "~/ui";
import { STEP_UP_CANCELLED } from "./labels";

type Mode = "password" | "code";

interface Pending {
  mode: Mode;
  retry: () => Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
}

/**
 * Wraps a sensitive command. When the server answers 401 `reauth_required` or `mfa_required`, a
 * dialog asks for the password or an authenticator code, calls
 * `POST /identity/session/reauthentication` and runs the command once more. Closing the dialog
 * rejects the command with `step_up_cancelled`, so nothing is changed.
 *
 * Render `dialog` once in the screen that calls `run`.
 */
export function useStepUp(): { run: <T>(command: () => Promise<T>) => Promise<T>; dialog: ReactNode } {
  const formId = useId();
  const [pending, setPending] = useState<Pending | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run<T>(command: () => Promise<T>): Promise<T> {
    try {
      return await command();
    } catch (err) {
      const mode = needsStepUp(err);
      if (!mode) throw err;
      return new Promise<T>((resolve, reject) => {
        setError(null);
        setValue("");
        setPending({ mode, retry: command, resolve: resolve as (value: unknown) => void, reject });
      });
    }
  }

  async function confirm() {
    if (!pending || busy) return;
    if (!value) {
      setError(pending.mode === "code" ? "Enter the 6-digit code from your authenticator app." : "Enter your password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await reauthenticate(pending.mode === "code" ? { code: value } : { password: value });
      const result = await pending.retry();
      pending.resolve(result);
      setPending(null);
    } catch (err) {
      if (isProblemError(err) && (err.code === "invalid_code" || err.status === 422)) {
        setError(pending.mode === "code" ? "That code did not work. Use the code your authenticator app shows now." : "That password is not correct. Check it and try again.");
      } else if (needsStepUp(err) === "code" && pending.mode === "password") {
        setPending({ ...pending, mode: "code" });
        setError("This change also needs a code from your authenticator app.");
      } else {
        pending.reject(err);
        setPending(null);
      }
    } finally {
      setBusy(false);
      setValue("");
    }
  }

  const cancel = () => {
    if (!pending) return;
    pending.reject(new Error(STEP_UP_CANCELLED));
    setPending(null);
    setValue("");
  };

  const dialog = (
    <Modal
      isOpen={pending !== null}
      onOpenChange={(open) => {
        if (!open) cancel();
      }}
      size="sm"
      title="Confirm it is you"
      description={
        pending?.mode === "code"
          ? "This change needs two-step verification. Enter the 6-digit code from your authenticator app."
          : "This change needs a recent sign-in. Enter your password to continue."
      }
      actions={
        <>
          <Button variant="ghost" onPress={cancel} isDisabled={busy}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy}>
            Confirm and continue
          </Button>
        </>
      }
    >
      <form
        id={formId}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void confirm();
        }}
      >
        {pending?.mode === "code" ? (
          <TextField
            key="code"
            label="Authenticator code"
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            isRequired
            value={value}
            onChange={setValue}
            error={error}
            className="lk-tnum"
          />
        ) : (
          <PasswordField key="password" label="Password" autoComplete="current-password" autoFocus isRequired value={value} onChange={setValue} error={error} />
        )}
      </form>
    </Modal>
  );

  return { run, dialog };
}
