/**
 * The ISBNs in text a camera frame was read into, and the reads that look like
 * one but fail the check digit.
 *
 * **The check digit is the whole safety of reading printed digits.** Character
 * recognition misreads a digit now and then (a 3 for an 8, a dropped 1), and a
 * misread ISBN is usually another real book. The check digit catches every
 * single digit error and every swap of two neighbours, so a read that passes is
 * offered for confirmation and one that fails is reported as a misread, never
 * looked up.
 *
 * **Read by line, then by group.** A book prints its ISBN grouped with hyphens
 * (`978-3-16-148410-0`) on the copyright page and grouped with spaces under the
 * barcode (`9 783161 484100`), so the groups of one line are joined until they
 * make ten or thirteen characters. A join only ever ends at the end of a group:
 * cutting a group in half would let the first ten digits of an EAN pass the
 * ISBN-10 check by chance, one time in eleven. A single digit group starts a
 * join and never continues one: under a barcode only the first group is one
 * digit, and a copyright page's printer's key (`10 9 8 7 6 5 4 3 2 1`) is
 * nothing but single digits, which would otherwise join into a misread.
 *
 * A label glued to the front (`ISBN978...`, `ISBN-13:`) is cut off, since the
 * recogniser often loses the space after it.
 */

import { normalise, parseIsbn } from "./isbn";

/** What `readPrintedIsbns` found in one recognised text. */
export interface PrintedIsbns {
  /** Canonical ISBN-13s whose check digit holds, in reading order, each once. */
  readonly isbns: readonly string[];
  /** ISBN shaped reads whose check digit fails, as read, each once. */
  readonly misread: readonly string[];
}

/**
 * A label in front of the first digit: `ISBN`, `ISBN-13:` and the like, or any
 * other letters the recogniser made of one.
 */
const LABEL = /^(?:ISBN(?:-?1[03])?:?|[A-Za-z:]+)(?=\d)/i;

/** Punctuation the recogniser leaves after a number at the end of a sentence. */
const TRAILING = /[.,;:]+$/;

/** One printed group: digits and hyphens, perhaps ending in the `X` of ten. */
const GROUP = /^\d[\d-]*[\dXx]?$/;

/** The groups of one line, label and trailing punctuation cut off. */
function groupsOf(line: string): string[] {
  return line
    .split(/\s+/)
    .map((token) => token.replace(LABEL, "").replace(TRAILING, ""))
    .filter((token) => GROUP.test(token));
}

/** One run of groups joined into an ISBN, or into something shaped like one. */
interface Joined {
  /** How many groups the join used. */
  readonly used: number;
  readonly canonical: string | null;
  readonly asRead: string;
}

/**
 * The joins of `groups` from its first group that end on a group boundary at
 * ten or thirteen characters, the longer first: a thirteen digit EAN read whole
 * beats the ISBN-10 its first groups might spell.
 */
function joinsFrom(groups: readonly string[]): Joined[] {
  const joins: Joined[] = [];
  let digits = "";
  for (let used = 1; used <= groups.length; used += 1) {
    const group = normalise(groups[used - 1]!);
    if (used > 1 && group.length < 2) break;
    digits += group;
    if (digits.length > 13) break;
    if (digits.length === 10 || digits.length === 13) {
      const asRead = groups.slice(0, used).join(" ");
      joins.unshift({ used, canonical: parseIsbn(digits), asRead });
    }
  }
  return joins;
}

/** Read one line's groups into what `readPrintedIsbns` reports. */
function readLine(
  groups: readonly string[],
  isbns: Set<string>,
  misread: Set<string>,
): void {
  let start = 0;
  while (start < groups.length) {
    const joins = joinsFrom(groups.slice(start));
    const valid = joins.find((join) => join.canonical !== null);
    if (valid) {
      isbns.add(valid.canonical!);
      start += valid.used;
      continue;
    }
    for (const join of joins) misread.add(join.asRead);
    start += 1;
  }
}

/** Read the text a camera frame was recognised into. Pure: no engine. */
export function readPrintedIsbns(text: string): PrintedIsbns {
  const isbns = new Set<string>();
  const misread = new Set<string>();
  for (const line of text.split(/\r?\n/)) {
    readLine(groupsOf(line), isbns, misread);
  }
  return { isbns: [...isbns], misread: [...misread] };
}
