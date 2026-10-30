import type { Metadata } from "next";
import { RoleEditorScreen } from "../../../_lib/roles";

export const metadata: Metadata = { title: "Edit role · Settings" };

export default async function EditRolePage({ params }: { params: Promise<{ roleId: string }> }) {
  const { roleId } = await params;
  return <RoleEditorScreen roleId={roleId} />;
}
