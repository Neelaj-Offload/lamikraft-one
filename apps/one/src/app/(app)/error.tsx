"use client";

import { useEffect } from "react";
import { Page } from "~/shell/page";
import { Button, ButtonLink } from "~/ui/button";
import { EmptyState } from "~/ui/empty-state";

/** A screen crashed while rendering. The shell stays; the person can retry or leave. */
export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <Page width="narrow">
      <EmptyState
        icon="alert"
        title="This screen hit a problem"
        text={
          <>
            Nothing you entered elsewhere is lost. Try the screen again; if it keeps failing, share this reference with your admin
            {error.digest ? (
              <>
                : <span className="t-code-sm lk-mono select-all">{error.digest}</span>
              </>
            ) : null}
            .
          </>
        }
        actions={
          <>
            <Button variant="inverse" iconLeft="refresh" onPress={reset}>
              Try again
            </Button>
            <ButtonLink href="/today" variant="ghost">
              Back to Today
            </ButtonLink>
          </>
        }
      />
    </Page>
  );
}
