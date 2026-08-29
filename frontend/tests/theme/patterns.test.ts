/** Tests for src/theme/patterns.ts. */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PATTERNS,
  flow,
  lattice,
  measure,
  mirror,
  patternDataUri,
  randomPattern,
  ribbon,
  swirl,
  wallpaperColours,
  wallpaperWeights,
  type Branch,
  type Layer,
  type LayerWeight,
  type Pattern,
  type Point,
} from "../../src/theme/patterns";
import { markWeight, parseHex } from "../../src/theme/oklab";
import {
  coverage,
  inkField,
  peakCoverage,
  tileField,
  tintContrast,
  widestEmptyRun,
} from "./rasterise";

/**
 * A stated palette, rather than the document's.
 *
 * `patternDataUri` is pure and takes its colours as an argument precisely so a
 * test can say what they are: the tokens it would otherwise read live in a
 * stylesheet, and the suite deliberately does not load one. The page is here
 * with the two inks because every layer's opacity is solved against it.
 */
const INK = { ink: "#0f766e", bloom: "#9f1239", page: "#fbfaf8" };

/**
 * The same palette in its dark mode, which is a different page as well as a
 * different pair of inks.
 *
 * Separate from `INK` because the two are not interchangeable and were being
 * used as though they were: a dark solve against the light page asks for the
 * dark weights over a near white ground, which is a combination that ships
 * nowhere. Both of these are `src/index.css` verbatim.
 */
const DARK_INK = { ink: "#71d8c1", bloom: "#fda4af", page: "#100e0c" };

/**
 * The palette that costs the most alpha to reach its weights.
 *
 * Solarized dark, from `palettes.css`: a dim ink on a page that is not very
 * dark, so the solve has to spend more to move it. It is here because the
 * opacity ceiling is a guard on the worst case and Endpaper is nowhere near it,
 * at 0.1322 against a ceiling of 0.30. This one reaches 0.2082, which is the
 * highest alpha anything in the shipped set is drawn at.
 *
 * **Which palette that is has to be recounted whenever one is added**, and this
 * fixture is the only thing naming it. Recounted over all ten by solving
 * `wallpaperWeights` against every palette's own tokens in both modes: Solarized
 * dark still wins at 0.2082, the next being Gruvbox dark at 0.2046 and
 * Everforest dark at 0.1993, so the three that landed with it did not move it.
 */
const DIMMEST_INK = { ink: "#68cac1", bloom: "#e599b5", page: "#002b36" };

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.style.cssText = "";
});

/** Every mark a layer draws, whether it is a shape or a reference to one. */
function marks(layer: Layer): number {
  return (layer.body.match(/<(use|path) /g) ?? []).length;
}

function layerOpacities(uri: string): number[] {
  return [...decodeURIComponent(uri).matchAll(/<g opacity="([\d.]+)"/g)].map(
    (match) => Number(match[1]),
  );
}

/**
 * What the tile weighs: coverage times the weight each layer is drawn at.
 *
 * The unit is an OKLab lightness delta, not an alpha, and the change of unit is
 * the whole of the retune. An alpha budget was a budget on the palette as much
 * as on the pattern, because the same alpha over ten inks is ten weights.
 * This is a budget on the pattern alone: `TARGETS` fixes what one mark of a
 * layer does to the page, identically for every palette, so what is left to
 * measure is how much of the tile carries it.
 */
const TARGETS: Record<LayerWeight, number> = {
  ground: 0.026,
  under: 0.033,
  foliage: 0.042,
  bloom: 0.057,
};

