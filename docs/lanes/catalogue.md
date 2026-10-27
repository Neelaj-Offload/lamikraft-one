# Lane report: catalogue (Slice 1, wave 1)

Branch `lane/s1w1-catalogue`, worktree `D:\lk-wt\catalogue`, env slot 3. Scope: catalogue, parties, pricing and
the commercial engine. Status: **implemented and green**. The only failing gate step is the expected `api:check`
(the routes changed, so `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts` need regenerating at merge).

## 1. Implemented items

### Catalogue (`backend/app/modules/catalogue/`)
- `models.py` holds the taxonomy, product and child tables.
  - Taxonomy: `catalogue_category` and `catalogue_subcategory`. Each has an active flag (default true, fixing legacy
    bug 7), a display order, catalogue-page provenance and a `name_key` unique per company.
  - `catalogue_product`:
    - Identity: an immutable `product_key` (unique per company, format CHECK and a DB trigger
      `trg_catalogue_product_key_immutable`) and a non-unique `display_sku`.
    - Master fields: `product_name`, brand, status, `category_id` FK, composite `(subcategory_id, category_id)` FK
      (a subcategory must belong to its category), `variant_group`, `product_type`, `unit_of_sale`, finish, shape,
      description and `internal_remarks`.
    - Decor: `decor_no` as text (leading zeros kept) with `decor_no_source`, plus `decor_name`, `decor_primary`,
      `decor_options` and `decor_options_text`.
    - Provenance: every legacy `source_*` field, `source_extra`, `origin` and `origin_ref`.
    - Search and size: a maintained `search_text`, and the effective size `size_*_mm` with its `size_basis`.
    - Stock attributes, all nullable: `hsn_sac`, `stock_uom_code`, `is_stock_tracked`, `track_lots`, `qc_required`.
  - `catalogue_product_specification` (1:1) carries every legacy specification field:
    - length, width, height and thickness in canonical mm (NUMERIC(12,3) and (8,3)), each with a `*_source` original;
    - material, finish, type, top sheet, stand material, grooves, bowls, bowl type, handles, boards, special
      features, care and usage.
  - `catalogue_product_packaging` (1:1) holds:
    - `carton_qty`, `inner_qty` and `unit_weight_g`;
    - `packing_type`, carton dimensions in cm, `cbm`, and net and gross kg;
    - packaging, fragile and status notes, plus `alias_provenance` recording which legacy alias supplied each value.
  - `catalogue_product_dimension` keeps every size string verbatim with its parsed mm values: master, spec, board,
    working, stand and plate 1–3 sizes.
  - `catalogue_lookup_reference` stores the legacy lookup rows.
- `normalise.py` is pure:
  - Identifiers: `0120` stays `0120`; `120.0` becomes `120` with the warning `DECOR_FLOAT_ARTEFACT_NORMALISED`;
    `0120` and `120` stay distinct.
  - Thickness: `0.8` and `0.80` are the same value.
  - Dimensions are parsed (`450 x 300`, `30 x 20 cm`, `12" x 8"`, `2440*1220*18`, Ø, thousands separators and
    decimal commas). Ranges stay unparsed, and a single value is flagged ambiguous.
  - Packaging alias pairs: a disagreement is an `alias_conflict` and the system never guesses. Cross-checks for CBM,
    gross below net, and inner above carton raise warnings only.
- `service.py`:
  - Commands used by seeds, imports and tests (the HTTP forms are Slice 2):
    - `create_category` and `create_subcategory`;
    - `create_product` and `update_product`. Updates are versioned and move the version by exactly one. They emit
      `changed_groups` and `changed_fields`.
  - `list_products`:
    - Every filter is applied in SQL before LIMIT/OFFSET, and one WHERE clause feeds `total`.
    - Filters: `q` (tokenised, escaped ILIKE over key, SKU, name, decor, finish, family and taxonomy), category,
      subcategory, family, size (either orientation), thickness, decor, finish, status, brand, completeness `issue`
      and `include_archived`.
    - A thickness filter needs a specification row (legacy bug 6).
  - Other reads:
    - `product_facets` uses exclude-self counts.
    - `product_stats` returns counts by status, archived, updated in the last 7 days, per category, and recently
      changed rows with the actor.
    - `completeness_summary` and the per-product `completeness` compute one SQL rule per check over the actual
      columns; the primary-image rule is listed as `not_evaluated` until media arrive.
    - `get_product` and `get_product_by_key` return the detail with every field group and deep-linkable `sections`.
      The pricing section appears only with `pricing.price.read`. The detail carries `capabilities.update`
      (computed by `ScopedRepository.capabilities` from the product policy, `catalogue.product.update`) and an empty
      `allowed_transitions` (status is a master field changed through update).
    - `list_categories`.
  - `resolve_product` returns unique, ambiguous or not_found. It is a service only; see question 8.
  - `product_refs` and `get_product_ref` are the read API for other modules.
  - `read_product_facts` is the source reader `catalogue.product`.
- `search.py` holds `PRODUCT_SEARCH` (the SearchProvider). `router.py` holds the read API. `policies.py` registers the
  `catalogue.product`, `catalogue.category` and `catalogue.subcategory` policies; subcategories are reached only
  through their category.

