import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { RoleEditor } from "~/screens/settings-access/role-editor";

export const metadata: Metadata = { title: "Edit role · Settings" };

/** Change a custom role's name, what it builds on, and its own grants and denies. */
export default async function EditRolePage({ params }: { params: Promise<{ roleId: string }> }) {
  const { roleId } = await params;
  if (!UUID_PATTERN.test(roleId)) notFound();
  return <RoleEditor key={roleId} roleId={roleId} />;
}
