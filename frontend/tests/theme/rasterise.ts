/**
 * Turn a generated tile back into ink, so the admission rule can be a test.
 *
 * A pattern is admitted only if its defining feature survives being drawn: at
 * true opacity, at native scale, on the page it is pasted onto. That was a
 * matter of opinion until this file existed, and the argument it came out of is
 * recorded in `docs/decisions.md`: fine interlaced strapwork collapses into an
 * even grey at six percent opacity, which is what killed a girih and forced the
 * khatam to be respecified coarser.
 *
 * Two numbers decide it, and both are read off the tile rather than off the
 * source:
 *
 * - **Tint contrast.** The tile's ink, blurred, measured as RMS contrast
 *   against its own mean. If nothing survives the blur, the pattern has no
 *   structure the eye can resolve at arm's length and the page is a flat wash
 *   however strongly it is drawn. This is the general form of "adjacent
 *   parallel marks at least 12px apart": it makes the same judgement without
 *   having to decide which marks are parallel, and it applies to a foliage
 *   repeat and a lattice alike. A grating at exactly the 12px floor measures
 *   0.196 through it, which is where the floor is set; at 4px it measures 0.018
 *   and at 30px 1.140. Those three are the calibration, and they are
 *   measurements rather than a formula: see `BLUR_RADIUS`.
 * - **Peak coverage.** The single most inked pixel of a layer. A pattern built
 *   from sub-pixel hairlines can pass the tint test and still be invisible,
 *   because nowhere does it lay down a mark that reaches the weight its layer is
 *   solved for. Such a pattern is drawn too thin rather than too faint, and the
 *   fix is stroke width rather than opacity.
 *
 * The field is **toroidal**. The tile is drawn surrounded by its own copies, so
 * a mark hanging off the right edge is ink on the left one, and the blur has to
 * wrap for the same reason.
 *
 * This also owns the coverage measure the ink budget uses, because both need
 * the same thing: the actual geometry, with every `<use>` resolved through
 * every enclosing transform. The coverage measure used to parse the layer body
 * with two regular expressions and it silently mismeasured the moment a `<use>`
 * appeared inside a stroked group, which is how every one of the decorated
 * papers is built.
 *
 * ## Reading a path here, and writing one in `patterns.ts`, stay separate
 *
 * `subpaths`, `parseTransform` and the de Casteljau below re-implement what
 * `patterns.ts` emits, and that duplication is right rather than merely
 * tolerable. Sharing it goes one of two ways and both are worse. Either the
 * reader ships in the bundle, where no user needs a path parser or a matrix
 * stack, or `patterns.ts` stops emitting strings and emits an AST for something
 * else to serialise, which buys a shared grammar by making the generator
 * indirect.
 *
 * It is the same call `src/theme/oklab.ts` records for the contrast maths in
 * `palettes.test.ts`: "merging them would put a test's instrument in the
 * product." Here the direction is reversed and the conclusion is not: this is a
 * measuring instrument, and an instrument that shares its parser with the thing
 * it measures cannot catch that thing writing a path it did not mean to.
 */

import type { Layer, Pattern } from "../../src/theme/patterns";

export type Point = [number, number];

/** An affine transform, `[a, b, c, d, e, f]` as SVG writes it. */
type Matrix = [number, number, number, number, number, number];

const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

function multiply(m: Matrix, n: Matrix): Matrix {
  return [
    m[0] * n[0] + m[2] * n[1],
    m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3],
    m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4],
    m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}

