import type { Metadata } from "next";
import { ImportNew } from "~/screens/settings-data/import-new";

export const metadata: Metadata = { title: "Start an import · Settings" };

export default function NewImportPage() {
  return <ImportNew />;
}
