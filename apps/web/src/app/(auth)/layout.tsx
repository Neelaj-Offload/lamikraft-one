import type { ReactNode } from "react";
import { Wordmark } from "@/components/shell/wordmark";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main id="main" className="flex min-h-dvh flex-col items-center justify-center gap-8 px-4 py-12">
      <Wordmark />
      <div className="w-full max-w-sm">{children}</div>
    </main>
  );
}