function apply(m: Matrix, [x, y]: Point): Point {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

/** The uniform scale a matrix applies, for scaling a stroke width with it. */
function scaleOf(m: Matrix): number {
  return Math.sqrt(Math.abs(m[0] * m[3] - m[1] * m[2]));
}

function parseTransform(text: string): Matrix {
  let result = IDENTITY;
  for (const [, name, args] of text.matchAll(/(\w+)\(([^)]*)\)/g)) {
    const values = (args!.match(/-?[\d.]+/g) ?? []).map(Number);
    if (name === "translate") {
      result = multiply(result, [1, 0, 0, 1, values[0] ?? 0, values[1] ?? 0]);
    } else if (name === "rotate") {
      const radians = ((values[0] ?? 0) * Math.PI) / 180;
      const cos = Math.cos(radians);
      const sin = Math.sin(radians);
      result = multiply(result, [cos, sin, -sin, cos, 0, 0]);
    } else if (name === "scale") {
      const sx = values[0] ?? 1;
      result = multiply(result, [sx, 0, 0, values[1] ?? sx, 0, 0]);
    } else {
      // Anything else would be applied as the identity, which is a wrong
      // measurement rather than a missing one.
      throw new Error(`rasterise does not handle transform "${name}"`);
    }
  }
  return result;
}

// ── Paths ────────────────────────────────────────────────────────────────────

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

/** A `d` attribute as a list of subpaths, each a polyline. */
export function subpaths(d: string): { points: Point[]; closed: boolean }[] {
  const tokens = d.match(/[MLCQZ]|-?\d*\.?\d+/g) ?? [];
  const out: { points: Point[]; closed: boolean }[] = [];
  let current: Point[] = [];
  let cursor: Point = [0, 0];
  let index = 0;
  const next = () => Number(tokens[index++]);
  const curve = (controls: Point[]) => {
    const all = [cursor, ...controls];
    for (let step = 1; step <= 8; step += 1) {
      current.push(deCasteljau(all, step / 8));
    }
    cursor = all[all.length - 1]!;
  };
  const flush = (closed: boolean) => {
    if (current.length > 1) out.push({ points: current, closed });
    current = [];
  };

  while (index < tokens.length) {
    const command = tokens[index++];
    if (command === "M") {
      flush(false);
      cursor = [next(), next()];
      current = [cursor];
    } else if (command === "L") {
      cursor = [next(), next()];
      current.push(cursor);
    } else if (command === "C") {
      curve([
        [next(), next()],
        [next(), next()],
        [next(), next()],
      ]);
    } else if (command === "Q") {
      curve([
        [next(), next()],
        [next(), next()],
      ]);
    } else if (command === "Z") {
      flush(true);
    } else {
      // A command nothing here handles would measure as no ink at all and
      // report a lighter tile than the one that ships.
      throw new Error(`rasterise does not handle "${command}"`);
    }
  }
  flush(false);
  return out;
}

// ── The marks a layer draws ──────────────────────────────────────────────────

export interface FillMark {
  kind: "fill";
  /** Subpaths, in tile coordinates. Holes included: the rule is even-odd. */
  rings: Point[][];
}

export interface StrokeMark {
  kind: "stroke";
  points: Point[];
  width: number;
}

export type Mark = FillMark | StrokeMark;

interface Context {
  matrix: Matrix;
  stroke: number | null;
}

/**
 * Every mark a layer draws, with `<use>` resolved and transforms composed.
 *
 * A tiny SVG reader rather than a regular expression, because the two
 * mechanisms a pattern is built from (a filled motif placed by `<use>`, and a
 * stroked path inside a group) can nest either way round, and the only thing
 * that tells them apart is which group they are in.
 */
