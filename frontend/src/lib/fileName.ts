/**
 * What a file's name and the folders above it say about the book, before
 * anything is opened.
 *
 * The floor under every format reader: a file whose own metadata is unusable is
 * a dead end without this, and an ordinary book that needs looking up with it.
 * For PDF that is the common case rather than the exception.
 *
 * **Strings in, strings out, and no `File` anywhere in this module.** It is the
 * same property `draftFromFile` has and it is asserted the same way, by the
 * signature: the reader modules hold the only `ArrayBuffer` of somebody's book
 * and `tests/houseRules.test.ts` keeps those off the network. This module is on
 * the other side of that line, because what it derives is *meant* to be sent,
 * so what it may see is a name and never a byte.
 *
 * **A name is untrusted input.** A member downloads files named by other
 * people, so everything here bounds rather than trusts: the query is cut to the
 * ceiling `/api/books/search` declares, control characters are removed, and an
 * ISBN is believed only when its own check digit agrees. What a crafted name
 * cannot do is cost more than one search, because the fan out is per file and
 * the number of files is what `hooks.ts` paces.
 *
 * **No filename grammar.** Naming conventions are open ended, and an
 * enumerating parser is the guard shape this repository has paid for more than
 * once. Four signals, each of which either fires or does not:
 *
 * 1. an ISBN anywhere in the name, decided by its check digit
 * 2. a four digit year in a plausible range, preferred from inside brackets
 * 3. a folder name that also appears in the file's own name, which is the only
 *    thing here that names an author
 * 4. everything else, handed to the catalogue as a plain query
 *
 * **Which side of a hyphen is the author is not guessed**, and that is the
 * exclusion worth stating: `Le Guin, Ursula K. - The Dispossessed.epub` and
 * `The Dispossessed - Le Guin, Ursula K..epub` are the same file to this
 * module. Both produce the same query, so the catalogue answers both the same
 * way; what differs is only the draft shown when the catalogue answers nothing,
 * and there the whole stem is the title, which is honest about what was known.
 */

import { BookFormat } from "../api/generated/model";
import { parseIsbn, normalise as normaliseIsbn } from "./isbn";

/**
 * The extensions the walk considers.
 *
 * **An enumeration is right here and it is the one shape this repository
 * distrusts, so the reason is stated**: this set is closed by a decision rather
 * than open by nature. The formats epic settled the seven that are in and the
 * eight that are out on 2026-09-05, and a format joining it is a ticket rather
 * than a file somebody drops in a folder.
 *
 * **`lib/audiobook.ts` names the same two audio extensions again**, because it
 * answers a question this map cannot: whether one file of a kind is a whole
 * book or one track of one. `tests/lib/fileName.test.ts` asserts the two sets
 * equal in both directions.
 *
 * **`.mp3` is here because the grouping rule now exists.** It was held out while
 * one tagged MP3 audiobook was still many rows: admitting it then would have
 * filed a 200 track audiobook as 200 books. `lib/audiobookGroups.ts` is the rule
 * that made it safe, and the picker files a folder of chapters as one candidate.
 *
 * **The cost of admitting it, stated rather than discovered**: a folder of music
 * is a folder of `.mp3`, and pointing the picker at one produces candidate
 * audiobooks. Nothing is written until the member confirms, and the queue says
 * how many files each candidate was made of.
 *
 * **`.fb2.zip` is one extension and is matched whole**, because a FictionBook
 * archive is not a zip that happens to hold one. The match is `endsWith`, so
 * what would make the order matter is one extension being a **suffix** of
 * another, and none here is; it is longest first to read as a set rather than to
 * be one.
 */
export const SUPPORTED_EXTENSIONS = [
  ".fb2.zip",
  ".azw3",
  ".epub",
  ".mobi",
  ".azw",
  ".fb2",
  ".m4b",
  ".cbz",
  ".mp3",
  ".pdf",
] as const;

export type SupportedExtension = (typeof SUPPORTED_EXTENSIONS)[number];

