// The editorial display face is loaded only here (motion-system §2 "Sign-in"; design spec §7.1).
import "@fontsource-variable/fraunces/opsz.css";

import type { Metadata, Route } from "next";
import { redirect } from "next/navigation";
import { safeNextPath } from "@/lib/api/client";
import { getRoute } from "@/lib/routes";
import { loadSession } from "@/lib/session/server";
import { LoginShowcase } from "./login-showcase";

const route = getRoute("login");

export const metadata: Metadata = { title: route.label };

/**
 * Sign-in: the one public showcase surface. The form is server-rendered and interactive from
 * first paint; the entrance choreography, parallax and smooth scroll are added by the client
 * component and switched off under reduced motion.
 */
export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const next = safeNextPath(typeof params.next === "string" ? params.next : null) ?? "/today";

  // Already signed in: go straight on. If the API cannot answer, the form is still shown.
  const session = await loadSession();
  if (session.status === "ok") redirect(next as Route);

  return <LoginShowcase next={next} />;
}
