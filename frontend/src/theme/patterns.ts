/**
 * Wallpaper: five William Morris repeats and five decorated papers.
 *
 * The second half are the papers a book is actually bound with: a marbled
 * nonpareil, two Japanese repeats, an Insular plait and a Persian marquetry
 * field. They are here for the same reason the Morris repeats are, and they
 * pull the engine in the other direction: a Morris tile is grown along curves
 * and a decorated paper is set out on a lattice, so between them they need both
 * halves of what is below.
 *
 * Drawn here rather than shipped as images, for three reasons. Morris designs
 * themselves are public domain (he died in 1896), but the high-resolution scans
 * that circulate are mostly museum photographs published under their own terms,
 * so "it is a Morris" is not on its own a licence. A tileable SVG is a few
 * kilobytes against a few hundred for a repeating raster, and it takes its
 * colour from the theme instead of needing a second file for dark mode.
 *
 * ## The foliage is grown along the stems, not placed beside them
 *
 * The first attempt at this hand-placed each leaf at a chosen coordinate. Two
 * things went wrong and both are visible immediately: the leaves float free of
 * the branches they are supposed to be growing from, and hand-placing enough of
 * them to reach the density of a real repeat is not something anybody sustains,
 * so the pattern comes out sparse and reads as a lattice with stamps on it.
 *
 * So a stem here is *data*, a list of cubic segments, and both the drawn path
 * and the placement of every leaf on it come from that same list. Leaves are
 * sampled along the curve and rotated to its tangent, which is why they sit on
 * the branch and lie along it. Density is then a number rather than an hour of
 * placing shapes.
 *
 * ## Planes, because one weight reads as clip art
 *
 * A repeat is never a single plane of motifs. There is a **ground**: the slow
 * meandering structure that carries the eye around the tile. There is an
 * **under** plane of foliage behind the foliage, which is depth rather than
 * more leaves. There is the **foliage** itself, drawn stronger. And there is
 * the **bloom**: the few flowers or berries that anchor the design, stronger
 * again and rare. A pattern declares only the planes it has, so a design with
 * no flower in it has two or three. Flattening the weights into one is what
 * turns an arabesque into a scatter of shapes.
 *
 * ## A motif is written once
 *
 * Willow places two shapes 166 times, Asanoha places one 84 times, and the
 * plait places its lozenge 32 times. Written out at every placement that is
 * kilobytes of repeated `d` attributes, and it is what makes detail
 * unaffordable, because a detail costs its own bytes times every instance. Each
 * shape goes into `<defs>` once and every placement is a `<use>`, so detail is
 * paid for once and the tile gets smaller as it gets more intricate.
 *
 * ## How strongly a layer is drawn is solved, not written down
 *
 * A layer states a **weight**, which is how far one of its marks should move
 * the page, in OKLab lightness. The opacity that reaches it is solved against
 * the palette's own ink and page. It has to be that way round: the ink follows
 * the palette, and one opacity over seven inks is seven different weights,
 * measured 1.27x apart in light and 1.32x in dark, which is the width of the
 * whole budget the tile is supposed to sit inside.
 *
 * ## Motifs are spaced along the curve, not along the parameter
 *
 * `grow` places one motif every `spacing` px of arc. It used to place a count
 * per cubic, which made density and segment count one variable: refining a stem
 * silently multiplied its foliage, so no judgement about intricacy could be made
 * without changing two things at once.
 *
 * ## Seamlessness is structural, not hand-placed
 *
 * Each layer is defined once and `<use>`d at nine offsets, so the tile is drawn
 * surrounded by its own neighbours and the viewBox clips the overhang. Motifs
 * can then run off any edge and reappear correctly on the opposite one, which
 * is what lets the stems be drawn as continuous growth rather than as shapes
 * carefully kept clear of the boundary.
 *
 * ## Anything that varies with position must be periodic in the tile
 *
 * The nine offsets handle a *shape* that crosses an edge. They do nothing for a
 * *quantity* that varies across the tile, and there are three of those here
 * already: the marbling's sine frequencies, the pitch of a lattice, and the
 * density a stem carries its foliage at. For any of them, seamlessness is one
 * condition:
 *
 * > `f(x + size, y) = f(x, y)` and `f(x, y + size) = f(x, y)`.
 *
 * A function built from harmonics of `2 pi / size` satisfies it, which is why
 * `flow` refuses a non-integer cycle count. A pitch satisfies it when it
 * divides `size`, which is why `lattice` throws when it does not. A monotonic
 * gradient across the tile satisfies it for no value at all, and produces a
 * visible band at every repeat.
 *
 * **A function of the branch parameter is seamless for free**, because all nine
 * copies draw the same branch. Only a function of absolute position needs the
 * condition. That is what makes density along a stem, which is deferred rather
 * than impossible, cost nothing to make correct when somebody wants it.
 *
 * It is written here once because it was discovered twice, in two
 * pattern-specific comments, and it is a property of the tiling rather than of
 * either pattern.
 *
 * They are still wallpaper: faint enough to give the page a texture at arm's
 * length, not enough to compete with a book cover.
 */

import type { ResolvedTheme } from "./index";
import { parseHex, solveAlpha } from "./oklab";
import { PAGE_TOKEN } from "./palettes";

/**
 * The weights a layer can be drawn at, faintest first.
 *
 * `under` is foliage drawn behind the foliage: the mass of small leaves a
 * Morris repeat has between its stems, which reads as depth rather than as more
 * leaves. It is a separate weight and not a fainter foliage because the order
 * matters, and the order is what this list is.
 */
export type LayerWeight = "ground" | "under" | "foliage" | "bloom";

export interface Layer {
  /** Which weight it is drawn at. `TARGETS` holds what that weight means. */
  weight: LayerWeight;
  /**
   * The layer body. `{ink}` and `{bloom}` are substituted for its colours, so a
   * pattern names no colour of its own.
   */
  body: string;
}

/**
 * Which group a pattern belongs to.
 *
 * The split is editorial rather than technical: a Morris repeat is a wallpaper
 * and a decorated paper is what is pasted inside the board of a book. The
 * picker will show it as two headings; what it already does is scope the one
 * rule that cannot apply to both, in `patterns.test.ts`. A repeat is admitted
 * partly on how densely it is grown, and a plait grown densely is not a plait.
 */
export type PatternFamily = "morris" | "papers";

export interface Pattern {
  /** Stable id, used as the storage key and in tests. */
  id: string;
  /** The historical title of the design, or the tradition it is drawn from. */
  name: string;
  /** Which heading it sits under. */
  family: PatternFamily;
  /** Tile size in px. Larger reads as wallpaper, smaller as noise. */
  size: number;
  /** One `<path id>` per distinct motif, however many times it is placed. */
  defs: string;
  /** Faintest first: `patternDataUri` draws them in this order. */
  layers: Layer[];
}

/**
 * Interns the motifs a pattern draws.
 *
 * A shape is defined by being placed, so nothing can reach `<defs>` that no
 * layer references and no `<use>` can point at a definition that is not there.
 */
export interface MotifSet {
  /** The id for a shape, defining it on first use. */
  id(shape: string): string;
  /** The `<defs>` body: every shape once, in first-use order. */
  defs(): string;
}

function motifSet(): MotifSet {
  const ids = new Map<string, string>();
  return {
    id(shape) {
      const existing = ids.get(shape);
      if (existing !== undefined) return existing;
      const next = `m${ids.size}`;
      ids.set(shape, next);
      return next;
    },
    defs() {
      return [...ids]
        .map(([shape, id]) => `<path id="${id}" d="${shape}"/>`)
        .join("");
    },
  };
}

// ── Curves ────────────────────────────────────────────────────────────────────

export type Point = [number, number];

/** One cubic Bezier: start, two control points, end. */
export type Cubic = [Point, Point, Point, Point];

/** A branch is a run of cubics sharing endpoints. */
export type Branch = Cubic[];

function pointAt([p0, p1, p2, p3]: Cubic, t: number): Point {
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const d = t * t * t;
  return [
    a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
  ];
}

/** The curve's direction at `t`, in degrees, for rotating a motif onto it. */
function angleAt([p0, p1, p2, p3]: Cubic, t: number): number {
  const u = 1 - t;
  const a = 3 * u * u;
  const b = 6 * u * t;
  const c = 3 * t * t;
  const dx = a * (p1[0] - p0[0]) + b * (p2[0] - p1[0]) + c * (p3[0] - p2[0]);
  const dy = a * (p1[1] - p0[1]) + b * (p2[1] - p1[1]) + c * (p3[1] - p2[1]);
  return (Math.atan2(dy, dx) * 180) / Math.PI;
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}

/** The `d` attribute for a branch. */
function branchPath(branch: Branch): string {
  const [first] = branch;
  if (!first) return "";
  const start = `M${round(first[0][0])} ${round(first[0][1])}`;
  const curves = branch
    .map(
      ([, c1, c2, end]) =>
        `C${round(c1[0])} ${round(c1[1])} ${round(c2[0])} ${round(c2[1])} ` +
        `${round(end[0])} ${round(end[1])}`,
    )
    .join("");
  return start + curves;
}

function stems(branches: Branch[], width: number): string {
  const paths = branches
    .map((branch) => `<path d="${branchPath(branch)}"/>`)
    .join("");
  return stroked(paths, width);
}

