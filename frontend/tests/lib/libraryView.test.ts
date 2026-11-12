/**
 * Tests for src/lib/libraryView.ts.
 *
 * A remembered view is a convenience, so every way storage can refuse to answer
 * has to end in a rendered library rather than an error. That is most of what
 * is worth pinning here.
 *
 * The rest is the property the per-mode default exists to protect: two keys, so
 * neither mode's choice is ever a merge of the other's. Asserted on the stored
 * keys as well as on what comes back, because a single key holding the right
 * value for the mode being read is indistinguishable from two until the other
 * mode is asked.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CATALOGUE_MODES } from "../../src/lib/catalogueMode";
import {
  DEFAULT_LIBRARY_VIEWS,
  libraryViewPreference,
} from "../../src/lib/libraryView";

import { whileStorageRefuses } from "../storageRefusal";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("reading a remembered view", () => {
  it("starts a household on the covers", () => {
    expect(libraryViewPreference.read("household")).toBe("grid");
    expect(DEFAULT_LIBRARY_VIEWS.household).toBe("grid");
  });

  it("starts a cataloguer on the dense rows", () => {
    // The whole of the ticket: a counter sees records without setting anything.
    expect(libraryViewPreference.read("cataloguer")).toBe("list");
    expect(DEFAULT_LIBRARY_VIEWS.cataloguer).toBe("list");
  });

  it("remembers a choice", () => {
    libraryViewPreference.write("household", "table");
    expect(libraryViewPreference.read("household")).toBe("table");
  });

  it("remembers the dense rows", () => {
    /** A third view was one entry in `LIBRARY_VIEWS`, and the type, the
     * validation and the storage followed from it. */
    libraryViewPreference.write("household", "list");
    expect(libraryViewPreference.read("household")).toBe("list");
  });

  it("remembers a cataloguer's move off the dense rows", () => {
    // The default is where library mode opens, not where it is pinned.
    libraryViewPreference.write("cataloguer", "grid");
    expect(libraryViewPreference.read("cataloguer")).toBe("grid");
  });

  it("ignores a value it does not know", () => {
    // A value written by a future version, or by hand.
    localStorage.setItem("libraryView", "carousel");
    expect(libraryViewPreference.read("household")).toBe("grid");
  });

  it("falls back to each mode's own default when storage refuses to answer", () => {
    // A private window. The library still has to render, and it has to render
    // as the mode being read rather than as the first one written down.
    // Both modes hold a choice, so each default can only come from the
    // refusal.
    libraryViewPreference.write("household", "table");
    libraryViewPreference.write("cataloguer", "table");
    whileStorageRefuses("getItem", () => {
      expect(libraryViewPreference.read("household")).toBe("grid");
      expect(libraryViewPreference.read("cataloguer")).toBe("list");
    });
  });
});

describe("writing one", () => {
  it("says nothing when storage refuses to keep it", () => {
    libraryViewPreference.write("household", "list");
    whileStorageRefuses("setItem", () => {
      expect(() =>
        libraryViewPreference.write("household", "table"),
      ).not.toThrow();
    });
    expect(libraryViewPreference.read("household")).toBe("list");
  });

  it("keeps a choice that happens to be the default", () => {
    // `libraryColumnsPreference` clears its key here and this deliberately
    // does not: there is no reset control whose visibility turns on the
    // answer, and a cataloguer who picks the dense view has picked it.
    libraryViewPreference.write("cataloguer", "list");
    expect(localStorage.getItem("libraryView.cataloguer")).toBe("list");
  });
});

describe("the two modes", () => {
  it("leaves the household's key alone when a cataloguer chooses", () => {
    libraryViewPreference.write("household", "table");
    libraryViewPreference.write("cataloguer", "grid");

    expect(libraryViewPreference.read("household")).toBe("table");
    expect(localStorage.getItem("libraryView")).toBe("table");
  });

  it("leaves the cataloguer's key alone when a household chooses", () => {
    libraryViewPreference.write("cataloguer", "grid");
    libraryViewPreference.write("household", "table");

    expect(libraryViewPreference.read("cataloguer")).toBe("grid");
    expect(localStorage.getItem("libraryView.cataloguer")).toBe("grid");
  });

  it("stores each mode under a key of its own", () => {
    // Two keys is the mechanism, so it is asserted rather than inferred from
    // the two reads above agreeing. Both write the same value, which is the
    // case a single shared key would survive.
    for (const mode of CATALOGUE_MODES)
      libraryViewPreference.write(mode, "table");

    // Read through `key(i)` rather than `Object.keys`: happy-dom's `Storage` is
    // a Proxy that answers false to `hasOwnProperty` for a key it will return
    // from `getItem`, so an enumeration is not a reliable instrument here.
    const stored = new Set<string>();
    for (let i = 0; i < localStorage.length; i += 1) {
      stored.add(localStorage.key(i)!);
    }
    expect(stored.size).toBe(CATALOGUE_MODES.length);
  });
});
