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

const ROUTES = import.meta.glob("../../../src/app/routes.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** The route table, as source. One file, so the lookup is not by name. */
const ROUTES_SOURCE = Object.values(ROUTES)[0] ?? "";

describe("SETTINGS_ROUTES", () => {
  it("is the six the owner settled on", () => {
    // Settled 2026-08-27: definitely fewer and larger groupings, and About its
    // own. Asserted whole, so moving a group is a deliberate edit to this list.
    expect(SETTINGS_ROUTES.map((route) => route.path)).toEqual([
      "/settings/appearance",
      "/settings/catalogue",
      "/settings/library",
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

  it("marks exactly the three routes whose whole body is admin only", () => {
    // `CatalogueSettingsPage`, `LendingSettingsPage` and `DataSettingsPage`
    // render everything they have inside `AdminSettings`, so a member who
    // follows one of those links gets a sentence and nothing else. The other
    // three hold something for every member: Appearance has the per device
    // language, Your library is open to any member by design, and About is the
    // same screen for everybody.
    //
    // Asserted whole, because the failure this prevents is silent: a route
    // that becomes admin only without gaining the flag is a dead end the index
    // advertises with a sentence promising content.
    expect(
      SETTINGS_ROUTES.filter((route) => route.adminOnly).map(
        (route) => route.path,
      ),
    ).toEqual(["/settings/catalogue", "/settings/lending", "/settings/data"]);
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