/**
 * A branch measured by arc length.
 *
 * Sampling uniformly in the Bezier parameter is not sampling uniformly along the
 * curve: motifs bunch where the curve is slow. On the stems as they stand that
 * is worth 1.14x on Pimpernel's ogee and nothing on the other three, which is
 * why nobody has needed it. It stops being true the moment a branch gains
 * segments: refining Willow's serpentine from two cubics to four takes its
 * spacing spread from 1.01x to 2.83x. Remove this and the next person to add a
 * cubic gets a bunched stem and twice the leaves.
 */
export interface Arc {
  /** Total length in px. */
  length: number;
  /** Position and tangent at a distance along the whole branch. */
  at(distance: number): { x: number; y: number; angle: number };
}

/** Samples per cubic. 16 measures these curves to well under a pixel. */
const ARC_SAMPLES = 16;

interface Mark {
  distance: number;
  segment: Cubic;
  t: number;
}

export function measure(branch: Branch): Arc {
  const marks: Mark[] = [];
  let total = 0;

  for (const segment of branch) {
    if (marks.length === 0) marks.push({ distance: 0, segment, t: 0 });
    let previous = pointAt(segment, 0);
    for (let step = 1; step <= ARC_SAMPLES; step += 1) {
      const t = step / ARC_SAMPLES;
      const point = pointAt(segment, t);
      total += Math.hypot(point[0] - previous[0], point[1] - previous[1]);
      marks.push({ distance: total, segment, t });
      previous = point;
    }
  }

  return {
    length: total,
    at(distance) {
      let index = 1;
      while (index < marks.length - 1 && marks[index]!.distance < distance) {
        index += 1;
      }
      const before = marks[index - 1]!;
      const after = marks[index]!;
      const span = after.distance - before.distance;
      const fraction = span > 0 ? (distance - before.distance) / span : 0;
      // Across a segment boundary the two marks are in different cubics, and
      // the earlier one is the later one's t=0: the endpoints are shared, so
      // interpolating from zero is exact rather than approximate.
      const from = before.segment === after.segment ? before.t : 0;
      const t = from + (after.t - from) * fraction;
      const [x, y] = pointAt(after.segment, t);
      return { x, y, angle: angleAt(after.segment, t) };
    },
  };
}

interface GrowOptions {
  /** The motif, drawn around the origin pointing along +x. */
  shape: string;
  /** Px between motifs, measured along the branch rather than per cubic. */
  spacing: number;
  /** Degrees off the tangent. Positive leans one way, negative the other. */
  lean?: number;
  /** Alternate the lean side down the branch, as a real stem does. */
  alternate?: boolean;
  /** Motif scale, or a pair cycled through for a less mechanical run. */
  scale?: number | number[];
  /** Skip the first and last fraction of the branch, where branches meet. */
  inset?: number;
  /**
   * What the scale is multiplied by at the far end of the branch.
   *
   * A stem thins as it grows and its leaves get smaller with it. Below 1 the
   * run tapers toward the tip, which is what a real branch does and what the
   * scale cycle alone cannot express: a cycle repeats, and growth does not.
   */
  taper?: number;
  /**
   * How far a placement may wander, as a fraction of the spacing.
   *
   * Seeded from the placement's own position, never from a counter and never
   * from `Math.random`. Two things depend on that: the tile has to render
   * identically on every call or the browser re-rasterises the background
   * continuously, and a placement's wander must not change when a placement
   * before it is added or removed.
   */
  jitter?: number;
}

/**
 * A deterministic number in [0, 1) from a position.
 *
 * FNV-1a over the coordinates, quantised to a sixteenth of a pixel. It is here
 * for two jobs. It seeds the jitter, and it phases the lean and scale cycles,
 * where it replaced `Math.round(x + y)`.
 *
 * That replacement fixes half of a defect the old comment recorded. A linear
 * phase collapses whenever two congruent branches are a multiple of the cycle
 * length apart, which is why Strawberry's two climbing stems came out
 * pixel-identical; a hash is not linear in the position, so a translation is
 * not a translation of the phase, and the two now differ from their first leaf.
 *
 * It does not fix the other half and cannot. A two-value scale cycle matches on
 * half its phases whatever function chooses them, so two congruent branches
 * still coincide half the time. What fixes that is the jitter, which is a
 * function of the position rather than of a phase, and it is why every run with
 * a two-value cycle asks for some.
 */
function seed(...values: number[]): number {
  let hash = 2166136261;
  for (const value of values) {
    hash ^= Math.round(value * 16) | 0;
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 8) & 0xffff) / 0x10000;
}

/** One placement of a defined motif. */
function place(
  href: string,
  x: number,
  y: number,
  rotation: number,
  size: number,
): string {
  const turn = round(rotation);
  return (
    `<use href="#${href}" transform="translate(${round(x)} ${round(y)})` +
    (turn === 0 ? "" : ` rotate(${turn})`) +
    (size === 1 ? "" : ` scale(${size})`) +
    `"/>`
  );
}

/**
 * Place motifs along a branch, rotated onto its tangent.
 *
 * This is the whole reason the patterns look like plants: a leaf inherits the
 * direction of the stem it grows from, so a run of them follows the curve
 * instead of pointing wherever it was typed.
 */
function grow(
  motifs: MotifSet,
  branches: Branch[],
  options: GrowOptions,
): string {
  const {
    shape,
    spacing,
    lean = 55,
    alternate = true,
    scale = 1,
    inset = 0.08,
    taper = 1,
    jitter = 0,
  } = options;
  const href = motifs.id(shape);
  const scales = Array.isArray(scale) ? scale : [scale];

  const parts: string[] = [];

  for (const branch of branches) {
    const arc = measure(branch);
    const usable = arc.length * (1 - 2 * inset);
    const count = Math.max(1, Math.round(usable / spacing) + 1);
    // Where the lean and scale cycles start, taken from where the branch does.
    //
    // The cycles used to run off a counter shared by every branch in the call,
    // so which side a leaf leaned to depended on how many motifs happened to be
    // emitted before it and adding one twig flipped every leaf downstream.
    // Restarting them at zero per branch fixes that and introduces the opposite
    // fault: congruent branches come out pixel-identical, and Willow has two
    // serpentines that are the same curve 130px apart. Phasing from the start
    // point separates them without making either depend on the others.
    const origin = branch[0]?.[0] ?? [0, 0];
    const phase = Math.floor(seed(origin[0], origin[1]) * 1024);

    for (let step = 0; step < count; step += 1) {
      const even =
        arc.length * inset +
        (count === 1 ? usable / 2 : (usable * step) / (count - 1));
      // Wander from the even spacing, never past half of it: two motifs that
      // swapped places would cross their own stem.
      const wander = jitter
        ? (seed(origin[0], origin[1], step) - 0.5) * jitter * spacing
        : 0;
      const along = Math.max(0, Math.min(arc.length, even + wander));
      const { x, y, angle } = arc.at(along);
      const cycle = step + phase;
      const side = alternate && cycle % 2 === 1 ? -1 : 1;
      // The taper runs on the even position rather than the jittered one, so
      // moving a leaf does not also resize it.
      const grown = count === 1 ? 1 : step / (count - 1);
      const shrink = 1 + (taper - 1) * grown;
      const wobble = jitter
        ? 1 + (seed(step, origin[1], origin[0]) - 0.5) * jitter
        : 1;
      parts.push(
        place(
          href,
          x,
          y,
          angle + lean * side,
          Math.round(scales[cycle % scales.length]! * shrink * wobble * 100) / 100,
        ),
      );
    }
  }
  return parts.join("");
}

/** A placement of one motif, for the few that are positioned deliberately. */
interface At {
  x: number;
  y: number;
  r?: number;
  s?: number;
}

/** Stamp a shape at chosen points, for blooms that anchor a repeat. */
function scatter(motifs: MotifSet, shape: string, placements: At[]): string {
  const href = motifs.id(shape);
  return placements
    .map(({ x, y, r = 0, s = 1 }) => place(href, x, y, r, s))
    .join("");
}

/**
 * Wrap motifs in the bloom colour.
 *
 * Every filled motif takes `{bloom}`, so the leaves are rose and only the stems
 * are ink. That is deliberate and long-standing rather than an oversight, and it
 * is the reason `bloom` names two things in this file: a layer weight, and the
 * colour every motif is painted in whatever weight it is drawn at.
 *
 * Splitting the flowers into their own layer is what makes the leaf colour
 * changeable at all, since the two can now be painted separately. Which colour
 * a leaf should be is deferred on purpose: at the tile mean the difference
 * measures 0.0026 to 0.0058 in OKLab, which is below anything worth arguing
 * about, so it is a decision to be taken by looking at it once.
 *
 * No veins. A midrib is buildable here for about fifty bytes, as a closed
 * sliver inside the leaf's own outline knocked out by `fill-rule="evenodd"`,
 * and it was built and measured before being taken out again: on Pimpernel it
 * removes 4.4% of the foliage's ink and moves the tile's tint contrast by
 * 0.35%, from 1.696 to 1.690, against an admission floor of 0.196. It is real
 * ink that changes nothing anybody can see, which is the definition of detail
 * that does not survive the scale it is drawn at. See `docs/decisions.md`.
 */
function filled(body: string): string {
  return `<g fill="{bloom}">${body}</g>`;
}

