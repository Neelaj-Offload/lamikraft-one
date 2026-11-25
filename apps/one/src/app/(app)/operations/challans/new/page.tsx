import type { Metadata } from "next";
import { ChallanNew } from "~/screens/challans/challan-new";

export const metadata: Metadata = { title: "New challan · Operations" };

/** Start a draft challan. The server gives it its number; the lines go in on the record. */
export default function NewChallanPage() {
  return <ChallanNew />;
}
