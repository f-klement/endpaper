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
      expect(pattern.body).toContain("{color}");
      expect(pattern.body).not.toMatch(/#[0-9a-f]{3,6}/i);
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

  it("is fainter in dark, where the same strength would glare", () => {
    const opacity = (uri: string) =>
      Number(decodeURIComponent(uri).match(/opacity="([\d.]+)"/)![1]);

    expect(opacity(patternDataUri(PATTERNS[0]!, "dark"))).toBeLessThan(
      opacity(patternDataUri(PATTERNS[0]!, "light")),
    );
  });

  it("tiles at the pattern's own size", () => {
    const uri = decodeURIComponent(patternDataUri(PATTERNS[0]!, "light"));
    expect(uri).toContain(`width="${PATTERNS[0]!.size}"`);
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