/**
 * Wrap marks in a stroke.
 *
 * The papers are drawn almost entirely in line rather than in mass, so this is
 * to them what `filled` is to the Morris repeats. `stems` is the same wrapper
 * with the branch drawing built in.
 */
function stroked(body: string, width: number, colour = "{ink}"): string {
  return (
    `<g fill="none" stroke="${colour}" stroke-width="${width}" ` +
    `stroke-linecap="round">${body}</g>`
  );
}

// ── Primitives for the decorated papers ─────────────────────────────────

/** How a lattice is laid out. See `lattice`. */
export interface LatticeOptions {
  /**
   * Offset every other row by half a column.
   *
   * What interlocks Seigaiha's fans into scales and what makes Asanoha's
   * hexagons a honeycomb rather than a grid of them. It is an option here and
   * not two lines at the call site because of what it costs to get wrong: the
   * offset repeats every two rows, so a tile with an **odd** number of rows
   * puts two unstaggered rows next to each other across the seam and the
   * lattice breaks in a band on every repeat.
   *
   * Asanoha shipped like that. Seven rows on a 420px tile, `row % 2` applied by
   * hand, and a 60px band of broken honeycomb at every tile boundary: 14% of
   * the page, visible in a render, and invisible to every test.
   */
  stagger?: boolean;
}

/**
 * Place a unit at every cell of a grid.
 *
 * Two invariants, both exceptions rather than tests, because both produce a
 * seam that is invisible in a diff, obvious on a page, and reachable only
 * through this one function.
 *
 * **The pitch must divide the extent**, or the cells do not meet across the
 * seam. Said honestly, this check is weaker than it looks: a caller that
 * derives its extent from its own pitch, as Asanoha does, satisfies it by
 * construction and learns nothing. It catches a typed pitch, not a wrong
 * layout.
 *
 * **A staggered lattice needs an even number of rows**, which is the one that
 * actually caught something. The pitch check could never have: it was cited as
 * the guard on Asanoha's seamlessness and it was vacuous for exactly that
 * pattern.
 */
export function lattice(
  size: number | { x: number; y: number },
  pitch: { x: number; y: number },
  unit: (cell: { x: number; y: number; column: number; row: number }) => string,
  options: LatticeOptions = {},
): string {
  // A pair rather than one number, because Asanoha's lattice is laid out in a
  // taller space than the tile and squashed into it afterwards. See the note on
  // the squash: the repeat has to be exact in the space the cells are counted
  // in, which for that pattern is not the tile.
  const extent = typeof size === "number" ? { x: size, y: size } : size;
  const columns = extent.x / pitch.x;
  const rows = extent.y / pitch.y;
  for (const [axis, count] of [["x", columns], ["y", rows]] as const) {
    if (Math.abs(count - Math.round(count)) > 1e-9) {
      throw new Error(
        `lattice pitch ${axis}=${pitch[axis]} does not divide ${extent[axis]}`,
      );
    }
  }
  if (options.stagger && Math.round(rows) % 2 !== 0) {
    throw new Error(
      `lattice: a staggered lattice needs an even row count, not ${Math.round(rows)}`,
    );
  }

  const parts: string[] = [];
  for (let column = 0; column < Math.round(columns); column += 1) {
    for (let row = 0; row < Math.round(rows); row += 1) {
      const shift = options.stagger && row % 2 === 1 ? pitch.x / 2 : 0;
      parts.push(
        unit({ x: column * pitch.x + shift, y: row * pitch.y, column, row }),
      );
    }
  }
  return parts.join("");
}

export interface RadialOptions {
  /** How many copies. */
  count: number;
  /** Degrees between them. 360 / count closes the ring; less makes a fan. */
  spread: number;
  /** One scale, or a cycle through several. */
  scale?: number | number[];
}

/**
 * A ring or a fan of one motif about a point.
 *
 * Written for Golden Lily, whose flowers were twenty four hand placed petals in
 * eight groups of three: the same three rotations and scales retyped with a new
 * origin, so a change to the flower meant twenty four edits and a recount. Eight
 * calls say the same thing, and the fact that a lily has three petals is then
 * stated once.
 */
export function radial(
  motifs: MotifSet,
  shape: string,
  at: At,
  options: RadialOptions,
): string {
  const { count, spread, scale = 1 } = options;
  const scales = Array.isArray(scale) ? scale : [scale];
  const href = motifs.id(shape);
  const centre = at.r ?? 0;
  // Centred on the placement's own rotation, so a fan of three points where the
  // flower points and a ring of eight is unaffected by where it starts.
  const first = centre - (spread * (count - 1)) / 2;
  const parts: string[] = [];
  for (let step = 0; step < count; step += 1) {
    const angle = first + spread * step;
    parts.push(
      place(href, at.x, at.y, angle, (at.s ?? 1) * scales[step % scales.length]!),
    );
  }
  return parts.join("");
}

/** One harmonic of a wave. See the note on periodicity in the header. */
export interface Harmonic {
  /** Cycles across the tile. An integer, or the wave does not meet itself. */
  cycles: number;
  amplitude: number;
  /** Degrees. */
  phase: number;
}

/**
 * A wave across the tile, as cubics.
 *
 * Emitted from the analytic slope at each sample rather than from the points
 * alone, so a dozen samples describe the curve as well as fifty points would:
 * the tangent is known everywhere, so each span is a Hermite segment and the
 * only error is in the curvature between samples.
 */
export function flow(size: number, harmonics: Harmonic[], samples = 24): string {
  for (const { cycles } of harmonics) {
    if (!Number.isInteger(cycles)) {
      throw new Error(`flow cycles ${cycles} is not periodic in the tile`);
    }
  }
  const at = (x: number): [number, number] => {
    let y = 0;
    let slope = 0;
    for (const { cycles, amplitude, phase } of harmonics) {
      const w = (2 * Math.PI * cycles) / size;
      const angle = w * x + (phase * Math.PI) / 180;
      y += amplitude * Math.sin(angle);
      slope += amplitude * w * Math.cos(angle);
    }
    return [y, slope];
  };

  const step = size / samples;
  const [y0] = at(0);
  let path = `M0 ${round(y0)}`;
  for (let index = 0; index < samples; index += 1) {
    const x0 = index * step;
    const x1 = x0 + step;
    const [ya, ma] = at(x0);
    const [yb, mb] = at(x1);
    path +=
      `C${round(x0 + step / 3)} ${round(ya + (ma * step) / 3)} ` +
      `${round(x1 - step / 3)} ${round(yb - (mb * step) / 3)} ` +
      `${round(x1)} ${round(yb)}`;
  }
  return path;
}

/**
 * Branches and their reflection in the tile's centre line.
 *
 * Branches rather than a body, because a stem is used twice: once to be drawn
 * and once to grow foliage along. Reflecting the drawn output would give a
 * mirrored stem carrying unmirrored leaves.
 *
 * The reflection reverses the winding, which matters to nothing here: `grow`
 * takes the tangent from the reflected curve, so the leaves lie along it either
 * way, and a leaf is not chiral.
 */
export function mirror(
  branches: Branch[],
  size: number,
  axis: "x" | "y",
): Branch[] {
  const flip = ([x, y]: Point): Point =>
    axis === "x" ? [size - x, y] : [x, size - y];
  return branches.map(
    (branch) => branch.map((cubic) => cubic.map(flip) as Cubic) as Branch,
  );
}

/**
 * The two edges of a band following a branch, broken where it passes under.
 *
 * This is how the plait draws over and under, and it is the whole reason that
 * pattern is possible at all: a transparent wallpaper has no ground colour to
 * hide behind, so the strand that goes under cannot be occluded by the one that
 * goes over. It is interrupted instead, which is what a scribe does with a pen.
 *
 * `spans` are the fractions of the branch's length where the band is visible,
 * so the gaps between them are the crossings it passes under.
 *
 * The width is one number and not a function of the arc. A width that varies
 * along the branch is what a tapering Morris stem needs, and the Morris stems
 * stayed stroked: measured, the taper moves nothing that the underfoliage plane
 * does not, and it changes all five silhouettes at once. Generality nothing
 * calls is generality nobody has checked.
 */
export function ribbon(
  branch: Branch,
  width: number,
  spans: [number, number][] = [[0, 1]],
): string {
  const arc = measure(branch);
  const parts: string[] = [];

  for (const [from, to] of spans) {
    if (to - from < 1e-6) continue;
    const length = arc.length * (to - from);
    // A sample every 12px of arc. The only caller draws straight bands, where
    // one span would do; the rate is set for a curved strand rather than for
    // the one that ships, because getting it wrong there is a faceted edge and
    // there is nothing to warn whoever writes the next one.
    const steps = Math.max(1, Math.ceil(length / 12));
    const edges: [Point[], Point[]] = [[], []];
    for (let step = 0; step <= steps; step += 1) {
      const t = from + ((to - from) * step) / steps;
      const { x, y, angle } = arc.at(arc.length * t);
      const radians = (angle * Math.PI) / 180;
      const half = width / 2;
      const nx = -Math.sin(radians) * half;
      const ny = Math.cos(radians) * half;
      edges[0].push([x + nx, y + ny]);
      edges[1].push([x - nx, y - ny]);
    }
    for (const edge of edges) {
      parts.push(
        `M${round(edge[0]![0])} ${round(edge[0]![1])}` +
          edge
            .slice(1)
            .map(([x, y]) => `L${round(x)} ${round(y)}`)
            .join(""),
      );
    }
  }
  return parts.join("");
}

