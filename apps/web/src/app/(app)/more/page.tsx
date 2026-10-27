import type { Metadata } from "next";
import { MoreHub } from "@/components/shell/hubs";
import { getRoute } from "@/lib/routes";

export const metadata: Metadata = { title: getRoute("more").label };

export default function MorePage() {
  return <MoreHub />;
}
