"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type Ref } from "react";
import { Button as RacButton } from "react-aria-components";
import { readFragmentToken } from "@/features/auth/auth-api";
import { riseIndex } from "~/lib/motion";
import { Banner, Icon, Skeleton, TextField, type TextFieldProps } from "~/ui";

/**
 * The shared pieces of every signed-out screen. Each screen is the same three things in the same
 * order: a serif heading, one sentence, then the form (or the single message that replaces it).
 */

export function AuthHeading({ title, lead, badge }: { title: ReactNode; lead?: ReactNode; /** A small label above the title, such as the Demo badge. */ badge?: ReactNode }) {
  return (
    <header className="rise flex flex-col gap-3">
      {badge ? <div className="flex">{badge}</div> : null}
      <h1 className="t-display-sm">{title}</h1>
      {lead ? <p className="t-body-lg text-ink-2">{lead}</p> : null}
    </header>
  );
}

/** The form column: fields, the one action, then at most one quiet way out. */
export function AuthForm({ children, onSubmit, label }: { children: ReactNode; onSubmit: () => void; label: string }) {
  return (
    <form
      noValidate
      aria-label={label}
      className="rise flex flex-col gap-5"
      style={riseIndex(1) as CSSProperties}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      {children}
    </form>
  );
}

/** A failed attempt, said once above the fields. It takes focus so it is read out. */
export function AuthProblem({
  title,
  children,
  requestId,
  ref,
  action,
}: {
  title: string;
  children: ReactNode;
  requestId?: string | null;
  ref?: Ref<HTMLDivElement>;
  action?: ReactNode;
}) {
  return (
    <div ref={ref} tabIndex={-1} className="rounded-md outline-none">
      <Banner tone="ember" title={title} action={action}>
        {children}
        {requestId ? (
          <>
            {" "}
            <span className="t-code-sm lk-mono select-all">Reference {requestId}</span>
          </>
        ) : null}
      </Banner>
    </div>
  );
}

/** A message that replaces the form: the link is missing or spent, or the job is done. */
export function AuthNotice({
  icon,
  tone = "neutral",
  title,
  children,
  actions,
}: {
  icon: "mail" | "key" | "link" | "checkCircle" | "alert" | "shield";
  tone?: "neutral" | "leaf" | "ember";
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  const toneClass = tone === "leaf" ? "bg-leaf-soft text-leaf-text" : tone === "ember" ? "bg-ember-soft text-ember-text" : "bg-gold-soft text-gold-strong";
  return (
    <section className="rise flex flex-col gap-5" style={riseIndex(1) as CSSProperties} role={tone === "ember" ? "alert" : "status"}>
      <div className="flex items-start gap-4">
        <span className={`grid size-11 flex-none place-items-center rounded-md ${toneClass}`} aria-hidden>
          <Icon name={icon} size={20} />
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="t-h3">{title}</h2>
          <div className="t-body text-ink-2">{children}</div>
        </div>
      </div>
      {actions ? <div className="flex flex-col gap-2">{actions}</div> : null}
    </section>
  );
}

/** Placeholder with the shape of a two-field form, while a link or a session is being checked. */
export function AuthLoading({ label, fields = 2 }: { label: string; fields?: number }) {
  return (
    <div className="flex flex-col gap-5" role="status" aria-label={label}>
      {Array.from({ length: fields }, (_, index) => (
        <div key={index} className="flex flex-col gap-2">
          <Skeleton width={96} height={12} />
          <Skeleton height={48} className="rounded-md" />
        </div>
      ))}
      <Skeleton height={48} className="rounded-pill" />
    </div>
  );
}

export type PasswordFieldProps = Omit<TextFieldProps, "type" | "suffix">;

/** A password input with a show and hide control. The value is never logged or kept beyond the form. */
export function PasswordField(props: PasswordFieldProps) {
  const [shown, setShown] = useState(false);
  return (
    <TextField
      {...props}
      type={shown ? "text" : "password"}
      suffix={
        <RacButton
          className="press -mr-1 grid size-8 place-items-center rounded-pill text-ink-3"
          aria-label={shown ? "Hide password" : "Show password"}
          aria-pressed={shown}
          onPress={() => setShown((current) => !current)}
        >
          <Icon name={shown ? "eyeOff" : "eye"} size={18} />
        </RacButton>
      }
    />
  );
}

/**
 * One-time links carry their token in the URL fragment (`#t=…`), which never reaches a server log
 * or a Referer header. The token is read once and removed from the address bar and from history;
 * after that it only ever travels in a POST body.
 *
 * `undefined` while reading, `null` when the page was opened without a token.
 */
export function useFragmentToken(): string | null | undefined {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const read = useRef(false);
  useEffect(() => {
    // Strict Mode runs effects twice in development; the second run would find the fragment already stripped.
    if (read.current) return;
    read.current = true;
    const value = readFragmentToken(window.location.hash);
    if (window.location.hash) window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}`);
    queueMicrotask(() => setToken(value));
  }, []);
  return token;
}
