import type { Metadata } from "next";
import { SignOutPanel } from "@/features/auth/sign-out-panel";
import { getRoute } from "@/lib/routes";

const route = getRoute("sign-out");

export const metadata: Metadata = { title: route.label };

export default function SignOutPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-center text-3xl font-bold tracking-tight">{route.label}</h1>
      <SignOutPanel />
    </div>
  );
}
