import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { EnquiryDetail } from "@/features/sales/enquiries";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-enquiry");

export const metadata: Metadata = { title: `${route.label} · Sales` };

export default async function EnquiryPage({ params }: { params: Promise<{ enquiryId: string }> }) {
  const { enquiryId } = await params;
  if (!UUID_PATTERN.test(enquiryId)) notFound();
  return <EnquiryDetail key={enquiryId} enquiryId={enquiryId} />;
}
