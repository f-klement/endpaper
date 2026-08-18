/** Tests for src/api/query-client.ts: the shared cache defaults. */

import { describe, expect, it } from "vitest";

import { ApiError } from "../../src/api/mutator";
import { createQueryClient } from "../../src/api/query-client";

/** Pull the retry predicate out of the client's query defaults. */
function retryPredicate() {
  const retry = createQueryClient().getDefaultOptions().queries?.retry;
  if (typeof retry !== "function")
    throw new Error("expected a retry predicate");
  return retry as (failureCount: number, error: unknown) => boolean;
}

describe("createQueryClient", () => {
  it("returns a fresh client each time", () => {
    // A module-level singleton would carry one test's data into the next, and
    // one member's data across a sign-out.
    expect(createQueryClient()).not.toBe(createQueryClient());
  });

  it("never retries a mutation", () => {
    // A request that may already have created a book must not be resent on
    // its own initiative.
    expect(createQueryClient().getDefaultOptions().mutations?.retry).toBe(
      false,
    );
  });

  it("keeps results briefly so navigating back does not refetch", () => {
    expect(
      createQueryClient().getDefaultOptions().queries?.staleTime,
    ).toBeGreaterThan(0);
  });
});

describe("retry policy", () => {
  const retry = retryPredicate();

  it.each([400, 401, 403, 404, 409, 413, 422])(
    "does not retry a %d",
    (status) => {
      // Retrying a 404 only makes the reader wait longer to be told the same
      // thing, and retrying a 401 races the redirect to the login page.
      expect(retry(0, new ApiError("nope", status))).toBe(false);
    },
  );

  it.each([500, 502, 503, 504])("retries a %d", (status) => {
    expect(retry(0, new ApiError("boom", status))).toBe(true);
  });

  it("retries a network failure that is not an ApiError", () => {
    expect(retry(0, new TypeError("Failed to fetch"))).toBe(true);
  });

  it("gives up after a bounded number of attempts", () => {
    expect(retry(5, new ApiError("boom", 500))).toBe(false);
  });
});
