import type { Metadata } from "next";
import { safeNextPath } from "@/lib/api/client";
import { TwoStepForm } from "./two-step-form";

export const metadata: Metadata = { title: "Two-step sign-in" };

/** Second sign-in step: enter the authenticator code, or set one up first when the role requires it. */
export default async function TwoStepPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const next = safeNextPath(typeof params.next === "string" ? params.next : null) ?? "/today";
  return <TwoStepForm next={next} />;
}
