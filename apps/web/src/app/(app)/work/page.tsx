import type { Metadata } from "next";
import { WorkHub } from "@/components/shell/hubs";
import { getRoute } from "@/lib/routes";

export const metadata: Metadata = { title: getRoute("work").label };

export default function WorkPage() {
  return <WorkHub />;
}
