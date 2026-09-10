/**
 * What a year is, for a value read out of somebody's file.
 *
 * **Two rules, one home, and the home is neither the readers nor the API
 * bounds.** `bookBounds.ts` is what `POST /api/books/scan` will hold, applied
 * to a value on its way out; this is what a number has to be before it is worth
 * calling a publication year at all. The window lived in that module and its
 * own docstring said the misfit out loud, that a window is part of reading a
 * year rather than part of bounding one for the API, and adding the date rule
 * beside it would have made a bounds module the home of a regular expression.
 *
 * **The same move `lib/xmlEntities.ts` and `lib/sqliteRow.ts` already are.**
 * One holds a parsing rule that four readers apply and the seam did not want;
 * the other holds the row vocabulary two database readers had each declared.
 * This is the third of that shape, so it states what may join it: a function
 * belongs here when it answers what a year is, out of a value some file
 * supplied, without knowing what kind of file supplied it. A rule that has to
 * read a SQLite cell, an XML element or an EXTH record to get its string is a
 * fact about that container and stays at its reader.
 *
 * **Not the API's bound and never a replacement for it.** A value on its way
 * into a request still goes through `bookBounds.boundNumber("year", ...)`,
 * which is what the column will hold. These two answer different questions
 * about the same number, and `tests/lib/year.test.ts` pins the difference with
 * the one value that separates them.
 */

/**
 * The window a year read out of a file has to fall in to be believed.
 *
 * **Plausibility, and `NUMBER_RANGES.year` is storability.** That one is what
 * `BookCreate` will hold; this one is what a publication year could credibly
 * be, and the two answer different questions about the same number. Collapsing
 * this into that is the simplification to refuse: it is wider, so it accepts
 * everything below and reports nothing.
 *
 * **Here because of a value real files carry, not as a validator.** Calibre
 * writes `0101-01-01T00:00:00+00:00` where a book has no date, and it writes it
 * into every field it uses for one: EXTH 106 in a MOBI, `dc:date` in an OPF,
 * `pubdate` in `metadata.db`. It reads as the year 101, which is inside
 * `NUMBER_RANGES.year`, so nothing downstream stops it and a member sees a book
 * published in the second century. 2 of the 69 real MOBI files measured
 * 2026-09-07 carry it; `calibre.ts::withoutPlaceholders` carries the count for
 * the OPF spelling, against a real library.
 *
 * **Chosen rather than measured, and wide on both ends on purpose**: a signal
 * that has to be wrong rarely, not a bound anything enforces. No schema stands
 * behind it, which is the other half of why it is not in `bookBounds.ts`: every
 * number there is recomputed from `openapi.json` by that module's own test, and
 * this pair is the one nothing can recompute. `tests/lib/year.test.ts` states
 * it, reads it back out of the declaration and asserts it has one home.
 *
 * Not exported, because `plausibleYear` is the whole interface: the readers
 * that each declared these two numbers each wrote the comparison out again
 * beside them, and handing out the pair leaves that second copy in place.
 */
const PLAUSIBLE_YEARS = [1450, 2100] as const;

/**
 * The year a file claims, when a book could have been published in it.
 *
 * **The one home of the window, and the readers that take a year out of a file
 * call it.** Three of them each held their own copy of the pair, and the third
 * was written by somebody who had read the second and pointed a comment at it;
 * what stops the next copy is that there is nothing left to copy.
 * `tests/lib/year.test.ts` names the callers, so the list is not written out
 * here as well.
 *
 * **Every reader that takes a year out of a file calls it, with no exception**,
 * which is what that list asserts rather than merely records.
 *
 * **A window is part of reading a year, not part of bounding one for the API.**
 * Every one of those readers says in its own docstring that it reports what its
 * file claims, so each of them raises this question and the answer is here
 * once: a number outside the window is not a publication year the file
 * asserted, it is a number sitting in a date field, and reporting it as a year
 * is the reader getting the field wrong. `cbz.readYear` reached the same
 * conclusion on its own for ComicRack's `-1`.
 *
 * **This is not `boundNumber("year", ...)` and does not replace it.** A value on
 * its way to a request still goes through that one, which is what the column
 * will hold; this says only that the number is worth sending. Swapping it in on
 * a year a member typed drops a genuine 1400 and says nothing, which is why
 * `tests/lib/year.test.ts` asserts who imports this by name.
 *
 * **The comparison is written here rather than taken from `bookBounds.within`**,
 * which is four lines this module could have imported. Importing it would make
 * what a year is depend on what a request body holds, which is the dependency
 * this module exists to remove, and it points the wrong way: a reader would
 * then reach the API bounds module through this one.
 */
export function plausibleYear(value: number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  if (!Number.isFinite(value)) return null;
  const [low, high] = PLAUSIBLE_YEARS;
  return value >= low && value <= high ? value : null;
}

/**
 * The year a timestamp leads with, where a book could have been published in it.
 *
 * **Four readers declared this and it was one function four times.**
 * `calibre.ts` and `kobo.ts` held it under one name, `readYear`, and `opf.ts`
 * and `mobi.ts` held the same two lines inline: the same anchored pattern, the
 * same `Number`, the same window. Measured 2026-09-10 across `src/lib`: those
 * four and no others. `fb2.ts` takes the first four digit run anywhere in the
 * text, `pdf.ts` the first anywhere at all and `fileName.ts` a standalone one
 * out of a file name, so those three are a different rule and are not this.
 *
 * **It is here rather than beside the readers because of where the seam is.**
 * The duplicated function knew two things: how to get a string out of a SQLite
 * cell, an XML element or an EXTH record, and what a leading four digit run
 * means. The first is the reader's own vocabulary and stays there, which
 * `string | null` is what enforces: a caller holding an `unknown` has to
 * coerce it at its own site. The second is what a year is, which is the
 * question `plausibleYear` above already answers.
 *
 * **Only the leading four digits, and the rest is ignored on purpose.** These
 * are ISO timestamps, so a timezone offset puts the day either side of
 * midnight and no book's year turns on it.
 *
 * **`\d` is ASCII, here and under `/u`, so a date written in Arabic-Indic or
 * Devanagari digits reads as no year.** That is what all four readers did
 * before this existed and it is not a decision this move made. It is stated
 * because one home is where somebody reaches for `\p{Nd}` for completeness and
 * changes four readers at once: none of these formats writes a date in
 * anything but ASCII, and a run of digits that is not a date is what the window
 * is for.
 *
 * **No trimming and no stripping here**, which is the other half of the seam:
 * `mobi.clean` takes NULs out of an EXTH record and the other three trim, each
 * for a reason about its own container. A normaliser migrating into this
 * function would silently give the other three an arm none of them has.
 */
export function leadingYear(raw: string | null): number | null {
  const match = raw === null ? null : /^(\d{4})/.exec(raw);
  return match === null ? null : plausibleYear(Number(match[1]));
}
