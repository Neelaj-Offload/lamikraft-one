import type { Metadata } from "next";
import { WhatIf } from "~/screens/production/what-if";

export const metadata: Metadata = { title: "What-if · Operations" };

/** A read-only production simulation: today against a stock or capacity change. Nothing is reserved, posted or saved. */
export default function WhatIfPage() {
  return <WhatIf />;
}
