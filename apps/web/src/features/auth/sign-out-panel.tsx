"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { SignOutIcon } from "@/components/ui/icons";
import { LinkButton } from "@/components/ui/link";
import { signOut } from "@/lib/session/sign-out";
import { authMessages as m } from "@/messages/auth";

/**
 * /sign-out asks before acting: a link from another site can open this page, but only the
 * person's own press revokes the session (no logout by cross-site navigation).
 */
export function SignOutPanel() {
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  const confirm = async () => {
    setPending(true);
    setFailed(false);
    const result = await signOut();
    if (result.ok) {
      window.location.replace("/login");
      return;
    }
    setPending(false);
    setFailed(true);
  };

  return (
    <div className="flex flex-col gap-5">
      <p className="text-center text-ink-muted">{m.signOut.body}</p>
      {failed ? (
        <p role="alert" className="rounded-lg border border-danger bg-danger-bg p-3 text-sm text-danger">
          {m.signOut.failed}
        </p>
      ) : null}
      <div className="flex flex-col gap-2">
        <Button
          variant="primary"
          onPress={() => void confirm()}
          isPending={pending}
          pendingLabel={m.signOut.working}
          icon={<SignOutIcon size={18} />}
          className="w-full"
        >
          {m.signOut.confirm}
        </Button>
        <LinkButton href="/today" variant="quiet" className="w-full">
          {m.signOut.cancel}
        </LinkButton>
      </div>
    </div>
  );
}
