/**
 * Tests for src/lib/sectionState.ts.
 *
 * Three things are worth pinning here. Storage that refuses to answer must end in
 * a rendered page rather than an error, as everywhere else this app stores a
 * habit. And absence must stay a third state distinct from "closed": a test
 * that only checks the default cannot tell those two apart, which is exactly
 * how this design gets broken later. And two pages fold, both with a section
 * called `about`, so a choice made on one must not reach the other.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  readSectionChoices,
  resolveOpen,
  writeSectionChoice,
} from "../../src/lib/sectionState";

/** One of the two stores. The pair is exercised in its own describe below. */
const STORE = "bookDetailSections";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("readSectionChoices", () => {
  it("starts with nothing said about any section", () => {
    expect(readSectionChoices(STORE)).toEqual({});
  });

  it("remembers a section that was opened", () => {
    writeSectionChoice(STORE, "lending", true);
    expect(readSectionChoices(STORE)).toEqual({ lending: "open" });
  });

  it("remembers a section that was closed", () => {
    writeSectionChoice(STORE, "lending", false);
    expect(readSectionChoices(STORE)).toEqual({ lending: "closed" });
  });

  it("ignores a stored shape from another version", () => {
    localStorage.setItem(
      STORE,
      JSON.stringify({ version: 99, sections: { lending: "open" } }),
    );
    expect(readSectionChoices(STORE)).toEqual({});
  });

  it("ignores a value that is neither open nor closed", () => {
    // Written by hand, or by a future version that added a third state.
    localStorage.setItem(
      STORE,
      JSON.stringify({ version: 1, sections: { lending: "maybe" } }),
    );
    expect(readSectionChoices(STORE)).toEqual({});
  });

  it("keeps an id no section answers to any more", () => {
    // A section renamed or dropped leaves its entry behind. Nothing asks for
    // it, so nothing renders it, and a section that comes back finds what the
    // reader last said rather than a fresh default.
    localStorage.setItem(
      STORE,
      JSON.stringify({
        version: 1,
        sections: { gone: "open", shelf: "closed" },
      }),
    );
    expect(readSectionChoices(STORE)).toEqual({
      gone: "open",
      shelf: "closed",
    });
  });

  it("returns nothing when the stored value is not JSON", () => {
    localStorage.setItem(STORE, "{half-writ");
    expect(readSectionChoices(STORE)).toEqual({});
  });

  it("returns nothing when storage refuses to answer", () => {
    // A private window. The book still has to render.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readSectionChoices(STORE)).toEqual({});
  });
});

describe("writeSectionChoice", () => {
  it("leaves every other section alone", () => {
    writeSectionChoice(STORE, "lending", true);
    writeSectionChoice(STORE, "writing", false);
    expect(readSectionChoices(STORE)).toEqual({
      lending: "open",
      writing: "closed",
    });
  });

  it("replaces what was said about the same section", () => {
    writeSectionChoice(STORE, "lending", true);
    writeSectionChoice(STORE, "lending", false);
    expect(readSectionChoices(STORE)).toEqual({ lending: "closed" });
  });

  it("says nothing when storage refuses to keep it", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => writeSectionChoice(STORE, "lending", true)).not.toThrow();
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

/**
 * One page folds now, and there are still two stores.
 *
 * The settings page stopped folding on 2026-08-27, so nothing writes
 * `settingsSections` any more. The name stays in the union and these two tests
 * stay with it, which is the whole reason it was not tidied away: old entries
 * are in readers' browsers, so a later folding page must not reuse the key, and
 * the merge below cannot be tested against one store.
 */
describe("keeping two stores apart", () => {
  it("keeps the same section id apart", () => {
    // Both the book page and the settings page had an `about` section. One
    // shared key would have made closing the blurb on a book close the app's
    // own about card, and nothing on either page would have looked wrong.
    writeSectionChoice("bookDetailSections", "about", false);

    expect(readSectionChoices("settingsSections")).toEqual({});
    expect(readSectionChoices("bookDetailSections")).toEqual({
      about: "closed",
    });
  });

  it("does not lose the other store's entries when one is written", () => {
    writeSectionChoice("settingsSections", "backup", true);
    writeSectionChoice("bookDetailSections", "lending", true);

    expect(readSectionChoices("settingsSections")).toEqual({ backup: "open" });
  });
});