export function marks(pattern: Pattern, layer: Layer): Mark[] {
  const shapes = new Map<string, string>();
  for (const [, id, d] of pattern.defs.matchAll(
    /<path id="([^"]+)" d="([^"]+)"\/>/g,
  )) {
    shapes.set(id!, d!);
  }

  const out: Mark[] = [];
  const stack: Context[] = [{ matrix: IDENTITY, stroke: null }];
  const top = () => stack[stack.length - 1]!;

  const emit = (d: string, context: Context) => {
    const parts = subpaths(d).map(({ points, closed }) => ({
      points: points.map((point) => apply(context.matrix, point)),
      closed,
    }));
    if (context.stroke !== null) {
      const width = context.stroke * scaleOf(context.matrix);
      for (const { points, closed } of parts) {
        out.push({
          kind: "stroke",
          points: closed ? [...points, points[0]!] : points,
          width,
        });
      }
    } else {
      out.push({ kind: "fill", rings: parts.map(({ points }) => points) });
    }
  };

  for (const [, tag] of layer.body.matchAll(/<(\/?[a-z]+[^>]*)>/g)) {
    const text = tag!;
    if (text.startsWith("/g")) {
      stack.pop();
      continue;
    }
    const transform = /transform="([^"]*)"/.exec(text)?.[1];
    const matrix = transform
      ? multiply(top().matrix, parseTransform(transform))
      : top().matrix;

    if (text.startsWith("g")) {
      const width = /stroke-width="([\d.]+)"/.exec(text)?.[1];
      stack.push({
        matrix,
        stroke: width === undefined ? top().stroke : Number(width),
      });
    } else if (text.startsWith("use")) {
      const href = /href="#([^"]+)"/.exec(text)![1]!;
      const shape = shapes.get(href);
      if (shape === undefined) throw new Error(`no definition for #${href}`);
      emit(shape, { matrix, stroke: top().stroke });
    } else if (text.startsWith("path")) {
      emit(/ d="([^"]+)"/.exec(text)![1]!, { matrix, stroke: top().stroke });
    }
  }
  return out;
}

// ── Coverage ─────────────────────────────────────────────────────────────────

function ringArea(points: Point[]): number {
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

/**
 * Ink area over tile area, before the layer's opacity.
 *
 * A hole subtracts. No motif has one today, and the arithmetic is here because
 * the alternative is a measure that silently reports a knocked-out shape as
 * solid: a hole is invisible to a measurement that only sums subpath areas, and
 * that is exactly the class of error this file was written to stop.
 *
 * **This is analytic and `inkField` is not, and they disagree.** This one sums
 * lengths and areas, so ink laid twice on one pixel is counted twice; and it
 * takes a stroke as length times width, so the round cap at each end is not
 * counted at all. The two errors run in opposite directions and which one wins
 * depends on the pattern. Measured across the ten, weighted identically and
 * compared against the same tiles rasterised:
 *
 * ```
 * lily +17.7%   acanthus +10.1%   asanoha +6.5%   willow +3.3%
 * plait -1.1%   seigaiha -2.6%    nonpareil -12.7%
 * ```
 *
 * A dense foliage tile overlaps constantly and reads heavy; a tile of sixteen
 * long thin strokes is nearly all cap and edge and reads light. All ten sit
 * inside the ink budget under either measure, so nothing is mis-admitted. The
 * **spread** across the set is not measure independent: 1.122x this way and
 * 1.235x from the field. Budgeting from the field is the better instrument and
 * is a retune rather than an edit, so it is not this change.
 */
export function coverage(pattern: Pattern, layer: Layer): number {
  let ink = 0;
  for (const mark of marks(pattern, layer)) {
    if (mark.kind === "stroke") {
      ink += polylineLength(mark.points) * mark.width;
    } else {
      const areas = mark.rings.map(ringArea).sort((a, b) => b - a);
      ink += areas.reduce(
        (total, area, index) => total + (index === 0 ? area : -area),
        0,
      );
    }
  }
  return ink / (pattern.size * pattern.size);
}

// ── The ink field ────────────────────────────────────────────────────────────

/**
 * Samples per pixel per axis.
 *
 * Four puts the peak coverage on a sixteenth, which is finer than the 0.9 floor
 * needs, and it is deliberately not finer than that because this runs over
 * every mark of every layer of ten tiles.
 *
 * Its limit, said out loud: a sample grid cannot resolve a mark thinner than
 * its own spacing, so a stroke between about 0.75px and 1px reports as fully
 * covered when it is not. That is inside the region the floor already accepts.
 * A hairline at 0.5px reports 0.5 and fails, which is the case the floor is
 * for.
 */
const SUBPIXEL = 4;

function insideEvenOdd(rings: Point[][], x: number, y: number): boolean {
  let inside = false;
  for (const ring of rings) {
    for (let i = 0; i < ring.length; i += 1) {
      const a = ring[i]!;
      const b = ring[(i + 1) % ring.length]!;
      if (a[1] > y !== b[1] > y) {
        const at = a[0] + ((y - a[1]) / (b[1] - a[1])) * (b[0] - a[0]);
        if (x < at) inside = !inside;
      }
    }
  }
  return inside;
}

function nearSegment(
  a: Point,
  b: Point,
  x: number,
  y: number,
  half: number,
): boolean {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const squared = dx * dx + dy * dy;
  const t =
    squared === 0
      ? 0
      : Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / squared));
  const px = a[0] + t * dx;
  const py = a[1] + t * dy;
  return (x - px) ** 2 + (y - py) ** 2 <= half * half;
}

