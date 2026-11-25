"use client";

import { useId, useState, type FormEvent } from "react";
import { confirmTotp, regenerateCodes, removeTotp, startTotp } from "@/app/(app)/settings/_lib/api";
import type { MfaEnrollment, MfaStatus } from "@/app/(app)/settings/_lib/types";
import { isProblemError } from "@/lib/api/errors";
import { useRefreshIdentity } from "~/data/settings-access";
import { Badge, Banner, Button, DateText, GlassPanel, Icon, Modal, TextField, toast } from "~/ui";
import { problemText } from "./labels";

/**
 * Two-step sign-in for the signed-in person: set up an authenticator app (QR code, then the first
 * code, then recovery codes shown once), make new recovery codes, or remove it when the role allows.
 */
export function TwoStepPanel({ status }: { status: MfaStatus }) {
  const refresh = useRefreshIdentity();
  const [codes, setCodes] = useState<string[] | null>(null);
  const [asking, setAsking] = useState<null | "remove" | "regenerate">(null);

  const finish = (issued: string[]) => {
    setCodes(issued);
    void refresh();
  };

  return (
    <GlassPanel
      as="section"
      title="Two-step sign-in"
      titleAs="h2"
      padding="lg"
      className="flex min-w-0 flex-col gap-5"
      action={
        status.enrolled ? (
          <Badge tone="leaf" icon="shield">
            On
          </Badge>
        ) : (
          <Badge tone={status.required ? "amber" : "neutral"} dot>
            {status.required ? "Required" : "Off"}
          </Badge>
        )
      }
    >
      <p className="t-body-sm text-ink-3">A code from your phone at every sign-in, and again before sensitive admin changes.</p>

      {codes ? <RecoveryCodes codes={codes} onDone={() => setCodes(null)} /> : null}

      {status.enrolled ? (
        <>
          <div className="flex min-w-0 flex-wrap items-start gap-4">
            <span className="grid size-11 flex-none place-items-center rounded-lg bg-leaf-soft text-leaf-text" aria-hidden>
              <Icon name="shield" size={20} />
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <p className="t-label text-ink">
                Authenticator app set up{status.confirmed_at ? " " : ""}
                {status.confirmed_at ? (
                  <span className="text-ink-2">
                    on <DateText value={status.confirmed_at} style="date" />
                  </span>
                ) : null}
              </p>
              <p className="t-body-sm text-ink-2">
                {status.recovery_codes_remaining === 1 ? "1 recovery code left." : `${status.recovery_codes_remaining} recovery codes left.`}
                {status.required ? " Your role requires two-step sign-in, so it stays on." : ""}
              </p>
            </div>
          </div>
          {status.recovery_codes_remaining <= 2 ? (
            <Banner tone="amber" title="You are running out of recovery codes.">
              Make new ones now, so a lost phone does not lock you out.
            </Banner>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" iconLeft="refresh" onPress={() => setAsking("regenerate")}>
              Make new recovery codes
            </Button>
            {status.required ? null : (
              <Button variant="ghost" onPress={() => setAsking("remove")}>
                Turn off two-step sign-in
              </Button>
            )}
          </div>
        </>
      ) : codes ? null : (
        <Enrolment required={status.required} onDone={finish} />
      )}

      <CodeModal
        key={`regenerate-${asking === "regenerate"}`}
        isOpen={asking === "regenerate"}
        onOpenChange={(open) => {
          if (!open) setAsking(null);
        }}
        title="Make new recovery codes"
        description="Your old recovery codes stop working. Enter the code your authenticator app shows now."
        confirmLabel="Make new codes"
        command={async (code) => {
          const result = await regenerateCodes(code);
          toast.success("New recovery codes made");
          finish(result.recovery_codes);
        }}
      />
      <CodeModal
        key={`remove-${asking === "remove"}`}
        isOpen={asking === "remove"}
        onOpenChange={(open) => {
          if (!open) setAsking(null);
        }}
        title="Turn off two-step sign-in"
        description="Your account goes back to a password alone. Enter a current authenticator or recovery code to confirm."
        confirmLabel="Turn it off"
        danger
        command={async (code) => {
          await removeTotp(code);
          toast.success("Two-step sign-in turned off");
          await refresh();
        }}
      />
    </GlassPanel>
  );
}

function Enrolment({ required, onDone }: { required: boolean; onDone: (codes: string[]) => void }) {
  const [enrollment, setEnrollment] = useState<MfaEnrollment | null>(null);
  const [code, setCode] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      setEnrollment(await startTotp());
    } catch (error) {
      setFailure(problemText(error));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (!code.trim()) {
      setFieldError("Enter the 6-digit code your app shows.");
      return;
    }
    setBusy(true);
    setFailure(null);
    setFieldError(null);
    try {
      const result = await confirmTotp(code.trim());
      toast.success("Two-step sign-in is on");
      onDone(result.recovery_codes);
    } catch (error) {
      if (isProblemError(error, "invalid_code")) setFieldError("That code did not work. Check the time on your phone, then type the code showing now.");
      else setFailure(problemText(error));
    } finally {
      setBusy(false);
    }
  };

  if (!enrollment) {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        {failure ? (
          <Banner tone="ember" title="Setup did not start.">
            {failure}
          </Banner>
        ) : null}
        {required ? (
          <Banner tone="amber" title="Your role requires two-step sign-in.">
            Set it up now. It takes a minute with any authenticator app.
          </Banner>
        ) : null}
        <p className="t-body text-ink-2">Any authenticator app works: Google Authenticator, Microsoft Authenticator or 1Password, for example.</p>
        <div>
          <Button variant="secondary" iconLeft="shield" loading={busy} onPress={() => void start()}>
            Set up an authenticator app
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={(event) => void confirm(event)} noValidate className="flex min-w-0 flex-col gap-4" aria-label="Set up an authenticator app">
      {failure ? (
        <Banner tone="ember" title="The code was not confirmed.">
          {failure}
        </Banner>
      ) : null}
      <ol className="t-body-sm m-0 flex list-none flex-col gap-1 p-0 text-ink-2">
        <li>1. Scan the square with your authenticator app.</li>
        <li>2. Type the 6-digit code it shows.</li>
      </ol>
      <GlassPanel variant="solid" padding="sm" className="flex min-w-0 flex-wrap items-center gap-4">
        {/* The server draws the SVG from the provisioning URI. It is shown as an image (a data: URL), so markup in it can
            never run in the page. A light ground in both themes: a QR code only scans dark on light. */}
        {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL, nothing for next/image to optimise */}
        <img
          width={148}
          height={148}
          className="flex-none rounded-sm p-1"
          style={{ colorScheme: "light", background: "Canvas" }}
          alt="QR code for your authenticator app"
          src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(enrollment.qr_svg)}`}
        />
        <div className="flex min-w-0 flex-1 basis-48 flex-col gap-1">
          <p className="t-label text-ink-3">Cannot scan? Type this key</p>
          <p className="t-code lk-mono select-all break-all">{enrollment.secret}</p>
        </div>
      </GlassPanel>
      <div className="flex min-w-0 flex-wrap items-start gap-3">
        <TextField
          className="lk-tnum min-w-0 flex-1 basis-48"
          label="6-digit code"
          inputMode="numeric"
          autoComplete="one-time-code"
          isRequired
          value={code}
          onChange={(value) => {
            setCode(value);
            if (fieldError) setFieldError(null);
          }}
          error={fieldError}
        />
        <Button type="submit" loading={busy} className="mt-[26px]">
          Confirm code
        </Button>
      </div>
    </form>
  );
}

/** Recovery codes, shown once. */
function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      toast.success("Recovery codes copied");
    } catch {
      toast.error("Could not copy", { description: "Select the codes and copy them by hand." });
    }
  };
  return (
    <GlassPanel variant="solid" padding="md" role="status" className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-1">
        <p className="t-label text-ink">Save these recovery codes now. They are shown only this once.</p>
        <p className="t-body-sm text-ink-2">Each one signs you in once if you cannot use your authenticator app.</p>
      </div>
      <ol className="t-code lk-mono m-0 grid list-none grid-cols-2 gap-x-6 gap-y-2 p-0 select-all sm:grid-cols-5" aria-label="Recovery codes">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" iconLeft="copy" onPress={() => void copy()}>
          Copy codes
        </Button>
        <Button variant="ghost" size="sm" onPress={onDone}>
          I have saved them
        </Button>
      </div>
    </GlassPanel>
  );
}

/** Asks for a current code before a two-step change. The server's answer shows on the field. */
function CodeModal({
  isOpen,
  onOpenChange,
  title,
  description,
  confirmLabel,
  danger = false,
  command,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  command: (code: string) => Promise<void>;
}) {
  const formId = useId();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (!code.trim()) {
      setError("Enter the code from your authenticator app.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await command(code.trim());
      onOpenChange(false);
    } catch (err) {
      setError(isProblemError(err, "invalid_code") ? "That code did not work. Use the code showing now, or a recovery code you have not used." : problemText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      title={title}
      description={description}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)} isDisabled={busy}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy} variant={danger ? "danger" : "primary"}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate>
        <TextField
          label="Authenticator or recovery code"
          autoComplete="one-time-code"
          autoFocus
          isRequired
          value={code}
          onChange={setCode}
          error={error}
          className="lk-tnum"
        />
      </form>
    </Modal>
  );
}
