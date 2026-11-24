import type { Metadata } from "next";
import { WorkScreen } from "~/screens/hubs/work";

export const metadata: Metadata = { title: "Work" };

export default function WorkPage() {
  return <WorkScreen />;
}
