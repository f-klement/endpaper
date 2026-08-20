/** Tests for src/theme/patterns.ts. */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PATTERNS,
  patternDataUri,
  randomPattern,
} from "../../src/theme/patterns";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PATTERNS", () => {
  it("has several to choose between", () => {
    // One would make "a different one each visit" a lie.
    expect(PATTERNS.length).toBeGreaterThan(1);
  });

  it("gives each a unique id", () => {
    const ids = PATTERNS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("leaves every colour to the theme", () => {
    // A hard-coded colour would look wrong in one mode or the other.
    for (const pattern of PATTERNS) {
      expect(pattern.ground).toContain("{ink}");
      expect(pattern.foliage).toContain("{bloom}");
      expect(pattern.ground + pattern.foliage).not.toMatch(/#[0-9a-f]{3,6}/i);
    }
  });

  it("gives every design both layers", () => {
    // One flat weight is what turns an arabesque into a scatter of shapes.
    for (const pattern of PATTERNS) {
      expect(pattern.ground.length).toBeGreaterThan(0);
      expect(pattern.foliage.length).toBeGreaterThan(0);
    }
  });

  it("grows enough foliage to read as a repeat rather than a lattice", () => {
    // The first version placed a couple of dozen shapes per tile and came out
    // looking like a trellis with stickers on it.
    for (const pattern of PATTERNS) {
      const motifs = pattern.foliage.match(/<path /g) ?? [];
      expect(motifs.length).toBeGreaterThan(30);
    }
  });

  it("puts the foliage on the stems", () => {
    // Every grown motif is rotated onto its branch's tangent. A run of them
    // with no rotation would be pointing wherever it was typed.
    for (const pattern of PATTERNS) {
      expect(pattern.foliage).toContain("rotate(");
    }
  });
});

describe("patternDataUri", () => {
  it("produces an inline svg", () => {
    const uri = patternDataUri(PATTERNS[0]!, "light");
    expect(uri).toMatch(/^url\("data:image\/svg\+xml,/);
  });

  it("substitutes every colour placeholder", () => {
    const uri = patternDataUri(PATTERNS[0]!, "light");
    expect(decodeURIComponent(uri)).not.toContain("{color}");
  });

  it("uses a different ink for each theme", () => {
    const light = patternDataUri(PATTERNS[0]!, "light");
    const dark = patternDataUri(PATTERNS[0]!, "dark");
    expect(light).not.toBe(dark);
  });

  it("is stronger in dark, where the same strength disappears", () => {
    // This assertion was the other way round once, on the reasoning that a
    // light ink on near-black glares. That holds for a solid fill and not for
    // this: the tile is mostly negative space, so at parity the pattern was
    // invisible on #030712 and the dark theme had no texture at all. Measured
    // against the real page background, not reasoned about twice.
    const opacity = (uri: string) =>
      Number(decodeURIComponent(uri).match(/opacity="([\d.]+)"/)![1]);

    expect(opacity(patternDataUri(PATTERNS[0]!, "dark"))).toBeGreaterThan(
      opacity(patternDataUri(PATTERNS[0]!, "light")),
    );
  });

  it("keeps both layers subtle enough to stay behind the content", () => {
    // The ceiling is what stops "make it visible" turning into a page that
    // competes with a book cover.
    for (const theme of ["light", "dark"] as const) {
      const opacities = [
        ...decodeURIComponent(patternDataUri(PATTERNS[0]!, theme)).matchAll(
          /<g opacity="([\d.]+)"/g,
        ),
      ].map((match) => Number(match[1]));
      for (const value of opacities) {
        expect(value).toBeLessThan(0.15);
      }
    }
  });

  it("tiles at the pattern's own size", () => {
    const uri = decodeURIComponent(patternDataUri(PATTERNS[0]!, "light"));
    expect(uri).toContain(`width="${PATTERNS[0]!.size}"`);
  });

  it("draws each layer at its own strength", () => {
    // The gap between them is what reads as depth. Equal weights would flatten
    // the pattern back into a single plane of shapes.
    const uri = decodeURIComponent(patternDataUri(PATTERNS[0]!, "light"));
    const opacities = [...uri.matchAll(/<g opacity="([\d.]+)"/g)].map((m) =>
      Number(m[1]),
    );
    expect(opacities).toHaveLength(2);
    expect(opacities[0]).toBeLessThan(opacities[1]!);
  });

  it("draws the tile surrounded by its own neighbours", () => {
    // Nine copies, so a motif running off one edge reappears on the opposite
    // one and the repeat has no seam. Without it every shape would have to be
    // kept clear of the edges.
    const uri = decodeURIComponent(patternDataUri(PATTERNS[0]!, "light"));
    const size = PATTERNS[0]!.size;
    expect(uri).toContain(`x="${-size}"`);
    expect(uri).toContain(`x="${size}"`);
    expect((uri.match(/<use /g) ?? []).length).toBe(18);
  });

  it("stays small enough to be worth inlining", () => {
    // The whole reason these are drawn rather than shipped as images.
    for (const pattern of PATTERNS) {
      expect(patternDataUri(pattern, "light").length).toBeLessThan(40_000);
    }
  });
});

describe("randomPattern", () => {
  it("returns one of the set", () => {
    expect(PATTERNS).toContain(randomPattern());
  });

  it("can return the last one", () => {
    // An off-by-one in the index would make one pattern unreachable forever.
    vi.spyOn(Math, "random").mockReturnValue(0.999999);
    expect(randomPattern()).toBe(PATTERNS[PATTERNS.length - 1]);
  });

  it("can return the first one", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(randomPattern()).toBe(PATTERNS[0]);
  });
});
