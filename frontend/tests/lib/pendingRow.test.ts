/**
 * @vitest-environment node
 */
/**
 * Tests for src/lib/pendingRow.ts.
 *
 * Reading the calls out of the mutation cache is reached through the pages
 * that use it, the trash and both loan lists. The set those calls make is
 * pinned here.
 */

import { describe, expect, it } from "vitest";

import { pendingRows } from "../../src/lib/pendingRow";

describe("pendingRows", () => {
  it("answers the row of every call still out, the zero row among them", () => {
    const calls = [{ bookId: 7 }, { bookId: 0 }, { bookId: 8 }];

    expect(pendingRows("bookId", calls)).toEqual(new Set([7, 0, 8]));
  });

  it("passes over a call that carries no row under the key", () => {
    const calls = [undefined, null, { loanId: 5 }, { bookId: "7" }];

    expect(pendingRows("bookId", calls)).toEqual(new Set());
  });
});
