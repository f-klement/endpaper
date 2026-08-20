/** Tests for src/theme/patterns.ts. */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PATTERNS,
  measure,
  patternDataUri,
  randomPattern,
  wallpaperInk,
  type Branch,
  type Layer,
  type Pattern,
  type Point,
} from "../../src/theme/patterns";

/**
 * A stated ink, rather than the document's.
 *
 * `patternDataUri` is pure and takes its two colours as an argument precisely so
 * a test can say what they are: the tokens it would otherwise read live in a
 * stylesheet, and the suite deliberately does not load one.
 */
const INK = { ink: "#0f766e", bloom: "#9f1239" };

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.style.cssText = "";
});

/** Every mark a layer draws, whether it is a shape or a reference to one. */
function marks(layer: Layer): number {
  return (layer.body.match(/<(use|path) /g) ?? []).length;
}

// ── Ink coverage ─────────────────────────────────────────────────────────────
//
// The area of every shape a tile draws, over the area of the tile, times the
// opacity of the layer it is on. It is the only measure that says how heavy a
// wallpaper actually is: a count of motifs cannot tell a leaf from a hairline,
// and a byte count cannot tell either from a comment.

function flatten(d: string): Point[] {
  const tokens = d.match(/[MCQZ]|-?\d*\.?\d+/g) ?? [];
  const points: Point[] = [];
  let cursor: Point = [0, 0];
  let index = 0;
  const next = () => Number(tokens[index++]);
  const curve = (controls: Point[]) => {
    const all = [cursor, ...controls];
    for (let step = 1; step <= 8; step += 1) points.push(deCasteljau(all, step / 8));
    cursor = all[all.length - 1]!;
  };

  while (index < tokens.length) {
    const command = tokens[index++];
    if (command === "M") {
      cursor = [next(), next()];
      points.push(cursor);
    } else if (command === "C") {
      curve([[next(), next()], [next(), next()], [next(), next()]]);
    } else if (command === "Q") {
      curve([[next(), next()], [next(), next()]]);
    } else if (command === "Z") {
      if (points[0]) points.push(points[0]);
    } else {
      // A new command would measure as nothing at all and quietly shrink the
      // reported coverage, so it fails here instead.
      throw new Error(`flatten does not handle "${command}"`);
    }
  }
  return points;
}

function deCasteljau(control: Point[], t: number): Point {
  let current = control;
  while (current.length > 1) {
    const next: Point[] = [];
    for (let i = 0; i + 1 < current.length; i += 1) {
      const a = current[i]!;
      const b = current[i + 1]!;
      next.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
    current = next;
  }
  return current[0]!;
}

function polygonArea(points: Point[]): number {
  let total = 0;
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i]!;
    const b = points[(i + 1) % points.length]!;
    total += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(total) / 2;
}

function polylineLength(points: Point[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    total += Math.hypot(
      points[i]![0] - points[i - 1]![0],
      points[i]![1] - points[i - 1]![1],
    );
  }
  return total;
}

function motifShapes(pattern: Pattern): Map<string, string> {
  const shapes = new Map<string, string>();
  for (const [, id, d] of pattern.defs.matchAll(
    /<path id="([^"]+)" d="([^"]+)"\/>/g,
  )) {
    shapes.set(id!, d!);
  }
  return shapes;
}

/** Ink area over tile area, as a fraction, before the layer's opacity. */
function coverage(pattern: Pattern, layer: Layer): number {
  const shapes = motifShapes(pattern);
  let ink = 0;

  for (const [, id, transform] of layer.body.matchAll(
    /<use href="#([^"]+)" transform="([^"]*)"/g,
  )) {
    const scale = Number(/scale\(([-\d.]+)\)/.exec(transform!)?.[1] ?? 1);
    ink += polygonArea(flatten(shapes.get(id!)!)) * scale * scale;
  }

  // Stroked stems: length times width, since a stem has no enclosed area.
  for (const [, width, group] of layer.body.matchAll(
    /stroke-width="([\d.]+)"[^>]*>((?:<path d="[^"]+"\/>)+)/g,
  )) {
    for (const [, d] of group!.matchAll(/<path d="([^"]+)"\/>/g)) {
      ink += polylineLength(flatten(d!)) * Number(width);
    }
  }

  return ink / (pattern.size * pattern.size);
}

