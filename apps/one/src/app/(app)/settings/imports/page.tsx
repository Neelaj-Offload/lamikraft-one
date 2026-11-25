import type { Metadata } from "next";
import { Imports } from "~/screens/settings-data/imports";
import { importsStateFrom } from "~/screens/settings-data/imports-shared";

export const metadata: Metadata = { title: "Imports · Settings" };

/** Import history: the type filter and the page offset live in the URL. */
export default async function ImportsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { importType, offset } = importsStateFrom(await searchParams);
  return <Imports key={`${importType}|${offset}`} importType={importType} offset={offset} />;
}
