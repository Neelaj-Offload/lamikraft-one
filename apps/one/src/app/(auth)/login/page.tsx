import type { Metadata, Route } from "next";
import { redirect } from "next/navigation";
import { safeNextPath } from "@/lib/api/client";
import { loadSession } from "@/lib/session/server";
import { LoginScreen } from "~/screens/auth/login";

export const metadata: Metadata = { title: "Sign in" };

/** `next` is only ever a same-origin path that is not the sign-in page itself. */
export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const next = safeNextPath(typeof params.next === "string" ? params.next : null) ?? "/today";

  // Already signed in: go straight on. If the API cannot answer, the form is still shown.
  const session = await loadSession();
  if (session.status === "ok") redirect(next as Route);

  return <LoginScreen next={next} />;
}
