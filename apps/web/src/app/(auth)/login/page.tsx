import type { Metadata, Route } from "next";
import { redirect } from "next/navigation";
import { LoginForm } from "@/features/auth/login-form";
import { safeNextPath } from "@/lib/api/client";
import { getRoute } from "@/lib/routes";
import { loadSession } from "@/lib/session/server";
import { authMessages as m } from "@/messages/auth";

const route = getRoute("login");

export const metadata: Metadata = { title: route.label };

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const next = safeNextPath(typeof params.next === "string" ? params.next : null) ?? "/today";

  // Already signed in: go straight on. If the API cannot answer, the form is still shown.
  const session = await loadSession();
  if (session.status === "ok") redirect(next as Route);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1 text-center">
        <h1 className="text-3xl font-bold tracking-tight">{route.label}</h1>
        <p className="text-ink-muted">{m.login.intro}</p>
      </header>
      <LoginForm next={next} />
    </div>
  );
}
