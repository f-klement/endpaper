/** Tests for src/pages/OverduePage/hooks.ts. */

import { waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useOverdue } from "../../../src/pages/OverduePage/hooks";
import { makeBook, makeLoan, makeLoanPage, resetIds } from "../../factories";
import { mockApi, renderHookWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/api/loans/overdue/mine", { body: { enabled: true, count: 1 } });
  api.on(/\/api\/loans\/overdue(\?|$)/, {
    body: makeLoanPage([
      makeLoan({ is_overdue: true, book: makeBook({ title: "Piranesi" }) }),
    ]),
  });
});

describe("the channel record has three states, not one nullable list", () => {
  it("is hidden when the viewer may not read it", async () => {
    // A member's 403. Folding this into an empty list would make the page say
    // "no channel sends these anywhere" to somebody who has not been allowed
    // to look.
    api.on("/api/settings/sender-health", { status: 403, body: {} });
    const { result } = renderHookWithProviders(() => useOverdue());

    await waitFor(() => expect(result.current.total).toBe(1));
    await waitFor(() =>
      expect(result.current.channels).toEqual({ state: "hidden" }),
    );
  });

  it("is empty when an admin looked and nothing pushes", async () => {
    api.on("/api/settings/sender-health", { body: [] });
    const { result } = renderHookWithProviders(() => useOverdue());

    await waitFor(() =>
      expect(result.current.channels).toEqual({
        state: "channels",
        channels: [],
      }),
    );
  });

  it("is unreadable when the request failed for a reason that is not a refusal", async () => {
    // A 500 used to be indistinguishable from a member's 403, and the page
    // keeps this query's error out of its own error slot on purpose, so the
    // fault was silent on a page that otherwise loaded.
    api.on("/api/settings/sender-health", { status: 500, body: {} });
    const { result } = renderHookWithProviders(() => useOverdue());

    await waitFor(() =>
      expect(result.current.channels).toEqual({ state: "unreadable" }),
    );
  });

  it("stays hidden rather than unreadable before the request answers", async () => {
    // The first render has no data and no error. Reporting a fault there
    // would flash "could not be read" on every visit.
    api.on("/api/settings/sender-health", { body: [] });
    const { result } = renderHookWithProviders(() => useOverdue());

    expect(result.current.channels).toEqual({ state: "hidden" });
  });
});

describe("returning a book from here", () => {
  it("refetches this page's own list", async () => {
    // The defect the `loans()` group was extracted for. The loans page named
    // its stale keys by hand and did not name this list, because the list did
    // not exist when those keys were written; the row a reader had just
    // returned stayed on this page until something else dropped the cache.
    //
    // Asserted as a refetch rather than as an invalidated cache entry, because
    // `createTestQueryClient` sets `gcTime: 0` and collects a seeded key that
    // nothing is observing. What the wider set covers is pinned separately, in
    // `tests/api/invalidate.test.ts`.
    api.on("/api/settings/sender-health", { status: 403, body: {} });
    const { result } = renderHookWithProviders(() => useOverdue());
    await waitFor(() => expect(result.current.loans).toHaveLength(1));

    const before = api.calls.filter((call) =>
      /\/api\/loans\/overdue\?/.test(call.url),
    ).length;
    const loanId = result.current.loans[0]!.id;
    api.on(`/api/loans/${loanId}/return`, { body: {} }, "PUT");
    result.current.markReturned(loanId);

    await waitFor(() =>
      expect(
        api.calls.filter((call) => /\/api\/loans\/overdue\?/.test(call.url))
          .length,
      ).toBeGreaterThan(before),
    );
  });
});
