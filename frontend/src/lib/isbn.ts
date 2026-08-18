/**
 * ISBN parsing, validation and canonicalisation.
 *
 * Mirrors `backend/isbn.py`. Duplicated deliberately rather than round-tripped
 * to the server: the barcode scanner has to decide within a video frame
 * whether what it just read is a book, and a network call per frame is not an
 * option. The two implementations are pinned to the same cases by tests on
 * both sides.
 *
 * Lives in `lib/` rather than a page folder because it is domain logic with no
 * UI: the scanner, the manual entry box and the metadata enrichment all use it.
 *
 * What this replaced was `/^(97[89]\d{10}|\d{10})$/`, which rejected every
 * ISBN-10 ending in X, accepted any ten or thirteen digits without checking
 * the digits agreed, and refused hyphenated input.
 */

/** Bookland prefixes. Any other EAN-13 is a real barcode for something that is not a book. */
const BOOKLAND_PREFIXES = ["978", "979"];

/** Strip the grouping publishers print, and upper-case an `X` check digit. */
export function normalise(raw: string): string {
  return raw.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
}

/** Modulus-11 check. The final character may be `X`, meaning ten. */
export function isValidIsbn10(candidate: string): boolean {
  if (candidate.length !== 10) return false;

  const body = candidate.slice(0, 9);
  const check = candidate[9]!;
  if (!/^\d{9}$/.test(body)) return false;
  if (!/^[\dX]$/.test(check)) return false;

  let total = 0;
  for (let index = 0; index < 9; index += 1) {
    total += Number(body[index]) * (10 - index);
  }
  total += check === "X" ? 10 : Number(check);
  return total % 11 === 0;
}

/** Modulus-10 check with alternating 1/3 weights (the EAN-13 scheme). */
export function isValidIsbn13(candidate: string): boolean {
  if (!/^\d{13}$/.test(candidate)) return false;

  let total = 0;
  for (let index = 0; index < 13; index += 1) {
    total += Number(candidate[index]) * (index % 2 === 0 ? 1 : 3);
  }
  return total % 10 === 0;
}

/** Convert a valid ISBN-10 to ISBN-13. The old check digit is discarded. */
export function isbn10ToIsbn13(isbn10: string): string {
  const body = `978${isbn10.slice(0, 9)}`;
  let total = 0;
  for (let index = 0; index < 12; index += 1) {
    total += Number(body[index]) * (index % 2 === 0 ? 1 : 3);
  }
  return body + String((10 - (total % 10)) % 10);
}

/**
 * Normalise and validate, returning the canonical ISBN-13.
 *
 * Null for anything that is not a real ISBN, so a caller can treat a falsy
 * result as "not a book" without a second check.
 */
export function parseIsbn(raw: string | null | undefined): string | null {
  if (!raw) return null;

  const candidate = normalise(raw);

  if (isValidIsbn13(candidate)) {
    return BOOKLAND_PREFIXES.some((prefix) => candidate.startsWith(prefix))
      ? candidate
      : null;
  }
  if (isValidIsbn10(candidate)) {
    return isbn10ToIsbn13(candidate);
  }
  return null;
}

export function isValidIsbn(raw: string | null | undefined): boolean {
  return parseIsbn(raw) !== null;
}
