import type { Metadata } from "next";
import { MoreScreen } from "~/screens/hubs/more";

export const metadata: Metadata = { title: "More" };

export default function MorePage() {
  return <MoreScreen />;
}
