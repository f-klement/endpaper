/**
 * Tests for src/lib/nameOrder.ts.
 *
 * Asserted as properties rather than as one expected array. `Intl`'s collation
 * data is the runtime's, not the app's, so a fixture pinned exactly here would
 * be pinning node's ICU build: what the app promises is that an accented name
 * files with its base letter, not that a particular ten names come out in a
 * particular order on a particular runtime.
 */

import { describe, expect, it } from "vitest";

import { Locale } from "../../src/api/generated/model";
import { sortByName } from "../../src/lib/nameOrder";

/** The shape every list this sorts has: a row with a name on it. */
function named(...names: string[]): { name: string }[] {
  return names.map((name) => ({ name }));
}

function order(names: string[], locale: Locale = Locale.en): string[] {
  return sortByName(named(...names), locale).map((row) => row.name);
}

function positionOf(name: string, names: string[]): number {
  return order(names).indexOf(name);
}

describe("sortByName", () => {
  it("files an accented name with its base letter", () => {
    // The issue, in one line. Both orderings the database can offer return
    // ['apple', 'Banana', 'Zebra', 'Ästhetik'], because U+00C4 is above every
    // ASCII letter: `order by lower(name)` and `order by name collate nocase`
    // were measured returning exactly that against the deployment's own data.
    const names = ["Zebra", "apple", "Banana", "Ästhetik"];
    expect(positionOf("Ästhetik", names)).toBeLessThan(
      positionOf("Banana", names),
    );
    expect(positionOf("Ästhetik", names)).toBeLessThan(
      positionOf("Zebra", names),
    );
  });

  it("files every accent this app is likely to meet with its base letter", () => {
    // One assertion per language a shelf of books is written in, rather than
    // one for German: the fix is a collation, and a collation that only fixed
    // the umlaut would be a fold with extra steps.
    const names = ["Zebra", "Émile", "Œuvres", "Ångström", "Ästhetik", "apple"];
    for (const accented of ["Émile", "Œuvres", "Ångström", "Ästhetik"]) {
      expect(positionOf(accented, names)).toBeLessThan(
        positionOf("Zebra", names),
      );
    }
  });

  it("leaves the plain ASCII ordering alone", () => {
    expect(order(["Zola", "apple", "Banana"])).toEqual([
      "apple",
      "Banana",
      "Zola",
    ]);
  });

  it("does not order by case", () => {
    // The other half of what a codepoint sort gets wrong, and the half a case
    // fold does fix: `Array.prototype.sort` puts every capital before every
    // lowercase letter, so "Zebra" lands above "apple".
    expect(order(["Zebra", "apple"])).toEqual(["apple", "Zebra"]);
  });

  it("keeps two spellings that differ only in case as two entries", () => {
    // `sensitivity: "base"` would call these equal, and a picker would then
    // show one of them at a position nothing in the data decides.
    expect(order(["Fiction", "fiction"])).toHaveLength(2);
  });

  it("orders the same way in both languages this app speaks", () => {
    // German standard collation (DIN 5007-1) and English both file Ä with A.
    // Worth pinning because the alternative German ordering, the phone book
    // one, files it as "ae", and a reader who noticed that would otherwise
    // have to read the collator to find out which this app uses.
    const names = ["Zebra", "Ästhetik", "apple"];
    expect(order(names, Locale.de)).toEqual(order(names, Locale.en));
  });

  it("does not touch the array it was given", () => {
    // Every caller passes a query cache entry, and `sort` mutates in place.
    const rows = named("Zebra", "apple");
    sortByName(rows, Locale.en);
    expect(rows.map((row) => row.name)).toEqual(["Zebra", "apple"]);
  });

  it("sorts an empty list", () => {
    expect(order([])).toEqual([]);
  });
});