function tileWeight(pattern: Pattern): number {
  return pattern.layers.reduce(
    (total, layer) => total + coverage(pattern, layer) * TARGETS[layer.weight],
    0,
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

  it("offers both families", () => {
    // Sixteen patterns under one heading would be a list. The split is what the
    // picker groups by, and it is what scopes the density rule below: a repeat
    // is judged partly on how densely it is grown, and a plait grown densely is
    // not a plait.
    const families = new Set(PATTERNS.map((pattern) => pattern.family));
    expect(families).toEqual(new Set(["morris", "papers"]));
  });

  it("leaves every colour to the theme", () => {
    // A hard-coded colour would look wrong in one mode or the other, and across
    // ten palettes it would look wrong in nine of them. The hrefs come out
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
    // weight out, and most do: Acanthus has no flower in it, and three of the
    // sixteen carry the underfoliage plane. It may not reorder them or use one
    // twice.
    const order: LayerWeight[] = ["ground", "under", "foliage", "bloom"];
    for (const pattern of PATTERNS) {
      const weights = pattern.layers.map((layer) => layer.weight);
      expect(weights).toContain("ground");
      expect(new Set(weights).size).toBe(weights.length);
      expect(weights).toEqual(
        [...weights].sort((a, b) => order.indexOf(a) - order.indexOf(b)),
      );
    }
  });

  it("grows enough foliage to read as a repeat rather than a lattice", () => {
    // The first version placed a couple of dozen shapes per tile and came out
    // looking like a trellis with stickers on it. Counted as marks rather than
    // as `<path>` elements, because a motif is now a reference to a definition.
    //
    // The Morris family only. A decorated paper is a lattice on purpose, and
    // Nonpareil draws sixteen marks in the whole tile: what stops it being a
    // wash is the admission rule below, which is the right instrument for it
    // and would say nothing useful about a mass of leaves.
    for (const pattern of PATTERNS.filter((p) => p.family === "morris")) {
      const drawn = pattern.layers.reduce(
        (total, layer) => total + marks(layer),
        0,
      );
      expect(drawn).toBeGreaterThan(30);
    }
  });

  it("writes every shape once, however many times it is placed", () => {
    // The saving is what makes detail affordable: a shape defined once is drawn
    // at every placement and paid for once. Willow places three motifs a
    // hundred and sixty six times, and inline that is their `d` attribute
    // repeated.
    //
    // Asserted as "no `d` appears twice" rather than as a ratio of definitions
    // to placements, because the two mechanisms a pattern is built from are
    // both capable of the same waste: a motif can be inlined at every
    // placement, and a stroked path can be emitted per lattice cell instead of
    // interned and referenced. This catches either.
    for (const pattern of PATTERNS) {
      const written = [
        ...[pattern.defs, ...pattern.layers.map((l) => l.body)]
          .join("")
          .matchAll(/ d="([^"]+)"/g),
      ].map((match) => match[1]!);
      const seen = new Set<string>();
      const twice = written.filter((d) => !seen.add(d));
      expect(twice).toEqual([]);
    }
  });

  it("places nothing it has not defined, and defines nothing it does not place", () => {
    // A dangling href draws nothing at all and reports no error anywhere: the
    // tile simply comes out emptier than it was written.
    for (const pattern of PATTERNS) {
      const defined = new Set(
        [...pattern.defs.matchAll(/<path id="([^"]+)"/g)].map((m) => m[1]!),
      );
      const referenced = new Set(
        pattern.layers
          .flatMap((layer) => [...layer.body.matchAll(/<use href="#([^"]+)"/g)])
          .map((match) => match[1]!),
      );
      expect([...referenced].filter((id) => !defined.has(id))).toEqual([]);
      expect([...defined].filter((id) => !referenced.has(id))).toEqual([]);
    }
  });

  it("keeps every tile inside the ink budget", () => {
    // What "must stay wallpaper" actually means, measured: the fraction of the
    // page the tile inks, weighted by how strongly each layer is drawn.
    //
    // Measured, and the same number in every palette by construction, because
    // the layer weights are perceptual and the alphas are solved from them:
    //
    //   shippo 0.00772     jasmine 0.00778   meander 0.00783
    //   nonpareil 0.00784  pimpernel 0.00788 curl 0.00804
    //   seigaiha 0.00805   asanoha 0.00806   acanthus 0.00815
    //   khatam 0.00818     trellis 0.00820   plait 0.00822
    //   lily 0.00855       willow 0.00868    marigold 0.00869
    //   strawberry 0.00879
    //
    // The band is the agreed 0.0070 to 0.0092 and it binds at both ends. Five
    // tiles had to move to reach it and all five moved the way the band
    // predicted. Willow was 0.00485, the sparsest of the five that then
    // shipped, and gained an underfoliage plane rather than a denser foliage:
    // 31% under is a tile that needs more depth, not more leaves. Golden Lily
    // was 0.01343, half again over the ceiling and almost all of it flower, and
    // its petals came down from 1.2 to 0.85. Trellis was 0.01030 and its roses
    // alone covered 0.0864 of the tile, half again Pimpernel's blooms, so they
    // came down by a quarter in each dimension. Jasmine arrived at 0.00482, 31%
    // under in its turn and for Willow's reason: it is a trail over a ground,
    // so both planes were thin. Marigold arrived at 0.00678 with its heads at
    // 0.0272 against Pimpernel's blooms at 0.0568, and its rays went up.
    //
    // Marigold then moved twice more and neither time was this band. It was
    // rebuilt onto the repeat's second mirror axis to close a 68px empty column
    // band, 0.00777 to 0.00846, and its cross link was arched rather than left
    // nearly straight, 0.00846 to 0.00869. See `MARIGOLD_SCROLL` and
    // `MARIGOLD_BAR`, and the two notes below on what the admission measures
    // could not see.
    //
    // The spread across the sixteen is 1.138x, against 2.65x for the five that
    // shipped before.
    //
    // That spread is a property of this measure as well as of the tiles.
    // `coverage` is analytic and double counts overlapping ink while missing
    // stroke caps, so against the same tiles rasterised it reads Golden Lily
    // 17.7% heavy and Nonpareil 12.7% light, and the spread is 1.235x rather
    // than 1.138x. Every tile is inside the band under either, which is what
    // this asserts; the spread is the claim to qualify. See `coverage`.
    //
    // Light only, and now that is not an approximation. The dark targets are
    // the light ones scaled, and the alpha that reaches them is solved per
    // palette, so measuring dark would assert the same coverage against the
    // same ratios.
    for (const pattern of PATTERNS) {
      expect(tileWeight(pattern)).toBeGreaterThan(0.007);
      expect(tileWeight(pattern)).toBeLessThan(0.0092);
    }
  });
});

