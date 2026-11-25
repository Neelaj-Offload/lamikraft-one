"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { isProblemError } from "@/lib/api/errors";
import { Button, GlassPanel, TextField, toast } from "~/ui";
import {
  confirmAuthenticatorSetup,
  fetchTwoStepStatus,
  startAuthenticatorSetup,
  verifyTwoStepCode,
  type TwoStepEnrollment,
} from "~/data/entry";
import { riseIndex } from "~/lib/motion";
import { AuthForm, AuthHeading, AuthLoading, AuthProblem } from "./parts";

/**
 * The second sign-in step. Three situations share this address:
 *   verify  the account has an authenticator: enter its code (or a recovery code)
 *   enrol   the role requires one and there is none yet: set it up, then save the recovery codes
 *   done    nothing left to do: continue to `next`
 * A session that has ended goes back to sign-in and returns here afterwards.
 */
type Stage = "checking" | "verify" | "enrol" | "codes";

function problemText(error: unknown): string {
  if (isProblemError(error)) return error.detail ?? error.title;
  return "Something went wrong. Try again.";
}

export function TwoStepScreen({ next }: { next: string }) {
  const [stage, setStage] = useState<Stage>("checking");
  const [codes, setCodes] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    const toSignIn = () => window.location.replace(`/login?next=${encodeURIComponent(next)}`);
    // An enrolment-only session can read its status; a session waiting for a code cannot (401).
    fetchTwoStepStatus().then(
      (status) => {
        if (!live) return;
        if (status.enrolled) window.location.assign(next);
        else setStage("enrol");
      },
      (error: unknown) => {
        if (!live) return;
        if (isProblemError(error, "mfa_verification_required")) setStage("verify");
        else if (isProblemError(error) && error.status === 401) toSignIn();
        else setStage("verify");
      },
    );
    return () => {
      live = false;
    };
  }, [next]);

  if (stage === "checking") {
    return (
      <>
        <AuthHeading
          title={
            <>
              One more <em>step</em>
            </>
          }
          lead="Checking where your sign-in stands."
        />
        <AuthLoading label="Checking your sign-in" fields={1} />
      </>
    );
  }
  if (stage === "verify") return <VerifyCode next={next} />;
  if (stage === "enrol") {
    return (
      <Enrol
        onDone={(issued) => {
          setCodes(issued);
          setStage("codes");
        }}
      />
    );
  }
  return <RecoveryCodes codes={codes} next={next} />;
}

