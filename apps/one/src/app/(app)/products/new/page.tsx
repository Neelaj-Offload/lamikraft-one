import type { Metadata } from "next";
import { ProductNew } from "~/screens/products/product-new";

export const metadata: Metadata = { title: "Add a product · Catalogue" };

export default function NewProductPage() {
  return <ProductNew />;
}