describe("the admission rule", () => {
  // A pattern is admitted only if its defining feature is discriminable at the
  // tile's true opacity and native scale. That was an opinion until it was two
  // numbers, and the argument it came out of is in `docs/decisions.md`: fine
  // interlaced strapwork collapses into an even grey, which is what refused a
  // girih and made the khatam ship at an 80px pitch and a 2.6px strap.

  // Both of these rasterise every tile at four samples per pixel per axis, and
  // both need a stated timeout: under the v8 coverage provider the work is
  // about six times slower, which puts them past vitest's 5s default. Failing
  // only under `test:coverage` is the kind of flake that costs a round.
  const SLOW = { timeout: 30_000 };

  it("shows structure at the scale the eye resolves it", SLOW, () => {
    // The floor is measured, not chosen. A field of parallel lines at exactly
    // the 12px mark pitch the rule names measures 0.196 through this filter; at
    // 4px, which is the grey wash, it measures 0.018.
    //
    // Both numbers are pinned as a test of their own, below, rather than left
    // as a claim in this comment.
    //
    // Measured on the sixteen:
    //
    //   nonpareil 0.354  curl 0.435       plait 0.477     seigaiha 0.506
    //   meander 0.546    shippo 0.589     asanoha 0.605   khatam 0.664
    //   willow 1.128     jasmine 1.329    trellis 1.431   marigold 1.526
    //   strawberry 1.530 acanthus 1.575   lily 1.658      pimpernel 1.696
    //
    // The tightest is still Nonpareil at 1.81x the floor, which is right: it is
    // the pattern that is closest to being nothing but a tint, and it earns its
    // place by the pitch of its comb. Curl is the next tightest at 2.22x, and
    // it is the same comb with a stylus drawn through it.
    //
    // **A high score here is not a good tile, and this measure can be gamed by
    // a defect.** It is the RMS contrast of the blurred ink against its own
    // mean, so a large empty region raises it: Marigold scored the highest of
    // the sixteen, 1.749, while carrying a 68px empty column band, and reads
    // 1.526 now that the band is gone. The blur is 3.46px, so nothing at that
    // scale is visible to it at all. Peak coverage does not see it either, it
    // asking only that some mark somewhere reaches full weight.
    //
    // That class is asserted, above, by the widest empty row or column on the
    // wrapped tile. Scoped to `morris` and at zero, because a threshold in
    // pixels turned out not to be derivable: see `widestEmptyRun`.
    for (const pattern of PATTERNS) {
      const contrast = tintContrast(tileField(pattern), pattern.size);
      expect({ id: pattern.id, contrast: contrast > 0.196 }).toEqual({
        id: pattern.id,
        contrast: true,
      });
    }
  });

  it("lays down a whole mark somewhere in every layer", SLOW, () => {
    // The other half, and it is a different failure: a pattern of sub-pixel
    // hairlines can have all the structure in the world and still be invisible,
    // because nowhere does it reach the weight its layer is solved for. A layer
    // whose thickest mark covers half a pixel is drawn at half the weight the
    // palette solved it to, and the fix for that is stroke width rather than
    // opacity.
    for (const pattern of PATTERNS) {
      for (const layer of pattern.layers) {
        const peak = peakCoverage(inkField(pattern, layer));
        expect({
          id: pattern.id,
          weight: layer.weight,
          thick: peak >= 0.9,
        }).toEqual({ id: pattern.id, weight: layer.weight, thick: true });
      }
    }
  });

  it("leaves no part of a Morris repeat empty", SLOW, () => {
    // The third way a tile fails, and the two measures above cannot see it: a
    // region of the repeat with nothing in it. Marigold shipped a round with 68
    // empty columns of its 300px tile, one contiguous run on the torus, having
    // been built with one mirror axis where a turnover has two.
    //
    // **The tint measure scored that tile the highest of the sixteen.** It is
    // contrast against the tile's own mean, so a void raises it: 1.749 with the
    // band, 1.526 without. The instrument rewarded the defect.
    //
    // Asserted at zero and scoped to `morris`, which is what removes the free
    // parameter. A threshold in pixels is not available: the 12px acuity pitch
    // is the only calibrated length here and it governs the gap between
    // adjacent marks, so a field of parallel lines at a 16px pitch measures
    // 0.488, two and a half times the admission floor, and still leaves a 12px
    // run. Every gap of this kind in the shipped set is a paper's mark pitch,
    // Meander and Curl at 11, and no Morris repeat has one at all. See
    // `widestEmptyRun`.
    //
    // **The margin is four pixels, and it is stated so that a first failure is
    // diagnosed rather than deleted.** The emptiest line of any repeat is
    // Acanthus's row 54, carrying 4 inked pixels of 300 and 2.88 px2 of ink,
    // with Pimpernel's row 0 also at 4, of 3.50 px2; the other six run 6 to 11.
    // So the two tightest sit four pixels from failing, and what they would
    // fail with is a **one pixel empty row**, which nobody can see and which is
    // not the defect this exists for. That is the shape a false positive takes
    // here, and meeting one is a reason to widen a stem by a hair, not to
    // conclude the rule is too strict and remove the thing that would have
    // caught the next 68.
    const repeats = PATTERNS.filter((pattern) => pattern.family === "morris");
    // Not vacuous: a mistyped family would leave nothing to iterate and this
    // would pass on an empty loop, which is how a scoped guard goes quiet.
    expect(repeats.length).toBeGreaterThan(0);
    for (const pattern of repeats) {
      expect({
        id: pattern.id,
        empty: widestEmptyRun(tileField(pattern), pattern.size),
      }).toEqual({ id: pattern.id, empty: 0 });
    }
  });

  /**
   * A field of parallel lines, which is what the floor was calibrated on.
   *
   * Deliberately not a member of `PATTERNS`: the two numbers below describe the
   * **filter**, not a tile, and a grating admitted to the catalogue to measure
   * the instrument would be a grating on somebody's page.
   */
  const grating = (pitch: number, width: number): Pattern => ({
    id: `grating-${pitch}`,
    name: "grating",
    family: "papers",
    size: 240,
    defs: "",
    layers: [
      {
        weight: "ground",
        body:
          `<g fill="none" stroke="{ink}" stroke-width="${width}" ` +
          `stroke-linecap="round">` +
          Array.from(
            { length: 240 / pitch },
            (_, index) =>
              `<path d="M0 ${index * pitch}L240 ${index * pitch}"/>`,
          ).join("") +
          `</g>`,
      },
    ],
  });

  it("measures the floor at the pitch the floor is named for", SLOW, () => {
    // The floor above is a measurement through this filter and not a formula,
    // and it lived only as a paragraph in `rasterise.ts` until now. That
    // paragraph said the moment to pin it was when an eleventh pattern was
    // admitted, because that is the first time anybody has reason to touch
    // either number; six arrived at once.
    //
    // What it pins is the instrument. `BLUR_RADIUS` and the three box passes
    // decide what "12px apart" means, and moving either changes every
    // pattern's headroom against a floor that still reads 0.196. Nothing else
    // in this file would notice: a wider blur passes less of every pattern and
    // the comparison is against a constant, so the failure arrives as tiles
    // being refused for no stated reason.
    expect(tintContrast(tileField(grating(12, 2.4)), 240)).toBeCloseTo(
      0.196,
      3,
    );
  });

  it("measures a grey wash far under the floor", SLOW, () => {
    // The other end of the calibration, and it is the one that says the filter
    // discriminates rather than merely scales: a wash at a third of the pitch
    // reads eleven times fainter, not three times.
    expect(tintContrast(tileField(grating(4, 1.2)), 240)).toBeCloseTo(0.018, 3);
  });

  // Nothing here measures a seam in a rendered tile. A test that tried was
  // written, could not be made to detect a deliberately broken Asanoha, and
  // was deleted: a test that reports clean for something it cannot see is
  // worse than no test. The seam is asserted on the layout instead, under
  // "the primitives" below, which is where it is decided.
});

