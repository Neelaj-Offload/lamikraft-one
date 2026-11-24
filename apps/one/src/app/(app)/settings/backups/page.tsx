import type { Metadata } from "next";
import { Backups } from "~/screens/settings-data/backups";

export const metadata: Metadata = { title: "Backups · Settings" };

/** The last backup and restore rehearsal. Read only: both run from the server's command line. */
export default function BackupsPage() {
  return <Backups />;
}