/**
 * A circular arc, as cubics.
 *
 * Not an `A` command. Everything downstream that reads these paths, the
 * coverage measure and the rasteriser the admission rule uses, understands
 * `M`, `L`, `C`, `Q` and `Z`, and a command none of them handles would be
 * measured as nothing at all and quietly report a lighter tile than ships.
 */
function arcPath(radius: number, fromDegrees: number, toDegrees: number): string {
  const total = ((toDegrees - fromDegrees) * Math.PI) / 180;
  const segments = Math.max(1, Math.ceil(Math.abs(total) / (Math.PI / 2)));
  const step = total / segments;
  // The control point offset that makes a cubic match a circular arc, exact at
  // the endpoints and within 0.02% of the radius in between for a quadrant.
  const k = (4 / 3) * Math.tan(step / 4) * radius;
  const start = (fromDegrees * Math.PI) / 180;
  const point = (angle: number): Point => [
    radius * Math.cos(angle),
    radius * Math.sin(angle),
  ];
  const [x0, y0] = point(start);
  let path = `M${round(x0)} ${round(y0)}`;
  for (let index = 0; index < segments; index += 1) {
    const a = start + step * index;
    const b = a + step;
    const [ax, ay] = point(a);
    const [bx, by] = point(b);
    path +=
      `C${round(ax - k * Math.sin(a))} ${round(ay + k * Math.cos(a))} ` +
      `${round(bx + k * Math.sin(b))} ${round(by - k * Math.cos(b))} ` +
      `${round(bx)} ${round(by)}`;
  }
  return path;
}

/** A star polygon outline: `points` outer vertices alternating with inner ones. */
function starPath(points: number, outer: number, inner: number): string {
  const vertices: Point[] = [];
  for (let index = 0; index < points * 2; index += 1) {
    const angle = (Math.PI * index) / points - Math.PI / 2;
    const radius = index % 2 === 0 ? outer : inner;
    vertices.push([radius * Math.cos(angle), radius * Math.sin(angle)]);
  }
  return (
    `M${round(vertices[0]![0])} ${round(vertices[0]![1])}` +
    vertices
      .slice(1)
      .map(([x, y]) => `L${round(x)} ${round(y)}`)
      .join("") +
    "Z"
  );
}

// ── Motifs ────────────────────────────────────────────────────────────────────
//
// Each is drawn around the origin and points along +x, so `grow` can rotate one
// onto any tangent without the shape's own geometry mattering.

/** The long pointed leaf of a willow: a lens, slightly recurved. */
const WILLOW_LEAF = "M0 0Q12 -6 25 -2Q12 5 0 0Z";

/** A broad leaf with a rounded tip, for the heavier designs. */
const ROUND_LEAF = "M0 0C6 -11 20 -11 27 0C20 11 6 11 0 0Z";

/** A serrated leaf: the same broad shape with the edge cut, as Morris drew it. */
const CUT_LEAF =
  "M0 0C5 -8 11 -12 17 -11C15 -7 16 -5 20 -5C18 -1 19 1 23 2C18 6 12 9 6 8C6 5 4 2 0 0Z";

/** An acanthus lobe: the curled, deeply cut leaf the whole style is built on. */
const ACANTHUS =
  "M0 0C10 -13 25 -16 37 -9C28 -5 21 3 15 13C11 21 5 24 0 21C5 13 5 7 0 0Z";

/** A tulip-shaped bloom, seen side on, as in Pimpernel. */
const BLOOM =
  "M0 0C1 -11 8 -19 18 -20C15 -14 14 -8 15 -2C19 -6 24 -7 28 -5C24 1 18 6 11 8C5 9 1 6 0 0Z";

/** A lily petal, longer and more recurved than the bloom. */
const PETAL = "M0 0C3 -14 14 -23 25 -20C17 -10 13 -1 11 10C6 8 2 4 0 0Z";

/** A strawberry, with its shoulders where the calyx sits. */
const BERRY = "M0 0C9 -8 18 -3 16 7C14 16 5 20 -2 16C-8 11 -7 5 0 0Z";

/** A small bud or seed head, for filling the gaps a repeat leaves. */
const BUD = "M0 0C3 -6 10 -6 14 0C10 6 3 6 0 0Z";

// ── The designs ───────────────────────────────────────────────────────────────

/** A serpentine climbing the full height of a tile, returning to its own x. */
function serpentine(x: number, size: number, sway: number): Branch {
  const quarter = size / 4;
  return [
    [
      [x, 0],
      [x + sway, quarter * 0.6],
      [x + sway, quarter * 1.4],
      [x, size / 2],
    ],
    [
      [x, size / 2],
      [x - sway, size / 2 + quarter * 0.6],
      [x - sway, size / 2 + quarter * 1.4],
      [x, size],
    ],
  ];
}

/** A twig leaving a stem, which is where most of the foliage actually hangs. */
function twig(from: Point, to: Point, bow: number): Branch {
  const [x0, y0] = from;
  const [x1, y1] = to;
  const midX = (x0 + x1) / 2;
  const midY = (y0 + y1) / 2;
  const dx = x1 - x0;
  const dy = y1 - y0;
  const length = Math.hypot(dx, dy) || 1;
  const normal: Point = [(-dy / length) * bow, (dx / length) * bow];
  return [
    [
      from,
      [x0 + dx * 0.25 + normal[0], y0 + dy * 0.25 + normal[1]],
      [midX + normal[0], midY + normal[1]],
      to,
    ],
  ];
}

const WILLOW_SIZE = 260;
const WILLOW_STEMS: Branch[] = [
  serpentine(30, WILLOW_SIZE, 22),
  serpentine(95, WILLOW_SIZE, -22),
  serpentine(160, WILLOW_SIZE, 22),
  serpentine(225, WILLOW_SIZE, -22),
];
const WILLOW_TWIGS: Branch[] = [
  twig([30, 40], [96, 12], 16),
  twig([95, 100], [30, 128], -16),
  twig([160, 40], [96, 68], 16),
  twig([225, 100], [162, 128], -16),
  twig([30, 170], [96, 142], 16),
  twig([95, 230], [30, 258], -16),
  twig([160, 170], [96, 198], 16),
  twig([225, 230], [162, 258], -16),
  twig([160, 220], [226, 192], 14),
  twig([95, 90], [160, 62], -14),
];

const ACANTHUS_SIZE = 300;
/** Two counter-scrolling waves crossing at the centre, the classic ogee. */
const ACANTHUS_STEMS: Branch[] = [
  [
    [
      [0, 150],
      [50, 90],
      [100, 90],
      [150, 150],
    ],
    [
      [150, 150],
      [200, 210],
      [250, 210],
      [300, 150],
    ],
  ],
  [
    [
      [150, 0],
      [90, 50],
      [90, 100],
      [150, 150],
    ],
    [
      [150, 150],
      [210, 200],
      [210, 250],
      [150, 300],
    ],
  ],
  [
    [
      [0, 0],
      [46, 34],
      [74, 22],
      [104, -18],
    ],
  ],
  [
    [
      [300, 300],
      [254, 266],
      [226, 278],
      [196, 318],
    ],
  ],
];
const ACANTHUS_TWIGS: Branch[] = [
  twig([150, 150], [232, 118], 26),
  twig([150, 150], [68, 182], 26),
  twig([0, 150], [46, 236], -22),
  twig([300, 150], [254, 64], -22),
  twig([150, 0], [232, 34], 20),
  twig([150, 300], [68, 266], 20),
];

const PIMPERNEL_SIZE = 280;
/** Half an ogee: one wave from corner to corner, bulging to the centre line. */
const PIMPERNEL_WAVE: Branch = [
  [
    [0, 0],
    [4, 78],
    [140, 62],
    [140, 140],
  ],
  [
    [140, 140],
    [140, 218],
    [4, 202],
    [0, 280],
  ],
];
/**
 * An ogee: two mirrored waves enclosing a pointed oval around each bloom.
 *
 * The second was the first retyped with every x subtracted from 280, which is
 * the same twelve control points written twice and a licence for the two halves
 * to drift apart under any edit. `mirror` states the symmetry instead, which is
 * the fact the design has.
 */
const PIMPERNEL_STEMS: Branch[] = [
  PIMPERNEL_WAVE,
  ...mirror([PIMPERNEL_WAVE], PIMPERNEL_SIZE, "x"),
];
const PIMPERNEL_TWIGS: Branch[] = [
  twig([140, 140], [88, 66], 22),
  twig([140, 140], [192, 214], 22),
  twig([0, 140], [62, 96], -20),
  twig([280, 140], [218, 184], -20),
  twig([70, 30], [140, 22], 18),
  twig([210, 250], [140, 258], 18),
];