### Parties (`backend/app/modules/parties/`)
- `models.py`:
  - `parties_party`:
    - Identity: `party_number` P-NNNNN (format CHECK), legal and display names, `country_code`, `default_currency`
      (enabled set) and `customer_type`.
    - Classification: status, and roles drawn from customer, vendor, fabricator and job_worker (array CHECK).
    - Ownership: `owner_user_id`, `branch_id`, a version, archive columns and `search_text`.
  - Contacts allow one live primary per party (partial unique index).
  - Addresses are billing or shipping, with one live default per kind.
  - Tax identifiers are optional. The value is unique among live rows, GSTIN and PAN have format CHECKs, and
    `verification_status` is always `unverified` (CHECK).
- `service.py`:
  - `create_party`: the number comes from `uow.allocate_number("parties.party")` using the never-reset SequenceDef
    `P-{seq:05}`. A sales user cannot assign another owner (`parties.party.assign`). The owner must be an active
    member.
  - `update_party`: dirty fields plus `expected_version` (409 when stale). Child lists use replace semantics, and rows
    left out are archived. Address changes are reported as `addresses.<kind>`, for example `addresses.shipping`.
  - `create_party_command` and `update_party_command` add optional `Idempotency-Key` replay.
  - `get_party`, `get_party_by_number` and `list_parties`: filters are applied before pagination.
  - `resolve_party` returns unique, ambiguous or not_found; it never picks among several matches.
  - `get_party_ref`, `party_labels` and `visible_party_ids` are the read API for other modules.
  - `read_party_facts` is the source reader `parties.party`.
- `policies.py`: the `parties.party` policy covers own, team, branch and company scope over `owner_user_id` and
  `branch_id`. Contacts, addresses and tax identifiers are children of their party.
- `search.py` holds `PARTY_SEARCH`, `tools.py` holds the `resolve_party` ToolDef, and `router.py` holds the API.
- The detail response carries `capabilities.update` and `allowed_transitions` (empty in Slice 1).

### Pricing (`backend/app/modules/pricing/`)
- `models.py`:
  - `pricing_price_list` columns:
    - `code`;
    - `price_type`: domestic, export, sample or distributor;
    - `scope_kind`: standard, customer_type or customer, with a CHECK that ties the target column to the scope;
    - `party_id` or `customer_type`;
    - `currency`, `default_unit_code` and `price_basis`;
    - validity, status (draft, active or retired) and an explicit `priority`;
    - provenance, plus activation and retirement stamps.
    It also has a UNIQUE `(id, currency)` that the Slice-2 quote-line FX constraint can target.
  - `pricing_price_list_item` columns:
    - product, `unit_code` and `unit_price` NUMERIC(18,4);
    - `final_price`, plus base and add-on prices with their labels;
    - `price_basis`, yield, `thickness_mm`, `moq` and `moq_unit_code`;
    - notes, effective dates, status and `superseded_by_item_id`;
    - provenance, including `source_sheet` and `source_row`.

    An exclusion constraint `ex_pricing_price_list_item_no_overlap` (btree_gist) prevents two active prices
    overlapping for the same (list, product, unit).
  - `pricing_price_list_item_history` is append-only (trigger plus revoked UPDATE/DELETE).
  - `pricing_product_cost` is append-only and versioned. It is restricted behind `pricing.cost.read`.
- `schemas.py`:
  - The guard `pricing.price_list.read` (model exposure allowed) covers the breakdown and provenance fields.
  - The guard `pricing.cost.read` (model exposure denied) covers cost.
  - The cost field names are registered with the log redactor in the manifest's `on_load`.
- `service.py`:
  - Commands used by seeds and tests (the price-list CRUD API is Slice 2): `create_price_list`, `add_item` (draft
    lists only), `activate_price_list` and `supersede_item`.
    - Activation rejects overlaps with 409 `price_list_overlap` unless both lists carry different explicit priorities.
    - Supersede is effective-dated and writes history and an event.
    - `record_product_cost` needs `pricing.cost.update`.
  - Reads: `list_price_lists`, `get_price_list`, `list_price_list_items`, `product_prices` and `list_product_costs`.
    - A customer list is visible only when its party is visible to the actor.
    - The price-list detail carries `capabilities` `add_item` (draft lists only, else `price_list_not_draft`) and
      `supersede_item`, both needing `pricing.price_list.manage` (else `permission_denied`), and
      `allowed_transitions` `activate` (draft -> active) for managers. They mirror the service guards.
    - `product_prices` returns cost only to cost readers; otherwise `current_cost` is listed in `redacted_fields`.
  - `resolve_price(uow, currency=, uom=, product_id=|product_key=, party_id=, on_date=, price_type=)`:
    - Tier order is customer agreement, then customer-type list, then standard list, and within a tier currency,
      unit and effective date.
    - An overlap without a unique explicit priority returns AMBIGUOUS with candidates and never falls through.
    - A zero price returns UNAVAILABLE and does not fall through.
    - A found price carries provenance: tier, list id and code, item id, validity and MOQ.
    - A price is returned only in its list currency. A missing currency gives `NO_PRICE_IN_CURRENCY` with hints and
      no relabel.
    - Units are never converted (`NO_PRICE_FOR_UNIT`).
