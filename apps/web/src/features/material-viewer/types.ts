/**
 * What the material viewer needs to know about a product. The products feature maps its
 * `ProductDetail` to this shape; the viewer never reads the catalogue API itself.
 * Measures are DecimalStr millimetres as the API sends them (never parsed to floats outside
 * the viewer's own geometry scaling).
 */
export interface MaterialSubject {
  product_key: string;
  product_name: string;
  decor_no: string | null;
  decor_name: string | null;
  material_type: string | null;
  finish: string | null;
  /** Canonical millimetres from the specification, or the master size when absent. */
  length_mm: string | null;
  width_mm: string | null;
  thickness_mm: string | null;
}
