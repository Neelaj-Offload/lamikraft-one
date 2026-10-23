import type { Metadata } from "next";
import { getRoute } from "@/lib/routes";

const route = getRoute("login");

export const metadata: Metadata = { title: route.label };

export default function LoginPage() {
  return <h1 className="text-center text-3xl font-bold tracking-tight">{route.label}</h1>;
}
