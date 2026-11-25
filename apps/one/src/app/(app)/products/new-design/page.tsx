import type { Metadata } from "next";
import { DesignBuilder } from "~/screens/products/design-builder";

export const metadata: Metadata = { title: "Add a design" };

export default function NewDesignPage() {
  return <DesignBuilder />;
}
