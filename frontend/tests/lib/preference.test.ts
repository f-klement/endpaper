/**
 * Tests for src/lib/preference.ts.
 *
 * Two jobs, and the first one is not about this module's code at all.
 *
 * **The stored key strings are a promise to browsers that already hold them**,
 * and this is the one place in the tree that says so. They were private to five
 * modules and restated verbatim by tests at a distance from them, so renaming
 * one turned those assertions green while every browser holding it silently
 * reset to a default. A literal written once, here, with every other site naming
 * the key through the preference, is what makes a rename fail rather than pass.
 *
 * **The rest is what the door absorbs so that five modules stop restating it**:
 * that neither reading nor writing throws, that absence and an unreadable value
 * both mean the default, that a snapshot is the same value until its own stored
 * string changes, that it cannot be edited, and that a write reaches readers.
 *
 * **A key is claimed once, and claiming is permanent within a worker**, so the
 * declarations made here use keys of their own. The suite shares one module
 * registry across the files in a worker, which is the same reason
 * `forgetPreferences` exists.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  declarePreference,
  declareScopedPreference,
  declaredKeys,
  forgetPreferences,
} from "../../src/lib/preference";
import { libraryColumnsPreference } from "../../src/lib/libraryColumns";
import { libraryViewPreference } from "../../src/lib/libraryView";
import { lastLocationPreference } from "../../src/lib/lastLocation";
import { savedSearchesPreference } from "../../src/lib/savedSearches";
import { sectionChoicesPreference } from "../../src/lib/sectionState";

beforeEach(() => {
  localStorage.clear();
  forgetPreferences();
});
afterEach(() => vi.restoreAllMocks());

/**
 * Every key this application stores a preference under, written out once.
 *
 * **Changing a string here is changing what is in somebody's browser.** A key
 * that moves does not migrate: the old entry is orphaned and the reader is
 * handed a default, which for the household's view means every existing library
 * opening on the grid it did not choose. That is the clobber the separate keys
 * exist to prevent, arriving from the other direction.
 */
const THE_KEYS_IN_READERS_BROWSERS = {
  libraryViewHousehold: "libraryView",
  libraryViewCataloguer: "libraryView.cataloguer",
  libraryColumnsHousehold: "libraryColumns.household",
  libraryColumnsCataloguer: "libraryColumns.cataloguer",
  savedSearches: "savedSearches",
  lastLocation: "lastLocation",
  bookDetailSections: "bookDetailSections",
  settingsSections: "settingsSections",
};

describe("the keys a browser already holds", () => {
  it("spells the view's two, the household's without a prefix", () => {
    // The household's key shipped before the modes did, so it has no prefix
    // where the column keys have one. The asymmetry is deliberate and is the
    // reason it cannot be tidied.
    expect(libraryViewPreference.keyFor("household")).toBe(
      THE_KEYS_IN_READERS_BROWSERS.libraryViewHousehold,
    );
    expect(libraryViewPreference.keyFor("cataloguer")).toBe(
      THE_KEYS_IN_READERS_BROWSERS.libraryViewCataloguer,
    );
  });

  it("spells the column set's two", () => {
    expect(libraryColumnsPreference.keyFor("household")).toBe(
      THE_KEYS_IN_READERS_BROWSERS.libraryColumnsHousehold,
    );
    expect(libraryColumnsPreference.keyFor("cataloguer")).toBe(
      THE_KEYS_IN_READERS_BROWSERS.libraryColumnsCataloguer,
    );
  });

  it("spells the ones that are kept once", () => {
    expect(savedSearchesPreference.key).toBe(
      THE_KEYS_IN_READERS_BROWSERS.savedSearches,
    );
    expect(lastLocationPreference.key).toBe(
      THE_KEYS_IN_READERS_BROWSERS.lastLocation,
    );
  });

  it("spells each folding page's, which is the page's own store name", () => {
    expect(sectionChoicesPreference.keyFor("bookDetailSections")).toBe(
      THE_KEYS_IN_READERS_BROWSERS.bookDetailSections,
    );
    // Nothing writes this one any more and the name is kept deliberately: the
    // entries are still in readers' browsers, so the key is spoken for and a
    // later folding page must not reuse it and inherit them.
    expect(sectionChoicesPreference.keyFor("settingsSections")).toBe(
      THE_KEYS_IN_READERS_BROWSERS.settingsSections,
    );
  });

  it("holds every key this application has declared, and no others", () => {
    // **The half that makes the table above a pin rather than a fourth
    // restatement.** Without this the table could agree with itself for ever
    // while a ninth preference went unpinned, which is the inclusion list shape:
    // it is satisfied by any subset of what exists. Read the other way, a key
    // renamed in its module fails the arms above, and a key *added* fails here.
    //
    // A preference declared by a test carries a `test.` prefix, deliberately, so
    // that the two can be told apart: claiming is permanent within a worker, and
    // the suite shares one module registry, so this file's own declarations and
    // those in `tests/app/hooks.test.ts` are in the set as well.
    expect(declaredKeys().filter((key) => !key.startsWith("test."))).toEqual(
      Object.values(THE_KEYS_IN_READERS_BROWSERS).sort(),
    );
  });

  it("gives no two scopes of one preference the same key", () => {
    // Two scopes sharing a key would share a snapshot, and worse, one mode's
    // choice would be the other's. Asserted rather than inferred from the four
    // reads above being different, which is the case one shared key survives.
    const keys = new Set(Object.values(THE_KEYS_IN_READERS_BROWSERS));
    expect(keys.size).toBe(Object.keys(THE_KEYS_IN_READERS_BROWSERS).length);
  });
});

