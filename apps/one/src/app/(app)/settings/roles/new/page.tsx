import type { Metadata } from "next";
import { RoleEditor } from "~/screens/settings-access/role-editor";

export const metadata: Metadata = { title: "Create role · Settings" };

/** A custom role: what it builds on, then its own grants and denies. */
export default function NewRolePage() {
  return <RoleEditor roleId={null} />;
}
