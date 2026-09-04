/**
 * @vitest-environment node
 *
 * Touches no DOM.
 */
/** Tests for src/lib/catalogueName.ts. */

import { describe, expect, it } from "vitest";

import { CatalogueSource } from "../../src/api/generated/model";
import { en } from "../../src/i18n/en";
import { catalogueName } from "../../src/lib/catalogueName";

/**
 * Every catalogue the API can send, read off the generated client.
 *
 * **Not off the message catalogue, which is what the first version did and is
 * circular.** It filtered `Object.keys(en)` on the `providers.name.` prefix,
 * which makes the catalogue both the subject and the oracle: a source the
 * server can send and nobody wrote a message for is absent from that list, so
 * the sweep never asks about it and the guard cannot see the one omission it
 * exists to catch. A security critic found it.
 *
 * `CatalogueSource` is a runtime const in the generated client, regenerated
 * from the backend enum, so this list moves when the roster does and the day a
 * source joins with no name the test goes red rather than quiet.
 */
const ON_THE_ROSTER = Object.values(CatalogueSource);

describe("a catalogue's name", () => {
  it("resolves to a real message for every source the API can send", () => {
    expect(ON_THE_ROSTER.length).toBeGreaterThan(0);
    for (const source of ON_THE_ROSTER) {
      expect(en[catalogueName(source)]).toBeTruthy();
    }
  });

  it("is not the key itself, which is what a wrong prefix would give", () => {
    for (const source of ON_THE_ROSTER) {
      expect(en[catalogueName(source)]).not.toContain("providers.name.");
    }
  });

  it("has a name for every source and no names for sources that do not exist", () => {
    // The other direction, so a catalogue removed from the roster leaves no
    // orphan message behind claiming a source this build cannot ask.
    const named = Object.keys(en)
      .filter((key) => key.startsWith("providers.name."))
      .map((key) => key.slice("providers.name.".length));

    expect(new Set(named)).toEqual(new Set<string>(ON_THE_ROSTER));
  });
});
