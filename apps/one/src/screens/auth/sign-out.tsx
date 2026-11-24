"use client";

import { useRef, useState, type CSSProperties } from "react";
import { signOut } from "@/lib/session/sign-out";
import { riseIndex } from "~/lib/motion";
import { Button, ButtonLink } from "~/ui";
import { AuthHeading, AuthProblem } from "./parts";

/**
 * /sign-out asks before acting: a link from another site can open this page, but only the person's
 * own press ends the session (no sign-out by cross-site navigation).
 */
export function SignOutScreen() {
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const problem = useRef<HTMLDivElement>(null);

  const confirm = async () => {
    if (pending) return;
    setPending(true);
    setFailed(false);
    const result = await signOut();
    if (result.ok) {
      window.location.replace("/login");
      return;
    }
    setPending(false);
    setFailed(true);
    window.requestAnimationFrame(() => problem.current?.focus());
  };

  return (
    <>
      <AuthHeading
        title={
          <>
            Sign out of this <em>device</em>?
          </>
        }
        lead="Only this device will be signed out. Anywhere else you are signed in stays as it is."
      />
      <div className="rise flex flex-col gap-5" style={riseIndex(1) as CSSProperties}>
        {failed ? (
          <AuthProblem ref={problem} title="You are still signed in.">
            The server could not be reached to end your session. Try again.
          </AuthProblem>
        ) : null}
        <div className="flex flex-col gap-2">
          <Button variant="inverse" size="lg" className="w-full" iconLeft="logOut" loading={pending} onPress={() => void confirm()}>
            Sign out
          </Button>
          <ButtonLink href="/today" variant="ghost" className="w-full">
            Stay signed in
          </ButtonLink>
        </div>
      </div>
    </>
  );
}