- `tools.py` holds the `resolve_price` ToolDef, and `router.py` holds the read API.

### Commercial (`backend/app/modules/commercial/`)
- `models.py`: `commercial_rule_set` is versioned per `code`, has one active version per code (partial unique index),
  and stores `params` JSONB validated by `QuoteCommercialRulesV1`.
- `engine.py` is pure Decimal with no I/O:
  - Line gross, discount and net are rounded HALF_UP to the currency minor unit.
  - The order-value recommendation is `ceil(minimum / positive price)` rounded up to a carton multiple: EUR 24 with a
    carton of 24 gives 216. It is labelled "not a product MOQ".
  - A missing or zero price makes the recommendation UNAVAILABLE with an explanation. No division happens.
  - A currency without a configured threshold gets NOT_EVALUATED; there is no FX-equivalent threshold.
  - The applicable subtotal is the net of the applicable line types after line discounts, excluding tax and surcharge.
  - The surcharge applies only when a threshold exists (v1: EUR only), every line is priced, the toggle is on and
    0 < applicable < minimum. Exactly 5,000.00 gets none.
  - Tax is null ("Excludes taxes"). The grand total is null while any line is unpriced.
  - Floats raise `TypeError`.
  - The result is a frozen `CalculationResult` holding the inputs, rule set id and version, per-line results,
    subtotals, adjustments, surcharge, tax, grand total, reason codes, warnings and the input hash. `as_dict()` is
    there for the sales module to persist.
- `service.py`:
  - `create_rule_set` and `activate_rule_set`: activation retires the previous version and emits an event.
  - `active_rules` raises 409 `not_configured` when no rule set is active.
  - `get_rule_set` returns `RuleSetDetail` with `capabilities.activate` (`commercial.rule_set.manage`, draft only,
    else `rule_set_not_draft`) and the `activate` transition for managers.
  - `calculate` runs the engine with the active rules.
  - `calculate_resolved_lines`: prices come from price-list item ids, never from the model. An item in another
    currency is a 422 `currency_mismatch`, so prices are never relabelled.
- `tools.py` holds the `calculate_quote` ToolDef.

### Migration and seeds
- `backend/migrations/versions/0005_catalogue_slice1.py` (revision `0005`, down_revision `0002`) contains all 16 lane
  tables:
  - forced fail-closed RLS (`helpers.enable_tenant_rls`);
  - append-only triggers (`helpers.append_only`);
  - 21 enum CHECKs (`helpers.enum_check`);
  - 6 UOM CHECKs `ck_<table>_<column>_uom`;
  - the exclusion constraint and the product_key trigger.

  Downgrade is implemented. Upgrade → downgrade → upgrade was run on `lk_wt3`; `alembic check` reports no drift and
  heads = 1.
- `backend/app/seed/world/parties.py` (SeedDef `parties.world`, order 20):
  - Creates the four Slice-1 customers through the service as Priya at D-120 .. D-117, giving numbers P-00001 ..
    P-00004 from the allocator. Meera owns three and Neha owns Thornbury.
  - Adds contacts (Lena Brandt, Camille Laurent, Erik Lindqvist, Oliver Hart) and fictional billing and shipping
    addresses. Tax identifiers are left empty.
  - Changes Maison's shipping address as Priya at D-1 10:05 IST (04:35Z), emitting `parties.party.updated` with
    `["addresses.shipping"]`.
- `backend/app/seed/world/catalogue.py` (order 30) creates the taxonomy, Serveware (Trays, Trivets, Boards) and
  Decorative Boards (Veneered panels), and the four products with specification and packaging per fixtures §5.
- `backend/app/seed/world/pricing.py` (order 40) creates and activates EXP-EUR-2026, EXP-GBP-2026 and DOM-INR-2026 with
  the §6 items. `backend/app/seed/world/commercial.py` (order 40) creates `quote_commercial` v1 (EUR 5000.00 /
  400.00; catalog, custom and manual) and activates it.
- All seeds:
  - run through services, acting as `keys.USERS.PRIYA` through `actor_for_member`, at their fixture clock times;
  - are idempotent on business keys (tested: a second run creates no rows, events or new refs);
  - record refs: parties, products, categories `CAT_*` and `SUB_*`, price lists `PL_*`, items `PLI_*` and
    `RULE_SET_QUOTE_COMMERCIAL`.

## 2. Tests

140 tests in the lane, all passing. The full backend suite (`npm run test:api`) passes with 232 tests.