describe("claiming a key", () => {
  it("refuses a key another preference already declared", () => {
    expect(() =>
      declarePreference("libraryView", {
        decode: (raw) => raw,
        encode: (value) => value,
        fallback: () => "",
      }),
    ).toThrow(/two preferences declare/);
  });

  it("refuses a key that belongs to something that is not a preference", () => {
    // The names beside these in one origin hold an identity and a token. This
    // is why the door takes declared literals and never a function that builds
    // a key: a literal can be checked when the module loads.
    for (const reserved of ["token", "user", "appearance", "theme", "locale"]) {
      expect(() =>
        declarePreference(reserved, {
          decode: (raw) => raw,
          encode: (value) => value,
          fallback: () => "",
        }),
      ).toThrow(/not a preference/);
    }
  });
});

/** A preference of this file's own, so nothing here depends on a real one. */
const colour = declarePreference<string>("test.colour", {
  decode: (raw) => (raw === "red" || raw === "blue" ? raw : undefined),
  encode: (value) => (value === "grey" ? null : value),
  fallback: () => "grey",
});

describe("reading", () => {
  it("answers with the default when nothing is stored", () => {
    expect(colour.read()).toBe("grey");
  });

  it("answers with the default for a value it cannot read", () => {
    localStorage.setItem("test.colour", "chartreuse");
    expect(colour.read()).toBe("grey");
  });

  it("answers with the default when storage refuses, rather than throwing", () => {
    // React calls a read while rendering, so a throw here is a blank screen
    // rather than a fallback.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => colour.read()).not.toThrow();
    expect(colour.read()).toBe("grey");
  });

  it("answers with the default when the decode itself throws", () => {
    const brittle = declarePreference<string>("test.brittle", {
      decode: () => {
        throw new Error("bad");
      },
      encode: (value) => value,
      fallback: () => "safe",
    });
    localStorage.setItem("test.brittle", "anything");
    expect(brittle.read()).toBe("safe");
  });

  it("sees a value written past it", () => {
    // A test seeding storage, or another tab. The snapshot is held against the
    // exact string it was decoded from, so it is correct rather than fresh.
    expect(colour.read()).toBe("grey");
    localStorage.setItem("test.colour", "red");
    expect(colour.read()).toBe("red");
  });
});

describe("a snapshot", () => {
  const list = declarePreference<readonly string[]>("test.list", {
    decode: (raw) => raw.split(","),
    encode: (value) => value.join(","),
    fallback: () => [],
  });

  it("is the same value until the stored string changes", () => {
    localStorage.setItem("test.list", "a,b");
    const first = list.read();
    expect(list.read()).toBe(first);

    localStorage.setItem("test.list", "a,c");
    expect(list.read()).not.toBe(first);
  });

  it("is the same value when storage refuses, so a read cannot loop", () => {
    // The default on this path is held rather than rebuilt. Handing back a new
    // one each call would make a private window the one place the library never
    // finished drawing.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(list.read()).toBe(list.read());
  });

  it("cannot be edited by the reader it was handed to", () => {
    localStorage.setItem("test.list", "a,b");
    const held = list.read() as string[];
    expect(() => held.push("c")).toThrow();
  });
});

describe("writing", () => {
  it("stores what the codec encodes", () => {
    colour.write("red");
    expect(localStorage.getItem("test.colour")).toBe("red");
    expect(colour.read()).toBe("red");
  });

  it("clears the key when the codec asks for it", () => {
    colour.write("red");
    colour.write("grey");
    expect(localStorage.getItem("test.colour")).toBeNull();
    expect(colour.read()).toBe("grey");
  });

  it("says nothing when storage refuses to keep it", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => colour.write("red")).not.toThrow();
  });

  it("tells a reader", () => {
    const heard = vi.fn();
    const stop = colour.subscribe(heard);
    colour.write("red");
    expect(heard).toHaveBeenCalled();
    stop();
  });

  it("tells a reader even when the write was refused", () => {
    // The reader is drawing whatever a control just tried to change, so a
    // notification that only fired on success would leave that control drawn as
    // though the press had taken.
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    const heard = vi.fn();
    const stop = colour.subscribe(heard);
    colour.write("red");
    expect(heard).toHaveBeenCalled();
    stop();
  });

  it("tells the readers of every preference, not only its own", () => {
    // One listener set for all of them, which is free because an untouched
    // preference hands its reader back the value it already held.
    const heard = vi.fn();
    const stop = colour.subscribe(heard);
    lastLocationPreference.write("Loft");
    expect(heard).toHaveBeenCalled();
    stop();
  });

  it("stops telling a reader that unsubscribed", () => {
    const heard = vi.fn();
    colour.subscribe(heard)();
    colour.write("red");
    expect(heard).not.toHaveBeenCalled();
  });
});

describe("a preference kept per scope", () => {
  const shelf = declareScopedPreference<"near" | "far", string>(
    { near: "test.shelf.near", far: "test.shelf.far" },
    "near",
    {
      decode: (raw) => raw,
      encode: (value) => value,
      fallback: (scope) => `default ${scope}`,
    },
  );

  it("gives each scope its own default", () => {
    expect(shelf.read("near")).toBe("default near");
    expect(shelf.read("far")).toBe("default far");
  });

  it("leaves one scope alone when the other is written", () => {
    shelf.write("near", "attic");
    expect(shelf.read("far")).toBe("default far");
    expect(localStorage.getItem("test.shelf.far")).toBeNull();
  });

  it("names which scope a reader gets before the real one is known", () => {
    expect(shelf.whenUnknown).toBe("near");
  });
});
