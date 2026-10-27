"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ErrorIcon, InfoIcon } from "@/components/ui/icons";
import { LinkButton } from "@/components/ui/link";
import { StateView } from "@/components/ui/states";
import { ProblemError } from "@/lib/api/errors";
import { authMessages as m } from "@/messages/auth";
import { demoSignIn, loginFailure, readFragmentToken } from "./auth-api";

type State =
  | { kind: "checking" }
  | { kind: "missing" }
  | { kind: "invalid" }
  | { kind: "error"; message: string; requestId: string | null };

/**
 * One-time demo links carry their token in a `#t=` fragment (api-conventions §7): fragments
 * never reach servers or Referer headers. The page reads the token once, removes it from the
 * address bar and history with replaceState, then POSTs it. The page is served with
 * `Referrer-Policy: no-referrer` (next.config.ts) as a second guard.
 */
export function DemoSignIn() {
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
      if (error instanceof ProblemError && (error.code === "link_invalid_or_used" || error.status === 401)) {
        token.current = null;
        setState({ kind: "invalid" });
        return;
      }
      const failure = loginFailure(error);
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
    void attempt();
  }, []);

  if (state.kind === "checking") {
    return (
      <p role="status" className="text-center text-ink-muted">
        {m.demo.checking}
      </p>
    );
  }
  if (state.kind === "missing" || state.kind === "invalid") {
    const missing = state.kind === "missing";
    return (
      <StateView
        icon={<InfoIcon />}
        title={missing ? m.demo.missingTitle : m.demo.invalidTitle}
        actions={<LinkButton href="/login">{m.demo.toLogin}</LinkButton>}
      >
        {missing ? m.demo.missingBody : m.demo.invalidBody}
      </StateView>
    );
  }
  return (
    <StateView
      icon={<ErrorIcon />}
      title={m.demo.errorTitle}
      tone="danger"
      role="alert"
      actions={
        <>
          <Button variant="primary" onPress={() => void attempt()}>
            {m.demo.retry}
          </Button>
          <LinkButton href="/login">{m.demo.toLogin}</LinkButton>
        </>
      }
    >
      <p>{state.message}</p>
      {state.requestId ? (
        <p className="mt-1 text-sm">
          {m.requestId}: <span className="font-mono text-ink select-all">{state.requestId}</span>
        </p>
      ) : null}
    </StateView>
  );
}