const STRAWBERRY_SIZE = 300;
const STRAWBERRY_STEMS: Branch[] = [
  [
    [
      [0, 70],
      [54, 34],
      [96, 98],
      [150, 76],
    ],
    [
      [150, 76],
      [204, 54],
      [246, 118],
      [300, 82],
    ],
  ],
  [
    [
      [0, 220],
      [54, 184],
      [96, 248],
      [150, 226],
    ],
    [
      [150, 226],
      [204, 204],
      [246, 268],
      [300, 232],
    ],
  ],
  [
    [
      [75, 0],
      [64, 44],
      [106, 66],
      [102, 112],
    ],
    [
      [102, 112],
      [98, 158],
      [54, 180],
      [64, 224],
    ],
    [
      [64, 224],
      [74, 268],
      [44, 288],
      [38, 300],
    ],
  ],
];
/** The second climbing stem is the first one mirrored, so it is said once. */
STRAWBERRY_STEMS.push(
  ...mirror([STRAWBERRY_STEMS[2]!], STRAWBERRY_SIZE, "x"),
);
const STRAWBERRY_TWIGS: Branch[] = [
  twig([102, 112], [164, 140], 18),
  twig([198, 112], [136, 140], -18),
  twig([64, 224], [22, 172], -18),
  twig([236, 224], [278, 172], 18),
  twig([150, 76], [150, 12], 20),
  twig([150, 226], [150, 290], 20),
];

const LILY_SIZE = 280;
const LILY_STEMS: Branch[] = [
  serpentine(70, LILY_SIZE, 32),
  serpentine(210, LILY_SIZE, -32),
];
/** Where a lily sits, and which way it faces. Three petals fan about that. */
const LILY_FLOWERS: At[] = [
  { x: 144, y: 18, r: 6 },
  { x: 136, y: 18, r: 174 },
  { x: -4, y: 86, r: 186 },
  { x: 284, y: 86, r: 6 },
  { x: 144, y: 158, r: 6 },
  { x: 136, y: 158, r: 174 },
  { x: -4, y: 226, r: 186 },
  { x: 284, y: 226, r: 6 },
];
const LILY_TWIGS: Branch[] = [
  twig([70, 36], [144, 18], 18),
  twig([70, 104], [-4, 86], -18),
  twig([70, 176], [144, 158], 18),
  twig([70, 244], [-4, 226], -18),
  twig([210, 36], [136, 18], -18),
  twig([210, 104], [284, 86], 18),
  twig([210, 176], [136, 158], -18),
  twig([210, 244], [284, 226], 18),
];

// ── The decorated papers ──────────────────────────────────────────────────────
//
// Everything below is set out on a lattice rather than grown along a curve, and
// every one of them is periodic in the tile by construction rather than by
// being kept clear of the edges. See the header on what that condition is.

const NONPAREIL_SIZE = 240;
/** Px between combed lines. The admission rule's floor is 12. */
const NONPAREIL_PITCH = 15;
/**
 * One combed line, drawn once and placed sixteen times.
 *
 * Every line in a nonpareil is the same waveform: the comb is drawn through the
 * whole bath in one pass, so what separates one line from the next is where it
 * starts, not what shape it is. Placing one motif at sixteen offsets says that,
 * and it is also what keeps the tile at a few hundred bytes instead of ten
 * thousand.
 *
 * Three harmonics, every one of them a whole number of cycles across the tile,
 * so the wave meets itself at the seam. One slow sway, one ripple and one
 * tremor, and 6 against 13 is deliberately not a multiple of anything: a single
 * frequency reads as corrugated iron and two in ratio read as a braid.
 */
const NONPAREIL_WAVE = flow(NONPAREIL_SIZE, [
  { cycles: 1, amplitude: 4.4, phase: 0 },
  { cycles: 6, amplitude: 3.1, phase: 90 },
  { cycles: 13, amplitude: 1.1, phase: 200 },
]);

/**
 * The comb line at `index`.
 *
 * Every line is the same wave at the same phase, which is not a simplification:
 * a comb is drawn through the bath in one pass, so the lines are parallel
 * because they were made by teeth on one bar.
 *
 * Shifting each line a little along its own length was tried and is wrong twice
 * over. Seamlessness forces the shift to be a multiple of the pitch, which
 * makes every line's crest land on a 45 degree line through its neighbour's,
 * and the eye reads that alignment as a hard diagonal ruled across the paper.
 * And any phase difference between neighbours makes the gap between them vary:
 * at this amplitude a quarter period offset takes two lines 15px apart to 2.3px
 * apart at the worst crossing, which is under the admission rule's floor and
 * looks like a printing fault.
 */
function nonpareilLine(motifs: MotifSet, index: number): string {
  return place(motifs.id(NONPAREIL_WAVE), 0, index * NONPAREIL_PITCH, 0, 1);
}

const SEIGAIHA_SIZE = 240;
/**
 * A fan of three arcs, split across two weights.
 *
 * Three rather than four, and 14px apart rather than 8. A fan of fine
 * concentric arcs is the exact shape the admission rule exists to refuse: it
 * has a strong motif and no resolvable structure, so it reads as a grey tint
 * with a texture you can only see by leaning in.
 *
 * The outer arc carries the wave and is drawn stronger; the two inside it are
 * the ground. That is the same three-weight reasoning the Morris repeats use,
 * and it is what stops eighteen identical fans reading as corrugation.
 */
const SEIGAIHA_CREST = arcPath(48, 180, 360);
const SEIGAIHA_INNER = [34, 20].map((r) => arcPath(r, 180, 360)).join("");
/**
 * Where the fans sit.
 *
 * A crest is 96px across on an 80px pitch, so each fan overlaps the one beside
 * it by 16px. That overlap is the pattern: without it the crests are a row of
 * arches, and with it they are scales.
 */
const SEIGAIHA_PITCH = { x: 80, y: 40 };

const ASANOHA_SIZE = 420;
/** Hexagons across the tile. Seven puts the hemp leaf's triangles at 34.6px. */
const ASANOHA_COLUMNS = 7;
const ASANOHA_RADIUS = ASANOHA_SIZE / (ASANOHA_COLUMNS * Math.sqrt(3));
/**
 * Rows of hexagons per tile.
 *
 * Two conditions, and the second was learned the hard way. The count that would
 * make the hexagons regular is 8.083 at seven columns, and it is irrational for
 * every column count, so it is rounded and the difference is taken out in the
 * squash below. And it **must be even**, because the honeycomb offsets every
 * other row: at seven rows the last row and the first are both unstaggered, and
 * they meet across the seam in a band of broken lattice on every repeat.
 *
 * That shipped, briefly, at six columns and seven rows: a 60px band on a 420px
 * tile, 14% of the page. `lattice` now refuses a staggered odd count rather
 * than leaving the condition to be remembered here.
 */
const ASANOHA_ROWS = 8;
/**
 * The squash that makes a hexagonal lattice fit a square tile.
 *
 * A honeycomb of regular hexagons repeats at `R * sqrt(3)` across and `1.5 * R`
 * down, and the ratio of those two is `2 / sqrt(3)`, which is irrational: no
 * whole number of rows ever lands exactly on a whole number of columns, so a
 * hexagonal pattern in a square tile is seamless at no size at all.
 *
 * So the lattice is built regular and then stretched by the amount it misses
 * by. At seven columns and eight rows that is 1.04%, which is one part in a
 * hundred of a hexagon's height and is not a thing anybody can see, while the
 * seam it removes is a thing anybody can see. Thirteen columns to fifteen rows
 * would miss by 0.073%, fourteen times less, and puts the triangles at 18.7px
 * on this tile, close enough to the admission rule's floor that the pattern
 * stops being a hemp leaf and becomes a mesh. Fifteen is also odd, which the
 * row count may not be.
 */
const ASANOHA_SQUASH =
  ASANOHA_SIZE / ASANOHA_ROWS / (1.5 * ASANOHA_RADIUS);

/** A hexagon's six vertices, pointy top, at the given radius. */
function hexagon(radius: number): Point[] {
  return [0, 1, 2, 3, 4, 5].map((index): Point => {
    const angle = ((-90 + 60 * index) * Math.PI) / 180;
    return [radius * Math.cos(angle), radius * Math.sin(angle)];
  });
}

/**
 * The honeycomb, and the hemp leaf inside it.
 *
 * `ASANOHA_CELL` is half a hexagon's edges. Half, because every edge of a
 * honeycomb belongs to two hexagons, and drawing all six would lay every edge
 * down twice: invisible in the tile, and double the bytes and double the
 * measured ink, so the pattern would be tuned to a weight it does not have.
 * Three consecutive edges per hexagon covers each edge exactly once.
 *
 * `ASANOHA_LEAF` is the six spokes from the centre to the vertices, which is
 * what makes this asanoha rather than a honeycomb: where three hexagons meet,
 * their spokes and edges form the six pointed star the pattern is named for.
 */
const ASANOHA_VERTICES = hexagon(ASANOHA_RADIUS);

function segment(a: Point, b: Point): string {
  return `M${round(a[0])} ${round(a[1])}L${round(b[0])} ${round(b[1])}`;
}

const ASANOHA_CELL = [0, 1, 2]
  .map((index) => segment(ASANOHA_VERTICES[index]!, ASANOHA_VERTICES[index + 1]!))
  .join("");

const ASANOHA_LEAF = ASANOHA_VERTICES.map((vertex) =>
  segment([0, 0], vertex),
).join("");

const PLAIT_SIZE = 240;
/** Perpendicular distance between the centrelines of two neighbouring bands. */
const PLAIT_PITCH = 60;
/** The band's own width. The break at a crossing is this plus two margins. */
const PLAIT_WIDTH = 14;
const PLAIT_MARGIN = 3;

