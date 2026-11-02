# Checkpoint 2 evidence (2026-11-02)

Captures from the in-app browser against the dev stack (`npm run dev`, demo seed, Chrome, 1440 px unless named
otherwise; the pane renders at a reduced width, so some frames show the tablet layout). Dark captures use the
`lk_ui` cookie `theme=dark`. JPEGs come from the browser pane, so they are viewport crops, not full pages.

| File | What it shows |
|---|---|
| `login-1440-light.jpg` | Sign-in showcase after the entrance timeline: Fraunces headline, lede, form, the four material boards |
| `login-1440-dark.jpg` | The same in the dark theme |
| `login-390-light.jpg` | Phone layout: the stage is replaced by the material row |
| `login-story-1440-light.jpg` | The story section below the fold (Lenis smooth scroll) |
| `today-1440-light.jpg` | Today after the greeting reveal (Meera, sales scope) |
| `sales-hub-1440-light.jpg` | Sales "my work in motion": status counts, needs-you lists, areas |
| `products-list-light.jpg` | Catalogue list with the fact strip, facets, swatch thumbs, size column |
| `product-material-static-light.jpg` | Product record, Material tab, static swatch while the scene loads |
| `product-material-3d-light.jpg` | The lazy Three.js slab (450 × 300 × 12 mm oak) once in view |

Routes swept on the clean dev server with no console errors: `/login`, `/today`, `/sales`, `/sales/parties`,
`/sales/parties/[id]`, `/sales/parties/new`, `/products`, `/products/[id]` (five tabs), `/products/completeness`,
`/products/taxonomy`, `/products/price-lists`, `/products/price-lists/[id]`, `/settings`, `/settings/profile`,
`/settings/company`, `/settings/reference`, `/settings/integrations`, `/settings/audit` (PermissionDenied for
management, as designed), `/operations`, `/finance`.
