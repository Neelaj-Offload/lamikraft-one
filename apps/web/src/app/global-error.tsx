"use client";

import "./globals.css";

import { buttonClasses } from "@/components/ui/styles";
import { stateMessages as m } from "@/messages/states";

/**
 * Last-resort boundary for errors in the root layout (frontend_verification §4). It replaces
 * the whole document, so it brings its own <html>, <body> and styles, and offers the two safe
 * next steps: try again, or go back to Today.
 */
export default function GlobalError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <html lang="en">
      <body className="bg-canvas font-sans text-ink">
        <main id="main" className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center gap-4 px-4 py-12">
          <title>{m.pageError.title}</title>
          <h1 className="text-3xl font-bold tracking-tight">{m.pageError.title}</h1>
          <p className="text-ink-muted">{m.pageError.body}</p>
          {error.digest ? (
            <p className="text-sm text-ink-muted">
              {m.requestId}: <span className="font-mono text-ink select-all">{error.digest}</span>
            </p>
          ) : null}
          <p className="flex flex-wrap gap-2">
            <button type="button" onClick={() => retry()} className={buttonClasses("primary")}>
              {m.retry}
            </button>
            {/* A full load on purpose: the app's providers may be what failed. */}
            <a href="/today" className={buttonClasses("secondary")}>
              {m.backToToday}
            </a>
          </p>
        </main>
      </body>
    </html>
  );
}
