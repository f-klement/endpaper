/**
 * Wallpaper in the William Morris idiom.
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
 * ## Two layers, because one weight reads as clip art
 *
 * A Morris repeat is never a single plane of motifs. There is a **ground**: the
 * slow meandering stem structure that carries the eye around the repeat, and a
 * **foliage** layer on top of it, drawn stronger. Flattening the two into one
 * weight is what turns an arabesque into a scatter of shapes.
 *
 * ## Seamlessness is structural, not hand-placed
 *
 * Each layer is defined once and `<use>`d at nine offsets, so the tile is drawn
 * surrounded by its own neighbours and the viewBox clips the overhang. Motifs
 * can then run off any edge and reappear correctly on the opposite one, which
 * is what lets the stems be drawn as continuous growth rather than as shapes
 * carefully kept clear of the boundary.
 *
 * They are still wallpaper: faint enough to give the page a texture at arm's
 * length, not enough to compete with a book cover.
 */

import type { ResolvedTheme } from "./index";

export interface Pattern {
  /** Stable id, used as the storage key and in tests. */
  id: string;
  /** The English name of the Morris design each is after. */
  name: string;
  /** Tile size in px. Larger reads as wallpaper, smaller as noise. */
  size: number;
  /**
   * The stem structure. Stroked, drawn faintest, sits behind everything.
   * `{ink}` is substituted for its colour.
   */
  ground: string;
  /**
   * Leaves, buds and blooms. Filled, drawn a little stronger.
   * `{bloom}` is substituted for its colour.
   */
  foliage: string;
}

// ── Curves ────────────────────────────────────────────────────────────────────

type Point = [number, number];

/** One cubic Bezier: start, two control points, end. */
type Cubic = [Point, Point, Point, Point];

/** A branch is a run of cubics sharing endpoints. */
type Branch = Cubic[];

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
  return (
    `<g fill="none" stroke="{ink}" stroke-width="${width}" ` +
    `stroke-linecap="round">${paths}</g>`
  );
}

interface GrowOptions {
  /** The motif, drawn around the origin pointing along +x. */
  shape: string;
  /** How many motifs per cubic segment. */
  per: number;
  /** Degrees off the tangent. Positive leans one way, negative the other. */
  lean?: number;
  /** Alternate the lean side down the branch, as a real stem does. */
  alternate?: boolean;
  /** Motif scale, or a pair cycled through for a less mechanical run. */
  scale?: number | number[];
  /** Skip the first and last fraction of each segment, where branches meet. */
  inset?: number;
}

/**
 * Place motifs along a branch, rotated onto its tangent.
 *
 * This is the whole reason the patterns look like plants: a leaf inherits the
 * direction of the stem it grows from, so a run of them follows the curve
 * instead of pointing wherever it was typed.
 */
