/**
 * Muted background patterns in the William Morris idiom.
 *
 * Drawn here rather than shipped as images, for three reasons. Morris designs
 * themselves are public domain (he died in 1896), but the high-resolution scans
 * that circulate are mostly museum photographs published under their own terms,
 * so "it is a Morris" is not on its own a licence. A tileable SVG is also about
 * a kilobyte against a few hundred for a repeating raster, and it takes its
 * colour from the theme instead of needing a second file for dark mode.
 *
 * They are wallpaper, so they are deliberately faint: enough to give the page a
 * texture at arm's length, not enough to compete with a book cover.
 */

import type { ResolvedTheme } from "./index";

export interface Pattern {
  /** Stable id, used as the storage key and in tests. */
  id: string;
  /** The English name of the Morris design each is after. */
  name: string;
  /** Tile size in px. Larger reads as wallpaper, smaller as noise. */
  size: number;
  /** SVG body, with `{color}` substituted for the stroke and fill. */
  body: string;
}

export const PATTERNS: Pattern[] = [
  {
    id: "willow",
    name: "Willow Bough",
    size: 120,
    body: `
      <path d="M10 60 Q35 30 60 60 T110 60" fill="none" stroke="{color}" stroke-width="1.4"/>
      <path d="M10 0 Q35 -30 60 0 T110 0" fill="none" stroke="{color}" stroke-width="1.4"/>
      <path d="M10 120 Q35 90 60 120 T110 120" fill="none" stroke="{color}" stroke-width="1.4"/>
      <ellipse cx="30" cy="44" rx="11" ry="5" fill="{color}" transform="rotate(-32 30 44)"/>
      <ellipse cx="62" cy="52" rx="11" ry="5" fill="{color}" transform="rotate(18 62 52)"/>
      <ellipse cx="92" cy="44" rx="11" ry="5" fill="{color}" transform="rotate(-32 92 44)"/>
      <ellipse cx="46" cy="78" rx="10" ry="4.5" fill="{color}" transform="rotate(24 46 78)"/>
      <ellipse cx="78" cy="82" rx="10" ry="4.5" fill="{color}" transform="rotate(-20 78 82)"/>
    `,
  },
  {
    id: "trellis",
    name: "Trellis",
    size: 100,
    body: `
      <path d="M0 50 H100 M50 0 V100" stroke="{color}" stroke-width="1.6" fill="none"/>
      <path d="M0 0 Q25 25 50 0 T100 0" fill="none" stroke="{color}" stroke-width="1.1"/>
      <path d="M0 100 Q25 75 50 100 T100 100" fill="none" stroke="{color}" stroke-width="1.1"/>
      <circle cx="50" cy="50" r="6" fill="none" stroke="{color}" stroke-width="1.4"/>
      <circle cx="50" cy="50" r="2" fill="{color}"/>
      <path d="M50 44 L54 38 M50 44 L46 38 M50 56 L54 62 M50 56 L46 62"
            stroke="{color}" stroke-width="1.1" fill="none"/>
    `,
  },
  {
    id: "daisy",
    name: "Daisy",
    size: 90,
    body: `
      <g fill="none" stroke="{color}" stroke-width="1.3">
        <circle cx="22" cy="24" r="4"/>
        <circle cx="68" cy="66" r="4"/>
      </g>
      <g fill="{color}">
        <ellipse cx="22" cy="15" rx="2.6" ry="6"/>
        <ellipse cx="22" cy="33" rx="2.6" ry="6"/>
        <ellipse cx="13" cy="24" rx="6" ry="2.6"/>
        <ellipse cx="31" cy="24" rx="6" ry="2.6"/>
        <ellipse cx="68" cy="57" rx="2.6" ry="6"/>
        <ellipse cx="68" cy="75" rx="2.6" ry="6"/>
        <ellipse cx="59" cy="66" rx="6" ry="2.6"/>
        <ellipse cx="77" cy="66" rx="6" ry="2.6"/>
      </g>
      <path d="M22 40 Q30 54 45 58 M68 50 Q60 36 45 32" fill="none"
            stroke="{color}" stroke-width="1.1"/>
    `,
  },
  {
    id: "acanthus",
    name: "Acanthus",
    size: 140,
    body: `
      <path d="M0 70 Q35 20 70 70 T140 70" fill="none" stroke="{color}" stroke-width="1.6"/>
      <path d="M70 70 Q86 46 106 44 Q92 62 84 80 Q76 74 70 70 Z" fill="{color}" opacity="0.75"/>
      <path d="M70 70 Q54 46 34 44 Q48 62 56 80 Q64 74 70 70 Z" fill="{color}" opacity="0.75"/>
      <path d="M0 0 Q35 50 70 0 T140 0" fill="none" stroke="{color}" stroke-width="1.6"/>
      <path d="M0 140 Q35 90 70 140 T140 140" fill="none" stroke="{color}" stroke-width="1.6"/>
      <circle cx="70" cy="70" r="3.5" fill="{color}"/>
    `,
  },
];

/**
 * How each theme paints them.
 *
 * Dark uses a lighter ink at a lower opacity than you would expect: a pattern
 * that reads as gentle on white becomes a glare on near-black at the same
 * strength.
 */
const PALETTE: Record<ResolvedTheme, { color: string; opacity: number }> = {
  light: { color: "#0f766e", opacity: 0.055 },
  dark: { color: "#5eead4", opacity: 0.035 },
};

/** A pattern as a `background-image` value for the given theme. */
export function patternDataUri(pattern: Pattern, theme: ResolvedTheme): string {
  const { color, opacity } = PALETTE[theme];
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${pattern.size}" height="${pattern.size}" ` +
    `viewBox="0 0 ${pattern.size} ${pattern.size}">` +
    `<g opacity="${opacity}">${pattern.body.replace(/\{color\}/g, color)}</g>` +
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
