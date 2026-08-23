/**
 * Tests for src/lib/sectionState.ts.
 *
 * Two things are worth pinning here. Storage that refuses to answer must end in
 * a rendered page rather than an error, as everywhere else this app stores a
 * habit. And absence must stay a third state distinct from "closed": a test
 * that only checks the default cannot tell those two apart, which is exactly
 * how this design gets broken later.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  readSectionChoices,
  resolveOpen,
  writeSectionChoice,
} from "../../src/lib/sectionState";

const KEY = "bookDetailSections";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("readSectionChoices", () => {
  it("starts with nothing said about any section", () => {
    expect(readSectionChoices()).toEqual({});
  });

  it("remembers a section that was opened", () => {
    writeSectionChoice("lending", true);
    expect(readSectionChoices()).toEqual({ lending: "open" });
  });

  it("remembers a section that was closed", () => {
    writeSectionChoice("lending", false);
    expect(readSectionChoices()).toEqual({ lending: "closed" });
  });

  it("ignores a stored shape from another version", () => {
    localStorage.setItem(
      KEY,
      JSON.stringify({ version: 99, sections: { lending: "open" } }),
    );
    expect(readSectionChoices()).toEqual({});
  });

  it("ignores a value that is neither open nor closed", () => {
    // Written by hand, or by a future version that added a third state.
    localStorage.setItem(
      KEY,
      JSON.stringify({ version: 1, sections: { lending: "maybe" } }),
    );
    expect(readSectionChoices()).toEqual({});
  });

  it("keeps an id no section answers to any more", () => {
    // A section renamed or dropped leaves its entry behind. Nothing asks for
    // it, so nothing renders it, and a section that comes back finds what the
    // reader last said rather than a fresh default.
    localStorage.setItem(
      KEY,
      JSON.stringify({ version: 1, sections: { gone: "open", shelf: "closed" } }),
    );
    expect(readSectionChoices()).toEqual({ gone: "open", shelf: "closed" });
  });

  it("returns nothing when the stored value is not JSON", () => {
    localStorage.setItem(KEY, "{half-writ");
    expect(readSectionChoices()).toEqual({});
  });

  it("returns nothing when storage refuses to answer", () => {
    // A private window. The book still has to render.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readSectionChoices()).toEqual({});
  });
});

describe("writeSectionChoice", () => {
  it("leaves every other section alone", () => {
    writeSectionChoice("lending", true);
    writeSectionChoice("writing", false);
    expect(readSectionChoices()).toEqual({
      lending: "open",
      writing: "closed",
    });
  });

  it("replaces what was said about the same section", () => {
    writeSectionChoice("lending", true);
    writeSectionChoice("lending", false);
    expect(readSectionChoices()).toEqual({ lending: "closed" });
  });

  it("says nothing when storage refuses to keep it", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => writeSectionChoice("lending", true)).not.toThrow();
  });
});

describe("resolveOpen", () => {
  it("follows the book when nobody has said anything", () => {
    expect(resolveOpen(undefined, true)).toBe(true);
    expect(resolveOpen(undefined, false)).toBe(false);
  });

  it("lets a reader close a section the book would open", () => {
    // The failure this whole design exists to prevent: closing the loan
    // section on a borrowed book, and finding it open again next visit.
    expect(resolveOpen("closed", true)).toBe(false);
  });

  it("lets a reader open a section the book would close", () => {
    expect(resolveOpen("open", false)).toBe(true);
  });
});