describe("the primitives", () => {
  // Exported so their guards can be reached. That was refused once, on the
  // grounds that nothing outside this module calls them, and the refusal cost
  // a shipped defect: Asanoha's honeycomb broke in a 60px band on every 420px
  // tile, 14% of the page, and the constructor invariant cited as the guard on
  // exactly that pattern turned out to be vacuous for it. A layout rule needs a
  // testable surface, and this is it.

  const draw = () => "<x/>";

  /** Curl's own centres: two staggered rows, the closest pair 80px apart. */
  const CURLS: Point[] = [
    [0, 0],
    [80, 0],
    [160, 0],
    [40, 120],
    [120, 120],
    [200, 120],
  ];

  it("refuses a pitch that does not divide the tile", () => {
    // The cells would not meet across the seam, once per repeat, forever.
    expect(() => lattice(240, { x: 70, y: 60 }, draw)).toThrow(/70/);
    expect(() => lattice(240, { x: 60, y: 70 }, draw)).toThrow(/70/);
  });

  it("says out loud what that check cannot catch", () => {
    // A caller that derives its extent from its own pitch passes by
    // construction and learns nothing. Asanoha does exactly that, which is why
    // this check was never the guard it was described as.
    expect(() =>
      lattice({ x: 240, y: 7 * 51.9615 }, { x: 60, y: 51.9615 }, draw),
    ).not.toThrow();
  });

  it("refuses a staggered lattice with an odd number of rows", () => {
    // The one that catches the real defect. The offset repeats every two rows,
    // so an odd count puts two unstaggered rows together across the seam.
    expect(() =>
      lattice(240, { x: 60, y: 80 }, draw, { stagger: true }),
    ).toThrow(/even row count, not 3/);
    expect(() =>
      lattice(240, { x: 60, y: 60 }, draw, { stagger: true }),
    ).not.toThrow();
  });

  it("offsets alternate rows by half a column, and closes across the seam", () => {
    const cells: { x: number; row: number }[] = [];
    lattice(
      240,
      { x: 60, y: 60 },
      (cell) => {
        cells.push(cell);
        return "";
      },
      { stagger: true },
    );
    const firstOfRow = [0, 1, 2, 3].map(
      (row) =>
        cells.filter((cell) => cell.row === row).map((cell) => cell.x)[0],
    );
    expect(firstOfRow).toEqual([0, 30, 0, 30]);
    // The property the even row count exists for: the tile's last row and the
    // first row of the tile below it are on opposite phases.
    expect(firstOfRow[firstOfRow.length - 1]).not.toBe(firstOfRow[0]);
  });

  it("refuses a wave that does not meet itself", () => {
    // A fractional cycle count leaves a step at the seam, and the wave is
    // placed at nine offsets, so the step is drawn nine times.
    expect(() => flow(240, [{ cycles: 2.5, amplitude: 4, phase: 0 }])).toThrow(
      /2\.5/,
    );
  });

  it("draws a wave that starts and ends at the same height", () => {
    const d = flow(240, [
      { cycles: 1, amplitude: 4.4, phase: 0 },
      { cycles: 6, amplitude: 3.1, phase: 90 },
    ]);
    const first = Number(/^M0 (-?[\d.]+)/.exec(d)![1]);
    const last = Number(/(-?[\d.]+)$/.exec(d)![1]);
    expect(last).toBeCloseTo(first, 1);
  });

  it("reflects a branch rather than the picture drawn from it", () => {
    // Branches and not a drawn body, because a stem is used twice: once to be
    // drawn and once to grow foliage along. Reflecting the output would give a
    // mirrored stem carrying unmirrored leaves.
    const branch: Branch = [
      [
        [10, 20],
        [40, 20],
        [60, 40],
        [90, 40],
      ],
    ];
    const [flipped] = mirror([branch], 100, "x");
    expect(flipped![0]![0]).toEqual([90, 20]);
    expect(flipped![0]![3]).toEqual([10, 40]);
    expect(measure(flipped!).length).toBeCloseTo(measure(branch).length, 6);
  });

  it("refuses swirl centres whose pulls overlap", () => {
    // Two centres closer than twice the reach make the field periodic nowhere,
    // and the discontinuity runs along a line inside the tile rather than at
    // its seam, so the nine offsets do not rescue it.
    expect(() => swirl(CURLS.slice(0, 2), 60, 3, 240)).toThrow(/80px apart/);
    expect(() => swirl([[40, 40]], 130, 3, 240)).toThrow(/240px apart/);
  });

  it("measures that overlap on the torus, not against nine written copies", () => {
    // Each of these is the same lattice written differently, and each overlaps.
    // The first two are what an enumeration of the eight neighbouring offsets
    // also catches; the third is not, because it is two tiles out, and there is
    // no bound on how far out a centre may be written.
    const overlapping: Point[][] = [
      [
        [5, 5],
        [235, 5],
      ],
      [
        [5, 5],
        [5, 236],
      ],
      [
        [0, 0],
        [484, 4],
      ],
    ];
    for (const centres of overlapping) {
      expect(() => swirl(centres, 38, 3, 240)).toThrow(/overlap at reach/);
    }
  });

  it("takes the centres it was checked on, not the array they arrived in", () => {
    // A guard that checks an argument and then closes over it has checked a
    // snapshot. Both of these put the field into a state the constructor
    // refuses: handed `[[10, 10], [210, 200]]` up front it throws, the two
    // being 64px apart on a 240 torus against a floor of 76.
    //
    // The probe is out of reach of the centre the guard saw and inside the
    // reach of the one added afterwards, because `swirl` returns on the first
    // centre in range. A probe covered by the original never consults the new
    // one, and a probe sitting on a centre does not move at all; both report
    // clean whatever the implementation does.
    //
    // Copying the array alone passes the first of these and fails the second,
    // which is why the constructor copies the coordinates out.
    const probe: Point = [200, 200];

    const pushed: Point[] = [[10, 10]];
    const afterPush = swirl(pushed, 38, 3, 240);
    const wasPush = afterPush(probe);
    pushed.push([210, 200]);
    expect(afterPush(probe)).toEqual(wasPush);

    const written: Point[] = [[10, 10]];
    const afterWrite = swirl(written, 38, 3, 240);
    const wasWrite = afterWrite(probe);
    written[0]![0] = 210;
    written[0]![1] = 200;
    expect(afterWrite(probe)).toEqual(wasWrite);
  });

  it("displaces a point identically however its centre was written", () => {
    // The same reduction, on the other side of the guard. A centre at the
    // origin and one a tile away are one centre.
    const inside = swirl([[40, 40]], 38, 3, 240);
    const outside = swirl([[280, 280]], 38, 3, 240);
    expect(outside([50, 50])).toEqual(inside([50, 50]));
  });

  it("carries a point round its centre without moving it off its own circle", () => {
    // A rotation maps every circle about the centre to itself, which is what
    // makes a combed line shear under a curl and never cross its neighbour.
    const warp = swirl([[120, 120]], 38, 3, 240);
    const moved = warp([140, 120]);
    expect(Math.hypot(moved[0] - 120, moved[1] - 120)).toBeCloseTo(20, 9);
    expect(moved).not.toEqual([140, 120]);
  });

  it("leaves a point beyond the reach exactly where it was", () => {
    // The support has to be compact, or the sum over the lattice is not
    // periodic and no guard on the spacing would make it so.
    expect(swirl([[120, 120]], 38, 3, 240)([120, 60])).toEqual([120, 60]);
  });

  it("repeats with the tile, which is what makes a displaced comb seamless", () => {
    const warp = swirl(CURLS, 38, 5, 240);
    for (const point of [
      [7, 3],
      [95, 44],
      [210, 190],
    ] as Point[]) {
      const here = warp(point);
      const across = warp([point[0] + 240, point[1] + 240]);
      expect(across[0] - 240).toBeCloseTo(here[0], 9);
      expect(across[1] - 240).toBeCloseTo(here[1], 9);
    }
  });

  it("breaks a band into one pair of edges per visible span", () => {
    // How the plait draws under: the strand is interrupted rather than
    // occluded, because a transparent wallpaper has no ground to hide behind.
    const straight: Branch = [
      [
        [0, 0],
        [40, 0],
        [80, 0],
        [120, 0],
      ],
    ];
    const whole = (ribbon(straight, 10).match(/M/g) ?? []).length;
    const broken = (
      ribbon(straight, 10, [
        [0, 0.4],
        [0.6, 1],
      ]).match(/M/g) ?? []
    ).length;
    expect(whole).toBe(2);
    expect(broken).toBe(4);
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

describe("wallpaperWeights", () => {
  it("solves an alpha per layer that lands on that layer's weight", () => {
    // The whole point of the change. What is constant across the palettes is
    // the weight, and the alpha is whatever reaches it.
    const weights = wallpaperWeights("light", INK)!;
    const page = parseHex(INK.page)!;
    expect(markWeight(parseHex(INK.ink)!, page, weights.ground)).toBeCloseTo(
      0.026,
      4,
    );
    expect(markWeight(parseHex(INK.bloom)!, page, weights.foliage)).toBeCloseTo(
      0.042,
      4,
    );
  });

  it("asks a dimmer palette for more alpha and gets the same weight", () => {
    // Measured across all ten shipped palettes, the alpha the dark ground needs
    // runs 0.0720 (Ayu) to 0.1093 (Rose Pine), a 1.52x spread, and in
    // continuous colour every one of them lands on 0.0610, the target itself.
    // At one alpha the weight was the thing that varied, by 1.32x, which is the
    // width of the entire ink budget.
    //
    // It read 0.078 to 0.109 over seven, which was the same measurement before
    // Ayu arrived with the brightest ink of the set. The weight it quoted, 0.0604
    // to 0.0622, was read through the compositor's 8 bit quantisation rather
    // than in continuous colour, which is the whole of that 1.03x; solving alone
    // holds it to 1.00x.
    const page = parseHex(DARK_INK.page)!;
    const bright = wallpaperWeights("dark", DARK_INK)!;
    const dim = wallpaperWeights("dark", {
      ink: "#3a6a62",
      bloom: "#8a5a60",
      page: DARK_INK.page,
    })!;
    expect(dim.ground).toBeGreaterThan(bright.ground);
    expect(
      markWeight(parseHex(DARK_INK.ink)!, page, bright.ground),
    ).toBeCloseTo(markWeight(parseHex("#3a6a62")!, page, dim.ground), 3);
  });

  it("draws the dark page more strongly than the light one", () => {
    // This assertion was the other way round once, on the reasoning that a
    // light ink on near-black glares. That holds for a solid fill and not for
    // this: the tile is mostly negative space, so at parity the pattern was
    // invisible on the dark page and the dark theme had no texture at all.
    const light = wallpaperWeights("light", INK)!;
    const dark = wallpaperWeights("dark", DARK_INK)!;
    const page = parseHex(INK.page)!;
    expect(markWeight(parseHex(INK.ink)!, page, dark.ground)).toBeGreaterThan(
      markWeight(parseHex(INK.ink)!, page, light.ground),
    );
  });

  it("gives nothing back for a colour it cannot read", () => {
    // A default alpha here would paint something and hide the reason. The
    // caller refuses to paint at all instead.
    expect(wallpaperWeights("light", { ...INK, page: "" })).toBeNull();
    expect(wallpaperWeights("light", { ...INK, ink: "teal" })).toBeNull();
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
      patternDataUri(PATTERNS[2]!, "light", {
        ink: "#123456",
        bloom: "#654321",
        page: "#fbfaf8",
      }),
    );
    expect(uri).toContain("#123456");
    expect(uri).toContain("#654321");
  });

  it("paints nothing at all when the palette is not on the document", () => {
    expect(patternDataUri(PATTERNS[0]!, "light", { ...INK, ink: "" })).toBe("");
  });

  it("keeps every layer subtle enough to stay behind the content", () => {
    // Not the weight ceiling: that is `TARGETS`, and it is the same perceptual
    // number for every palette. This is the guard on what an ink may spend
    // reaching it, and it binds only where an ink is so close to its own page
    // that no reasonable alpha gets there. The highest solve across the
    // twenty shipped palette-modes is still Solarized dark's bloom at 0.2082,
    // recounted against all ten palettes rather than carried over from seven.
    //
    // It replaced a flat 0.15, which was right while the alpha was the
    // instrument and is wrong now: seven of the ten palettes need more than
    // 0.15 in dark to reach the weight Endpaper reaches at 0.1322.
    //
    // Three cases, not two. On Endpaper alone this asserts 0.1322 against a
    // ceiling of 0.30 and would pass however wrong the ceiling was, so the
    // dimmest shipped palette is measured with it.
    const cases = [
      ["light", INK],
      ["dark", DARK_INK],
      ["dark", DIMMEST_INK],
    ] as const;
    for (const [theme, colours] of cases) {
      for (const pattern of PATTERNS) {
        for (const opacity of layerOpacities(
          patternDataUri(pattern, theme, colours),
        )) {
          expect(opacity).toBeLessThanOrEqual(0.3);
        }
      }
    }
  });

  it("draws each layer at its own strength", () => {
    // Equal weights would flatten the pattern back into a single plane of
    // shapes. One opacity per layer, ascending, whether there are two or four.
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
            new RegExp(
              `<use href="#l${index}" x="(-?\\d+)" y="(-?\\d+)"/>`,
              "g",
            ),
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
    // Willow is still the largest at 21,556, which is 89.8% of the cap.
    //
    // The cap is asserted per pattern, so "leave room for the next one" is not
    // an argument for keeping it high: a new pattern gets its own 24,000
    // whatever this one weighs. Willow is still the only tile the cap
    // constrains at all, the next largest now being Jasmine at 17,410, which is
    // 72.5%. Jasmine is the second Morris repeat to carry four planes and it is
    // what the cap will bind on next. It is left at 24,000 because moving it
    // in the change that added the tiles it is measured against would be
    // tuning the guard to the measurement.
    for (const pattern of PATTERNS) {
      expect(patternDataUri(pattern, "light", INK).length).toBeLessThan(24_000);
    }
  });

  it("renders the same tile every time", () => {
    // Any randomness in the placement would change the data URI on every
    // render, so the browser would re-rasterise the background continuously and
    // no test here could assert anything. The jitter is seeded from each
    // placement's own position, which is what makes it survive this.
    for (const pattern of PATTERNS) {
      expect(patternDataUri(pattern, "light", INK)).toBe(
        patternDataUri(pattern, "light", INK),
      );
    }
  });

  it("moves a placement without renumbering the ones after it", () => {
    // What the seed buys over a counter. The jitter is a function of where a
    // motif is, not of how many were emitted before it, so adding a twig to a
    // stem cannot shuffle every leaf on the branches that follow.
    const willow = PATTERNS.find((pattern) => pattern.id === "willow")!;
    const placements = [
      ...willow.layers[1]!.body.matchAll(/translate\(([-\d.]+) ([-\d.]+)\)/g),
    ];
    expect(placements.length).toBeGreaterThan(10);
    const spacings = placements
      .slice(1)
      .map((match, index) =>
        Math.hypot(
          Number(match[1]) - Number(placements[index]![1]),
          Number(match[2]) - Number(placements[index]![2]),
        ),
      );
    // Jittered, so no two gaps are the same; bounded, so none is zero.
    expect(new Set(spacings.map((s) => s.toFixed(1))).size).toBeGreaterThan(5);
    expect(Math.min(...spacings)).toBeGreaterThan(0);
  });
});

describe("wallpaperColours", () => {
  // Values no palette would hold, so the assertion cannot pass on the ones the
  // suite's own setup writes.
  it("reads the colours from the document's own tokens", () => {
    document.documentElement.style.setProperty("--color-accent-700", "#010203");
    document.documentElement.style.setProperty("--color-bloom-700", "#040506");
    document.documentElement.style.setProperty("--color-paper-50", "#070809");

    expect(wallpaperColours("light")).toEqual({
      ink: "#010203",
      bloom: "#040506",
      page: "#070809",
    });
  });

  it("takes a lighter step in the dark", () => {
    // Not a second set of hexes: the same ramps, read further up, against the
    // page the dark mode actually paints.
    document.documentElement.style.setProperty("--color-accent-300", "#070809");
    document.documentElement.style.setProperty("--color-bloom-300", "#0a0b0c");
    document.documentElement.style.setProperty("--color-paper-950", "#0d0e0f");

    expect(wallpaperColours("dark")).toEqual({
      ink: "#070809",
      bloom: "#0a0b0c",
      page: "#0d0e0f",
    });
  });

  it("gives nothing back when the palette is not on the document", () => {
    // An empty custom property reaches the SVG as `fill=""`, and an SVG shape
    // with no fill is black rather than invisible.
    document.documentElement.style.cssText = "";

    expect(wallpaperColours("light")).toEqual({ ink: "", bloom: "", page: "" });
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
