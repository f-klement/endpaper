/**
 * Tests for src/lib/goodreads.ts.
 *
 * Mirrors backend/tests/test_goodreads.py's TestSearchUrl, deliberately: the
 * two implementations must agree, and the way to keep them agreeing is to ask
 * them the same questions.
 */

import { describe, expect, it } from "vitest";

import { searchUrl } from "../../src/lib/goodreads";

describe("searchUrl", () => {
  it("points at Goodreads search", () => {
    expect(searchUrl("Dune")).toMatch(
      /^https:\/\/www\.goodreads\.com\/search\?q=/,
    );
  });

  it("prefers the ISBN", () => {
    // A title search for "Dune" returns dozens of editions; an ISBN search
    // returns the one on the shelf.
    expect(searchUrl("Dune", "9780441013593")).toContain("9780441013593");
  });

  it("falls back to the title when there is no ISBN", () => {
    expect(searchUrl("Dune", null)).toContain("Dune");
  });

  it("treats a blank ISBN as absent", () => {
    expect(searchUrl("Dune", "   ")).toContain("Dune");
  });

  it("escapes spaces and punctuation", () => {
    const url = searchUrl("Eats, Shoots & Leaves");
    expect(url).not.toContain(" ");
    // An unescaped & would truncate the query at the first word.
    expect(url.split("q=")[1]).not.toContain("&");
  });

  it("escapes a title that would otherwise change the URL's meaning", () => {
    const url = searchUrl("a?b=c#d");
    expect(url.split("q=")[1]).toBe("a%3Fb%3Dc%23d");
  });

  it("trims a padded ISBN", () => {
    expect(searchUrl("Dune", "  9780441013593  ")).toContain("q=9780441013593");
  });
});
