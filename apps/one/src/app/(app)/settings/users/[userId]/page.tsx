import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { userViewFrom } from "~/screens/settings-access/labels";
import { UserRecord } from "~/screens/settings-access/user-record";

export const metadata: Metadata = { title: "Person · Settings" };

/** One person: overview, roles and permissions, sign-in (`?view=`). */
export default async function UserPage({
  params,
  searchParams,
}: {
  params: Promise<{ userId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { userId } = await params;
  if (!UUID_PATTERN.test(userId)) notFound();
  const view = userViewFrom((await searchParams).view);
  return <UserRecord key={userId} userId={userId} view={view} />;
}