| File | Tests | Covers |
|---|---|---|
| `backend/tests/unit/catalogue/test_normalise.py` | 36 | decor 0120/120/120.0 cases, hypothesis property that text identifiers never lose digits, 0.8 = 0.80, dimension parsing, alias pairs/conflicts, cross-checks |
| `backend/tests/unit/commercial/test_engine.py` | 17 | every scenario D case (216; 4,800 off/on; 5,000; 4,999.99; 20 % discount; zero/missing price; USD), HALF_UP, floats rejected, frozen result; hypothesis properties (minimal carton-multiple recommendation; grand = net + surcharge + tax; surcharge iff EUR ∧ toggle ∧ 0 < applicable < 5000; determinism) |
| `backend/tests/unit/pricing/test_cost_guard.py` | 5 | cost fields restricted, nulled without the key, denied to model context even when permitted, breakdown guard, log scrubbing |
| `backend/tests/unit/parties/test_party_schemas.py` | 10 | input validation, tool input has no identity fields |
| `backend/tests/integration/catalogue/test_seed_world.py` | 5 | numbers follow creation order, counts and taxonomy, idempotent seeds, Maison change event at 04:35Z, oak tray fields |
| `backend/tests/integration/catalogue/test_product_list.py` | 14 | thickness filter before paging (12 of 32, pages 5+5+2, same total; products without specs excluded), 0.8 = 0.80, product_name search, literal search input (`%`, `_`, `.*`, `(a+)+$`), decor normalisation and filters, taxonomy/family/size/finish/status filters, facets, stats |
| `backend/tests/integration/catalogue/test_product_fields_round_trip.py` | 3 | every legacy master, decor, provenance and stock field; every specification field with mm canonical + `*_source` and all seven dimension rows (cm, inch, `*`, Ø, range left unparsed); every packaging field with the four legacy alias pairs reconciled and recorded in `alias_provenance` |
| `backend/tests/integration/catalogue/test_product_detail.py` | 8 | field groups and sections, capabilities from the product policy, completeness from actual fields, versioned update with alias provenance and event groups, write guards, product_key DB trigger, isolation (404 cross-company, 403 without read), source reader, search provider, resolve_product |
| `backend/tests/integration/catalogue/test_lane_api.py` | 4 | operationIds and `x-authz`, catalogue routes, party scope 404/403, Idempotency-Key replay and `idempotency_key_reused`, 409 version conflict, pricing and commercial routes, DecimalStr strings |
| `backend/tests/integration/parties/test_parties.py` | 9 | Meera vs Neha own scope (404 on each other's party), company scope, visible-but-forbidden 403, filters before paging, P-00005, events with changed fields, resolve_party (unique, ambiguous with "Nordhaus Logistik AG", not_found by scope), search and source reader scope |
| `backend/tests/integration/pricing/test_price_resolution.py` | 11 | tiers, ambiguity without fall-through, explicit priority, legacy multiple-EUR-rows by price type, activation overlap 409, no currency relabel and no unit conversion, effective dates and supersede history, zero price, party scope, tool |
| `backend/tests/integration/pricing/test_price_lists.py` | 6 | read APIs, capabilities and the activate transition by permission and state, breakdown guard, cost restricted (403, `redacted_fields`, model context), append-only history and cost, exclusion constraint |
| `backend/tests/integration/commercial/test_commercial.py` | 8 | rule set v1 and its event, new version retires the old one (with `activate` capability before and after), scenario C and D through `calculate_quote`, GBP not evaluated, relabel rejected, missing rule set |
| `backend/tests/contract/catalogue/test_lane_schema.py` | 4 | DB enum CHECKs equal the StrEnums, UOM CHECKs, RLS/append-only/exclusion/trigger present, event payload fields equal the frozen catalogue, tools/providers/readers/sequence/seeds/policies registered |

Gate (`npm run check -- --keep-going`):

| Step | Result |
|---|---|
| ruff | PASS |
| pytest unit + contract | PASS (144) |
| alembic heads == 1 | PASS |
| web lint, typecheck and vitest | PASS (vitest 134) |
| api:check | FAIL — expected; the routes changed |

## 3. API endpoints added

| Method and path | operationId | Permission |
|---|---|---|
| GET `/api/v1/catalogue/products?price_currency=&price_type=` | `catalogue_list_products` | catalogue.product.read (`prices` column guarded by pricing.price.read) |
| GET `/api/v1/catalogue/products/facets` | `catalogue_get_product_facets` | catalogue.product.read |
| GET `/api/v1/catalogue/products/stats` | `catalogue_get_product_stats` | catalogue.product.read |
| GET `/api/v1/catalogue/products/completeness` | `catalogue_get_product_completeness` | catalogue.product.read |
| GET `/api/v1/catalogue/products/lookup?key=` | `catalogue_get_product_by_key` | catalogue.product.read |
| GET `/api/v1/catalogue/products/{product_id}` | `catalogue_get_product` | catalogue.product.read (overview `prices` guarded by pricing.price.read; `pricing` section needs pricing.price_list.read) |
| GET `/api/v1/catalogue/categories` | `catalogue_list_categories` | catalogue.product.read |
| GET `/api/v1/parties/parties` | `parties_list_parties` | parties.party.read |
| POST `/api/v1/parties/parties` | `parties_create_party` | parties.party.create (optional Idempotency-Key) |
| GET `/api/v1/parties/parties/lookup?party_number=` | `parties_get_party_by_number` | parties.party.read |
| GET `/api/v1/parties/parties/{party_id}` | `parties_get_party` | parties.party.read |
| PATCH `/api/v1/parties/parties/{party_id}` | `parties_update_party` | parties.party.update (optional Idempotency-Key) |
| GET `/api/v1/pricing/price-lists` | `pricing_list_price_lists` | pricing.price.read |
| GET `/api/v1/pricing/price-lists/{price_list_id}` | `pricing_get_price_list` | pricing.price.read |
| GET `/api/v1/pricing/price-lists/{price_list_id}/items` | `pricing_list_price_list_items` | pricing.price.read (breakdown guarded by pricing.price_list.read) |
| GET `/api/v1/pricing/products/{product_id}/prices` | `pricing_list_product_prices` | pricing.price.read (cost guarded by pricing.cost.read) |
| GET `/api/v1/pricing/products/{product_id}/costs` | `pricing_list_product_costs` | pricing.cost.read (Page; every read returning rows is audited) |
| GET `/api/v1/pricing/prices/resolve` | `pricing_resolve_price` | pricing.price.read |
| GET `/api/v1/commercial/rule-sets` | `commercial_list_rule_sets` | commercial.rule_set.read (Page) |
| GET `/api/v1/commercial/rule-sets/{rule_set_id}` | `commercial_get_rule_set` | commercial.rule_set.read (returns `RuleSetDetail`) |

## 4. Events, permissions, contributions

- **Events emitted** (all from the frozen catalogue; payloads carry ids, keys and field names only):
  - `catalogue.product.created` and `catalogue.product.updated`;
  - `catalogue.category.created` and `catalogue.subcategory.created`;
  - `parties.party.created` and `parties.party.updated`;
  - `pricing.price_list.created`, `pricing.price_list.activated`, `pricing.price_list_item.superseded` and
    `pricing.product_cost.recorded`;
  - `commercial.rule_set.activated`.
- **Events consumed:** none.
- **Permissions used** (all from the frozen catalogue):
  - catalogue: `catalogue.product.read`, `.create`, `.update`, `catalogue.taxonomy.manage`;
  - parties: `parties.party.read`, `.create`, `.update`, `.assign`;
  - pricing: `pricing.price.read`, `pricing.price_list.read` (field guard), `pricing.price_list.manage`,
    `pricing.cost.read` (field guard), `pricing.cost.update`;
  - commercial: `commercial.rule_set.read`, `commercial.rule_set.manage`.
- **Sequence:** `parties.party` `P-{seq:05}`, never reset.
- **Seeds:** `parties.world` (20), `catalogue.world` (30), `pricing.world` (40), `commercial.world` (40),
  `parties.world.changes` (55, Maison's D-1 shipping change).
- **Agent tools:** `resolve_party`, `resolve_price`, `calculate_quote` (all `effect="read"`).
- **Search providers:** `catalogue.product`, `parties.party`.
- **Source readers:** `catalogue.product`, `parties.party`.
- **Not added:** settings and jobs.
- **Shared files:** none edited (`registry.py`, `keys.py`, `conftest.py`, `helpers.py`, `core/**`, lockfiles and
  generated API files are untouched).

## 5. Dependencies requested

None.

## 6. Contract questions

1. **UOM foreign keys.** `org.uom` does not exist in this worktree. Unit codes are validated strings with a CHECK
   `ck_<table>_<column>_uom` on the documented list for six columns:
   - `catalogue_product.unit_of_sale` and `catalogue_product.stock_uom_code`;
   - `pricing_price_list.default_unit_code`;
   - `pricing_price_list_item.unit_code` and `pricing_price_list_item.moq_unit_code`;
   - `pricing_product_cost.unit_code`.

   At merge, the integrator should replace each CHECK with an FK to `uom.code`.
2. **Immutability trigger helper.** `migrations/helpers.py` has no immutability helper. The `product_key` guard
   (`lk_catalogue_product_key_immutable` plus `trg_catalogue_product_key_immutable`) is raw SQL in 0005. Please add a
   helper, for example `immutable_columns(table, *cols)`, and move it there. A `tenant_table` helper is also named in
   the docs but missing; `enable_tenant_rls` was used.
3. **`keys.py` additions requested:**
   - product names (`Oak serving tray 450`, ...) and the taxonomy names;
   - customer contacts;
   - the ref names the seeds publish:
     - categories `CAT_SERVEWARE`, `CAT_DECORATIVE_BOARDS`;
     - subcategories `SUB_TRAYS`, `SUB_TRIVETS`, `SUB_BOARDS`, `SUB_VENEERED_PANELS`;
     - price lists `PL_EXP_EUR`, `PL_EXP_GBP`, `PL_DOM_INR`;
     - items `PLI_EXP_EUR_OAK_TRAY`, ...;
     - `RULE_SET_QUOTE_COMMERCIAL`.

   Tests use these through the seed modules for now.
4. **Seed runtime.** Seeds act as Priya through `actor_for_member`, which needs the identity builder and the identity
   seed's refs under `keys.USERS.*`. They use `app.seed.context.D0` for offsets; `SeedContext` has no anchor, so an
   `--anchor-date` shift needs an `anchor` field on it. The `lk seed demo` runner is not in this worktree.
5. **Seed event origin.** Persona actions record origin `user`. Products created by the seed carry provenance
   `origin=seed`, and so does their `catalogue.product.created` event. Please confirm.
6. **Slice-2 events emitted early.** `catalogue.category.created` and `catalogue.subcategory.created` are marked
   Slice 2 in events.md but are emitted now, when the seed creates taxonomy rows. The same holds for
   `pricing.price_list.created` (every `create_price_list`, seed included) and `pricing.product_cost.recorded`
   (`record_product_cost`). Please confirm early emission or ask the lane to hold them until Slice 2.
7. **Party roles.** Roles are limited to customer, vendor, fabricator and job_worker, as briefed. Challan destinations
   include Transporter, so Slice 2 may want a `transporter` role.
8. **`resolve_product`.** It is a catalogue service. No ToolDef is registered, to avoid a duplicate tool name if the
   sales lane registers one. The integrator decides who owns the tool.
9. **Price-list scope value.** It is named `customer` (the brief's term); the design source used
   `customer_agreement`.
10. **Shared capability schema.** `app/core/http` has no `Capability` / `TransitionRead` type, so parties,
    catalogue, pricing and commercial each declare identical models (approvals already does the same). Pydantic
    emits one `Capability` and one `TransitionRead` OpenAPI component because the schemas are equal, but a single
    core type would stop them drifting. Please add one to core and the lanes will switch to it.
11. **PARITY_MATRIX test names.** The matrix names planned test files that this lane covers under other names:
    - FG-PRD-*, FG-SPC-*, FG-PKG-05/08/09: `tests/integration/catalogue/test_product_fields_round_trip.py`;
    - FG-PKG-01..04, 06, 07 and FG-PRD-09: `tests/unit/catalogue/test_normalise.py`;
    - LM-10, FG-SPC-02: `tests/integration/catalogue/test_product_list.py`;
    - LM-13, FG-PRD-01: `tests/integration/catalogue/test_product_detail.py`;
    - FG-PRC-*: `tests/integration/pricing/test_price_lists.py` and `test_price_resolution.py`;
    - LM-61, FG-PRC-10: `tests/unit/commercial/test_engine.py`.

    The matrix rows can point at these when they move to `done`.

## 7. Known gaps (with reasons)

- **Slice 2 or out of this lane's scope:**
  - **Write APIs and taxonomy management.** Catalogue writes have no HTTP routes; services exist and seeds use them.
    The forms are Slice 2. Taxonomy rename, delete and reassign are also Slice 2.
  - **Price-list CRUD API.** There are no HTTP routes yet; the services exist (create, add item, activate,
    supersede). FX snapshots and Pass B conversion are Slice 2. The schema keeps a list `UNIQUE(id, currency)` and
    item provenance for them.
  - **Media.** Product media and primary images are Slice 2. The completeness rule `no_primary_image` is reported as
    `not_evaluated`. The fixture photos and swatches are not seeded.
  - **Lookup reference.** `lookup_reference` has a table only. The browser, export and import are Slice 2
    (`catalogue.lookup.read` is a Slice-2 key).
- **Owned by other lanes:**
  - **Price enrichment in catalogue reads.** Done in the fix pass: list rows and the overview carry `prices`
    (pricing.display_prices plus the engine recommendation) through a contribution the commercial manifest registers
    (`catalogue.register_price_columns`), so the catalogue still never imports pricing. Stats still lack "without
    pricing" (Slice 2 dashboard).
  - **Identity in tests.** Tests register a stand-in member-actor builder (template grants from the frozen catalogue)
    and override the session dependency for HTTP tests, because identity and the test-support sign-in are another
    lane.
- **Accepted for now:**
  - **Active-list price immutability.** Enforced in the service and, since the fix pass, by the raw-SQL trigger
    `trg_pricing_price_list_item_immutable` in 0005 (move it to the helper of question 2 when it exists).
  - **Supersede versions.** A superseded item's version moves by two: it is shortened, then linked. This is required
    by the non-deferrable exclusion constraint.

## Fix pass (2026-10-27)

Two adversarial reviews (correctness-security, spec-conformance; 2026-10-23) produced 27 findings. A first fix pass
was interrupted with uncommitted work; this pass reconciled it against every finding, finished it, added the missing
regression tests and committed everything. Commits: `c3442c6` (pricing), `1a4d312` (commercial), `31d543f`
(catalogue), `3e43745` (parties seed and tests), `5b07f7d` (test name), and this report.

### Correctness-security lens

| finding | severity | status |
|---|---|---|
| CS-1 calculate_quote prices lines from draft, retired or expired lists | major | fixed in `c3442c6` + `1a4d312`: PricedItem carries list status and validity; a line whose list is not active or whose list or item is not effective on the business date is a 422 `price_not_current` (test `test_draft_retired_or_expired_prices_are_never_totalled`) |
| CS-2 activation overlap guard is racy | minor | fixed in `c3442c6`: advisory xact lock per overlap target before the check (`test_activation_takes_the_target_lock`) |
| CS-3 unbounded quantity crashes with InvalidOperation | minor | fixed in `1a4d312`: `le=99999999999999`, `decimal_places=6`; engine ValueError/ArithmeticError become ValidationFailed (`test_out_of_range_quantities_are_a_422_never_an_arithmetic_error`, `test_largest_wire_quantity_is_calculated`) |
| CS-4 size facet counts disagree with the size filter | minor | fixed in `31d543f`: facet groups on least/greatest (`test_size_facet_counts_match_the_orientation_insensitive_filter`) |
| CS-5 sub-scale values hit a DB CHECK (500) | minor | fixed in `31d543f`: below_precision / too_large field errors for lengths, thickness and packaging (`test_positive_values_below_the_column_scale_are_rejected_not_zeroed`, `test_values_outside_the_column_scale_are_a_422_not_a_db_error`) |
| CS-6 mixed-unit dimension text parsed silently | minor | fixed in `31d543f`: status ambiguous + MIXED_UNITS (`test_mixed_units_are_ambiguous_never_guessed`) |
| CS-7 numeric 120.0 identifiers normalised without warning | minor | fixed in `31d543f` (`tests/unit/catalogue/test_normalise_identifier.py`) |
| CS-8 fractional quantities for integer units | minor | fixed in `1a4d312`: conventions §6 entry rule per item unit, 422 `uom_integer_only` / `uom_max_decimals` (`test_quantities_follow_the_unit_entry_rule`) |
| CS-9 sensitive cost reads not audited | minor | fixed in `c3442c6`: `pricing.product_cost.read` audit with field names and versions only (`test_cost_reads_are_audited_without_values`) |
| CS-10 CalculationResult inputs mutable through as_dict | minor | fixed in `1a4d312`: inputs deeply frozen, as_dict returns a copy (`test_result_is_frozen_and_carries_its_inputs`) |
| CS-11 rule-set effective_from ignored | minor | fixed in `1a4d312`: activation before effective_from is a 409 `rule_set_not_yet_effective`, capability mirrors it (`test_future_rule_set_is_not_activated_before_its_effective_date`) |
| CS-12 N+1 in _activation_conflicts | minor | fixed in `c3442c6`: one set-based join (covered by `test_overlapping_list_activation_is_rejected`, `test_unique_explicit_priority_resolves_the_overlap`) |
| CS-13 supersede allowed on draft and retired lists | minor | fixed in `c3442c6`: 409 `price_list_not_active`, capability reason (`test_supersede_only_on_active_lists`) |
| CS-14 active item immutability only in the service | minor | fixed in `c3442c6`: BEFORE UPDATE trigger in 0005 (`test_active_item_prices_are_immutable_in_the_database`) |

### Spec-conformance lens

| finding | severity | status |
|---|---|---|
| SC-1 money and quantities not {amount,currency} / {value,uom} | major | fixed in `c3442c6` + `1a4d312` + `31d543f`: price-list items, candidates, resolutions, costs, MOQ, calculation subtotals, adjustments, surcharge, grand total, line and recommended quantities (engine and HTTP tests assert the wire shape) |
| SC-2 UI-35 / LM-11 price and recommendation columns missing | major | fixed in `c3442c6` + `1a4d312` + `31d543f`: `pricing.display_prices` batch read plus engine recommendation, registered into catalogue reads (`test_price_columns_require_pricing_price_read`, `test_overview_prices_only_from_real_lists`, `test_rows_enriched_without_n_plus_one`) |
| SC-3 taxonomy rules untested | major | fixed in `31d543f`: `tests/integration/catalogue/test_taxonomy.py` (`test_created_category_active_by_default`, `test_composite_fk_rejects_foreign_subcategory`, duplicates, inactive parent, display order) |
| SC-4 pricing tab gated on pricing.price.read | major | fixed in `31d543f`: gated on pricing.price_list.read (`test_detail_returns_all_field_groups_with_section_guards`) |
| SC-5 DB trigger for active-list prices | minor | fixed in `c3442c6` (same as CS-14) |
| SC-6 verifying tests not under matrix names | minor | fixed in `31d543f`, `1a4d312`, `5b07f7d` for LM-10/API-10, BUG-05/FG-PRD-09, SCN-D1/D2/D4, BR-01..04, FG-PRD-01, UI-35, UI-39, UI-40, FG-TAX, BUG-07, BUG-10; GAP-01 is mapped below (row is 1→2) |
| SC-7 seed history not chronological | minor | fixed in `3e43745`: `parties.world.changes` SeedDef at order 55 (`test_seed_history_is_chronological`) |
| SC-8 packaging summary separator | minor | fixed in `31d543f`: "450g · 24/ctn · Poly bag" (`test_oak_tray_fixture_fields`) |
| SC-9 bare-array lists, action route, lookup parameter | minor | fixed in `c3442c6` + `1a4d312` + `31d543f`: Page for rule sets and costs, `GET /pricing/prices/resolve`, `lookup?key=` (`test_lane_api.py`, `test_lookup_by_key_with_special_characters`) |
| SC-10 Slice-2 pricing events not disclosed | minor | fixed in this report (contract question 6) |
| SC-11 fractional quantities for integer units | minor | duplicate of CS-8, fixed in `1a4d312` |
| SC-12 tests assert literal fixture values | minor | fixed in `31d543f` + `3e43745`: party number from the sequence definition, taxonomy and product names from the seed modules |
| SC-13 customer types as enum CHECKs; no import_job_id | minor | partly fixed in `c3442c6` (nullable `import_job_id` on items; FK when imports land). Customer-type reference table deferred: customer types become manageable in Slice 2 (`parties.customer_type.manage`); the migration to a `parties_customer_type` table with FKs from `parties_party` and `pricing_price_list` belongs with that work |

No finding contradicted a contract document.

### PARITY_MATRIX row-to-test mapping (Slice-1 rows of this lane)

- LM-10 / API-10: `tests/integration/catalogue/test_product_list.py::test_search_and_filters_apply_before_pagination`
- UI-35 / LM-11: `test_product_list.py::test_price_columns_require_pricing_price_read`, `::test_rows_enriched_without_n_plus_one`
- UI-39: `test_product_detail.py::test_overview_prices_only_from_real_lists`
- UI-40: `test_product_detail.py::test_detail_returns_all_field_groups_with_section_guards`
- API-13: `test_product_detail.py::test_lookup_by_key_with_special_characters`
- FG-PRD-01: `tests/integration/catalogue/test_product_crud.py::test_product_key_immutable_api_and_db_trigger`
- FG-PRD-05 / FG-REL-01: `tests/integration/catalogue/test_taxonomy.py::test_composite_fk_rejects_foreign_subcategory`
- FG-TAX-01..06: `test_taxonomy.py` (`test_duplicate_name_keys_conflict`, `test_inactive_parent_hides_its_children`, `test_tree_follows_display_order`); reorder and activation endpoints are Slice 2
- BUG-07: `test_taxonomy.py::test_created_category_active_by_default`
- BUG-05 / FG-PRD-09: `tests/unit/catalogue/test_normalise_identifier.py::test_normalise_identifier`, `::test_120_0_becomes_120_and_0120_stays_distinct`
- FG-PKG-11: `tests/integration/catalogue/test_seed_world.py::test_oak_tray_fixture_fields`
- SCN-D1 / LM-61 / BR-03: `tests/unit/commercial/test_engine.py::test_recommended_quantity`
- BR-02 / SCN-D2: `test_engine.py::test_surcharge_table`
- BR-01: `test_engine.py::test_minimum_order_meets_below_not_evaluated`
- SCN-D4: `test_engine.py::test_missing_zero_price_and_non_eur`
- FG-PRC-10: `test_engine.py::test_product_moq_distinct_from_recommendation`
- BR-04 / BUG-10: `tests/integration/pricing/test_price_resolution.py::test_legacy_multi_eur_rows_resolved_by_price_type`
- FG-PRC-02/03/11/13: `tests/integration/pricing/test_price_lists.py` (`test_lists_items_and_product_prices`, `test_breakdown_fields_need_price_list_read`, `test_product_cost_is_restricted_everywhere`, `test_items_never_overlap_for_the_same_list_product_and_unit`) and `test_price_resolution.py`
- GAP-01 (1→2): `tests/integration/parties/test_parties.py` (`test_create_allocates_the_next_number_and_emits_created`, `test_update_reports_changed_field_names_and_checks_versions`, `test_sales_users_see_only_their_own_parties`, `test_company_scope_and_visible_but_forbidden`); the matrix name `test_party_contacts_addresses_roles_scope` can point there

### Gate output

- `npm run test:api`: `274 passed in 140.55s (0:02:20)`
- `npm run check -- --keep-going`: ruff check PASS; pytest unit + contract PASS (157 passed); alembic heads == 1 PASS;
  api:check FAIL (expected: "backend/openapi.json is out of date", routes and schemas changed); web lint PASS; web
  typecheck PASS; web vitest PASS (134 passed)

### Requests for the integrator

1. Regenerate `backend/openapi.json` and the web client types (routes and DTOs changed: money and quantity objects,
   `/pricing/prices/resolve`, `lookup?key=`, Page for rule sets and costs, `prices` on catalogue rows and detail).
2. Cross-lane contract change for the sales lane: `engine.LineInput` now needs `uom`; `CalculationResult.as_dict()`
   and `CalculationResultOut` carry money as `{amount, currency}` and quantities as `{value, uom}` (the recommended
   quantity is a Quantity, not an int); `PriceResolution.unit_price` and `product_moq` are Money and Quantity
   (`moq_unit_code` is gone); `PriceListItemRead` has no `currency` (it is inside `unit_price`); `list_rule_sets`
   returns a Page. calculate_quote rejects non-current prices and quantities that break the unit entry rule.
3. Seed order: `parties.world.changes` is order 55, chosen to run after the sales history seed (expected around 50)
   and before tasks (80). Please confirm the slot when the sales seed lands.
4. Migration 0005 was edited in place (trigger and `import_job_id`); databases already at 0005 need a downgrade to
   0002 and upgrade (done for `lk_wt3` and `lk_wt3_test`).
5. Unchanged earlier requests: immutability helper (question 2, now also for `trg_pricing_price_list_item_immutable`),
   keys.py taxonomy and product constants (question 3), shared Capability type (question 10).
