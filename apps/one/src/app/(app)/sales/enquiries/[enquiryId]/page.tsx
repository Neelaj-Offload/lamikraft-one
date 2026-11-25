import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { enquiryViewFrom } from "~/screens/sales/enquiries/labels";
import { EnquiryRecord } from "~/screens/sales/enquiries/record";

export const metadata: Metadata = { title: "Enquiry" };

export default async function EnquiryPage({
  params,
  searchParams,
}: {
  params: Promise<{ enquiryId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { enquiryId } = await params;
  if (!UUID_PATTERN.test(enquiryId)) notFound();
  return <EnquiryRecord key={enquiryId} enquiryId={enquiryId} view={enquiryViewFrom((await searchParams).view)} />;
}
