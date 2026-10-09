/**
 * Tests for src/pages/SettingsPage/types.ts.
 *
 * The table two files are written against: the index page draws it, and
 * `app/routes.tsx` mounts a component at each of its paths. Nothing in the type
 * system connects those two, so a route added to one and not the other is a
 * link to the 404 page, or a screen nothing reaches. That is what this file
 * checks, by reading the route table's source rather than by trusting it.
 */

import { describe, expect, it } from "vitest";

import { SETTINGS_ROUTES } from "../../../src/pages/SettingsPage/types";
import { en } from "../../../src/i18n/en";

const TYPES = import.meta.glob("../../../src/pages/SettingsPage/types.ts", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** The route table's own source, for the counts its comment states. */
const TYPES_SOURCE = Object.values(TYPES)[0] ?? "";

/** The number words the comment is allowed to use, up to a size nobody wants. */
/** Sentence case, for a count that opens a sentence in that comment. */
function capitalised(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

const WORDS = [
  "zero",
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "nine",
  "ten",
  "eleven",
  "twelve",
];

const ROUTES = import.meta.glob("../../../src/app/routes.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** The route table, as source. One file, so the lookup is not by name. */
const ROUTES_SOURCE = Object.values(ROUTES)[0] ?? "";

describe("SETTINGS_ROUTES", () => {
  it("is the eight the owner settled on", () => {
    // Settled 2026-08-27: definitely fewer and larger groupings, and About its
    // own. Asserted whole, so moving a group is a deliberate edit to this list.
    // "Your account" arrived with `users.email` (issue #80): the member's own
    // address fits none of the six, Appearance being what the app looks like
    // and Data and accounts being admin only.
    expect(SETTINGS_ROUTES.map((route) => route.path)).toEqual([
      "/settings/appearance",
      "/settings/account",
      "/settings/catalogue",
      "/settings/library",
      "/settings/public",
      "/settings/lending",
      "/settings/data",
      "/settings/about",
    ]);
  });

  it("names a message key that exists, twice per route", () => {
    // `MessageKey` already makes a typo a compile error. What it cannot catch
    // is a key deleted from the catalogue while the table still names it,
    // because `en` is the type's own source.
    for (const route of SETTINGS_ROUTES) {
      expect(en[route.title]).toBeTruthy();
      expect(en[route.summary]).toBeTruthy();
    }
  });

  it("has a route mounted at every path it lists", () => {
    // Read from the router's source, because the alternative is rendering the
    // whole app six times to find out that one link goes to the 404 page.
    expect(ROUTES_SOURCE).not.toBe("");
    for (const route of SETTINGS_ROUTES) {
      expect(ROUTES_SOURCE).toContain(`path="${route.path}"`);
    }
  });

  it("marks exactly the four routes whose whole body is admin only", () => {
    // `CatalogueSettingsPage`, `PublicCatalogueSettingsPage`,
    // `LendingSettingsPage` and `DataSettingsPage` render everything they have
    // inside `AdminSettings`, so a member who follows one of those links gets a
    // sentence and nothing else. The other four hold something for every member: Appearance has the per device
    // language, Your account is the member's own address, Your library is open
    // to any member by design, and About is the same screen for everybody.
    //
    // Asserted whole, because the failure this prevents is silent: a route
    // that becomes admin only without gaining the flag is a dead end the index
    // advertises with a sentence promising content.
    expect(
      SETTINGS_ROUTES.filter((route) => route.adminOnly).map(
        (route) => route.path,
      ),
    ).toEqual([
      "/settings/catalogue",
      "/settings/public",
      "/settings/lending",
      "/settings/data",
    ]);
  });

  it("states its own size correctly in its own comment", () => {
    // Three sentences in that comment carry a count, and two of them were
    // stale within one evening: two changes each added a route and each
    // corrected a different one. A number written in prose does not recount
    // itself, so this recounts it.
    expect(TYPES_SOURCE).not.toBe("");
    const total = WORDS[SETTINGS_ROUTES.length] ?? "";
    const admin =
      WORDS[SETTINGS_ROUTES.filter((r) => r.adminOnly).length] ?? "";
    // A count past the end of WORDS would make every assertion below search
    // for the empty string, which every source contains.
    expect(total).not.toBe("");
    expect(admin).not.toBe("");

    expect(TYPES_SOURCE).toContain(`The ${total} settings routes, as data.`);
    expect(TYPES_SOURCE).toContain(
      `**${capitalised(admin)} routes hold nothing for a member who is not an admin**`,
    );
    expect(TYPES_SOURCE).toContain(`${total} links with no such mark`);
    expect(TYPES_SOURCE).toContain(`would turn one refusal into ${admin}`);
  });

  it("gives every route its own path and its own icon", () => {
    // Two entries sharing a path is a link that lands somewhere else; two
    // sharing an icon is an index a reader cannot scan by shape.
    const paths = SETTINGS_ROUTES.map((route) => route.path);
    const icons = SETTINGS_ROUTES.map((route) => route.icon);

    expect(new Set(paths).size).toBe(paths.length);
    expect(new Set(icons).size).toBe(icons.length);
  });
});
