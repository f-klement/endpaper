/**
 * Text a name, a path or a tag carries, drawn up to the bound its callers
 * enforce and one code point past it.
 *
 * **Up to the bound and not past it by more than one, on purpose.**
 * `fileName.ts`'s patterns are quadratic: at 64 KiB one of them spends eight
 * seconds, measured by the security seat, and no caller hands either door
 * anything that long. A property drawing that far would report a cost nothing
 * can reach. So each door's bound is read from the constant its callers
 * enforce, and the one past it is the arm that says the bound was the bound.
 *
 * **Code points, never units**, because every bound here is counted in code
 * points, which is the trap `bookBounds.ts` states at its own site: an astral
 * character is two units and one point, and a run of them is where a cut in
 * units lands between the halves of a pair.
 */

import fc from "fast-check";

import { type Repeated } from "../property";

/**
 * Characters each of which some rule here treats specially: separators,
 * debris, brackets, digits an ISBN or a year is made of, controls, format
 * controls, the zero width space, line and paragraph separators, a
 * bidirectional override, and astral letters. Spelled by code point, because
 * a glyph is not a reliable carrier for several of them.
 */
const SPECIAL = [
  0x20, 0x5f, 0x2e, 0x2d, 0x2013, 0x2014, 0x2c, 0x3b, 0x3a, 0x28, 0x29, 0x5b,
  0x5d, 0x7b, 0x7d, 0x2f, 0x30, 0x31, 0x35, 0x39, 0x58, 0x09, 0x0a, 0x00, 0x7f,
  0x200b, 0x200c, 0x200d, 0x2028, 0x2029, 0x202e, 0xfeff, 0x1f4da, 0x1d400,
  0x10ffff,
].map((point) => String.fromCodePoint(point));

/** One code point: a special one, a word character, or any at all. */
export const codePoint: fc.Arbitrary<string> = fc.oneof(
  { arbitrary: fc.constantFrom(...SPECIAL), weight: 3 },
  { arbitrary: fc.constantFrom(..."abcxyzDUNE"), weight: 3 },
  {
    arbitrary: fc
      .integer({ min: 0, max: 0x10ffff })
      .filter((point) => point < 0xd800 || point > 0xdfff)
      .map((point) => String.fromCodePoint(point)),
    weight: 1,
  },
);

/** How many code points a string is. */
export function points(text: string): number {
  return [...text].length;
}

/** Whether a string carries half of a surrogate pair on its own. */
export function hasLoneSurrogate(text: string): boolean {
  return /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(
    text,
  );
}

/**
 * `length` code points of `run` over and over after `before`, as a
 * `Repeated`: the run whole as often as it fits, then the start of it.
 */
export function repeatedTo(
  run: readonly string[],
  length: number,
  before = "",
): Repeated {
  return {
    before,
    unit: run.join(""),
    times: Math.floor(length / run.length),
    after: run.slice(0, length % run.length).join(""),
  };
}

/**
 * Text of at most `bound + 1` code points: mostly short, and a quarter of the
 * time exactly the bound or one past it, made of a short drawn run repeated.
 *
 * **The long arm is a `Repeated`**, so a counterexample at a path budget
 * prints as a run and a count rather than as four thousand code points; a
 * door spells it with `property.spelled` before handing it on.
 */
export function boundedText(bound: number): fc.Arbitrary<string | Repeated> {
  const short = fc
    .array(codePoint, { maxLength: 24 })
    .map((drawn) => drawn.join(""));
  const atTheBound = fc
    .tuple(
      fc.array(codePoint, { minLength: 1, maxLength: 6 }),
      fc.constantFrom(bound, bound + 1),
    )
    .map(([run, length]) => repeatedTo(run, length));
  return fc.oneof(
    { arbitrary: short, weight: 3 },
    { arbitrary: atTheBound, weight: 1 },
  );
}
