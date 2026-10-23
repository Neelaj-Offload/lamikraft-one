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
| GET `/api/v1/catalogue/products` | `catalogue_list_products` | catalogue.product.read |
| GET `/api/v1/catalogue/products/facets` | `catalogue_get_product_facets` | catalogue.product.read |
| GET `/api/v1/catalogue/products/stats` | `catalogue_get_product_stats` | catalogue.product.read |
| GET `/api/v1/catalogue/products/completeness` | `catalogue_get_product_completeness` | catalogue.product.read |
| GET `/api/v1/catalogue/products/lookup?product_key=` | `catalogue_get_product_by_key` | catalogue.product.read |
| GET `/api/v1/catalogue/products/{product_id}` | `catalogue_get_product` | catalogue.product.read |
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
| GET `/api/v1/pricing/products/{product_id}/costs` | `pricing_list_product_costs` | pricing.cost.read |
| GET `/api/v1/pricing/resolve` | `pricing_resolve_price` | pricing.price.read |
| GET `/api/v1/commercial/rule-sets` | `commercial_list_rule_sets` | commercial.rule_set.read |
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
- **Seeds:** `parties.world` (20), `catalogue.world` (30), `pricing.world` (40), `commercial.world` (40).
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
   Slice 2 in events.md but are emitted now, when the seed creates taxonomy rows.
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
  - **Price enrichment in catalogue reads.** List rows lack the EUR price and order-value recommendation (LM-11), and
    stats lack "without pricing". The catalogue cannot import pricing (pricing depends on catalogue). A composition
    endpoint, in sales or pricing, or a client join is needed.
  - **Identity in tests.** Tests register a stand-in member-actor builder (template grants from the frozen catalogue)
    and override the session dependency for HTTP tests, because identity and the test-support sign-in are another
    lane.
- **Accepted for now:**
  - **Active-list price immutability.** It is enforced in the service only: `add_item` accepts draft lists only, and
    changes go through supersede. There is no DB trigger yet, because no helper exists (see question 2).
  - **Supersede versions.** A superseded item's version moves by two: it is shortened, then linked. This is required
    by the non-deferrable exclusion constraint.
