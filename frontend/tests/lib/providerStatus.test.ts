/**
 * @vitest-environment node
 *
 * Touches no DOM. Building one costs more than this file spends running.
 */
/**
 * Tests for src/lib/providerStatus.ts.
 *
 * **The sweep is the point of the file.** Two rounds running, the defect was an
 * arm that names registration groups being reached without consulting the field
 * that says whether the remit is applied, and both times it was found by
 * measuring one plan rather than by reading the chain. A test over every
 * combination of the fields cannot miss the third one.
 */

import { describe, expect, it } from "vitest";

import type { CatalogueSourceOut } from "../../src/api/generated/model";
import { en, type MessageKey } from "../../src/i18n/en";
import { isFiltered, statusOf } from "../../src/lib/providerStatus";

/**
 * Every message that **interpolates** the registration groups, found rather than
 * listed.
 *
 * **Derived from the catalogue, so a new one is covered the day it is written.**
 * A hand written list of two keys is the "enumerates something open" shape, and
 * this rule already grew from one such message to two in a single round.
 *
 * **Interpolates, not names, and the word is the whole reach of this guard.**
 * What it finds is every message that can *carry* the data, because the
 * placeholder is what it matches. A message spelling a group into its own text,
 * "only for Greek ISBNs, 978-960", names the groups and is **invisible here**,
 * so the sweep below would not hold it to the invariant. Write a new one with
 * `{groups}` and it is covered; hard code a group and nothing catches it.
 *
 * Said rather than left to be found, because a comment claiming a reach wider
 * than its evidence is the defect this whole ticket has spent the night
 * closing, and this guard was written to stop that class.
 */
const INTERPOLATES_THE_GROUPS: ReadonlySet<MessageKey> = new Set(
  (Object.keys(en) as MessageKey[]).filter((key) =>
    en[key].includes("{groups}"),
  ),
);

const FLAGS = [
  "enabled",
  "answers_lookup",
  "answers_search",
  "asked_first",
  "needs_a_key",
  "has_key",
  "ready",
] as const;

/** Every row the wire can carry, at the granularity this module reads. */
function everyRow(): CatalogueSourceOut[] {
  const rows: CatalogueSourceOut[] = [];
  for (let bits = 0; bits < 1 << FLAGS.length; bits += 1) {
    for (const serves_groups of [[], ["978-960", "978-618"]]) {
      const row = {
        source: "nlg",
        serves_groups,
      } as unknown as CatalogueSourceOut;
      FLAGS.forEach((flag, index) => {
        (row as unknown as Record<string, boolean>)[flag] =
          (bits & (1 << index)) !== 0;
      });
      rows.push(row);
    }
  }
  return rows;
}

describe("the line under a catalogue", () => {
  it("names groups only where the remit actually narrows what is asked", () => {
    // **The invariant, over the whole field space.** `serves_groups` is the
    // remit declared, not the filter applied: the leading tier is asked about
    // every ISBN whatever a source's remit, so a promoted catalogue carries a
    // populated remit and is asked about everything. A line naming its groups
    // there is the screen promising what the server does not do.
    //
    // **The name states the invariant and the loop covers the messages that
    // interpolate it.** Those are the same set today and need not stay so; the
    // gap and what closes it are in `INTERPOLATES_THE_GROUPS`.
    for (const row of everyRow()) {
      if (INTERPOLATES_THE_GROUPS.has(statusOf(row))) {
        expect(isFiltered(row), JSON.stringify(row)).toBe(true);
      }
    }
  });

  it("reaches every interpolating message at least once", () => {
    // Anti vacuity. The assertion above passes on a `statusOf` that never
    // returns one of these at all, which is exactly what a fourth condition
    // added to the wrong branch would produce.
    const reached = new Set(
      everyRow()
        .map(statusOf)
        .filter((key) => INTERPOLATES_THE_GROUPS.has(key)),
    );
    expect(INTERPOLATES_THE_GROUPS.size).toBeGreaterThanOrEqual(2);
    expect(reached).toEqual(INTERPOLATES_THE_GROUPS);
  });

  it("says a promoted lookup only catalogue is asked on every scan", () => {
    // **The row that was wrong, and it is reachable rather than theoretical: a
    // plan of `nkp, k10plus, dnb` gives the Czech National Library
    // `asked_first: true, answers_search: false`.** Give it a remit, which is
    // the future the combined message exists for, and the screen claimed it
    // answers only for Czech ISBNs while it sat in a tier nothing filters.
    expect(
      statusOf(
        row({
          answers_search: false,
          asked_first: true,
          serves_groups: ["978-80"],
        }),
      ),
    ).toBe("providers.status.lookupOnly");
  });

  it("says a lookup only catalogue below the tier is regional", () => {
    // The other half, or the fix above is indistinguishable from deleting the
    // combined message.
    expect(
      statusOf(
        row({
          answers_search: false,
          asked_first: false,
          serves_groups: ["978-80"],
        }),
      ),
    ).toBe("providers.status.lookupOnlyRegional");
  });

  it("says a promoted regional catalogue is asked on every scan", () => {
    // The same defect on the other group naming arm, which was correct only
    // because of where it sat in the chain.
    expect(statusOf(row({ asked_first: true, serves_groups: ["978-3"] }))).toBe(
      "providers.status.askedFirst",
    );
  });

  it("does not call a switched off catalogue regional", () => {
    expect(statusOf(row({ enabled: false, serves_groups: ["978-3"] }))).toBe(
      "providers.status.off",
    );
  });
});

function row(over: Partial<CatalogueSourceOut>): CatalogueSourceOut {
  return {
    source: "nlg",
    enabled: true,
    answers_lookup: true,
    answers_search: true,
    asked_first: false,
    needs_a_key: false,
    has_key: true,
    ready: true,
    serves_groups: [],
    ...over,
  } as CatalogueSourceOut;
}
