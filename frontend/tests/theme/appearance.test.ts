/** Tests for src/theme/appearance.ts. */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_APPEARANCE,
  DOOR_APPEARANCE,
  cacheAppearance,
  readCachedAppearance,
  resolveAppearance,
  sameAppearance,
  type Appearance,
} from "../../src/theme/appearance";
import { isPaletteId } from "../../src/theme/palettes";

/**
 * A palette id this build does not have, and no build ever will.
 *
 * It used to be "kanagawa", which was a fine sentinel until Kanagawa shipped as
 * a real palette and this test failed on its own premise rather than on the
 * behaviour it names. A sentinel is only a sentinel while it stays unreal, so
 * the premise is asserted below rather than assumed: adding a palette can no
 * longer break this test without saying which half broke.
 */
const NOT_A_PALETTE = "no such palette";

const GRUVBOX: Appearance = {
  palette: "gruvbox",
  mode: "dark",
  wallpaper: "willow",
};

beforeEach(() => {
  localStorage.clear();
});

describe("resolveAppearance", () => {
  it("takes a whole appearance as it stands", () => {
    expect(resolveAppearance(GRUVBOX)).toEqual(GRUVBOX);
  });

  it("falls back for a palette this build does not have", () => {
    // Not an error: an older build has to be able to render a newer one's
    // stored choice, and the reader gets the house palette rather than an
    // unstyled page. It is a read that degrades, not a round trip that
    // preserves: the next change this client makes writes the default back.
    expect(isPaletteId(NOT_A_PALETTE)).toBe(false);
    expect(
      resolveAppearance({ ...GRUVBOX, palette: NOT_A_PALETTE }).palette,
    ).toBe("endpaper");
  });

  it("falls back for a mode that is not one of the three", () => {
    expect(resolveAppearance({ mode: "sepia" }).mode).toBe("system");
  });

  it("reads nothing out of nothing", () => {
    expect(resolveAppearance(null)).toEqual(DEFAULT_APPEARANCE);
    expect(resolveAppearance(undefined)).toEqual(DEFAULT_APPEARANCE);
  });

  it("keeps a wallpaper it cannot check", () => {
    // Which patterns exist is not this module's business, and a value it
    // dropped here would be pushed back to the server as a cleared preference.
    expect(resolveAppearance({ wallpaper: "hollyhock" }).wallpaper).toBe(
      "hollyhock",
    );
  });
});

describe("the cache", () => {
  it("gives back what was stored for an account", () => {
    cacheAppearance(3, GRUVBOX);
    expect(readCachedAppearance(3)).toEqual(GRUVBOX);
  });

  it("keeps two accounts apart", () => {
    // A library shares devices, and one member's dark Gruvbox is not the
    // other's. Keyed per account is the whole reason this is not one value.
    cacheAppearance(3, GRUVBOX);
    cacheAppearance(4, { palette: "nord", mode: "light", wallpaper: null });

    expect(readCachedAppearance(3).palette).toBe("gruvbox");
    expect(readCachedAppearance(4).palette).toBe("nord");
  });

  it("paints the login screen with whoever was here last", () => {
    cacheAppearance(3, GRUVBOX);
    cacheAppearance(4, { palette: "nord", mode: "light", wallpaper: null });

    expect(readCachedAppearance().palette).toBe("nord");
  });

  it("shows the front door when this device has never signed anybody in", () => {
    // Not the new-account default, which is Surprise me. The login screen is
    // fixed: a door that is a different pattern every visit reads as a slot
    // machine rather than as a house.
    expect(readCachedAppearance()).toEqual(DOOR_APPEARANCE);
    expect(DOOR_APPEARANCE.wallpaper).toBe("willow");
  });

  it("keeps Surprise me for an account that has not chosen", () => {
    // The other half of the same rule. Asking for an account is what tells the
    // two fallbacks apart, so no caller has to know which is which.
    expect(readCachedAppearance(99).wallpaper).toBeNull();
  });

  it("defaults for an account this device has not seen", () => {
    cacheAppearance(3, GRUVBOX);
    expect(readCachedAppearance(99)).toEqual(DEFAULT_APPEARANCE);
  });

  it("carries over a mode stored by the version before this one", () => {
    // The preference used to be a bare string under `theme`, per device. Read
    // once as a fallback so nobody's dark mode is forgotten by an upgrade.
    localStorage.setItem("theme", "dark");
    expect(readCachedAppearance()).toEqual({
      ...DOOR_APPEARANCE,
      mode: "dark",
    });
  });

  it("prefers the account's own record over the old device one", () => {
    localStorage.setItem("theme", "light");
    cacheAppearance(3, GRUVBOX);

    expect(readCachedAppearance(3).mode).toBe("dark");
  });

  it("survives a half-written entry", () => {
    // A corrupt value would otherwise throw during the very first render,
    // before React exists, and white-screen the app with no way back short of
    // clearing site data by hand.
    localStorage.setItem("appearance", "{not json");
    expect(readCachedAppearance()).toEqual(DOOR_APPEARANCE);
  });

  it("survives storage that refuses to be written", () => {
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("QuotaExceededError");
      });

    expect(() => cacheAppearance(3, GRUVBOX)).not.toThrow();
    setItem.mockRestore();
  });
});

describe("sameAppearance", () => {
  it("compares the three fields and nothing else", () => {
    expect(sameAppearance(GRUVBOX, { ...GRUVBOX })).toBe(true);
    expect(sameAppearance(GRUVBOX, { ...GRUVBOX, mode: "light" })).toBe(false);
    expect(sameAppearance(GRUVBOX, { ...GRUVBOX, wallpaper: null })).toBe(
      false,
    );
  });
});
