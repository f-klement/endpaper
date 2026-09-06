/**
 * What each published scheme is called on screen, what a heading reads as, and
 * what its kind is called where that is worth saying.
 *
 * **One table, because there were about to be three.** The book page's panel
 * and the library's filter each carried their own copy, and the table view
 * would have been the third. `Record<ClassificationScheme, MessageKey>` makes
 * a *missing* scheme a compile error in every copy, so the keys could not
 * drift; the values could, and three places pointing at three different
 * spellings of the same scheme is exactly the drift nobody notices.
 */

import { ClassificationScheme, HeadingKind } from "../api/generated/model";
import type { MessageKey } from "../i18n/en";

export const SCHEME_LABEL: Record<ClassificationScheme, MessageKey> = {
  [ClassificationScheme.ddc]: "classification.scheme.ddc",
  [ClassificationScheme.lcc]: "classification.scheme.lcc",
  [ClassificationScheme.gnd]: "classification.scheme.gnd",
  [ClassificationScheme.lcsh]: "classification.scheme.lcsh",
};

/**
 * What a heading's kind is called, or null where saying it adds nothing.
 *
 * A subject is what a reader already assumes a heading is, so marking every
 * subject would put a word on almost every chip to distinguish it from almost
 * nothing. The two that are worth a word are the ones a catalogue writes into
 * the same field as a subject and that are not one: a disc and a genre.
 *
 * `Record<HeadingKind, ...>` rather than a partial map, so a fourth kind is a
 * compile error here and a decision somebody has to make, rather than a chip
 * that quietly says nothing about it.
 */
export const KIND_LABEL: Record<HeadingKind, MessageKey | null> = {
  [HeadingKind.subject]: null,
  [HeadingKind.content]: "classification.kind.content",
  [HeadingKind.carrier]: "classification.kind.carrier",
};

/**
 * What a heading asserts, reading an undeclared one as a subject.
 *
 * The client's half of `classifications.kind_of`, and the two must not
 * disagree: the API sends null for every row written before the column existed
 * and for every scheme whose records declare no vocabulary, which is all of
 * them but the GND.
 */
export function headingKind(kind: HeadingKind | null | undefined): HeadingKind {
  return kind ?? HeadingKind.subject;
}

/**
 * The words a heading reads as: the caption where there is one, the identifier
 * where there is not.
 *
 * **GND is why the fallback is that way round.** Its `number` is an opaque
 * authority id (`4203576-4`) and its `label` is the heading a person reads,
 * while LCSH carries the heading in `number` and no label at all, and a Dewey
 * number is a notation that is its own caption. So a chip built the other way
 * round shows a German reader a row of digits.
 *
 * **The identifier is still what a filter carries.** This is the display half
 * only: the key stays `scheme:number`, which is the pair that identifies a
 * heading and the reason two catalogues writing one concept in two languages
 * are one filter rather than two.
 */
export function headingText(heading: {
  number: string;
  label?: string | null;
}): string {
  return heading.label ?? heading.number;
}