/**
 * What kind of object a file of this extension is a copy of.
 *
 * A total map, so an extension added above without an answer here is a compile
 * error rather than a row filed as whatever the last arm said.
 *
 * **`satisfies` and not an annotation, and the difference is load bearing for a
 * caller.** Both check totality; only `satisfies` leaves the indexed access
 * saying which values are actually in here. Annotated, `FORMAT_FOR_EXTENSION[e]`
 * is the whole of `BookFormat`, so a caller narrowing to what a filename can
 * mean gets `hardcover` in its type and cannot assign the result anywhere that
 * takes only the three below. `lib/moonReader.ts::MoonReaderFormat` is derived
 * from this and is what noticed.
 *
 * **A comic gets `BookFormat.comic`, and it is evidence rather than a guess.**
 * A `.cbz` is a comic the way a `.m4b` is an audiobook: the container is only
 * ever written for one kind of object, so the extension answers this without
 * anything being opened. `backend/enums.py` states what a value has to be able
 * to do to earn a place in that set, and this is the half of it that is here.
 *
 * **`""` is still in the value type and nothing takes it today.** It is what an
 * extension whose object has no member says, which is what `.cbz` said until
 * the enum grew one; the column is nullable precisely so that an extension can
 * answer that rather than be filed as the nearest thing.
 */
export const FORMAT_FOR_EXTENSION = {
  ".epub": BookFormat.ebook,
  ".mobi": BookFormat.ebook,
  ".azw": BookFormat.ebook,
  ".azw3": BookFormat.ebook,
  ".fb2": BookFormat.ebook,
  ".fb2.zip": BookFormat.ebook,
  ".pdf": BookFormat.ebook,
  ".m4b": BookFormat.audiobook,
  ".mp3": BookFormat.audiobook,
  ".cbz": BookFormat.comic,
} satisfies Record<SupportedExtension, BookFormat | "">;

/**
 * A name as it may be printed, with what is not text taken out.
 *
 * The extension is kept: this names the file a member picked rather than the
 * book, and it is what a removal is announced by.
 */
export function plainName(name: string): string {
  return collapse(clean(name));
}

/** The extension this name ends in, or null for a file the walk passes over. */
export function supportedExtension(name: string): SupportedExtension | null {
  const lowered = name.toLowerCase();
  return (
    SUPPORTED_EXTENSIONS.find((extension) => lowered.endsWith(extension)) ??
    null
  );
}

/**
 * How wide a derived query may be, and how narrow.
 *
 * Both are `/api/books/search`'s own bounds on `q` rather than numbers chosen
 * here, for the reason `lib/bookBounds.ts` gives at length: a value outside what
 * the request body will take is a 422 in the middle of somebody's batch.
 * `tests/lib/fileName.test.ts` recomputes both from `openapi.json`.
 *
 * **Nothing bounds the number of words, deliberately.** The server ANDs its
 * terms, so a long query finds less rather than costing more, and the cost of
 * one search is one request per source whatever it says.
 */
// Both live in `bookBounds.ts`, which owns what a request will take. Re-exported
// rather than re-declared so this module's callers need not know that, and so the
// number cannot come back here as a fourth copy.
import { QUERY_CEILING, QUERY_FLOOR } from "./bookBounds";
import { plausibleYear } from "./year";

export { QUERY_CEILING, QUERY_FLOOR };

/** A folder shorter than this corroborates nothing. `A/` is not an author. */
const MIN_FOLDER_LENGTH = 3;

/** Separators a name uses instead of spaces, and the debris left by a split. */
const SEPARATORS = /[_.]+/g;
// Written as escapes because the house rule refuses those two characters in
// this tree's source, and a name on somebody's disk is under no such rule.
const DEBRIS = "\\s\\-\u2013\u2014_.,;:";
const EDGE_DEBRIS = new RegExp(`^[${DEBRIS}]+|[${DEBRIS}]+$`, "g");

/** Bracketed groups, which is where a name puts everything that is not the title. */
const BRACKETED = /[([{][^)\]}]*[)\]}]/g;

/**
 * Anything that is not text, in the two halves that are treated differently.
 *
 * **Removed rather than refused**, both of them: a name is not a query somebody
 * typed, so a bidirectional override in one is debris rather than a reason to
 * drop the book.
 *
 * **A control becomes a space and a format control is deleted**, which is the
 * same split `targets._JOINS` and `targets._MASKS` make on the server and for
 * the same reason: a control separates two things, and a format control sits
 * inside one word. A zero width non joiner is meaningful inside a Persian or a
 * Hindi word, and spacing it would split one term into two that the fan out
 * then ANDs, which finds less rather than more.
 *
 * **U+200B is the one format control on the other side of that split, and it is
 * measured rather than argued.** ICU's own word segmentation, over all 170
 * `\p{Cf}` code points, breaks a word at exactly **1** of them: the zero width
 * space. It is the only word separator Thai, Khmer, Lao and Burmese names have,
 * and `metadata._search_terms` splits on whitespace, so deleting it would hand
 * the fan out one term that matches nothing. That is the failure this split was
 * made to avoid, moved onto a different character.
 */
