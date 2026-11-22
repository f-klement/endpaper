/**
 * @vitest-environment node
 *
 * Tests for src/lib/accession.ts. What both implementations answer is in
 * `conformance/cases/accession.json`, run by `tests/conformance/accession.test.ts`;
 * this holds the refusals a case cannot state, since a case expects an answer.
 */

import { describe, expect, it } from "vitest";

import { mint } from "../../src/lib/accession";

describe("mint", () => {
  it("refuses an id past what nine digits carry rather than minting ten", () => {
    expect(() => mint(10_000_000)).toThrow(RangeError);
  });

  it("refuses an id no row can have", () => {
    expect(() => mint(0)).toThrow(RangeError);
  });

  it("refuses a fractional id rather than printing its decimal point", () => {
    expect(() => mint(4711.5)).toThrow(RangeError);
  });
});
