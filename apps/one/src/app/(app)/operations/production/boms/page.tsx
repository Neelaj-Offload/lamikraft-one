import type { Metadata } from "next";
import { VersionList } from "~/screens/production/version-list";
import { versionSearchFrom } from "~/screens/production/views";

export const metadata: Metadata = { title: "Bills of materials · Operations" };

/** Every bill of materials version; the product search lives in the URL (`?q=`). */
export default async function BomsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const q = versionSearchFrom(await searchParams);
  return <VersionList key={q} kind="boms" q={q} />;
}
