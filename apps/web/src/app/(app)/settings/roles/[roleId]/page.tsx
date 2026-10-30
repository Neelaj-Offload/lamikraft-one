import type { Metadata } from "next";
import { RoleDetailScreen } from "../../_lib/roles";

export const metadata: Metadata = { title: "Role · Settings" };

export default async function RolePage({ params }: { params: Promise<{ roleId: string }> }) {
  const { roleId } = await params;
  return <RoleDetailScreen roleId={roleId} />;
}
