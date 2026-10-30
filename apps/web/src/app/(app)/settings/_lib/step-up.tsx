"use client";

import { useRef, useState, type ReactNode } from "react";
import { Form } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { PasswordField, TextField } from "@/components/ui/text-field";
import { isProblemError } from "@/lib/api/errors";
import { reauthenticate } from "./api";

export const STEP_UP_CODES = new Set(["reauth_required", "mfa_required"]);

/** The problem codes that ask the person to confirm it is them before a sensitive change (permissions.md §6). */
export function needsStepUp(error: unknown): "password" | "code" | null {
  if (!isProblemError(error) || !STEP_UP_CODES.has(error.code)) return null;
  return error.code === "mfa_required" ? "code" : "password";
}

type Pending = { mode: "password" | "code"; retry: () => Promise<unknown>; resolve: (value: unknown) => void; reject: (error: unknown) => void };

/**
 * Wraps sensitive commands: when the server answers 401 `reauth_required` or `mfa_required`, a dialog asks for the
 * password or an authenticator code, calls `POST /identity/session/reauthentication` and retries the command once.
 */
export function useStepUp(): { run: <T>(command: () => Promise<T>) => Promise<T>; dialog: ReactNode } {
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const value = useRef("");

  async function run<T>(command: () => Promise<T>): Promise<T> {
    try {
      return await command();
    } catch (err) {
      const mode = needsStepUp(err);
      if (!mode) throw err;
      return new Promise<T>((resolve, reject) => {
        setError(null);
        setPending({ mode, retry: command, resolve: resolve as (v: unknown) => void, reject });
      });
    }
  }

  async function confirm() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await reauthenticate(pending.mode === "code" ? { code: value.current } : { password: value.current });
      const result = await pending.retry();
      pending.resolve(result);
      setPending(null);
    } catch (err) {
      if (isProblemError(err) && (err.code === "invalid_code" || err.status === 422)) {
        setError(pending.mode === "code" ? "That code did not work. Use the current code from your authenticator app." : "That password is not correct.");
      } else if (needsStepUp(err) === "code" && pending.mode === "password") {
        setPending({ ...pending, mode: "code" });
        setError("This change also needs a code from your authenticator app.");
      } else {
        pending.reject(err);
        setPending(null);
      }
    } finally {
      setBusy(false);
      value.current = "";
    }
  }

  const dialog = (
    <Dialog
      isOpen={pending !== null}
      onOpenChange={(open) => {
        if (!open && pending) {
          pending.reject(new Error("step_up_cancelled"));
          setPending(null);
        }
      }}
      size="sm"
      title="Confirm it is you"
      description={
        pending?.mode === "code"
          ? "This change needs two-step verification. Enter the 6-digit code from your authenticator app."
          : "This change needs a recent sign-in. Enter your password."
      }
    >
      <Form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void confirm();
        }}
      >
        {pending?.mode === "code" ? (
          <TextField label="Authenticator code" inputMode="numeric" autoComplete="one-time-code" autoFocus isRequired onChange={(v) => (value.current = v)} errorMessage={error ?? undefined} isInvalid={!!error} />
        ) : (
          <PasswordField label="Password" autoComplete="current-password" autoFocus isRequired onChange={(v) => (value.current = v)} errorMessage={error ?? undefined} isInvalid={!!error} />
        )}
        <div className="flex justify-end gap-2">
          <Button type="submit" variant="primary" isPending={busy} pendingLabel="Checking…">
            Confirm and continue
          </Button>
        </div>
      </Form>
    </Dialog>
  );

  return { run, dialog };
}
