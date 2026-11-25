import type { Metadata } from "next";
import { ActivityScreen } from "~/screens/activity/activity-screen";

export const metadata: Metadata = { title: "Activity" };

/** Recent activity across the records the person can open (never anything they cannot). */
export default function ActivityPage() {
  return <ActivityScreen />;
}
