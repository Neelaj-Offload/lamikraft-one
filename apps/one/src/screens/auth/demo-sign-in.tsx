"use client";

import { useEffect, useRef, useState } from "react";
import { demoSignIn, readFragmentToken } from "@/features/auth/auth-api";
import { ProblemError } from "@/lib/api/errors";
import { Badge, Button, ButtonLink, Skeleton } from "~/ui";
import { AuthHeading, AuthNotice } from "./parts";
import { signInFailure } from "./problems";

type State =
  | { kind: "checking" }
  | { kind: "missing" }
  | { kind: "invalid" }
  | { kind: "error"; message: string; requestId: string | null };

/**
 * One-time demo links carry their token in a `#t=` fragment, which never reaches a server or a
 * Referer header. The page reads the token once, removes it from the address bar and history,
 * then posts it. Nothing here needs a press: the link itself is the request to sign in.
 */
export function DemoSignInScreen() {
  const [state, setState] = useState<State>({ kind: "checking" });
  const token = useRef<string | null>(null);
  const started = useRef(false);

  const attempt = async () => {
    if (!token.current) {
      setState({ kind: "missing" });
      return;
    }
    setState({ kind: "checking" });
    try {
      await demoSignIn(token.current);
      token.current = null;
      window.location.replace("/today");
    } catch (error) {
      // A token the server will not even read (cut short when the link was copied) is as dead as a spent one.
      if (error instanceof ProblemError && (error.code === "link_invalid_or_used" || error.status === 401 || error.status === 422)) {
        token.current = null;
        setState({ kind: "invalid" });
        return;
      }
      const failure = signInFailure(error);
      setState({ kind: "error", message: failure.message, requestId: failure.requestId });
    }
  };

  useEffect(() => {
    // Strict Mode runs effects twice in development; the token must be read and spent once.
    if (started.current) return;
    started.current = true;
    token.current = readFragmentToken(window.location.hash);
    if (window.location.hash) {
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}`);
    }
    // The first paint already shows "checking"; the attempt only sets state after its request settles.
    queueMicrotask(() => void attempt());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once; `attempt` reads refs only
  }, []);

  const heading = (
    <AuthHeading
      title={
        <>
          The demo <em>workspace</em>
        </>
      }
      badge={
        <Badge tone="gold" dot>
          Demo
        </Badge>
      }
      lead="Fictional people, customers and documents. Nothing is sent outside Lamikraft One."
    />
  );

  if (state.kind === "checking") {
    return (
      <>
        {heading}
        <div className="flex flex-col gap-3" role="status">
          <p className="t-body text-ink-2">Signing you in.</p>
          <Skeleton height={48} className="rounded-pill" />
        </div>
      </>
    );
  }

  if (state.kind === "missing" || state.kind === "invalid") {
    const missing = state.kind === "missing";
    return (
      <>
        {heading}
        <AuthNotice
          icon="link"
          title={missing ? "Open the full demo link" : "This demo link can no longer be used"}
          actions={
            <ButtonLink href="/login" variant="inverse" size="lg" className="w-full">
              Sign in with your email
            </ButtonLink>
          }
        >
          {missing
            ? "This page signs you in from a one-time demo link. Open the whole link you were given, or sign in with your own email."
            : "Demo links work once and expire. Ask for a new link, or sign in with your own email."}
        </AuthNotice>
      </>
    );
  }

  return (
    <>
      {heading}
      <AuthNotice
        icon="alert"
        tone="ember"
        title="The demo sign-in did not finish"
        actions={
          <>
            <Button size="lg" className="w-full" iconLeft="refresh" onPress={() => void attempt()}>
              Try again
            </Button>
            <ButtonLink href="/login" variant="ghost" className="w-full">
              Sign in with your email
            </ButtonLink>
          </>
        }
      >
        <p>{state.message}</p>
        {state.requestId ? <p className="t-code-sm lk-mono mt-1 select-all">Reference {state.requestId}</p> : null}
      </AuthNotice>
    </>
  );
}
