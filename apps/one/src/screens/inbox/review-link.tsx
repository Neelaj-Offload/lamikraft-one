"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { resolveReviewLink } from "@/features/channels/api";
import { isProblemError, seedCsrfToken } from "@/lib/api/client";
import { safeAppPath } from "@/lib/safe-path";
import { useSession } from "@/lib/session/context";
import { Page, PageHeader } from "~/shell/page";
import { ButtonLink, GlassPanel, Icon, SkeletonText } from "~/ui";

interface LinkProblem {
  title: string;
  text: string;
}

const INVALID: LinkProblem = {
  title: "This link does not work",
  text: "It may have been cut short when it was copied. Open the request from your inbox instead.",
};

/** The problem codes of `POST /review-links/{token}/resolve`, as what the person reads. */
function problemOf(error: unknown): LinkProblem {
  if (!isProblemError(error)) return INVALID;
  if (error.code === "review_link_wrong_user") {
    return { title: "This link was sent to someone else", text: "Sign in as the person it was sent to, or open your own requests from your inbox." };
  }
  if (error.code === "review_link_expired") {
    return { title: "This link has expired", text: "Ask Lamikraft on WhatsApp for a fresh one, or open the request from your inbox." };
  }
  if (error.code === "review_link_used") {
    return { title: "This link has already been used", text: "A review link opens once. The request is still in your inbox." };
  }
  return INVALID;
}

/**
 * `/r/{token}`: the token points at a request, it does not sign anyone in. The signed-in frame has
 * already required a session; the server checks the link belongs to this person, then the screen
 * moves to the address it names. A link that no longer works says why and offers the inbox.
 */
export function ReviewLinkScreen({ token }: { token: string }) {
  const router = useRouter();
  const { bootstrap } = useSession();
  const [problem, setProblem] = useState<LinkProblem | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // a single-use link is resolved once, even under Strict Mode
    started.current = true;
    // This effect runs before the session provider's own (child effects first): seed the rotated
    // CSRF token now, or the single-use POST would be refused on a fresh page load.
    seedCsrfToken(bootstrap.csrf_token);
    resolveReviewLink(token)
      .then((resolved) => {
        const target = safeAppPath(resolved.redirect_path);
        if (target) router.replace(target as Route);
        else setProblem(INVALID);
      })
      .catch((error: unknown) => setProblem(problemOf(error)));
  }, [bootstrap.csrf_token, router, token]);

  if (problem) {
    return (
      <Page width="narrow">
        <PageHeader
          display
          eyebrow="Review link"
          title={problem.title}
          lead={problem.text}
          actions={
            <ButtonLink href="/inbox" iconRight="arrowRight">
              Open your inbox
            </ButtonLink>
          }
        />
      </Page>
    );
  }

  return (
    <Page width="narrow">
      <PageHeader display eyebrow="Review link" title="Opening your review" lead="Checking that this link is yours and still good." />
      <GlassPanel padding="lg" className="rise flex items-start gap-4" role="status" aria-label="Checking the link">
        <span className="bg-ink/6 text-ink-2 grid size-10 flex-none place-items-center rounded-md" aria-hidden="true">
          <Icon name="link" size={18} />
        </span>
        <div className="flex-1 pt-1">
          <SkeletonText lines={2} />
        </div>
      </GlassPanel>
    </Page>
  );
}
