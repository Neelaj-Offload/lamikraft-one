import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { roleViewFrom } from "~/screens/settings-access/labels";
import { RoleRecord } from "~/screens/settings-access/role-record";

export const metadata: Metadata = { title: "Role · Settings" };

/** One role: how it is built and everything it allows (`?view=`). */
export default async function RolePage({
  params,
  searchParams,
}: {
  params: Promise<{ roleId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { roleId } = await params;
  if (!UUID_PATTERN.test(roleId)) notFound();
  const view = roleViewFrom((await searchParams).view);
  return <RoleRecord key={roleId} roleId={roleId} view={view} />;
}
