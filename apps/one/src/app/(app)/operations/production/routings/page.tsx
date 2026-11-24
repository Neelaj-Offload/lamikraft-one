import type { Metadata } from "next";
import { VersionList } from "~/screens/production/version-list";
import { versionSearchFrom } from "~/screens/production/views";

export const metadata: Metadata = { title: "Routings · Operations" };

/** Every routing version; the product search lives in the URL (`?q=`). */
export default async function RoutingsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const q = versionSearchFrom(await searchParams);
  return <VersionList key={q} kind="routings" q={q} />;
}
