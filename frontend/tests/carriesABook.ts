/**
 * What a value has to be typed as to carry a member's book.
 *
 * `File` extends `Blob`, and both array views are what a reader hands back, so
 * naming only the first is the weaker of two spellings of one rule. Two guards
 * shipped one commit apart naming different sets, `File` in one and `File|Blob`
 * in the other, and the narrower one admitted a parameter taking a member's
 * book with no cast.
 *
 * **One home, so that holding this rule is using it.** The alternative was a
 * copy per guard and a sibling asserting the text appears in each, which is a
 * presence check: it passes while a guard narrows the copy it actually applies.
 * That was measured, with a `Blob` parameter admitted and every arm green.
 *
 * `tests/lib/fileName.test.ts` writes the pattern out rather than importing it,
 * and `tests/pages/ScanPage/types.test.ts` asserts that this exact text is
 * there. That one is a different rule over a different module and shares only
 * the literal.
 *
 * ## Families, because a list of type names is a list somebody adds to
 *
 * This was four names in an alternation until it was attacked: six spellings of
 * a binary buffer passed it, `DataView` among them, and `DataView` has eleven
 * occurrences in `src/lib/mobi.ts`. A fifth arm would have admitted the
 * seventh. So the shape is a morpheme with anything either side of it:
 *
 * - `Array` catches every typed array, which is what the family is named by:
 *   `Uint8Array`, `Int8Array`, `Uint8ClampedArray`, `BigInt64Array`.
 * - `Blob` catches `BlobPart`, which is `BufferSource | Blob | string`.
 * - `Buffer` catches every name carrying that morpheme. The ones it alone
 *   catches are those carrying none of `Array`, `Blob` or `Stream`, which
 *   includes `AllowSharedBufferSource`, itself `ArrayBuffer` or a view over
 *   one. `ArrayBuffer` and its views reach the array arm first, which is why
 *   the row driving this arm names `BufferSource` rather than a view.
 * - `Stream` catches `ReadableStream` and its reader.
 *
 * **`Blob` is a family and not a bare name, and that was the security seat's
 * finding.** Written out beside `DataView` it refused `Blob` and admitted
 * `BlobPart`, which carries a member's book: a builder taking one passed every
 * arm. A name written out is a name somebody has to think of; a morpheme is
 * not.
 *
 * **The morpheme half over-matches, and two of the three guards read whole
 * lines or whole modules rather than a parameter.** The bare words `Array`,
 * `Buffer` and `Stream` are refused, and so is every `MediaStream*`. So
 * `Array.from(...)` in `lib/fileName.ts`, or `tags: Array<string>` in
 * `pages/ScanPage/types.ts`, would fail a no-custody rule while carrying no
 * book. Neither spelling is in either module today. It is the loud direction
 * and it is written down here because the failure would otherwise arrive with
 * no explanation attached to it.
 *
 * **A prefix has to be capitalised**, so a parameter named `bookArray` and a
 * call to `isArray` are not mentions of a type. It fires on nothing in the two
 * modules read whole today, which is why the admitted row
 * `a parameter merely named for an array is admitted` exists: without it this
 * refinement is a narrowing nothing would notice the loss of.
 *
 * **The `File` family is the one with no structural separator**, because this
 * tree spells its own types the same way the DOM spells its handles:
 * `FileMetadata` and `FileNaming` sit beside `FileList` and
 * `FileSystemFileHandle`. So this half is inverted: every `File`-prefixed name
 * is refused **except** the ones this repository declares. That is the
 * direction that fails loudly. A DOM type nobody here anticipated is refused
 * the day it is written, where the enumeration it replaces admitted it in
 * silence; the cost is that a new `File`-prefixed type of this tree's own is
 * refused until it is named above, which reports itself by name.
 *
 * `FileReader` is refused and is not an oversight: this tree declares one, in
 * `src/lib/fileReaders.ts`, and it is `(file: Blob) => Promise<FileReading>`.
 * A builder handed one can read a member's book.
 *
 * **Nothing is exempted that the tree does not spell.** `FileResponse` was on
 * the list and occurs in `src/` only inside a docstring, which the census
 * strips, so removing it changed nothing: an exemption covering nothing is one
 * waiting to cover something, and the backend returns a `FileResponse` from
 * `routers/covers.py`, so a generated model of that name would have arrived
 * admitted. It is refused now, and the census names it the day it is code.
 *
 * **The exception list is pinned against the tree rather than trusted.**
 * `tests/houseRules.test.ts::sorts every File name the source spells onto one
 * side or the other` recomputes both sides from `src/` with comments stripped,
 * so a name arriving on neither fails there and says which it is.
 *
 * ## What it does not see, as a property rather than as a list
 *
 * **It reads type names.** So a byte carrier sharing no morpheme with a family
 * and no prefix with `File` is outside it, `ImageBitmap` and `MediaSource`
 * among them, and `DataView` is written out because it is the one such name a
 * builder in this tree is actually handed.
 *
 * **And a structural type spelled with brackets is outside it too**, which is
 * the same type on both sides of the line: `Array<number>` is refused because
 * `Array` is a name, and `number[]` is admitted.
 *
 * **A bracket arm was proposed and refused, and the reason is not the obvious
 * one.** An array of a carrier is already refused on its element name:
 * `Uint8Array[]`, `Blob[]` and `File[]` all match as they stand. What such an
 * arm would newly reach is `number[]`, which is bytes by convention only, and
 * which this tree spells as `tagIds: number[]` in `pages/ScanPage/types.ts`,
 * a module one of these guards reads a line at a time. So it adds no carrier
 * and costs a false positive.
 *
 * And spelled inside the word boundaries this pattern is wrapped in it would
 * add nothing whatever: `]` is not a word character, so the trailing `\b`
 * wants one after it and there never is one. Measured both ways, because the
 * first draft of this paragraph argued the false positive from a reading taken
 * on the bare arm and the dead arm from a reading taken on the wrapped one,
 * and stated them as though they were one measurement.
 */
export const CARRIES_A_BOOK =
  /\b(?:DataView|(?:[A-Z]\w*)?(?:Array|Blob|Buffer|Stream)\w*|File(?!Metadata|Naming|Identifier|Failure|Reading|PickPanel)\w*)\b/;
