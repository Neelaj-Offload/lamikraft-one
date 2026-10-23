import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Page not found",
};

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center gap-4 px-4 py-12">
      <h1 className="text-3xl font-bold tracking-tight">Page not found</h1>
      <p className="text-ink-muted">This address does not match a page in Lamikraft One.</p>
      <p>
        <Link
          href="/today"
          className="inline-flex min-h-11 items-center rounded-md bg-forest px-4 font-semibold text-on-forest transition-colors hover:bg-forest-strong"
        >
          Back to Today
        </Link>
      </p>
    </main>
  );
}
