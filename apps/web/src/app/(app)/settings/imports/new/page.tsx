import type { Metadata } from "next";
import { NewImport } from "@/features/imports/workbench";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-import-new");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function NewImportPage() {
  return <NewImport />;
}