/**
 * One strand of the plait: a straight band across the tile at 45 degrees.
 *
 * `rise` is +1 for the family running down to the right and -1 for the other.
 * `offset` picks which of the family it is, and only its value modulo the tile
 * matters: the seven offsets a family contributes are four distinct lines, and
 * three of those enter the tile twice, once at each end of a diagonal. The nine
 * offsets rejoin the halves, which is why nothing here has to know that a
 * strand runs off one corner and back in at the other.
 */
function plaitBand(rise: 1 | -1, offset: number): Branch {
  const size = PLAIT_SIZE;
  // Where the line y = rise * x + offset enters and leaves the tile. Two
  // candidates always survive, because a straight line crosses a square's
  // boundary exactly twice unless it misses it, and no offset here misses.
  const at = (x: number): Point => [x, rise * x + offset];
  const inside = (y: number) => y >= -1e-9 && y <= size + 1e-9;
  const candidates: Point[] = [];
  for (const x of [0, size]) if (inside(at(x)[1])) candidates.push(at(x));
  for (const y of [0, size]) {
    const x = (y - offset) / rise;
    if (x > 1e-9 && x < size - 1e-9) candidates.push([x, y]);
  }
  const [start, end] = candidates.sort((a, b) => a[0] - b[0]) as [Point, Point];
  const lerp = (t: number): Point => [
    start[0] + (end[0] - start[0]) * t,
    start[1] + (end[1] - start[1]) * t,
  ];
  return [[start, lerp(1 / 3), lerp(2 / 3), end]];
}

/**
 * The stretches of a band that are drawn, which is everywhere it is not under.
 *
 * Over and under alternate along every strand, which is what makes this a plait
 * rather than a grid: the parity of the two band indices decides, and because
 * both indices step by one per neighbour, following either strand flips it at
 * every crossing.
 *
 * The parity survives the tile edge. A strand leaving the top right is the same
 * strand entering the bottom left, and its index there differs by four, so the
 * two halves agree about which one goes over.
 */
function plaitSpans(rise: 1 | -1, offset: number): [number, number][] {
  const branch = plaitBand(rise, offset);
  const length = measure(branch).length;
  const [[start, , , end]] = branch as [Cubic];
  const index = Math.round(offset / PLAIT_PITCH);
  const gaps: [number, number][] = [];
  // Crossings are where the other family's lines are, which is every PITCH / 2
  // in x, so the parity to compare against is that line's own index.
  for (
    let other = Math.ceil((-2 * PLAIT_SIZE) / PLAIT_PITCH);
    other <= (3 * PLAIT_SIZE) / PLAIT_PITCH;
    other += 1
  ) {
    const crossing = (other * PLAIT_PITCH - offset) / (2 * rise);
    const t = (crossing - start[0]) / (end[0] - start[0]);
    if (t < -0.2 || t > 1.2) continue;
    // One of the two strands at a crossing goes under and the other over, so
    // the two families read the same parity and take opposite answers from it.
    if ((index + other) % 2 === (rise === 1 ? 0 : 1)) continue;
    const half = (PLAIT_WIDTH / 2 + PLAIT_MARGIN) / length;
    gaps.push([t - half, t + half]);
  }

  gaps.sort((a, b) => a[0] - b[0]);
  const spans: [number, number][] = [];
  let cursor = 0;
  for (const [from, to] of gaps) {
    if (from > cursor) spans.push([cursor, Math.min(from, 1)]);
    cursor = Math.max(cursor, to);
  }
  if (cursor < 1) spans.push([cursor, 1]);
  return spans.filter(([from, to]) => to - from > 1e-6);
}

/**
 * Where each family's strands sit.
 *
 * The two families are the same set of lines reflected, so one list serves
 * both: reflecting `y = x + c` in the tile's vertical centre gives
 * `y = -x + (size + c)`, which is why the second family reads the same offsets
 * a tile further along.
 */
const PLAIT_OFFSETS = [-180, -120, -60, 0, 60, 120, 180];

function plaitOffset(rise: 1 | -1, offset: number): number {
  return rise === 1 ? offset : offset + PLAIT_SIZE;
}

/** A lozenge, the filler an Insular scribe puts in the openings of a plait. */
const PLAIT_LOZENGE = "M0 -6L9 0L0 6L-9 0Z";

const KHATAM_SIZE = 240;
/** Star centres, and the setting-out grid, are on this pitch. */
const KHATAM_PITCH = 80;
/**
 * The eight point star, flat and not woven.
 *
 * Flat is a decision and not a deferral. Weaving it would mean breaking the
 * outline at every crossing, which is the plait's trick done twice in one set
 * of ten, and it would put the pattern's defining feature back at the scale
 * that the admission rule refuses.
 *
 * Not girih either, which names the five tile quasi-periodic system and has no
 * square repeat at all. This is periodic, so calling it girih would be wrong in
 * the one way a reader who knows the field notices immediately.
 *
 * The inner radius is 0.5 of the outer rather than the 0.414 a strict {8/3}
 * star polygon has: at 0.414 the points are needles, and a needle is the shape
 * the admission rule is least kind to. The outer radius is 34 against a pitch of
 * 80, so neighbouring stars stop 12px short of each other. At 40 they touched,
 * and eight point stars that touch read as one lobed rosette rather than as a
 * field of stars, which is the first thing a rendering showed.
 */
const KHATAM_STAR = starPath(8, 34, 17);
/** The cross between four stars, filling the opening their points leave. */
const KHATAM_CROSS = starPath(4, 20, 8);

interface PatternSpec {
  id: string;
  name: string;
  family: PatternFamily;
  size: number;
  /** Built against a motif set, so a shape placed a hundred times is written once. */
  build: (motifs: MotifSet) => Layer[];
}

function define({ id, name, family, size, build }: PatternSpec): Pattern {
  const motifs = motifSet();
  const layers = build(motifs);
  // defs() after build(), never before: the set only knows a shape once a layer
  // has asked for it.
  return { id, name, family, size, defs: motifs.defs(), layers };
}

