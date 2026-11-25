import type { Metadata } from "next";
import { UUID_PATTERN } from "@/lib/app-links";
import { AccessCheck } from "~/screens/settings-access/access-check";

export const metadata: Metadata = { title: "Check access · Settings" };

const one = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value) ?? null;

/** The person (`?user=`) or role (`?role=`) being explained lives in the URL. */
export default async function SimulatePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const user = one(params.user);
  const role = one(params.role);
  const userId = user && UUID_PATTERN.test(user) ? user : null;
  const roleId = role && UUID_PATTERN.test(role) ? role : null;
  return <AccessCheck key={`${userId}|${roleId}`} userId={userId} roleId={roleId} />;
}