function grow(branches: Branch[], options: GrowOptions): string {
  const {
    shape,
    per,
    lean = 55,
    alternate = true,
    scale = 1,
    inset = 0.08,
  } = options;
  const scales = Array.isArray(scale) ? scale : [scale];

  const parts: string[] = [];
  let index = 0;

  for (const branch of branches) {
    for (const segment of branch) {
      for (let step = 0; step < per; step += 1) {
        const t = inset + ((1 - 2 * inset) * step) / Math.max(per - 1, 1);
        const [x, y] = pointAt(segment, t);
        const side = alternate && index % 2 === 1 ? -1 : 1;
        const rotation = angleAt(segment, t) + lean * side;
        const size = scales[index % scales.length]!;
        parts.push(
          `<path d="${shape}" transform="translate(${round(x)} ${round(y)}) ` +
            `rotate(${round(rotation)})` +
            (size === 1 ? "" : ` scale(${size})`) +
            `"/>`,
        );
        index += 1;
      }
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
function scatter(shape: string, placements: At[]): string {
  return placements
    .map(({ x, y, r = 0, s = 1 }) => {
      const transform =
        `translate(${x} ${y})` +
        (r ? ` rotate(${r})` : "") +
        (s !== 1 ? ` scale(${s})` : "");
      return `<path d="${shape}" transform="${transform}"/>`;
    })
    .join("");
}

function filled(body: string): string {
  return `<g fill="{bloom}">${body}</g>`;
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
/** An ogee: two mirrored waves enclosing a pointed oval around each bloom. */
const PIMPERNEL_STEMS: Branch[] = [
  [
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
  ],
  [
    [
      [280, 0],
      [276, 78],
      [140, 62],
      [140, 140],
    ],
    [
      [140, 140],
      [140, 218],
      [276, 202],
      [280, 280],
    ],
  ],
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
  [
    [
      [225, 0],
      [236, 44],
      [194, 66],
      [198, 112],
    ],
    [
      [198, 112],
      [202, 158],
      [246, 180],
      [236, 224],
    ],
    [
      [236, 224],
      [226, 268],
      [256, 288],
      [262, 300],
    ],
  ],
];
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

export const PATTERNS: Pattern[] = [
  {
    id: "willow",
    name: "Willow Bough",
    size: WILLOW_SIZE,
    ground: stems(WILLOW_STEMS, 2) + stems(WILLOW_TWIGS, 1.1),
    // The densest of the five, which is faithful: the original is a mass of
    // small leaves with barely any ground showing between them.
    foliage:
      filled(
        grow(WILLOW_STEMS, {
          shape: WILLOW_LEAF,
          per: 7,
          lean: 62,
          scale: [0.85, 0.7, 0.95],
        }),
      ) +
      filled(
        grow(WILLOW_TWIGS, {
          shape: WILLOW_LEAF,
          per: 5,
          lean: 48,
          scale: [0.7, 0.55],
        }),
      ) +
      filled(
        grow(WILLOW_TWIGS, {
          shape: BUD,
          per: 2,
          lean: 100,
          scale: 0.6,
          inset: 0.3,
        }),
      ),
  },
  {
    id: "acanthus",
    name: "Acanthus",
    size: ACANTHUS_SIZE,
    ground: stems(ACANTHUS_STEMS, 2.6) + stems(ACANTHUS_TWIGS, 1.3),
    foliage:
      filled(
        grow(ACANTHUS_STEMS, {
          shape: ACANTHUS,
          per: 3,
          lean: 40,
          scale: [1.05, 0.85, 1.2],
        }),
      ) +
      filled(
        grow(ACANTHUS_TWIGS, {
          shape: CUT_LEAF,
          per: 4,
          lean: 52,
          scale: [0.95, 0.75],
        }),
      ) +
      filled(
        scatter(BUD, [
          { x: 150, y: 150, r: 0, s: 1.5 },
          { x: 0, y: 150, r: 90, s: 1.1 },
          { x: 300, y: 150, r: 90, s: 1.1 },
          { x: 150, y: 0, r: 0, s: 1.1 },
          { x: 150, y: 300, r: 0, s: 1.1 },
        ]),
      ),
  },
  {
    id: "pimpernel",
    name: "Pimpernel",
    size: PIMPERNEL_SIZE,
    ground: stems(PIMPERNEL_STEMS, 2.4) + stems(PIMPERNEL_TWIGS, 1.2),
    foliage:
      filled(
        grow(PIMPERNEL_STEMS, {
          shape: ROUND_LEAF,
          per: 5,
          lean: 58,
          scale: [0.9, 0.7, 1],
        }),
      ) +
      filled(
        grow(PIMPERNEL_TWIGS, {
          shape: CUT_LEAF,
          per: 3,
          lean: 46,
          scale: [0.9, 0.7],
        }),
      ) +
      // The blooms are placed rather than grown: each one is the centre of an
      // ogee, which is the point of the design and not somewhere a sampler
      // would happen to land.
      filled(
        scatter(BLOOM, [
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
  {
    id: "strawberry",
    name: "Strawberry Thief",
    size: STRAWBERRY_SIZE,
    ground: stems(STRAWBERRY_STEMS, 2.2) + stems(STRAWBERRY_TWIGS, 1.1),
    foliage:
      filled(
        grow(STRAWBERRY_STEMS, {
          shape: CUT_LEAF,
          per: 4,
          lean: 56,
          scale: [0.95, 0.75, 1.05],
        }),
      ) +
      filled(
        grow(STRAWBERRY_TWIGS, {
          shape: ROUND_LEAF,
          per: 2,
          lean: 44,
          scale: 0.8,
        }),
      ) +
      filled(
        scatter(BERRY, [
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
  {
    id: "lily",
    name: "Golden Lily",
    size: LILY_SIZE,
    ground: stems(LILY_STEMS, 2.4) + stems(LILY_TWIGS, 1.3),
    foliage:
      filled(
        grow(LILY_STEMS, {
          shape: ROUND_LEAF,
          per: 5,
          lean: 64,
          scale: [0.9, 0.7, 1],
        }),
      ) +
      filled(
        grow(LILY_TWIGS, {
          shape: WILLOW_LEAF,
          per: 3,
          lean: 44,
          scale: [0.8, 0.6],
        }),
      ) +
      // Each lily is three petals from one point, which no tangent sampler
      // produces: a flower is a cluster, not a run.
      filled(
        scatter(PETAL, [
          { x: 144, y: 18, r: -34, s: 1.2 },
          { x: 144, y: 18, r: 6, s: 1.35 },
          { x: 144, y: 18, r: 46, s: 1.2 },
          { x: -4, y: 86, r: 146, s: 1.2 },
          { x: -4, y: 86, r: 186, s: 1.35 },
          { x: -4, y: 86, r: 226, s: 1.2 },
          { x: 284, y: 86, r: -34, s: 1.2 },
          { x: 284, y: 86, r: 6, s: 1.35 },
          { x: 284, y: 86, r: 46, s: 1.2 },
          { x: 144, y: 158, r: -34, s: 1.2 },
          { x: 144, y: 158, r: 6, s: 1.35 },
          { x: 144, y: 158, r: 46, s: 1.2 },
          { x: -4, y: 226, r: 146, s: 1.2 },
          { x: -4, y: 226, r: 186, s: 1.35 },
          { x: -4, y: 226, r: 226, s: 1.2 },
          { x: 284, y: 226, r: -34, s: 1.2 },
          { x: 284, y: 226, r: 6, s: 1.35 },
          { x: 284, y: 226, r: 46, s: 1.2 },
          { x: 136, y: 18, r: 134, s: 1.2 },
          { x: 136, y: 18, r: 174, s: 1.35 },
          { x: 136, y: 18, r: 214, s: 1.2 },
          { x: 136, y: 158, r: 134, s: 1.2 },
          { x: 136, y: 158, r: 174, s: 1.35 },
          { x: 136, y: 158, r: 214, s: 1.2 },
        ]),
      ),
  },
];

/**
 * How each theme paints them.
 *
 * Dark uses lighter inks at lower opacity than you would expect: a pattern that
 * reads as gentle on white becomes a glare on near-black at the same strength.
 *
 * The ground is deliberately weaker than the foliage. That gap is the whole
 * reason the pattern reads as depth rather than as a flat scatter, so it is the
 * first thing to preserve if these are ever retuned.
 */
const PALETTE: Record<
  ResolvedTheme,
  { ink: string; bloom: string; groundOpacity: number; foliageOpacity: number }
> = {
  light: {
    ink: "#0f766e",
    bloom: "#9f1239",
    groundOpacity: 0.055,
    foliageOpacity: 0.075,
  },
  dark: {
    ink: "#5eead4",
    bloom: "#fda4af",
    // Roughly twice the light values, which is not a mistake and is the second
    // time this has been tuned. The first pass reasoned that a light ink on
    // near-black glares at the same strength as a dark ink on white. True for a
    // solid fill, wrong for this: the tile is mostly negative space, so at
    // parity the pattern simply disappeared into #030712 and the dark theme had
    // no texture at all. Measured against the real page background rather than
    // reasoned about a second time.
    groundOpacity: 0.075,
    foliageOpacity: 0.105,
  },
};

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

/** A pattern as a `background-image` value for the given theme. */
export function patternDataUri(pattern: Pattern, theme: ResolvedTheme): string {
  const { ink, bloom, groundOpacity, foliageOpacity } = PALETTE[theme];
  const { size } = pattern;

  const ground = pattern.ground.replace(/\{ink\}/g, ink);
  const foliage = pattern.foliage.replace(/\{bloom\}/g, bloom);

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" ` +
    `viewBox="0 0 ${size} ${size}">` +
    `<defs><g id="g">${ground}</g><g id="f">${foliage}</g></defs>` +
    `<g opacity="${groundOpacity}">${tiled("g", size)}</g>` +
    `<g opacity="${foliageOpacity}">${tiled("f", size)}</g>` +
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
