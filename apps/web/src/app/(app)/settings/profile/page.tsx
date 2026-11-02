import type { Metadata } from "next";
import { ProfileView } from "@/features/settings/profile-view";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-profile");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function SettingsProfilePage() {
  return <ProfileView />;
}
