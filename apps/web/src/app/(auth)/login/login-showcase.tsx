"use client";

import { useEffect, useRef } from "react";
import { Wordmark } from "@/components/shell/wordmark";
import { ArrowDownIcon } from "@/components/ui/icons";
import { linkClasses } from "@/components/ui/styles";
import { LoginForm } from "@/features/auth/login-form";
import { cx } from "@/lib/cx";
import { playLoginEntrance } from "@/lib/motion/showcase/login-entrance";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";
import { authMessages as m } from "@/messages/auth";
import { MaterialRow, MaterialStage } from "./material-stage";
import { LoginStory } from "./story";
import { useLenis } from "./use-lenis";

/**
 * The sign-in showcase: an editorial split (headline and form left, the material composition
 * right from 1024 px), a GSAP entrance of at most 900 ms once per load, pointer parallax of at
 * most 12 px and Lenis smooth scroll to the story below the fold. Reduced motion (OS or in-app):
 * the composition is static, there is no parallax and no Lenis, and the form is simply there.
 */
export function LoginShowcase({ next }: { next: string }) {
  const root = useRef<HTMLDivElement>(null);
  const reduced = useIsMotionReduced();
  useLenis(!reduced);

  // Plays once the client knows motion is allowed (the server snapshot is "reduced"). Strict Mode
  // runs this twice in development: the first run's cleanup reverts before its import resolves.
  useEffect(() => {
    if (reduced || !root.current) return;
    let cancelled = false;
    let cleanup: (() => void) | null = null;
    void playLoginEntrance(root.current).then((revert) => {
      if (cancelled) revert();
      else cleanup = revert;
    });
    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [reduced]);

  return (
    <div ref={root} id="top" className="bg-canvas">
      <main id="main" className="grid min-h-dvh grid-cols-1 lg:grid-cols-[minmax(0,11fr)_minmax(0,10fr)] xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex flex-col px-6 py-8 md:px-12 lg:px-16 xl:px-24">
          <header data-entrance="mark" className="flex items-center">
            <Wordmark />
          </header>

          <div className="my-auto flex max-w-xl flex-col gap-7 py-14 md:py-20">
            <p data-entrance="copy" className="text-xs font-semibold tracking-[0.12em] text-ink-muted uppercase">
              {m.showcase.eyebrow}
            </p>
            <h1 className="font-display text-[44px] leading-[0.98] font-medium tracking-[-0.025em] text-ink sm:text-[56px] md:text-[64px] xl:text-[76px]">
              {m.showcase.headline.map((line) => (
                <span key={line} data-entrance="line" className="block">
                  {line}
                </span>
              ))}
            </h1>
            <p data-entrance="copy" className="max-w-md text-lg leading-relaxed text-ink-muted">
              {m.showcase.lede}
            </p>
            <MaterialRow className="lg:hidden" />
            <div data-entrance="copy" className="w-full max-w-sm pt-2">
              <LoginForm next={next} />
            </div>
          </div>

          <footer data-entrance="copy" className="flex items-center justify-between gap-4 text-sm text-ink-muted">
            <a href="#story" className={cx(linkClasses, "inline-flex items-center gap-1.5 no-underline hover:underline")}>
              {m.showcase.scrollHint}
              <ArrowDownIcon size={16} />
            </a>
            <span>Lamikraft One</span>
          </footer>
        </div>

        <MaterialStage parallax={!reduced} className="hidden min-h-[640px] lg:block" />
      </main>
      <LoginStory />
    </div>
  );
}
