import type { Metadata } from "next";
import { Exceptions } from "~/screens/finance/exceptions";
import { exceptionKindFrom, exceptionViewFrom } from "~/screens/finance/views";

export const metadata: Metadata = { title: "Exceptions · Finance" };

/** Finance exceptions: documents (narrowed by `?kind=`) or quotations below the margin policy (`?view=margin`). */
export default async function ExceptionsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <Exceptions view={exceptionViewFrom(params.view)} kind={exceptionKindFrom(params.kind)} />;
}