function VerifyCode({ next }: { next: string }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async () => {
    if (pending) return;
    if (!code.trim()) {
      setError("Enter the code from your authenticator app.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await verifyTwoStepCode(code.trim());
      window.location.assign(next);
    } catch (err) {
      if (isProblemError(err, "session_expired")) {
        window.location.replace(`/login?next=${encodeURIComponent(next)}`);
        return;
      }
      setError(isProblemError(err, "invalid_code") ? "That code did not work. Use the code showing now, or a recovery code you have not used." : problemText(err));
      setPending(false);
    }
  };

  return (
    <>
      <AuthHeading
        title={
          <>
            Enter your <em>code</em>
          </>
        }
        lead="Open your authenticator app and type the 6-digit code for Lamikraft One."
      />
      <AuthForm label="Two-step sign-in" onSubmit={() => void submit()}>
        <TextField
          label="Code"
          name="code"
          size="lg"
          autoComplete="one-time-code"
          inputMode="text"
          autoFocus
          isRequired
          value={code}
          onChange={(value) => {
            setCode(value);
            if (error) setError(null);
          }}
          help="No phone to hand? Type one of your recovery codes instead."
          error={error}
          className="lk-tnum"
        />
        <Button type="submit" size="lg" className="w-full" loading={pending} iconRight="arrowRight">
          Continue
        </Button>
      </AuthForm>
    </>
  );
}

function Enrol({ onDone }: { onDone: (codes: string[]) => void }) {
  const [enrollment, setEnrollment] = useState<TwoStepEnrollment | null>(null);
  const [code, setCode] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const problem = useRef<HTMLDivElement>(null);

  const start = async () => {
    if (pending) return;
    setPending(true);
    setFailure(null);
    try {
      setEnrollment(await startAuthenticatorSetup());
    } catch (err) {
      setFailure(problemText(err));
      window.requestAnimationFrame(() => problem.current?.focus());
    } finally {
      setPending(false);
    }
  };

  const confirm = async () => {
    if (pending) return;
    if (!code.trim()) {
      setFieldError("Enter the 6-digit code your app shows.");
      return;
    }
    setPending(true);
    setFailure(null);
    setFieldError(null);
    try {
      const result = await confirmAuthenticatorSetup(code.trim());
      onDone(result.recovery_codes);
    } catch (err) {
      if (isProblemError(err, "invalid_code")) setFieldError("That code did not work. Check the time on your phone, then type the code showing now.");
      else {
        setFailure(problemText(err));
        window.requestAnimationFrame(() => problem.current?.focus());
      }
      setPending(false);
    }
  };

  if (!enrollment) {
    return (
      <>
        <AuthHeading
          title={
            <>
              Add a second <em>step</em>
            </>
          }
          lead="Your role needs an authenticator app. Set it up once and it protects every sign-in after this one."
        />
        <div className="rise flex flex-col gap-5" style={riseIndex(1) as CSSProperties}>
          {failure ? (
            <AuthProblem ref={problem} title="Setup did not start.">
              {failure}
            </AuthProblem>
          ) : null}
          <p className="t-body text-ink-2">Any authenticator app works: Google Authenticator, Microsoft Authenticator or 1Password, for example.</p>
          <Button size="lg" className="w-full" loading={pending} onPress={() => void start()} iconLeft="shield">
            Set up an authenticator app
          </Button>
        </div>
      </>
    );
  }

  return (
    <>
      <AuthHeading
        title={
          <>
            Scan, then <em>confirm</em>
          </>
        }
        lead="Scan the square with your authenticator app, then type the 6-digit code it shows."
      />
      <AuthForm label="Set up an authenticator app" onSubmit={() => void confirm()}>
        {failure ? (
          <AuthProblem ref={problem} title="The code was not confirmed.">
            {failure}
          </AuthProblem>
        ) : null}
        <GlassPanel variant="solid" padding="sm" className="flex items-center gap-4">
          {/* The server draws the SVG from the provisioning URI. It is shown as an image (a data: URL), so markup
              in it can never run in the page. The system "Canvas" colour under a light scheme keeps the ground
              white in both themes: a QR code only scans dark on light. */}
          {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL, nothing for next/image to optimise */}
          <img
            width={132}
            height={132}
            className="flex-none rounded-sm p-1"
            style={{ colorScheme: "light", background: "Canvas" }}
            alt="QR code for your authenticator app"
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(enrollment.qr_svg)}`}
          />
          <div className="flex min-w-0 flex-col gap-1">
            <p className="t-label text-ink-3">Cannot scan? Type this key</p>
            <p className="t-code lk-mono select-all break-all">{enrollment.secret}</p>
          </div>
        </GlassPanel>
        <TextField
          label="6-digit code"
          name="code"
          size="lg"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus
          isRequired
          value={code}
          onChange={(value) => {
            setCode(value);
            if (fieldError) setFieldError(null);
          }}
          error={fieldError}
          className="lk-tnum"
        />
        <Button type="submit" size="lg" className="w-full" loading={pending}>
          Confirm code
        </Button>
      </AuthForm>
    </>
  );
}

function RecoveryCodes({ codes, next }: { codes: string[]; next: string }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      toast.success("Recovery codes copied");
    } catch {
      toast.error("Could not copy", { description: "Select the codes and copy them by hand." });
    }
  };
  return (
    <>
      <AuthHeading
        title={
          <>
            Keep these <em>codes</em>
          </>
        }
        lead="Each one signs you in once if you cannot use your authenticator app. They are shown only this time."
      />
      <div className="rise flex flex-col gap-5" style={riseIndex(1) as CSSProperties}>
        <GlassPanel variant="solid" padding="sm" role="status">
          <ol className="t-code lk-mono grid list-none grid-cols-2 gap-x-6 gap-y-2 p-0 select-all" aria-label="Recovery codes">
            {codes.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ol>
        </GlassPanel>
        <div className="flex flex-col gap-2">
          <Button size="lg" className="w-full" onPress={() => window.location.assign(next)} iconRight="arrowRight">
            I have saved them, continue
          </Button>
          <Button variant="ghost" className="w-full" iconLeft="copy" onPress={() => void copy()}>
            Copy codes
          </Button>
        </div>
      </div>
    </>
  );
}
