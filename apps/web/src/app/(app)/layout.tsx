import Link from "next/link";
import type { ReactNode } from "react";
import { PrimaryNav } from "@/components/shell/primary-nav";
import { SkipLink } from "@/components/shell/skip-link";
import { Wordmark } from "@/components/shell/wordmark";

/** Minimal signed-in frame; the full shell (sidebar, top bar, rail, phone tabs) arrives in Slice 1. */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[208px_minmax(0,1fr)]">
      <SkipLink />
      <header className="flex flex-col gap-3 border-b bg-surface px-4 pt-3 pb-2 lg:sticky lg:top-0 lg:h-dvh lg:gap-6 lg:border-r lg:border-b-0 lg:px-3 lg:py-5">
        <Link href="/today" className="inline-flex min-h-11 items-center self-start rounded-md px-1 lg:px-3">
          <Wordmark />
        </Link>
        <PrimaryNav />
      </header>
      <main id="main" tabIndex={-1} className="min-w-0 px-4 py-6 outline-none lg:px-10 lg:py-8">
        {children}
      </main>
    </div>
  );
}
