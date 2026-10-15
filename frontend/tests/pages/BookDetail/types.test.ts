/** Tests for src/pages/BookDetail/types.ts. */

import { describe, expect, it } from "vitest";

import { BookFormat } from "../../../src/api/generated/model";
import { isRequestedNotLent } from "../../../src/pages/BookDetail/types";

describe("which copies are asked for rather than lent", () => {
  it("matches the server's rule for every format, with and without a file", () => {
    // The same table as backend/tests/test_lending.py walks for
    // `lending.is_requested_not_lent`: a change to one side reddens its own
    // test, and the table here is what that change has to be held against.
    const requested = Object.values(BookFormat).flatMap((format) =>
      [false, true]
        .filter((hasFile) => isRequestedNotLent(format, hasFile))
        .map((hasFile) => `${format}:${hasFile}`),
    );
    expect(requested).toEqual(["ebook:false", "ebook:true", "audiobook:true"]);
  });
});
