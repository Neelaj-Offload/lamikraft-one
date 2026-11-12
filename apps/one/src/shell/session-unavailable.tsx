"use client";

import type { ProblemDetails } from "@/lib/api/errors";
import { Button, ButtonLink } from "~/ui/button";
import { EmptyState } from "~/ui/empty-state";

/** The session could not be loaded (API down, network). Never implies the person is signed out. */
export function SessionUnavailable({ problem }: { problem: ProblemDetails }) {
  return (
    <>
      <div className="app-scene" aria-hidden />
      <main id="main" className="relative z-[1] grid min-h-dvh place-items-center p-5">
        <div className="lk-glass lk-glass-pad-lg w-full max-w-xl scale-in">
          <EmptyState
            icon="alert"
            title="Your workspace could not be opened"
            text={
              <>
                Lamikraft One could not load your session. Your work is safe; reload in a moment.
                {problem.request_id ? (
                  <>
                    {" "}
                    <span className="t-code-sm lk-mono select-all">Reference {problem.request_id}</span>
                  </>
                ) : null}
              </>
            }
            actions={
              <>
                <Button variant="inverse" iconLeft="refresh" onPress={() => window.location.reload()}>
                  Reload
                </Button>
                <ButtonLink href="/login" variant="ghost">
                  Go to sign-in
                </ButtonLink>
              </>
            }
          />
        </div>
      </main>
    </>
  );
}
