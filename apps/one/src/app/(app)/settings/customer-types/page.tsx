import type { Metadata } from "next";
import { CustomerTypes } from "~/screens/settings-data/customer-types";

export const metadata: Metadata = { title: "Customer types · Settings" };

export default function CustomerTypesPage() {
  return <CustomerTypes />;
}
