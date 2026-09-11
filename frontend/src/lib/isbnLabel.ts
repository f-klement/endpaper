/**
 * The ISBN label a catalogue writes in front of the number.
 *
 * **Separate from `isbn.ts` because that module is a mirror and this is not.**
 * `isbn.ts` mirrors `backend/isbn.py` case for case, and
 * `tests/conformance/isbn.test.ts` refuses an export there that has no shared
 * case: a rule with a second implementation and nothing pinning the two
 * together is the drift that directory exists to stop. This rule has no Python
 * counterpart on purpose. `backend/opds.py` strips `urn:isbn:` and deliberately
 * nothing else, because widening it there would admit the tail of every other
 * URN scheme as an ISBN candidate, and that narrowness is argued at its own
 * site rather than shared with this one.
 *
 * **One home for a rule four readers each spelled for themselves.**
 * `appleBooks.ts` and `adobeDigitalEditions.ts` took `urn:` as optional;
 * `opf.ts` and `calibre.ts` required it, so both refused `ISBN:` and `isbn_` on
 * a value that had announced itself as an ISBN, and the same book imported from
 * two places kept its ISBN once and lost it once.
 */

/**
 * How a catalogue writes that an identifier is an ISBN.
 *
 * **`urn:` optional, because the two spellings are the same fact.** EPUB 3 puts
 * `urn:isbn:`, Apple and Adobe put a bare `isbn`, and Calibre's plugins write
 * both.
 *
 * **Only the letters come off, and that is the whole of it.** `parseIsbn`
 * normalises away everything that is not alphanumeric, so a separator after the
 * word needs no arm here; a class matching one would be dead code that the next
 * reader takes for the thing that makes `isbn_` work.
 *
 * **Anchored, and the anchor is the guard.** Unanchored it would eat `isbn`
 * anywhere in the value, so `9780306406157isbn0306406152` would strip from the
 * middle and hand `parseIsbn` a number the file never wrote. Three readers
 * carried this rule with the `^` untested: removing it left 57, 59 and 85 arms
 * green in `appleBooks.ts`, `opf.ts` and `calibre.ts`. One home is worth having
 * because one test for the anchor covers all of them.
 *
 * **A spelling that is actually written, not a guessed one.** Of the 4 ISBNs
 * `opf.ts` found over 79 real EPUBs, 2 are `urn:isbn:` and 2 are bare; the
 * Apple store measured three more, bare, hyphenated and `isbn_` prefixed,
 * because `ZEPUBID` is an EPUB's own `dc:identifier` copied verbatim.
 *
 * **Being wrong about the prefix cannot invent an ISBN.** Only a literal `isbn`
 * or `urn:isbn` comes off, so what `parseIsbn` then sees is the rest of a value
 * that announced itself as one, and it still has to carry a check digit and a
 * Bookland prefix.
 */
const ISBN_PREFIX = /^(?:urn:)?isbn/i;

/**
 * A catalogue identifier with any ISBN label taken off the front.
 *
 * Returns the value unchanged when it carries no such label, so a caller passes
 * everything through it rather than deciding first.
 */
export function stripIsbnPrefix(value: string): string {
  return value.replace(ISBN_PREFIX, "");
}
