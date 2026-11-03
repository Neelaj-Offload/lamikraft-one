import type { Metadata } from "next";
import { ChallanCreate } from "@/features/challans/challan-create";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-challan-new");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** A new draft challan: header fields, an optional first line; numbering happens on the server. */
export default function NewChallanPage() {
  return <ChallanCreate />;
}
