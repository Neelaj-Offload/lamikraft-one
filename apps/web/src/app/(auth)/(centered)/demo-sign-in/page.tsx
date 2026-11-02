import type { Metadata } from "next";
import { DemoSignIn } from "@/features/auth/demo-sign-in";
import { getRoute } from "@/lib/routes";

const route = getRoute("demo-sign-in");

export const metadata: Metadata = {
  title: route.label,
  // The token lives in the URL fragment until this page strips it; never leak the URL onwards.
  referrer: "no-referrer",
};

export default function DemoSignInPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-center text-3xl font-bold tracking-tight">{route.label}</h1>
      <DemoSignIn />
    </div>
  );
}