/**
 * Ink coverage per pixel, 0 to 1, wrapped onto the tile.
 *
 * Only the marks are rasterised, not the layer's opacity: what a layer is drawn
 * at is solved from the palette and is the same for every pattern, so mixing it
 * in here would measure the palette rather than the pattern.
 */
const FIELDS = new WeakMap<Layer, Float32Array>();

export function inkField(pattern: Pattern, layer: Layer): Float32Array {
  // Memoised on the layer, which is built once at module load and never
  // mutated. Two assertions want the same fields and rasterising ten tiles
  // twice is the difference between a fast test and one that times out under
  // the coverage provider's instrumentation.
  const cached = FIELDS.get(layer);
  if (cached) return cached;

  const { size } = pattern;
  const field = new Float32Array(size * size);
  const weight = 1 / (SUBPIXEL * SUBPIXEL);

  const paint = (
    minX: number,
    minY: number,
    maxX: number,
    maxY: number,
    hit: (x: number, y: number) => boolean,
  ) => {
    const x0 = Math.floor(minX);
    const y0 = Math.floor(minY);
    const x1 = Math.ceil(maxX);
    const y1 = Math.ceil(maxY);
    for (let py = y0; py <= y1; py += 1) {
      const row = ((py % size) + size) % size;
      for (let px = x0; px <= x1; px += 1) {
        const column = ((px % size) + size) % size;
        let covered = 0;
        for (let sy = 0; sy < SUBPIXEL; sy += 1) {
          const y = py + (sy + 0.5) / SUBPIXEL;
          for (let sx = 0; sx < SUBPIXEL; sx += 1) {
            if (hit(px + (sx + 0.5) / SUBPIXEL, y)) covered += 1;
          }
        }
        if (covered > 0) {
          const index = row * size + column;
          // Layers of one pattern are painted over each other rather than
          // added: two marks on the same pixel are one opaque pixel, not two.
          field[index] = Math.min(1, field[index]! + covered * weight);
        }
      }
    }
  };

  for (const mark of marks(pattern, layer)) {
    if (mark.kind === "fill") {
      const xs = mark.rings.flat().map(([x]) => x);
      const ys = mark.rings.flat().map(([, y]) => y);
      paint(
        Math.min(...xs),
        Math.min(...ys),
        Math.max(...xs),
        Math.max(...ys),
        (x, y) => insideEvenOdd(mark.rings, x, y),
      );
    } else {
      const half = mark.width / 2;
      for (let i = 1; i < mark.points.length; i += 1) {
        const a = mark.points[i - 1]!;
        const b = mark.points[i]!;
        paint(
          Math.min(a[0], b[0]) - half,
          Math.min(a[1], b[1]) - half,
          Math.max(a[0], b[0]) + half,
          Math.max(a[1], b[1]) + half,
          (x, y) => nearSegment(a, b, x, y, half),
        );
      }
    }
  }
  FIELDS.set(layer, field);
  return field;
}

/** The whole tile's ink, every layer over every other. */
export function tileField(pattern: Pattern): Float32Array {
  const total = new Float32Array(pattern.size * pattern.size);
  for (const layer of pattern.layers) {
    const field = inkField(pattern, layer);
    for (let index = 0; index < total.length; index += 1) {
      total[index] = Math.min(1, total[index]! + field[index]!);
    }
  }
  return total;
}

