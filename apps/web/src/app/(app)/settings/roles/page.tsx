import type { Metadata } from "next";
import { RoleListScreen } from "../_lib/roles";

export const metadata: Metadata = { title: "Roles · Settings" };

export default function RolesPage() {
  return <RoleListScreen />;
}