// `spacing` is px of arc between motifs. The values below reproduce the motif
// counts the tiles shipped with, so the change of mechanism is not also a change
// of weight. Strawberry's stems are the one place they differ: two of its four
// branches carry three cubics and two carry two, so per-cubic placement was
// giving the longer branches half again as much foliage per px. Evening that out
// keeps the total and redistributes it.
export const PATTERNS: Pattern[] = [
  define({
    id: "willow",
    name: "Willow Bough",
    family: "morris",
    size: WILLOW_SIZE,
    build: (m) => [
      {
        weight: "ground",
        body: stems(WILLOW_STEMS, 2) + stems(WILLOW_TWIGS, 1.1),
      },
      {
        // The mass of leaf behind the leaf, which is what a willow actually
        // looks like and what the two-layer version could not say: a Morris
        // repeat has depth, and depth is another plane rather than more shapes
        // on the same one.
        //
        // It is here because Willow needed the weight. At two layers it
        // measured 0.00485 mean tile dL against a floor of 0.0070, the only
        // tile under the band and by 31%, and it was under because it is the
        // sparsest of the five rather than because it is drawn faint. Adding
        // ink to the foliage would have made it denser; adding a plane behind
        // makes it deeper, which is the same number and a different tile.
        weight: "under",
        body:
          filled(
            grow(m, WILLOW_STEMS, {
              shape: ROUND_LEAF,
              spacing: 62,
              lean: 96,
              scale: [1, 0.82],
              taper: 0.85,
              jitter: 0.4,
            }),
          ) +
          filled(
            grow(m, WILLOW_TWIGS, {
              shape: ROUND_LEAF,
              spacing: 68,
              lean: 118,
              scale: 0.7,
              jitter: 0.4,
            }),
          ),
      },
      {
        // The densest of the five, which is faithful: the original is a mass of
        // small leaves with barely any ground showing between them.
        weight: "foliage",
        body:
          filled(
            grow(m, WILLOW_STEMS, {
              shape: WILLOW_LEAF,
              spacing: 17.5,
              lean: 62,
              scale: [0.85, 0.7, 0.95],
              taper: 0.85,
              jitter: 0.3,
            }),
          ) +
          filled(
            grow(m, WILLOW_TWIGS, {
              shape: WILLOW_LEAF,
              spacing: 16.1,
              lean: 48,
              scale: [0.7, 0.55],
              jitter: 0.35,
            }),
          ) +
          filled(
            grow(m, WILLOW_TWIGS, {
              shape: BUD,
              spacing: 30,
              lean: 100,
              scale: 0.6,
              inset: 0.3,
            }),
          ),
      },
    ],
  }),
  define({
    id: "acanthus",
    name: "Acanthus",
    family: "morris",
    size: ACANTHUS_SIZE,
    build: (m) => [
      {
        weight: "ground",
        body: stems(ACANTHUS_STEMS, 2.6) + stems(ACANTHUS_TWIGS, 1.3),
      },
      {
        weight: "foliage",
        body:
          filled(
            grow(m, ACANTHUS_STEMS, {
              shape: ACANTHUS,
              spacing: 60.7,
              lean: 40,
              scale: [1.05, 0.85, 1.2],
              taper: 0.85,
              jitter: 0.25,
            }),
          ) +
          filled(
            grow(m, ACANTHUS_TWIGS, {
              shape: CUT_LEAF,
              spacing: 27.7,
              lean: 52,
              scale: [0.95, 0.75],
              jitter: 0.35,
            }),
          ) +
          // Buds, not blooms: Acanthus has no flower, so it has no bloom layer.
          filled(
            scatter(m, BUD, [
              { x: 150, y: 150, r: 0, s: 1.5 },
              { x: 0, y: 150, r: 90, s: 1.1 },
              { x: 300, y: 150, r: 90, s: 1.1 },
              { x: 150, y: 0, r: 0, s: 1.1 },
              { x: 150, y: 300, r: 0, s: 1.1 },
            ]),
          ),
      },
    ],
  }),
  define({
    id: "pimpernel",
    name: "Pimpernel",
    family: "morris",
    size: PIMPERNEL_SIZE,
    build: (m) => [
      {
        weight: "ground",
        body: stems(PIMPERNEL_STEMS, 2.4) + stems(PIMPERNEL_TWIGS, 1.2),
      },
      {
        weight: "foliage",
        body:
          filled(
            grow(m, PIMPERNEL_STEMS, {
              shape: ROUND_LEAF,
              spacing: 39.3,
              lean: 58,
              scale: [0.9, 0.7, 1],
              taper: 0.85,
              jitter: 0.3,
            }),
          ) +
          filled(
            grow(m, PIMPERNEL_TWIGS, {
              shape: CUT_LEAF,
              spacing: 41.2,
              lean: 46,
              scale: [0.9, 0.7],
              jitter: 0.35,
            }),
          ),
      },
      {
        // The blooms are placed rather than grown: each one is the centre of an
        // ogee, which is the point of the design and not somewhere a sampler
        // would happen to land.
        weight: "bloom",
        body: filled(
          scatter(m, BLOOM, [
            { x: 70, y: 70, r: -50, s: 1.5 },
            { x: 210, y: 210, r: 130, s: 1.5 },
            { x: 210, y: 70, r: 230, s: 1.3 },
            { x: 70, y: 210, r: 50, s: 1.3 },
            { x: 140, y: 140, r: -90, s: 1 },
            { x: 0, y: 140, r: 0, s: 1 },
            { x: 280, y: 140, r: 180, s: 1 },
          ]),
        ),
      },
    ],
  }),
  define({
    id: "strawberry",
    name: "Strawberry Thief",
    family: "morris",
    size: STRAWBERRY_SIZE,
    build: (m) => [
      {
        weight: "ground",
        body: stems(STRAWBERRY_STEMS, 2.2) + stems(STRAWBERRY_TWIGS, 1.1),
      },
      {
        weight: "under",
        body: filled(
          grow(m, STRAWBERRY_STEMS, {
            shape: ROUND_LEAF,
            spacing: 66,
            lean: 104,
            scale: [0.85, 0.7],
            taper: 0.85,
            jitter: 0.4,
          }),
        ),
      },
      {
        weight: "foliage",
        body:
          filled(
            grow(m, STRAWBERRY_STEMS, {
              shape: CUT_LEAF,
              spacing: 29,
              lean: 56,
              scale: [0.95, 0.75, 1.05],
              taper: 0.85,
              jitter: 0.3,
            }),
          ) +
          filled(
            grow(m, STRAWBERRY_TWIGS, {
              shape: ROUND_LEAF,
              spacing: 62,
              lean: 44,
              scale: 0.8,
              jitter: 0.35,
            }),
          ),
      },
      {
        weight: "bloom",
        body: filled(
          scatter(m, BERRY, [
            { x: 150, y: 76, r: 10, s: 1.2 },
            { x: 150, y: 226, r: 190, s: 1.2 },
            { x: 22, y: 172, r: -70, s: 1 },
            { x: 278, y: 172, r: 110, s: 1 },
            { x: 102, y: 112, r: 40, s: 0.9 },
            { x: 198, y: 112, r: 140, s: 0.9 },
            { x: 64, y: 224, r: 220, s: 0.9 },
            { x: 236, y: 224, r: 320, s: 0.9 },
          ]),
        ),
      },
    ],
  }),
  define({
    id: "lily",
    name: "Golden Lily",
    family: "morris",
    size: LILY_SIZE,
    build: (m) => [
      {
        weight: "ground",
        body: stems(LILY_STEMS, 2.4) + stems(LILY_TWIGS, 1.3),
      },
      {
        weight: "foliage",
        body:
          filled(
            grow(m, LILY_STEMS, {
              shape: ROUND_LEAF,
              spacing: 28.1,
              lean: 64,
              scale: [0.9, 0.7, 1],
              taper: 0.85,
              jitter: 0.3,
            }),
          ) +
          filled(
            grow(m, LILY_TWIGS, {
              shape: WILLOW_LEAF,
              spacing: 34.5,
              lean: 44,
              scale: [0.8, 0.6],
              jitter: 0.35,
            }),
          ),
      },
      {
        // Each lily is three petals from one point, which no tangent sampler
        // produces: a flower is a cluster, not a run.
        //
        // This was twenty four placements, the same three rotations and the
        // same three scales retyped under eight origins. `radial` says it once,
        // so "a lily has three petals, forty degrees apart" is now a fact with
        // one home rather than a pattern in a list that has to be read to be
        // seen.
        //
        // The petals also came down from 1.2 / 1.35 to 0.85 / 0.98. Golden Lily
        // was measured at a mean tile weight of 0.01343 against a ceiling of
        // 0.0092: half again as heavy as the heaviest tile the budget allows,
        // and it was all flower. The foliage layer is 7.4% of the tile and the
        // blooms were 16.8%.
        weight: "bloom",
        body: filled(
          LILY_FLOWERS.map((at) =>
            radial(m, PETAL, at, {
              count: 3,
              spread: 40,
              scale: [0.85, 0.98, 0.85],
            }),
          ).join(""),
        ),
      },
    ],
  }),
  define({
    id: "nonpareil",
    name: "Nonpareil",
    family: "papers",
    size: NONPAREIL_SIZE,
    build: (m) => {
      const lines = (parity: number) =>
        Array.from(
          { length: NONPAREIL_SIZE / NONPAREIL_PITCH },
          (_, index) => index,
        )
          .filter((index) => index % 2 === parity)
          .map((index) => nonpareilLine(m, index))
          .join("");
      return [
        { weight: "ground", body: stroked(lines(0), 3.2) },
        // The alternate lines carry the second colour, which is what a marbler
        // gets by dropping two pigments on the bath before combing. Adjacent
        // lines are 15px apart whichever colour they are, so the alternation
        // costs nothing against the mark pitch floor.
        { weight: "foliage", body: stroked(lines(1), 3.2, "{bloom}") },
      ];
    },
  }),
  define({
    id: "seigaiha",
    name: "Seigaiha",
    family: "papers",
    size: SEIGAIHA_SIZE,
    build: (m) => {
      // The stagger is what interlocks the fans into scales instead of
      // stacking them into columns, and it is `lattice`'s to apply: it is the
      // half of the layout that has to come out even for the tile to meet
      // itself, and six rows do.
      const fans = (shape: string) =>
        lattice(
          SEIGAIHA_SIZE,
          SEIGAIHA_PITCH,
          ({ x, y }) => place(m.id(shape), x, y, 0, 1),
          { stagger: true },
        );
      return [
        { weight: "ground", body: stroked(fans(SEIGAIHA_INNER), 2.4) },
        { weight: "foliage", body: stroked(fans(SEIGAIHA_CREST), 2.4, "{bloom}") },
      ];
    },
  }),
  define({
    id: "asanoha",
    name: "Asanoha",
    family: "papers",
    size: ASANOHA_SIZE,
    build: (m) => {
      const pitch = {
        x: (ASANOHA_SIZE / ASANOHA_COLUMNS),
        y: 1.5 * ASANOHA_RADIUS,
      };
      const field = (shape: string) =>
        `<g transform="scale(1 ${round(ASANOHA_SQUASH * 1000) / 1000})">` +
        lattice(
          { x: ASANOHA_SIZE, y: ASANOHA_ROWS * pitch.y },
          pitch,
          ({ x, y }) => place(m.id(shape), x, y, 0, 1),
          { stagger: true },
        ) +
        `</g>`;
      return [
        { weight: "ground", body: stroked(field(ASANOHA_CELL), 2.2) },
        { weight: "foliage", body: stroked(field(ASANOHA_LEAF), 2.2, "{bloom}") },
      ];
    },
  }),
  define({
    id: "plait",
    name: "Plait",
    family: "papers",
    size: PLAIT_SIZE,
    build: (m) => {
      const strands = ([1, -1] as const).flatMap((rise) =>
        PLAIT_OFFSETS.map((base) => {
          const offset = plaitOffset(rise, base);
          return ribbon(
            plaitBand(rise, offset),
            PLAIT_WIDTH,
            plaitSpans(rise, offset),
          );
        }),
      );
      return [
        {
          // The openings between the strands, which a scribe never leaves bare.
          weight: "ground",
          body: filled(
            lattice(PLAIT_SIZE, { x: 60, y: 60 }, ({ x, y }) =>
              scatter(m, PLAIT_LOZENGE, [
                { x: x + 30, y, r: 45 },
                { x, y: y + 30, r: 45 },
              ]),
            ),
          ),
        },
        {
          weight: "foliage",
          body: stroked(
            strands.map((d) => `<path d="${d}"/>`).join(""),
            2.2,
            "{bloom}",
          ),
        },
      ];
    },
  }),
  define({
    id: "khatam",
    name: "Khatam",
    family: "papers",
    size: KHATAM_SIZE,
    build: (m) => [
      {
        // The setting-out grid the marquetry is laid on, drawn as the joiner
        // leaves it: through the crosses, not through the stars.
        weight: "ground",
        body: stroked(
          [0, 1, 2]
            .flatMap((index) => {
              const at = KHATAM_PITCH / 2 + index * KHATAM_PITCH;
              return [
                `<path d="M${at} 0L${at} ${KHATAM_SIZE}"/>`,
                `<path d="M0 ${at}L${KHATAM_SIZE} ${at}"/>`,
              ];
            })
            .join(""),
          1.2,
        ),
      },
      {
        weight: "foliage",
        body: stroked(
          lattice(KHATAM_SIZE, { x: KHATAM_PITCH, y: KHATAM_PITCH }, ({ x, y }) =>
            place(m.id(KHATAM_STAR), x, y, 0, 1) +
            place(
              m.id(KHATAM_CROSS),
              x + KHATAM_PITCH / 2,
              y + KHATAM_PITCH / 2,
              45,
              1,
            ),
          ),
          2.6,
          "{bloom}",
        ),
      },
    ],
  }),
];

