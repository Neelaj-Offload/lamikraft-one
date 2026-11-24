import type { Metadata } from "next";
import { SettingsHub } from "~/screens/settings-hub/settings-hub";

export const metadata: Metadata = { title: "Settings" };

/** Every settings screen this person may open, grouped under plain headings. */
export default function SettingsPage() {
  return <SettingsHub />;
}
