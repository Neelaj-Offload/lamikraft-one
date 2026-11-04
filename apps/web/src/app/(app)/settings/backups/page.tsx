import type { Metadata } from "next";
import { BackupsPage } from "@/features/migration/backups-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-backups");

export const metadata: Metadata = { title: `${route.label} · Settings` };

/** Settings › Backups: the last backup and restore rehearsal (read-only; backups run from the CLI). */
export default function SettingsBackupsPage() {
  return <BackupsPage />;
}