/**
 * How strongly each layer is drawn, as a weight rather than as an opacity.
 *
 * These are OKLab lightness deltas: how far one mark of that layer moves the
 * page it sits on. They were opacities until the ink started following the
 * palette, and then they could not be, because one alpha over seven inks is
 * seven weights. Measured at the shipped alphas the mean tile weight ran 1.27x
 * apart across the seven palettes in light and 1.32x in dark, against a budget
 * band 1.31x wide: the palette alone consumed the whole budget, and the dimmer
 * inks landed up to 30% under target in dark.
 *
 * Solving the alpha from the weight instead takes that spread to 1.052x in
 * light and 1.030x in dark, and what is left is not the palette: in continuous
 * colour the seven agree to 1.002x, and the residual is the compositor
 * quantising the blend to 8 bits per channel. The measurements are in
 * `docs/decisions.md`.
 *
 * Dark asks for more than light. A pattern that reads as gentle on white
 * disappears into near-black at the same strength, because the tile is mostly
 * negative space: the earlier tuning reasoned the opposite, from the glare a
 * solid light fill has on a dark ground, and was wrong.
 *
 * The gaps between the four are the whole reason the pattern reads as depth
 * rather than as a flat scatter, so they are the first thing to preserve if
 * these are ever retuned.
 */
const TARGETS: Record<ResolvedTheme, Record<LayerWeight, number>> = {
  light: { ground: 0.026, under: 0.033, foliage: 0.042, bloom: 0.057 },
  dark: { ground: 0.061, under: 0.07, foliage: 0.083, bloom: 0.102 },
};

/**
 * The most alpha a layer may be solved to.
 *
 * Not the weight ceiling: that is `TARGETS`, and it is the same perceptual
 * number for every palette. This is the guard on what an ink is allowed to
 * spend reaching it, and it binds only where the ink is so close to its own
 * page that no reasonable alpha gets there. The highest solve across the
 * fourteen palette-modes is Solarized dark's bloom at 0.2082, so at 0.30 this
 * catches an ink that is genuinely unusable rather than one that is merely dim.
 *
 * It replaced a flat 0.15, which was the right number while the alpha was the
 * instrument and is the wrong one now: five of the seven palettes need more
 * than 0.15 in dark to reach a weight Endpaper reaches at 0.13.
 */
const ALPHA_CEILING = 0.3;

/**
 * Which ramp steps the wallpaper takes its colours from.
 *
 * These were four hexes written out in this file. Three of them were exactly
 * `accent-700`, `bloom-700` and `bloom-300`, and the fourth was a teal one step
 * off `accent-300`: the rule was already here, written a second time in the one
 * place that could not follow a palette. Naming the tokens instead is what makes
 * a new palette's wallpaper correct without this file being opened, and it is
 * why nothing here is a colour any more.
 *
 * The page is read for the same reason the inks are. A weight is a distance
 * from something, and the something is the page the tile is pasted onto, so the
 * solve needs all three. The page token comes from `palettes.ts` rather than
 * being named again here: it is the one row this table and the picker's share,
 * and a cross-reference in a comment is not a mechanism.
 */
const COLOUR_TOKENS: Record<ResolvedTheme, WallpaperColours> = {
  light: {
    ink: "--color-accent-700",
    bloom: "--color-bloom-700",
    page: PAGE_TOKEN.light,
  },
  dark: {
    ink: "--color-accent-300",
    bloom: "--color-bloom-300",
    page: PAGE_TOKEN.dark,
  },
};

/**
 * The colours a tile is drawn with, and the page it is drawn on.
 *
 * Token names going in, values coming out. The page is not an ink and is never
 * painted: it is there because the alpha is solved against it.
 */
export interface WallpaperColours {
  ink: string;
  bloom: string;
  page: string;
}

/**
 * The alpha each weight is drawn at, solved for these colours.
 *
 * Exported and pure so a test can state the colours and read the answer. The
 * ground layer is drawn in `ink` and everything with a fill in `bloom`, which
 * is why the two are solved separately: at one alpha they are two weights.
 *
 * An unparseable colour yields nothing rather than a default. `applyWallpaper`
 * refuses to paint at all in that case, and a fallback alpha here would paint
 * something and hide the reason.
 */
export function wallpaperWeights(
  theme: ResolvedTheme,
  colours: WallpaperColours,
): Record<LayerWeight, number> | null {
  const page = parseHex(colours.page);
  const ink = parseHex(colours.ink);
  const bloom = parseHex(colours.bloom);
  if (!page || !ink || !bloom) return null;

  const solve = (weight: LayerWeight): number =>
    Math.min(
      ALPHA_CEILING,
      solveAlpha(weight === "ground" ? ink : bloom, page, TARGETS[theme][weight]),
    );

  return {
    ground: solve("ground"),
    under: solve("under"),
    foliage: solve("foliage"),
    bloom: solve("bloom"),
  };
}

/**
 * Read the colours for `theme` off the document's own tokens.
 *
 * Separate from `patternDataUri` because a data URI cannot see a custom
 * property: CSS variables do not cross into the SVG document, so the value has
 * to be resolved here and substituted in. Keeping the read out of the generator
 * also keeps the generator pure, which is what lets a test state the colours
 * rather than mount a stylesheet.
 */
export function wallpaperColours(theme: ResolvedTheme): WallpaperColours {
  const style = getComputedStyle(document.documentElement);
  const tokens = COLOUR_TOKENS[theme];
  return {
    ink: style.getPropertyValue(tokens.ink).trim(),
    bloom: style.getPropertyValue(tokens.bloom).trim(),
    page: style.getPropertyValue(tokens.page).trim(),
  };
}

/**
 * The nine positions a tile is drawn at to make the repeat seamless.
 *
 * Itself plus its eight neighbours, so a motif hanging off any edge is drawn
 * again on the opposite one and the viewBox clips the rest. Without this every
 * shape would have to be kept clear of the edges, which is what makes a
 * hand-placed repeat look like a grid of stamps.
 */
const TILING = [-1, 0, 1];

function tiled(id: string, size: number): string {
  return TILING.flatMap((column) =>
    TILING.map(
      (row) => `<use href="#${id}" x="${column * size}" y="${row * size}"/>`,
    ),
  ).join("");
}

/**
 * A pattern as a `background-image` value, in the given colours.
 *
 * Returns nothing for colours it cannot parse, which is the same answer
 * `wallpaperWeights` gives and for the same reason: a tile drawn in a colour
 * nobody chose is worse than no tile.
 */
export function patternDataUri(
  pattern: Pattern,
  theme: ResolvedTheme,
  colours: WallpaperColours,
): string {
  const { size } = pattern;
  const weights = wallpaperWeights(theme, colours);
  if (!weights) return "";

  // Motif definitions first, then one group per layer, all inside the same
  // <defs>: a <use> pointing at a group that itself contains <use> elements is
  // two levels deep, which is legal and is what keeps the nine offsets working
  // now that a motif is a reference rather than a shape.
  const defs = [pattern.defs];
  const drawn: string[] = [];

  pattern.layers.forEach((layer, index) => {
    const id = `l${index}`;
    const body = layer.body
      .replace(/\{ink\}/g, colours.ink)
      .replace(/\{bloom\}/g, colours.bloom);
    defs.push(`<g id="${id}">${body}</g>`);
    // Four decimals: the solve settles far finer than that, and every digit
    // past it is bytes in a string that is regenerated on every theme change.
    const alpha = weights[layer.weight].toFixed(4);
    drawn.push(`<g opacity="${alpha}">${tiled(id, size)}</g>`);
  });

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" ` +
    `viewBox="0 0 ${size} ${size}">` +
    `<defs>${defs.join("")}</defs>` +
    drawn.join("") +
    `</svg>`;

  // encodeURIComponent rather than base64: it stays readable in devtools and
  // avoids the btoa unicode trap entirely.
  return `url("data:image/svg+xml,${encodeURIComponent(svg.replace(/\s+/g, " "))}")`;
}

/**
 * Pick one at random.
 *
 * A different pattern each time somebody comes back, which is the point: it is
 * a small pleasure rather than a setting. Deliberately *not* stored, because
 * remembering it would defeat the whole idea.
 */
export function randomPattern(): Pattern {
  return PATTERNS[Math.floor(Math.random() * PATTERNS.length)]!;
}
