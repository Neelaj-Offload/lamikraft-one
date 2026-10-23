import { describe, expect, it } from "vitest";
import { NetworkError, ProblemError } from "@/lib/api/errors";
import { DEFAULT_STALE_TIME_MS, makeQueryClient, retryDelay, shouldRetryQuery } from "./query";

const problem = (status: number) => new ProblemError({ code: "x", title: "x", status });

describe("query retry policy", () => {
  it("retries network failures at most twice", () => {
    const error = new NetworkError(new TypeError("Failed to fetch"));
    expect(shouldRetryQuery(0, error)).toBe(true);
    expect(shouldRetryQuery(1, error)).toBe(true);
    expect(shouldRetryQuery(2, error)).toBe(false);
  });

  it("never retries HTTP answers", () => {
    for (const status of [400, 401, 403, 404, 409, 422, 429, 500, 503]) {
      expect(shouldRetryQuery(0, problem(status)), String(status)).toBe(false);
    }
  });

  it("does not retry programming errors", () => {
    expect(shouldRetryQuery(0, new TypeError("x is undefined"))).toBe(false);
  });

  it("backs off exponentially with a cap", () => {
    expect([0, 1, 2, 3, 6].map(retryDelay)).toEqual([1000, 2000, 4000, 8000, 8000]);
  });
});

describe("makeQueryClient", () => {
  it("applies the defaults", () => {
    const defaults = makeQueryClient().getDefaultOptions();
    expect(defaults.queries?.staleTime).toBe(DEFAULT_STALE_TIME_MS);
    expect(defaults.queries?.retry).toBe(shouldRetryQuery);
    expect(defaults.mutations?.retry).toBe(false);
  });
});
