/**
 * The accession number: the code on a copy's label, and its rules.
 *
 * Mirrors `backend/accession.py`, which says why the code has the shape it has:
 * nine ASCII digits, a lead `2`, the zero padded row id, a Damm check digit.
 * Duplicated rather than asked of the server for the ISBN's reason: a scanner
 * decides within a frame what it just read. `conformance/cases/accession.json`
 * pins the two to the same answers, so this module exports the shared surface
 * and nothing else (`tests/conformance/accession.test.ts` refuses a fourth
 * function).
 */
import { parseIsbn } from "./isbn";

const LEAD = "2";
const SERIAL_DIGITS = 7;
const MAX_SERIAL = 10 ** SERIAL_DIGITS - 1;

/** Damm's quasigroup of order 10: the table every published implementation uses. */
const DAMM: readonly (readonly number[])[] = [
  [0, 3, 1, 7, 5, 9, 8, 6, 4, 2],
  [7, 0, 9, 2, 1, 5, 4, 8, 6, 3],
  [4, 2, 0, 6, 8, 7, 1, 3, 5, 9],
  [1, 7, 5, 0, 9, 8, 3, 4, 2, 6],
  [6, 1, 2, 3, 0, 4, 5, 9, 7, 8],
  [3, 6, 7, 4, 2, 0, 9, 5, 8, 1],
  [5, 8, 6, 9, 7, 2, 0, 1, 3, 4],
  [8, 9, 4, 5, 3, 6, 2, 0, 1, 7],
  [9, 4, 3, 8, 6, 1, 7, 2, 0, 5],
  [2, 5, 8, 1, 4, 3, 6, 7, 9, 0],
];

/** `[0-9]`, never `\d`: the backend's `re.ASCII` and this agree only so. */
const SHAPE = new RegExp(`^${LEAD}[0-9]{${SERIAL_DIGITS + 1}}$`);

/** What a scanned or typed string is, before any lookup. */
export type Reading = "accession" | "isbn" | "unreadable";

/** The last code unit `classify` drops: ASCII space, after every C0 control. */
const WEDGE_NOISE_MAX = 0x20;

/**
 * `text` without ASCII space or any C0 control at either end.
 *
 * Pinned rather than `trim()`, whose set is not Python's `strip()`: `trim()`
 * keeps U+001C to U+001F and drops U+FEFF. A keyboard wedge sends U+001D for a
 * Code 128 FNC1, and `backend/accession.py` drops this same set.
 */
function withoutWedgeNoise(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && text.charCodeAt(start) <= WEDGE_NOISE_MAX) start++;
  while (end > start && text.charCodeAt(end - 1) <= WEDGE_NOISE_MAX) end--;
  return text.slice(start, end);
}

function damm(digits: string): number {
  let interim = 0;
  for (const digit of digits) {
    interim = DAMM[interim]![Number(digit)]!;
  }
  return interim;
}

/**
 * The accession number of the Book with this id.
 *
 * Throws past the largest serial rather than widening: a tenth digit would make
 * the code an ISBN-10's length, the one property the shape exists for.
 */
export function mint(bookId: number): string {
  if (!Number.isInteger(bookId) || bookId < 1 || bookId > MAX_SERIAL) {
    throw new RangeError(
      `${bookId} is outside the range an accession number can carry`,
    );
  }
  const body = LEAD + String(bookId).padStart(SERIAL_DIGITS, "0");
  return body + String(damm(body));
}

/** Whether `text` is, exactly, a minted accession number with a sound check digit. */
export function isAccession(text: string): boolean {
  return SHAPE.test(text) && damm(text) === 0;
}

/**
 * What a scanned or typed string names: a copy, a book by ISBN, or nothing.
 *
 * ASCII space and C0 controls are dropped from either end, since a keyboard
 * wedge ends its digits with a newline and may open them with a group
 * separator; nothing inside is.
 */
export function classify(text: string): Reading {
  const stripped = withoutWedgeNoise(text);
  if (isAccession(stripped)) return "accession";
  if (parseIsbn(stripped) !== null) return "isbn";
  return "unreadable";
}
