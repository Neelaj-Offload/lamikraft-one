"use client";

import { Button } from "@/components/ui/button";
import { ErrorIcon, RefreshIcon } from "@/components/ui/icons";
import { LinkButton } from "@/components/ui/link";
import { StateView } from "@/components/ui/states";
import type { ProblemDetails } from "@/lib/api/errors";
import { stateMessages } from "@/messages/states";
import { shellMessages as m } from "@/messages/shell";
import { Wordmark } from "./wordmark";

/**
 * Rendered by the (app) layout when the session bootstrap fails for a reason other than 401
 * (API down, 5xx, unreadable payload). Signing in again would not help, so it offers Reload,
 * shows the request id, and keeps sign-in reachable.
 */
export function SessionUnavailable({ problem }: { problem: ProblemDetails }) {
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center gap-6 px-4 py-12">
      <Wordmark />
      <StateView
        icon={<ErrorIcon />}
        title={m.sessionUnavailable.title}
        headingLevel={1}
        tone="danger"
        role="alert"
        actions={
          <>
            <Button variant="primary" onPress={() => window.location.reload()} icon={<RefreshIcon size={18} />}>
              {m.sessionUnavailable.reload}
            </Button>
            <LinkButton href="/login">{m.sessionUnavailable.signIn}</LinkButton>
          </>
        }
      >
        <p>{m.sessionUnavailable.body}</p>
        {problem.request_id ? (
          <p className="mt-1 text-sm">
            {stateMessages.requestId}: <span className="font-mono text-ink select-all">{problem.request_id}</span>
          </p>
        ) : null}
      </StateView>
    </main>
  );
}
