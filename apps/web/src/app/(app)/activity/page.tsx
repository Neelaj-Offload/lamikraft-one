import type { Metadata } from "next";
import { ActivityFeed } from "@/features/collab/activity";

export const metadata: Metadata = { title: "Activity" };

/** Recent activity across the records you can open (never anything you cannot). */
export default function ActivityPage() {
  return <ActivityFeed />;
}