/** The most inked pixel. Below 1 the pattern nowhere lays down a whole mark. */
export function peakCoverage(field: Float32Array): number {
  let peak = 0;
  for (const value of field) peak = Math.max(peak, value);
  return peak;
}

/**
 * The blur the tint test looks through.
 *
 * Three passes of a box of width `2 * BLUR_RADIUS + 1`, which is the cheap way
 * to approximate a Gaussian: four additions per pixel per axis, against a
 * kernel fifteen wide. Three passes of a width 7 box has a standard deviation
 * of **3.46 px**, and its exact response is `(sin(pi w / p) / (w sin(pi / p)))^3`,
 * which measures 0.0029 at a period of 4px, **0.1515 at 12px**, and 0.7648 at
 * 30px, with the half amplitude point at **18.9px**.
 *
 * Those numbers are stated because the obvious closed form gives different ones
 * and somebody will reach for it. This constant was documented as the sigma of
 * a true Gaussian chosen so that `exp(-2 pi^2 sigma^2 / p^2) = 0.5` at p = 12,
 * which is a filter 1.54x narrower than the one that runs: at 12px the real
 * cascade passes 0.15 of the amplitude, not 0.5.
 *
 * **The admission floor does not come from that formula.** It comes from
 * measuring a grating at the 12px mark pitch through this exact filter, which
 * is why the wrong sigma cost nothing: the calibration never used it. Anyone
 * moving the pitch floor should re-measure the same way rather than re-derive
 * a sigma.
 *
 * **That is prose, and prose is not a mechanism.** The same diff that wrote
 * this replaced six literals in `tests/setup.ts` with an extraction, on exactly
 * that reasoning, and left this one as a paragraph. Ten lines would pin it: a
 * calibration test building the 12px pitch, 2.4px wide grating and asserting it
 * measures the floor, and the 4px, 1.2px one and asserting it falls well under.
 * Both numbers are already measured and are in the header. It is not built now
 * because the filter and the floor have moved together exactly once and a test
 * written in the same hour as the thing it checks tends to encode the mistake;
 * **the moment to add it is when the eleventh pattern is admitted**, which is
 * the first time anyone will have a reason to touch either number.
 */
const BLUR_RADIUS = 3;

function blur(field: Float32Array, size: number): Float64Array {
  const radius = BLUR_RADIUS;
  let current = Float64Array.from(field);
  const next = new Float64Array(field.length);
  for (let pass = 0; pass < 3; pass += 1) {
    for (const horizontal of [true, false]) {
      const width = radius * 2 + 1;
      for (let a = 0; a < size; a += 1) {
        for (let b = 0; b < size; b += 1) {
          let total = 0;
          for (let offset = -radius; offset <= radius; offset += 1) {
            const c = (((b + offset) % size) + size) % size;
            total += horizontal
              ? current[a * size + c]!
              : current[c * size + a]!;
          }
          const index = horizontal ? a * size + b : b * size + a;
          next[index] = total / width;
        }
      }
      current = Float64Array.from(next);
    }
  }
  return current;
}

/**
 * How much structure survives being seen from across the room.
 *
 * The RMS contrast of the tile's ink after that blur, as a fraction of its own
 * mean, so it says the same thing about a faint pattern and a heavy one. Zero
 * means every part of the tile carries the same ink at the scale the eye
 * resolves, which is a flat wash however strongly it is drawn: the pattern is
 * there, and nobody can see it is there.
 *
 * The field wraps, and so does the blur. A window at the seam has to see both
 * edges, because a reader does.
 */
export function tintContrast(field: Float32Array, size: number): number {
  const seen = blur(field, size);
  let total = 0;
  for (const value of seen) total += value;
  const mean = total / seen.length;
  if (mean === 0) return 0;
  let variance = 0;
  for (const value of seen) variance += (value - mean) ** 2;
  return Math.sqrt(variance / seen.length) / mean;
}
