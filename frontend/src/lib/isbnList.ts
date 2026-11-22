/**
 * A pasted or uploaded list of ISBNs, read into what can be looked up and
 * what cannot.
 *
 * **Separated by anything that is not part of an ISBN**: a line break, a
 * space, a comma, a semicolon, a tab, a quote or a bar, so a column copied out
 * of a spreadsheet and a line of a CSV both read. The hyphens a publisher
 * prints stay inside the token and `isbn.normalise` strips them. The one
 * spelling this loses is an ISBN printed with spaces between its groups,
 * which reads as several short tokens; nothing in a list reads that way more
 * often than one ISBN a line does.
 *
 * **Three answers, not two.** A token shaped like an ISBN, ten or thirteen
 * characters once normalised, whose check digit fails or whose prefix is not
 * Bookland's, is `invalid` and is reported by what was written, so the member
 * can find the typo. Every other token (a header such as `ISBN`, a title, a
 * year) is `ignored` and only counted: listing each word of a title back as a
 * bad ISBN would bury the one real typo under them.
 */

import { normalise, parseIsbn } from "./isbn";

/** What `readIsbnList` made of one text. */
export interface IsbnList {
  /** Canonical ISBN-13s in the order first written, each once. */
  readonly isbns: readonly string[];
  /** ISBN shaped tokens that are not ISBNs, as written, each once. */
  readonly invalid: readonly string[];
  /** Valid ISBNs written again, by either spelling, after their first time. */
  readonly repeated: number;
  /** Tokens that are not shaped like an ISBN at all. */
  readonly ignored: number;
}

const SEPARATORS = /[\s,;|"']+/;

/**
 * The label copied bibliographic text puts on the front, as in
 * `ISBN:9780306406157` or `ISBN-13:978...`. `isbn.normalise` keeps letters,
 * so without this the token is neither an ISBN nor shaped like one, and a
 * real ISBN is only counted as ignored, which nothing names back.
 */
const LABEL = /^ISBN(?:-?1[03])?:?/i;

/** Ten characters ending in a digit or `X`, or thirteen digits. */
const ISBN_SHAPED = /^(\d{9}[\dX]|\d{13})$/;

/** Read `text` as a list of ISBNs. Pure: no request and no bound. */
export function readIsbnList(text: string): IsbnList {
  const isbns = new Set<string>();
  const invalid = new Set<string>();
  let repeated = 0;
  let ignored = 0;
  for (const token of text.split(SEPARATORS)) {
    if (token === "") continue;
    const bare = token.replace(LABEL, "");
    const canonical = parseIsbn(bare);
    if (canonical === null) {
      if (ISBN_SHAPED.test(normalise(bare))) invalid.add(token);
      else ignored += 1;
    } else if (isbns.has(canonical)) {
      repeated += 1;
    } else {
      isbns.add(canonical);
    }
  }
  return { isbns: [...isbns], invalid: [...invalid], repeated, ignored };
}
