/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom. Building one costs more than this file
 * spends running: measured across the suite, `environment` was 168s of a 245s
 * run, paid once per file.
 */
/** Tests for src/theme/oklab.ts. */

import { describe, expect, it } from "vitest";

import {
  lightness,
  markWeight,
  parseHex,
  solveAlpha,
} from "../../src/theme/oklab";

describe("parseHex", () => {
  it("reads a six digit hex", () => {
    expect(parseHex("#0f766e")).toEqual([15, 118, 110]);
  });

  it("expands a three digit hex", () => {
    expect(parseHex("#fb0")).toEqual([255, 187, 0]);
  });

  it("ignores the surrounding whitespace a custom property comes with", () => {
    // `getPropertyValue` returns the declaration's text, leading space and all.
    expect(parseHex("  #fbfaf8 ")).toEqual([251, 250, 248]);
  });

  it("refuses a form carrying alpha", () => {
    // Truncating `#0f766e80` to its opaque part would silently paint a mark at
    // twice the weight the token asked for.
    expect(parseHex("#0f766e80")).toBeNull();
    expect(parseHex("#0f76")).toBeNull();
  });

  it("refuses anything that is not a hex at all", () => {
    expect(parseHex("")).toBeNull();
    expect(parseHex("teal")).toBeNull();
    expect(parseHex("var(--color-accent-700)")).toBeNull();
  });
});

describe("lightness", () => {
  it("puts black at zero and white at one", () => {
    expect(lightness([0, 0, 0])).toBeCloseTo(0, 6);
    expect(lightness([255, 255, 255])).toBeCloseTo(1, 6);
  });

  it("puts mid grey near the perceptual middle", () => {
    // The whole reason for OKLab over relative luminance: sRGB 128 is 0.216 of
    // the light and about 0.60 of the perceived lightness. A budget stated in
    // luminance would call this ground a fifth as bright as white.
    expect(lightness([128, 128, 128])).toBeCloseTo(0.5998, 3);
  });

  it("separates two colours a contrast ratio cannot", () => {
    // A ratio is dominated by the lighter of its pair, so a saturated blue and
    // a saturated yellow of the same luminance share one. Their lightnesses do
    // not, which is what makes this the right instrument for "how far does this
    // mark move the page".
    expect(lightness([0, 0, 255])).toBeLessThan(lightness([255, 200, 0]));
  });
});

/**
 * Endpaper's two pages and the ink drawn on each, as `src/index.css` states
 * them: `paper-50` with `accent-700`, and `paper-950` with `accent-300`.
 *
 * Written out rather than read, because this module knows nothing about
 * palettes and these are here as a pair of real colours to measure. The dark
 * page was `#1a1816` and that is not a colour this project ships: it is 27%
 * lighter than `paper-950`, so every number measured against it was measured
 * against nothing.
 */
const PAGE: [number, number, number] = [251, 250, 248];
const INK: [number, number, number] = [15, 118, 110];
const DARK_PAGE: [number, number, number] = [16, 14, 12];
const DARK_INK: [number, number, number] = [113, 216, 193];

describe("markWeight", () => {
  it("moves nothing at zero alpha", () => {
    expect(markWeight(INK, PAGE, 0)).toBe(0);
  });

  it("moves further the more opaque the mark is", () => {
    const weights = [0.05, 0.1, 0.2, 0.4].map((a) => markWeight(INK, PAGE, a));
    expect(weights).toEqual([...weights].sort((a, b) => a - b));
  });

  it("composites in gamma encoded sRGB, not in linear light", () => {
    // What the compositor does, so the solve has to do the same. This pairing
    // measures 0.0715 blended in sRGB and 0.0443 blended in linear light, so a
    // solve done the principled way would ship the light wallpaper at 1.61x the
    // weight it asked for. The dark page is worse and in the other direction:
    // `accent-300` on `paper-950` is 0.1145 against 0.2737, a factor of 2.39.
    expect(markWeight(INK, PAGE, 0.15)).toBeCloseTo(0.0715, 4);
    expect(markWeight(DARK_INK, DARK_PAGE, 0.15)).toBeCloseTo(0.1145, 4);
  });
});

describe("solveAlpha", () => {
  it("lands on the weight it was asked for", () => {
    const ink: [number, number, number] = [15, 118, 110];
    const alpha = solveAlpha(ink, PAGE, 0.026);
    expect(markWeight(ink, PAGE, alpha)).toBeCloseTo(0.026, 5);
  });

  it("asks a dimmer ink for more alpha to reach the same weight", () => {
    // The finding this module exists for. Two palettes' ink at one alpha are
    // two different weights on the page; at one weight they are two alphas.
    const strong = solveAlpha([15, 118, 110], PAGE, 0.026);
    const faint = solveAlpha([160, 200, 195], PAGE, 0.026);
    expect(faint).toBeGreaterThan(strong);
  });

  it("works upward from a dark page as well as down from a light one", () => {
    // The ground weight the dark mode asks for, on the page it asks for it on.
    // 0.0782 is what Endpaper's dark wallpaper is drawn at.
    const alpha = solveAlpha(DARK_INK, DARK_PAGE, 0.061);
    expect(alpha).toBeCloseTo(0.0782, 4);
    expect(markWeight(DARK_INK, DARK_PAGE, alpha)).toBeCloseTo(0.061, 5);
  });

  it("gives up rather than looping when the ink cannot reach the target", () => {
    // An ink nearly the colour of its own page. Opaque is as far as it goes,
    // and the honest answer is 1 rather than an alpha that does not exist.
    expect(solveAlpha([250, 249, 247], PAGE, 0.5)).toBe(1);
  });
});