/** Coverage times opacity, summed over the layers: the tile's mean ink alpha. */
function meanAlpha(pattern: Pattern, uri: string): number {
  const opacities = layerOpacities(uri);
  return pattern.layers.reduce(
    (total, layer, index) => total + coverage(pattern, layer) * opacities[index]!,
    0,
  );
}

function layerOpacities(uri: string): number[] {
  return [...decodeURIComponent(uri).matchAll(/<g opacity="([\d.]+)"/g)].map(
    (match) => Number(match[1]),
  );
}

describe("PATTERNS", () => {
  it("has several to choose between", () => {
    // One would make "a different one each visit" a lie.
    expect(PATTERNS.length).toBeGreaterThan(1);
  });

  it("gives each a unique id", () => {
    const ids = PATTERNS.map((pattern) => pattern.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("leaves every colour to the theme", () => {
    // A hard-coded colour would look wrong in one mode or the other, and from
    // seven palettes on it would look wrong in six of them. The hrefs come out
    // first because a reference is not a colour.
    for (const pattern of PATTERNS) {
      const written = [pattern.defs, ...pattern.layers.map((l) => l.body)]
        .join("")
        .replace(/href="#[^"]*"/g, "");
      expect(written).not.toContain("#");
      for (const layer of pattern.layers) {
        expect(layer.body).toMatch(/\{(ink|bloom)\}/);
      }
    }
  });

  it("draws its ground first and any bloom last", () => {
    // The gap between the weights is what reads as depth. A pattern may leave a
    // weight out, and Acanthus does: it has no flower in it. It may not reorder
    // them or use one twice.
    const order = ["ground", "foliage", "bloom"];
    for (const pattern of PATTERNS) {
      const weights = pattern.layers.map((layer) => layer.weight);
      expect(weights).toContain("ground");
      expect(new Set(weights).size).toBe(weights.length);
      expect(weights).toEqual([...weights].sort(
        (a, b) => order.indexOf(a) - order.indexOf(b),
      ));
    }
  });

  it("grows enough foliage to read as a repeat rather than a lattice", () => {
    // The first version placed a couple of dozen shapes per tile and came out
    // looking like a trellis with stickers on it. Counted as marks rather than
    // as `<path>` elements, because a motif is now a reference to a definition.
    for (const pattern of PATTERNS) {
      const drawn = pattern.layers.reduce((total, layer) => total + marks(layer), 0);
      expect(drawn).toBeGreaterThan(30);
    }
  });

  it("writes each motif once however many times it is placed", () => {
    // The saving is what makes detail affordable: a vein added to a definition
    // is drawn on every instance and paid for once. Inline it would be its
    // ninety bytes times a hundred and twenty six leaves in Willow alone.
    for (const pattern of PATTERNS) {
      const defined = motifShapes(pattern).size;
      const placed = pattern.layers.reduce(
        (total, layer) => total + (layer.body.match(/<use /g) ?? []).length,
        0,
      );
      expect(defined).toBeLessThan(placed / 5);
    }
  });

  it("places nothing it has not defined, and defines nothing it does not place", () => {
    // A dangling href draws nothing at all and reports no error anywhere: the
    // tile simply comes out emptier than it was written.
    for (const pattern of PATTERNS) {
      const defined = new Set(motifShapes(pattern).keys());
      const referenced = new Set(
        [...pattern.layers.flatMap((layer) => [
          ...layer.body.matchAll(/<use href="#([^"]+)"/g),
        ])].map((match) => match[1]!),
      );
      expect([...referenced].filter((id) => !defined.has(id))).toEqual([]);
      expect([...defined].filter((id) => !referenced.has(id))).toEqual([]);
    }
  });

  it("keeps every tile inside the ink budget", () => {
    // What "must stay wallpaper" actually means, measured: the fraction of the
    // page the tile inks, weighted by how strongly each layer is drawn.
    //
    // Light only. The dark weights are the light ones scaled by roughly 1.36
    // across the board (0.0126 to 0.0319), so measuring both would assert the
    // same ordering twice and would not catch anything the first one misses.
    //
    // Measured, light:
    //
    //   willow 0.00905  strawberry 0.01450  pimpernel 0.01513
    //   acanthus 0.01612  lily 0.02394
    //
    // Two things that band records. Lily is 2.65 times the weight of Willow and
    // nothing in the code says so, which is the finding the budget exists for.
    // And splitting the blooms into their own layer, at the agreed 0.10, is what
    // took the spread from 2.18x: strawberry gained 6.0%, pimpernel 10.3% and
    // Lily 21.2%, so the heaviest tile got heavier. The ceiling is Lily plus a
    // little, deliberately: it binds today rather than ratifying the widening.
    //
    // The retune is where those close up, to a mean tile dL of 0.0070 to 0.0092.
    // That is a perceptual lightness delta rather than an alpha, so it is not
    // this number and cannot be compared with it: it is stated here only so the
    // person doing the retune knows the target is not written in these units.
    for (const pattern of PATTERNS) {
      const alpha = meanAlpha(pattern, patternDataUri(pattern, "light", INK));
      expect(alpha).toBeGreaterThan(0.008);
      expect(alpha).toBeLessThan(0.0245);
    }
  });
});

describe("measure", () => {
  /** A cubic whose controls bunch at one end, so the parameter is not the arc. */
  const LOPSIDED: Branch = [
    [
      [0, 0],
      [90, 0],
      [100, 0],
      [100, 0],
    ],
  ];

  it("measures a branch at its own length", () => {
    expect(measure(LOPSIDED).length).toBeCloseTo(100, 1);
  });

  it("gives the same length however the branch is cut into cubics", () => {
    // The reason `spacing` is px rather than a count per cubic: refining a stem
    // must not change how much foliage it carries.
    const whole: Branch = [
      [
        [0, 0],
        [40, 0],
        [60, 0],
        [100, 0],
      ],
    ];
    const halved: Branch = [
      [
        [0, 0],
        [20, 0],
        [30, 0],
        [50, 0],
      ],
      [
        [50, 0],
        [70, 0],
        [80, 0],
        [100, 0],
      ],
    ];
    expect(measure(halved).length).toBeCloseTo(measure(whole).length, 1);
  });

  it("walks the curve at constant speed, not the parameter", () => {
    // On this curve the parameter's own midpoint is at x = 83.75, because the
    // controls bunch at the far end. Sampling there is what made motifs pile up
    // where a curve is slow.
    expect(measure(LOPSIDED).at(50).x).toBeCloseTo(50, 0);
  });

  it("takes the tangent from the segment the distance lands in", () => {
    const bend: Branch = [
      [
        [0, 0],
        [50, 0],
        [100, 0],
        [100, 0],
      ],
      [
        [100, 0],
        [100, 50],
        [100, 100],
        [100, 100],
      ],
    ];
    const arc = measure(bend);
    expect(arc.at(1).angle).toBeCloseTo(0, 0);
    expect(arc.at(arc.length - 1).angle).toBeCloseTo(90, 0);
  });
});

describe("patternDataUri", () => {
  it("produces an inline svg", () => {
    const uri = patternDataUri(PATTERNS[0]!, "light", INK);
    expect(uri).toMatch(/^url\("data:image\/svg\+xml,/);
  });

  it("substitutes every colour placeholder", () => {
    const uri = decodeURIComponent(patternDataUri(PATTERNS[0]!, "light", INK));
    expect(uri).not.toMatch(/\{[a-z]+\}/);
  });

  it("takes its ink from the colours it is given", () => {
    // The file owns no hex. Handed a palette's own steps it draws in them, which
    // is what makes a new theme's wallpaper right without touching this module.
    const uri = decodeURIComponent(
      patternDataUri(PATTERNS[2]!, "light", { ink: "#123456", bloom: "#654321" }),
    );
    expect(uri).toContain("#123456");
    expect(uri).toContain("#654321");
  });

  it("is stronger in dark, where the same strength disappears", () => {
    // This assertion was the other way round once, on the reasoning that a
    // light ink on near-black glares. That holds for a solid fill and not for
    // this: the tile is mostly negative space, so at parity the pattern was
    // invisible on the dark page and the dark theme had no texture at all.
    const light = layerOpacities(patternDataUri(PATTERNS[0]!, "light", INK));
    const dark = layerOpacities(patternDataUri(PATTERNS[0]!, "dark", INK));
    expect(dark[0]).toBeGreaterThan(light[0]!);
  });

  it("keeps every layer subtle enough to stay behind the content", () => {
    // The ceiling is what stops "make it visible" turning into a page that
    // competes with a book cover.
    for (const theme of ["light", "dark"] as const) {
      for (const pattern of PATTERNS) {
        for (const opacity of layerOpacities(patternDataUri(pattern, theme, INK))) {
          expect(opacity).toBeLessThan(0.15);
        }
      }
    }
  });

  it("draws each layer at its own strength", () => {
    // Equal weights would flatten the pattern back into a single plane of
    // shapes. One opacity per layer, ascending, whether there are two or three.
    for (const pattern of PATTERNS) {
      const opacities = layerOpacities(patternDataUri(pattern, "light", INK));
      expect(opacities).toHaveLength(pattern.layers.length);
      expect(opacities).toEqual([...opacities].sort((a, b) => a - b));
      expect(new Set(opacities).size).toBe(opacities.length);
    }
  });

  it("draws every layer surrounded by its own neighbours", () => {
    // Nine copies of each layer, so a motif running off one edge reappears on
    // the opposite one and the repeat has no seam. Asserted as the nine offsets
    // rather than as a count of `<use>`, which is now also how a motif is
    // placed: counting them pinned the implementation instead of the property.
    for (const pattern of PATTERNS) {
      const uri = decodeURIComponent(patternDataUri(pattern, "light", INK));
      const { size } = pattern;
      pattern.layers.forEach((_, index) => {
        const offsets = [
          ...uri.matchAll(
            new RegExp(`<use href="#l${index}" x="(-?\\d+)" y="(-?\\d+)"/>`, "g"),
          ),
        ].map((match) => `${match[1]},${match[2]}`);
        expect(new Set(offsets)).toEqual(
          new Set(
            [-size, 0, size].flatMap((x) =>
              [-size, 0, size].map((y) => `${x},${y}`),
            ),
          ),
        );
      });
    }
  });

  it("stays small enough to be worth inlining", () => {
    // The whole reason these are drawn rather than shipped as images.
    //
    // Re-derived once the motifs moved into <defs>, because a cap nothing
    // approaches enforces nothing: Willow measures 16,490 and is the largest of
    // the five, against 20,740 before. At the old 40,000 the guard had gone
    // from 1.93x the maximum to 2.43x, so the refactor meant to tighten it
    // loosened it instead.
    for (const pattern of PATTERNS) {
      expect(patternDataUri(pattern, "light", INK).length).toBeLessThan(24_000);
    }
  });

  it("renders the same tile every time", () => {
    // Any randomness in the placement would change the data URI on every
    // render, so the browser would re-rasterise the background continuously and
    // no test here could assert anything. Jitter, when it comes, is seeded.
    for (const pattern of PATTERNS) {
      expect(patternDataUri(pattern, "light", INK)).toBe(
        patternDataUri(pattern, "light", INK),
      );
    }
  });
});

describe("wallpaperInk", () => {
  // Values no palette would hold, so the assertion cannot pass on the ones the
  // suite's own setup writes.
  it("reads the ink from the document's own tokens", () => {
    document.documentElement.style.setProperty("--color-accent-700", "#010203");
    document.documentElement.style.setProperty("--color-bloom-700", "#040506");

    expect(wallpaperInk("light")).toEqual({ ink: "#010203", bloom: "#040506" });
  });

  it("takes a lighter step in the dark", () => {
    // Not a second set of hexes: the same two ramps, read further up.
    document.documentElement.style.setProperty("--color-accent-300", "#070809");
    document.documentElement.style.setProperty("--color-bloom-300", "#0a0b0c");

    expect(wallpaperInk("dark")).toEqual({ ink: "#070809", bloom: "#0a0b0c" });
  });

  it("gives nothing back when the palette is not on the document", () => {
    // An empty custom property reaches the SVG as `fill=""`, and an SVG shape
    // with no fill is black rather than invisible.
    document.documentElement.style.cssText = "";

    expect(wallpaperInk("light")).toEqual({ ink: "", bloom: "" });
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