const NOT_TEXT = /[\p{Cc}\p{Zl}\p{Zp}\u200B]/gu;
const INSIDE_A_WORD = /(?!\u200B)\p{Cf}/gu;

/** What one file's name and its folders were able to say. */
export interface NameClues {
  /** A checksummed ISBN found in the name, or null. */
  isbn: string | null;
  /**
   * The best guess at a title. Never empty unless the name itself is, because
   * the whole cleaned stem is the floor.
   */
  title: string;
  /** A folder that also appears in the name, or null. Never a guessed one. */
  author: string | null;
  /** A four digit year `year.plausibleYear` believes, or null. */
  year: number | null;
  /**
   * What to ask the catalogue, bounded, or null when nothing usable is left.
   *
   * The whole stem rather than the title alone: `q` takes "title, author or
   * both" and the ranking uses every term it recognises, so throwing the author
   * half away to look tidy would cost the match it exists to find.
   */
  query: string | null;
}

/** A file's name and where it sat, which is everything this module may see. */
export interface FileNaming {
  name: string;
  /** Enclosing folders, outermost first. Empty for a file picked on its own. */
  folders: readonly string[];
}

/** The name with its extension, separators and non-text taken off. */
function stemOf(name: string): string {
  const extension = supportedExtension(name);
  const stem = extension ? name.slice(0, -extension.length) : name;
  return collapse(clean(stem).replace(SEPARATORS, " "));
}

