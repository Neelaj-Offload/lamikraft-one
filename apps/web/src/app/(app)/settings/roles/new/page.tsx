import type { Metadata } from "next";
import { RoleEditorScreen } from "../../_lib/roles";

export const metadata: Metadata = { title: "New role · Settings" };

export default function NewRolePage() {
  return <RoleEditorScreen roleId={null} />;
}
