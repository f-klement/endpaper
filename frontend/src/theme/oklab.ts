/**
 * Enough OKLab to weigh a wallpaper.
 *
 * The wallpaper's opacity used to be a constant per mode. It cannot be, now
 * that the ink follows the palette: the same alpha over seven different inks
 * lands seven different weights on the page, measured at 1.27x apart in light
 * and 1.32x in dark, which is the width of the whole budget the tile is
 * supposed to sit inside. So the constant moved from the alpha to the weight,
 * and the alpha is solved from it here.
 *
 * Lightness only, and OKLab rather than WCAG contrast, because the question is
 * "how far does this mark move the page", not "can this be read". A contrast
 * ratio is a ratio of luminances and is dominated by the lighter of the two, so
 * two inks that move a page by visibly different amounts can share one. OKLab's
 * L is perceptually uniform and a difference in it is the thing being budgeted.
 *
 * `frontend/tests/theme/palettes.test.ts` has its own contrast maths for the
 * ramp contract, deliberately not shared with this: that one is a test
 * measuring the stylesheets, this one ships in the bundle and decides what gets
 * painted. Merging them would put a test's instrument in the product.
 */

/** sRGB channels, 0 to 255. */
type Rgb = [number, number, number];

/**
 * Parse `#rgb` or `#rrggbb`.
 *
 * Longer forms carry alpha, which a palette token never does, so they are
 * rejected rather than silently truncated to their opaque part.
 */
export function parseHex(value: string): Rgb | null {
  const text = value.trim();
  const short = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(text);
  if (short) {
    return [
      Number.parseInt(short[1]! + short[1]!, 16),
      Number.parseInt(short[2]! + short[2]!, 16),
      Number.parseInt(short[3]! + short[3]!, 16),
    ];
  }
  const long = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(text);
  if (!long) return null;
  return [
    Number.parseInt(long[1]!, 16),
    Number.parseInt(long[2]!, 16),
    Number.parseInt(long[3]!, 16),
  ];
}

function toLinear(channel: number): number {
  const value = channel / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function cubeRoot(value: number): number {
  return value > 0 ? Math.cbrt(value) : 0;
}

/** The OKLab lightness of an sRGB triple, 0 for black and 1 for white. */
export function lightness([r, g, b]: Rgb): number {
  const lr = toLinear(r);
  const lg = toLinear(g);
  const lb = toLinear(b);
  const l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb;
  const m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb;
  const s = 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb;
  return (
    0.2104542553 * cubeRoot(l) +
    0.793617785 * cubeRoot(m) -
    0.0040720468 * cubeRoot(s)
  );
}

/**
 * `foreground` over `background` at `alpha`, the way a browser does it.
 *
 * Gamma-encoded sRGB, not linear light. SVG group opacity composites according
 * to `color-interpolation`, which defaults to sRGB, and CSS composites the
 * result the same way. Blending in linear light gives a different and visibly
 * wrong answer on a dark ground, so this has to match the compositor rather
 * than be the more principled of the two.
 */
function over(foreground: Rgb, background: Rgb, alpha: number): Rgb {
  return [0, 1, 2].map(
    (index) =>
      alpha * foreground[index]! + (1 - alpha) * background[index]!,
  ) as Rgb;
}

/** How far one mark of `ink` at `alpha` moves `page`, in OKLab lightness. */
export function markWeight(ink: Rgb, page: Rgb, alpha: number): number {
  return Math.abs(lightness(over(ink, page, alpha)) - lightness(page));
}

/**
 * The alpha at which one mark of `ink` moves `page` by `target`.
 *
 * Bisection rather than a closed form: the OKLab lightness of an sRGB blend is
 * not invertible in closed form, and 24 halvings of the unit interval settle
 * the answer to under 1e-7, which is three orders finer than the four decimals
 * it is written out at.
 *
 * Monotone in alpha for any ink and any page, so the bisection cannot land in a
 * local answer: increasing the coverage of a colour moves the result toward it
 * and never back.
 *
 * Returns 1 for an ink that cannot reach the target at any alpha, which is an
 * ink whose own lightness is nearer the page than the target is: an ink that
 * faint cannot draw a mark that heavy, and the tile comes out faint rather than
 * fully opaque, because the alpha is capped downstream.
 */
export function solveAlpha(ink: Rgb, page: Rgb, target: number): number {
  if (markWeight(ink, page, 1) < target) return 1;
  let low = 0;
  let high = 1;
  for (let step = 0; step < 24; step += 1) {
    const mid = (low + high) / 2;
    if (markWeight(ink, page, mid) < target) low = mid;
    else high = mid;
  }
  return (low + high) / 2;
}
