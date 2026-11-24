import type { Metadata } from "next";
import { CustomProductNew } from "~/screens/sales/custom-products/custom-product-new";

export const metadata: Metadata = { title: "New custom product · Sales" };

/** Record a custom product in three steps. */
export default function NewCustomProductPage() {
  return <CustomProductNew />;
}