function collapse(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** The text with what is not text taken out, each half its own way. */
function clean(text: string): string {
  return text.replace(INSIDE_A_WORD, "").replace(NOT_TEXT, " ");
}

/**
 * An ISBN anywhere in the name, or null.
 *
 * **The check digit decides, never the shape**, which is what makes this a
 * signal rather than a grammar: `parseIsbn` refuses a thirteen digit run that is
 * not bookland and a ten digit one whose modulus 11 does not close.
 *
 * **A ten digit candidate is taken only as a whole token, and a thirteen digit
 * one from anywhere inside a longer run.** The asymmetry is a false positive
 * rate: a random ten digit run passes modulus 11 about one time in eleven, so
 * sliding a window over a date stamped name would invent an ISBN roughly every
 * ninth file. A thirteen digit window has to carry a bookland prefix as well,
 * which no ordinary number in a filename does.
 */
function isbnIn(stem: string): string | null {
  for (const token of stem.split(/[^0-9Xx-]+/)) {
    const candidate = normaliseIsbn(token);
    if (candidate.length !== 10 && candidate.length !== 13) continue;
    const isbn = parseIsbn(candidate);
    if (isbn) return isbn;
  }

  for (const run of stem.match(/\d{14,}/g) ?? []) {
    for (let start = 0; start + 13 <= run.length; start += 1) {
      const isbn = parseIsbn(run.slice(start, start + 13));
      if (isbn) return isbn;
    }
  }
  return null;
}

/** A standalone four digit number that could be a year, brackets preferred. */
function yearIn(stem: string): number | null {
  const bracketed = (stem.match(BRACKETED) ?? []).join(" ");
  return scanForYear(bracketed) ?? scanForYear(stem);
}

/**
 * The first four digit run in the text that is a plausible year.
 *
 * **The window is `year.plausibleYear`'s**, which is where a year a file
 * claims is believed or not.
 *
 * **A run outside it is skipped and the scan goes on**, rather than ending the
 * scan: `Dune 1234 1965.epub` names a book published in 1965, and stopping at
 * the first four digit run answers null for it. Spelled without brackets on
 * purpose, since `yearIn` tries the bracketed groups first and a bracketed
 * example would pass with or without the skip. `tests/lib/fileName.test.ts`
 * carries that name as its own arm.
 */
function scanForYear(text: string): number | null {
  for (const found of text.match(/(?<!\d)\d{4}(?!\d)/g) ?? []) {
    const year = plausibleYear(Number(found));
    if (year !== null) return year;
  }
  return null;
}

/**
 * The folder that also names something in the file's own name, and what is left.
 *
 * **Corroboration, not parsing.** Two instruments have to agree before anything
 * is called an author: a folder says a name and the file repeats it. A folder
 * that appears nowhere in the name says nothing here, because `Downloads`,
 * `Books` and `to read` are folders too.
 *
 * **Outermost first**, which is what a library on disk is shaped like: the
 * author is the folder above the book, and the folder immediately above a file
 * is usually named for the book itself.
 *
 * **A folder that consumes the whole name is refused**, because an author is
 * what is left beside a title. `The Dispossessed/The Dispossessed.epub` names a
 * book twice and no author at all.
 */
function corroboratedAuthor(
  stem: string,
  folders: readonly string[],
): { author: string; title: string } | null {
  for (const folder of folders) {
    const candidate = collapse(clean(folder).replace(SEPARATORS, " "));
    if (candidate.length < MIN_FOLDER_LENGTH) continue;
    const at = stem.toLowerCase().indexOf(candidate.toLowerCase());
    if (at === -1) continue;
    const rest = collapse(
      (stem.slice(0, at) + " " + stem.slice(at + candidate.length)).replace(
        EDGE_DEBRIS,
        "",
      ),
    );
    if (rest === "") continue;
    return { author: candidate, title: rest };
  }
  return null;
}

/** The query the catalogue is asked, bounded, or null when nothing is left. */
function queryFrom(stem: string, isbn: string | null): string | null {
  let text = stem.replace(BRACKETED, " ");
  if (isbn) {
    // The digits themselves are noise in a title search, and the ISBN has
    // already been read off them: they go to the lookup route instead.
    text = text.replace(/[0-9][0-9-]{8,}[0-9Xx]/g, " ");
  }
  const cleaned = collapse(text.replace(EDGE_DEBRIS, ""));
  const points = [...cleaned];
  if (points.length < QUERY_FLOOR) return null;
  if (points.length <= QUERY_CEILING) return cleaned;
  // Cut in code points, never in UTF-16 units, and on a word boundary where
  // there is one inside the last quarter: a query cut mid word asks for a term
  // that is not a word. `lib/bookBounds.ts` carries the reason for the unit.
  const cut = points.slice(0, QUERY_CEILING).join("");
  const space = cut.lastIndexOf(" ");
  return space > QUERY_CEILING * 0.75 ? cut.slice(0, space) : cut;
}

/**
 * What the catalogue is asked about a piece of text that is not a file name.
 *
 * **Here rather than at the caller, because the bound is here.** The scan
 * page's audiobook path has a title and an author out of a file's tags rather
 * than out of its name, and it needs the same cleaning, the same floor and the
 * same cut in code points that a derived query gets. It called `readName` for
 * them, which also applied every rule this module has about **names**: it
 * stripped a trailing supported extension off an album and hunted an ISBN
 * through the author line.
 *
 * **`SEPARATORS` is not applied either, and that is the third name rule.** A
 * file name writes a space as a `_` or a `.`; a tag writes a space. Measured:
 * with it, `S.P.Q.R. Mary Beard` becomes six terms of which four are one
 * letter, and the server ANDs the terms it is given, so an initialism that a
 * catalogue holds whole finds nothing.
 */
export function queryFor(text: string): string | null {
  return queryFrom(collapse(clean(text)), null);
}

/** Everything the name and its folders were able to say about the book. */
export function readName({ name, folders }: FileNaming): NameClues {
  const stem = stemOf(name);
  const isbn = isbnIn(stem);
  const split = corroboratedAuthor(stem, folders);
  // The whole stem is the title when no folder corroborated, brackets and all
  // taken off: a name is a better title than a blank one, and a member editing
  // it is looking at what they picked.
  const bare = collapse((split?.title ?? stem).replace(BRACKETED, " ")).replace(
    EDGE_DEBRIS,
    "",
  );

  return {
    isbn,
    // **No third fallback onto the raw name**, which would carry the extension
    // into the title. A name that reduces to nothing has said nothing, and the
    // caller turns an empty title into one file's failure.
    title: collapse(bare) || collapse(stem),
    author: split?.author ?? null,
    year: yearIn(stem),
    query: queryFrom(stem, isbn),
  };
}
