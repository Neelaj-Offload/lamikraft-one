"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Form } from "react-aria-components";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { LocalDateTime, RelativeTime } from "@/components/ui/format";
import { EmptyState } from "@/components/ui/states";
import { PasswordField, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import {
  changePassword,
  confirmTotp,
  endMyOtherSessions,
  endMySession,
  fetchMfa,
  fetchMySessions,
  regenerateCodes,
  removeTotp,
  startTotp,
} from "./api";
import type { MfaEnrollment } from "./types";
import { fieldErrors, problemText, QueryState, Section, SettingsPage } from "./ui";

/** Recovery codes, shown once, with a plain-text copy for saving. */
export function RecoveryCodes({ codes }: { codes: string[] }) {
  return (
    <div role="status" className="flex flex-col gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3">
      <p className="font-semibold">Save these recovery codes now. They are shown only once.</p>
      <p className="text-sm">Each code works once if you cannot use your authenticator app.</p>
      <ol className="grid grid-cols-2 gap-1 font-mono text-sm md:grid-cols-5">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Set up an authenticator: start (QR code + secret), confirm with the first code, then show the recovery codes.
 * Used on the security page and on the two-step page when the role requires enrolment before anything else.
 */
export function TotpEnrolment({ onDone }: { onDone: (codes: string[]) => void }) {
  const [enrollment, setEnrollment] = useState<MfaEnrollment | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setEnrollment(await startTotp());
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(code: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await confirmTotp(code);
      onDone(result.recovery_codes);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!enrollment) {
    return (
      <div className="flex flex-col gap-2">
        <p>Use an authenticator app (for example Google Authenticator, Microsoft Authenticator or 1Password).</p>
        {error ? <p role="alert" className="text-danger">{problemText(error)}</p> : null}
        <div>
          <Button variant="primary" isPending={busy} onPress={() => void start()}>
            Set up an authenticator app
          </Button>
        </div>
      </div>
    );
  }
  const invalid = isProblemError(error) && error.code === "invalid_code";
  return (
    <div className="flex flex-col gap-3">
      <ol className="list-decimal ps-5 text-sm">
        <li>Scan this code with your authenticator app.</li>
        <li>Enter the 6-digit code it shows.</li>
      </ol>
      {/* The SVG is produced by the server from the provisioning URI (no third party ever sees the secret). It is
          shown as an image (a data: URL), so markup in it can never run in the page. */}
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL, nothing for next/image to optimise */}
      <img className="w-48 rounded-lg border bg-white p-2" alt="QR code for your authenticator app" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(enrollment.qr_svg)}`} />
      <TextField label="Or type this key" value={enrollment.secret} isReadOnly inputClassName="font-mono" />
      <Form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void confirm(String(new FormData(event.currentTarget).get("code") ?? ""));
        }}
      >
        <TextField name="code" label="6-digit code" inputMode="numeric" autoComplete="one-time-code" isRequired isInvalid={invalid} errorMessage={invalid ? "That code did not work. Check the time on your phone and try the current code." : undefined} />
        <Button type="submit" variant="primary" isPending={busy} pendingLabel="Checking…">
          Confirm
        </Button>
      </Form>
      {error && !invalid ? <p role="alert" className="text-danger">{problemText(error)}</p> : null}
    </div>
  );
}

function CodeDialog({ title, description, open, onClose, onSubmit, busy, error }: { title: string; description: string; open: boolean; onClose: () => void; onSubmit: (code: string) => void; busy: boolean; error: unknown }) {
  return (
    <Dialog isOpen={open} onOpenChange={(o) => !o && onClose()} size="sm" title={title} description={description}>
      <Form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(String(new FormData(event.currentTarget).get("code") ?? ""));
        }}
      >
        <TextField name="code" label="Authenticator or recovery code" autoComplete="one-time-code" isRequired isInvalid={!!error} errorMessage={error ? problemText(error) : undefined} />
        <div className="flex justify-end">
          <Button type="submit" variant="primary" isPending={busy}>
            Confirm
          </Button>
        </div>
      </Form>
    </Dialog>
  );
}

export function SecurityScreen() {
  const client = useQueryClient();
  const mfa = useQuery({ queryKey: queryKeys.identity.mfa(), queryFn: ({ signal }) => fetchMfa(signal) });
  const sessions = useQuery({ queryKey: queryKeys.identity.sessions(), queryFn: ({ signal }) => fetchMySessions(signal) });
  const [codes, setCodes] = useState<string[] | null>(null);
  const [dialog, setDialog] = useState<null | "remove" | "regenerate">(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [pwError, setPwError] = useState<unknown>(null);
  const [pwBusy, setPwBusy] = useState(false);

  const refresh = () => client.invalidateQueries({ queryKey: queryKeys.identity.all() });

  async function withCode(kind: "remove" | "regenerate", code: string) {
    setBusy(true);
    setError(null);
    try {
      if (kind === "remove") {
        await removeTotp(code);
        toast.success("Two-step sign-in removed");
      } else {
        setCodes((await regenerateCodes(code)).recovery_codes);
        toast.success("New recovery codes created");
      }
      setDialog(null);
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function savePassword(form: FormData) {
    setPwBusy(true);
    setPwError(null);
    try {
      await changePassword(String(form.get("current_password") ?? ""), String(form.get("new_password") ?? ""));
      toast.success("Password changed. Your other sessions were signed out.");
      await refresh();
    } catch (err) {
      setPwError(err);
    } finally {
      setPwBusy(false);
    }
  }

  return (
    <SettingsPage title="Security" intro="Your password, two-step sign-in and the places you are signed in.">
      <Section title="Two-step sign-in" description="An authenticator code at sign-in, and before sensitive administration changes.">
        {mfa.isPending || mfa.isError ? (
          <QueryState isPending={mfa.isPending} error={mfa.error} what="your two-step settings" area="security" onRetry={() => void mfa.refetch()} />
        ) : mfa.data.enrolled ? (
          <div className="flex flex-col gap-3">
            <p>
              <Badge tone="success">On</Badge> since <LocalDateTime value={mfa.data.confirmed_at} />. {mfa.data.recovery_codes_remaining} recovery codes left.
              {mfa.data.required ? " Your role requires it." : ""}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button onPress={() => setDialog("regenerate")}>New recovery codes</Button>
              {mfa.data.required ? null : (
                <Button variant="danger" onPress={() => setDialog("remove")}>
                  Remove
                </Button>
              )}
            </div>
          </div>
        ) : (
          <TotpEnrolment
            onDone={(c) => {
              setCodes(c);
              void refresh();
            }}
          />
        )}
        {codes ? <RecoveryCodes codes={codes} /> : null}
      </Section>
      <Section title="Password" description="At least 12 characters; long passphrases are best. Changing it signs you out everywhere else.">
        <Form
          className="flex max-w-md flex-col gap-3"
          validationErrors={fieldErrors(pwError)}
          onSubmit={(event) => {
            event.preventDefault();
            void savePassword(new FormData(event.currentTarget));
          }}
        >
          <PasswordField name="current_password" label="Current password" autoComplete="current-password" isRequired />
          <PasswordField name="new_password" label="New password" autoComplete="new-password" isRequired />
          {pwError && !Object.keys(fieldErrors(pwError)).length ? <p role="alert" className="text-danger">{problemText(pwError)}</p> : null}
          <div>
            <Button type="submit" variant="primary" isPending={pwBusy}>
              Change password
            </Button>
          </div>
        </Form>
      </Section>
      <Section
        title="Where you are signed in"
        actions={
          <Button
            onPress={() =>
              void endMyOtherSessions()
                .then((r) => {
                  toast.success(`Signed out of ${r.revoked} other session${r.revoked === 1 ? "" : "s"}`);
                  return refresh();
                })
                .catch((err: unknown) => toast.error(problemText(err)))
            }
          >
            Sign out everywhere else
          </Button>
        }
      >
        {sessions.isPending || sessions.isError ? (
          <QueryState isPending={sessions.isPending} error={sessions.error} what="your sessions" area="security" onRetry={() => void sessions.refetch()} />
        ) : sessions.data.items.length === 0 ? (
          <EmptyState title="No other sessions" headingLevel={3} />
        ) : (
          <ul className="divide-y">
            {sessions.data.items.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>
                  {s.current ? <Badge tone="forest">This browser</Badge> : null} Signed in <LocalDateTime value={s.created_at} /> ·
                  last active <RelativeTime value={s.last_seen_at} /> · {s.mfa_verified ? "two-step verified" : s.auth_method.replace("_", " ")}
                </span>
                {s.current ? null : (
                  <Button size="sm" variant="quiet" onPress={() => void endMySession(s.id).then(refresh).catch((err: unknown) => toast.error(problemText(err)))}>
                    Sign out
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <CodeDialog title="Remove two-step sign-in?" description="Enter a current code to confirm." open={dialog === "remove"} onClose={() => setDialog(null)} onSubmit={(c) => void withCode("remove", c)} busy={busy} error={error} />
      <CodeDialog title="Create new recovery codes?" description="Your old codes stop working. Enter a current authenticator code." open={dialog === "regenerate"} onClose={() => setDialog(null)} onSubmit={(c) => void withCode("regenerate", c)} busy={busy} error={error} />
    </SettingsPage>
  );
}
