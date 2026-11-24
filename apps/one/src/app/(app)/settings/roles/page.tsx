import type { Metadata } from "next";
import { RolesList } from "~/screens/settings-access/roles-list";

export const metadata: Metadata = { title: "Roles · Settings" };

/** Every role: the built-in ones and the custom ones made from them. */
export default function RolesPage() {
  return <RolesList />;
}
