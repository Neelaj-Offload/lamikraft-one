/**
 * The canonical fixture world as e2e tests see it (docs/architecture/fixtures.md §1 rule 6):
 * people are signed in by fixture key through `POST /api/v1/_test/sign-in`, and ids, document
 * numbers and expected figures come from `GET /api/v1/_test/fixtures`, never from literals.
 *
 * `/_test/fixtures` returns `{company_id, company_key, slice_max, refs, facts}` (seed/runner.py
 * `world_summary`). The expected results are read from `facts.expected` (string values of
 * `keys.EXPECTED`), `facts.quotes` (`keys.QUOTES`) and `facts.enquiries` (`keys.ENQUIRIES`);
 * `refs` carries ids by fixture key and, for quotes and enquiries, by business key too.
 */

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

export interface World {
  company_id: string;
  company_key: string;
  slice_max: number;
  refs: Record<string, string>;
  facts: Record<string, unknown>;
}

/** Fixture person keys (`keys.PEOPLE`), not names. */
export type PersonKey = "MEERA" | "SAHIL" | "NEHA" | "RAVI" | "KABIR" | "ARJUN" | "PRIYA";

export async function loadWorld(request: APIRequestContext): Promise<World> {
  const response = await request.get("/api/v1/_test/fixtures");
  expect(response.status(), "GET /api/v1/_test/fixtures (is the e2e API seeded?)").toBe(200);
  return (await response.json()) as World;
}

/** Signs the browser context in as a fixture person; the session cookies land in the context. */
export async function signInAs(page: Page, person: PersonKey): Promise<void> {
  await page.context().clearCookies();
  // The API's CSRF/Origin check refuses unsafe requests without the app's Origin (a browser sends it).
  const origin = new URL(test.info().project.use.baseURL ?? "http://127.0.0.1").origin;
  const response = await page.request.post("/api/v1/_test/sign-in", { data: { user_key: person }, headers: { Origin: origin } });
  expect(response.status(), `test sign-in as ${person}`).toBe(200);
}

function section(world: World, name: string): Record<string, unknown> {
  const value = world.facts[name];
  return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

/** A published fact (`facts[section][key]`, e.g. `quotes.NORDHAUS_DRAFT`), or null. */
export function fact(world: World, name: string, key: string): string | null {
  const value = section(world, name)[key];
  return typeof value === "string" && value !== "" ? value : null;
}

/** An expected figure or number (`keys.EXPECTED.*`, `keys.QUOTES.*`), as published by the seed. */
export function expected(world: World, key: string): string {
  const value = fact(world, "expected", key) ?? fact(world, "quotes", key);
  if (value === null) throw new Error(`The fixture world does not publish "${key}" in /_test/fixtures facts (expected or quotes).`);
  return value;
}

/** The id of a seeded record by its business key (quote number, `PROP_MAISON`, `ENQ-2026-0001` …). */
export function ref(world: World, key: string): string | null {
  return world.refs[key] ?? null;
}

/** Money as the app formats it (en-IN), from the DecimalStr string; never through a float. */
export function moneyText(amount: string, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(amount as unknown as number);
}

/** Skips the running test (or, from a hook, its group) outside the given Playwright projects. */
export function onlyOnProjects(...names: readonly string[]): void {
  const project = test.info().project.name;
  test.skip(!names.includes(project), `runs on ${names.join(" and ")} only`);
}
