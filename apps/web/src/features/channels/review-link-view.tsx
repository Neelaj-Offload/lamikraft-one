"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { InfoIcon } from "@/components/ui/icons";
import { LinkButton } from "@/components/ui/link";
import { Loading, StateView } from "@/components/ui/states";
import { isProblemError, seedCsrfToken } from "@/lib/api/client";
import { safeAppPath } from "@/lib/safe-path";
import { useSession } from "@/lib/session/context";
import { channelsMessages } from "@/messages/channels";
import { resolveReviewLink } from "./api";

const m = channelsMessages.review;

/** The problem codes of POST /review-links/{token}/resolve, as the sentence the person reads. */
export function reviewLinkProblem(error: unknown): string {
  if (!isProblemError(error)) return m.invalid;
  if (error.code === "review_link_wrong_user") return m.wrongUser;
  if (error.code === "review_link_expired") return m.expired;
  if (error.code === "review_link_used") return m.used;
  return m.invalid;
}

/**
 * `/r/{token}`: the token is a reference, not authentication. The (app) layout already requires a
 * signed-in session; the server checks the link belongs to this person, then we go to the canonical screen.
 */
export function ReviewLinkView({ token }: { token: string }) {
  const router = useRouter();
  const { bootstrap } = useSession();
  const [problem, setProblem] = useState<string | null>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // a single-use link must be resolved once, even under Strict Mode
    started.current = true;
    // this effect runs before the SessionProvider's (child effects first): seed the rotated CSRF token now, or the
    // single-use POST would be refused on a fresh page load
    seedCsrfToken(bootstrap.csrf_token);
    resolveReviewLink(token)
      .then((resolved) => {
        const target = safeAppPath(resolved.redirect_path);
        if (target) router.replace(target as Route);
        else setProblem(m.invalid);
      })
      .catch((error: unknown) => setProblem(reviewLinkProblem(error)));
  }, [bootstrap.csrf_token, router, token]);
  if (problem) {
    return (
      <StateView icon={<InfoIcon />} title={m.title} headingLevel={1}>
        <p>{problem}</p>
        <div className="mt-3">
          <LinkButton href="/inbox">{m.goInbox}</LinkButton>
        </div>
      </StateView>
    );
  }
  return (
    <div className="flex max-w-xl flex-col gap-3">
      <h1 className="text-xl font-bold text-ink">{m.title}</h1>
      <Loading label={m.opening} rows={1} />
    </div>
  );
}
