/**
 * What a Kindle or Mobipocket file says about the book, read in the member's
 * own browser.
 *
 * **One parser for three extensions.** `.mobi`, `.azw` and `.azw3` are the same
 * Palm Database container holding a MOBI header of a different version, and no
 * byte read here depends on which name the file arrived under. What differs
 * between them is the *content* format, which this never opens: the metadata is
 * in the EXTH block inside record 0 and needs no decompression at all.
 *
 * **Nothing here is decompressed and no text record is read.** The reader takes
 * the 94 byte head of the file, then one record, and stops. That is why this
 * costs no dependency and no WASM, and it is also the bound that matters: a
 * hostile file cannot make this allocate more than `MAX_RECORD_ZERO_BYTES`
 * whatever it declares about itself.
 *
 * **Every read is bounded and no read throws.** `DataView` answers a
 * `RangeError` past its end, which in a member's import is a crashed panel
 * rather than one file's failure, so every accessor below answers `null`
 * instead and every offset the file supplied is checked against the buffer it
 * points into before it is believed. The custody rule and the reason the parse
 * happens here at all are stated once, in `epub.ts`.
 *
 * ## What was measured, and against what
 *
 * **69 real files, fetched 2026-09-07**, none of them converted here: a
 * converter's output agrees with its own reader, which is a harness agreeing
 * with itself. 48 from Project Gutenberg's cache (24 works in both their
 * `.mobi` and their KF8 rendering, public domain), 9 `.azw3` from Standard
 * Ebooks (CC0), 11 from the Internet Archive under a stated Creative Commons
 * licence, and 1 `.mobi` from the household's own Calibre library. **0 real
 * `.azw` files**: DRM free ones are not distributed, and the extension is the
 * only thing about one that differs.
 *
 * **Every offset this reader believes a file about is annotated with which of
 * the two it came from**: a file that exercised it, or the format's
 * specification with no file behind it. The Palm header's own two are at
 * `RECORD_COUNT_AT` and `recordZeroExtent`, and record 0's are tabulated above
 * them. The sizes that are not offsets, the 78 byte header, the 8 byte table
 * entry and the EXTH headers, are the format's fixed shape rather than
 * something read out of a particular file.
 *
 * **Both container shapes are in that corpus, which is what makes reading only
 * record 0 safe rather than lucky.** 5 of the 69 are joint MOBI6 and KF8
 * containers, where record 0 is the MOBI6 header and EXTH 121 names the
 * boundary at which the KF8 half starts; in the other 64 record 0 is the only
 * header, 33 of those declaring file version 8. This reader opens record 0 and
 * nothing else, so the two shapes are the same to it.
 *
 * ## What this cannot supply, stated as the exclusion
 *
 * **Series, series index and subtitle: the format has no field for any of
 * them.** Not a gap in this reader. EXTH has no series record in either
 * independent implementation of it, and Calibre, which invented the EPUB 2
 * spelling of a series because that format lacked one too, writes nothing for
 * it here. A book whose series matters arrives from the catalogue lookup or
 * from the member.
 *
 * **Page count and cover: not read.** The cover is a record of image bytes and
 * this reader does not open records.
 */

import { plausibleYear } from "./bookBounds";
import { parseIsbn } from "./isbn";
import type { FileIdentifier, FileMetadata } from "./fileReaders";

/**
 * Why a file yielded nothing.
 *
 * A subset of `fileReaders.FileFailure`, and two of the three are names that
 * union already carried: a file that is damaged is damaged whatever format it
 * claimed, and a member reading the sentence does not care which parser said
 * it. Only `not-a-mobi` is new, and it is new for the reason `not-an-epub` is
 * its own reason: it is the one that means "this is a different kind of file",
 * which is the sentence that tells a member to check what they picked.
 */
export type MobiFailure =
  /** Not a Palm Database, or one holding something that is not MOBI. */
  | "not-a-mobi"
  /** A Palm Database whose own offsets do not agree with its length. */
  | "damaged"
  /** Encrypted, which here means DRM, and DRM is out of scope. */
  | "protected";

export type MobiReading =
  | { readonly ok: true; readonly metadata: FileMetadata }
  | { readonly ok: false; readonly failure: MobiFailure };

/** The fixed Palm Database header, ahead of the record offset table. */
const PDB_HEADER_BYTES = 78;

/** One entry in that table: a four byte offset, then attributes and an id. */
const PDB_ENTRY_BYTES = 8;

/**
 * Where the type and creator sit in that header, and what a MOBI's say.
 *
 * **This is the refusal the format's neighbours need**, and it is first because
 * it is the only test that costs nothing to be wrong about: the container is
 * shared with eReader (`PNRd`), Plucker (`DataPlkr`) and PalmDOC (`TEXtREAd`),
 * so a `.pdb` renamed to `.mobi` reaches here and has to be told apart from a
 * book. Refusing on these eight bytes refuses it **before any offset inside the
 * file has been believed**, which is worth more than the eight bytes suggest.
 *
 * It is not on its own sufficient, and is not treated as though it were:
 * anybody can write `BOOKMOBI` in front of anything, so record 0's own magic is
 * checked as well. Measured `BOOK` and `MOBI` in 69 of 69 real files.
 *
 * **KFX is refused here too, and by construction rather than by a rule about
 * KFX.** It is not a Palm Database at all, so it has no type and no creator to
 * match and never reaches the header reads below. That is the whole of the
 * refusal the formats epic asked for: it is a different container, it is
 * normally DRM bound, and reading it is a different problem with a legal
 * dimension this one does not have. Nothing should be added here to make it
 * work.
 */
const PDB_TYPE_AND_CREATOR = "BOOKMOBI";
const PDB_TYPE_AT = 60;

/**
 * How much of record 0 this will hold.
 *
 * Measured over the 69 files: record 0 is 2,432 to 10,616 bytes, median 9,132.
 * 1 MiB is 98 times the largest, which leaves room for a producer writing a
 * very long description or a hundred subjects into the EXTH block, and still
 * refuses a file whose offset table claims a 400 MB record 0. It is a bound on
 * what is **allocated**, taken before the slice is read, so a declared size is
 * never what decides how much memory this costs.
 *
 * **Passing it is reported as `damaged`, not as a file being large.** At 98
 * times the largest record 0 ever seen, nothing that reaches this arm is a big
 * book: it is a file whose offset table disagrees with itself, which is what
 * `damaged` says. "This file is too large to read here" would send somebody to
 * look for a smaller copy of a file that may be 200 kB.
 */
const MAX_RECORD_ZERO_BYTES = 1024 * 1024;

/**
 * The smallest record 0 that could hold a MOBI header at all.
 *
 * The PalmDOC header is 16 bytes and the MOBI magic is the four after it, so
 * this is the point below which the encryption field and the magic cannot both
 * be read. Every fixed offset past it is checked again by `u16` and `u32`.
 */
const MIN_RECORD_ZERO_BYTES = 20;

/**
 * How many records the database says it holds, in the Palm header.
 *
 * Read off a file: 69 of 69 carry a count whose table ends exactly two bytes
 * before record 0 begins.
 */
const RECORD_COUNT_AT = 76;

/**
 * Offsets inside record 0, each with what it was read off.
 *
 * | offset | field | read off |
 * |---|---|---|
 * | 0x0c | encryption | the specification. All 69 files declare 0, so nothing here has a real DRM file behind it |
 * | 0x10 | the `MOBI` magic | 69 of 69 |
 * | 0x14 | MOBI header length | 69 of 69, since the EXTH magic lands at 16 plus it |
 * | 0x1c | code page | 68 of 69 declare 65001, and the one declaring 1252 decodes correctly under it |
 * | 0x54, 0x58 | full name offset and length | 69 of 69, and equal to EXTH 503 in the 61 files carrying both |
 */
const ENCRYPTION_AT = 0x0c;
const MOBI_MAGIC_AT = 0x10;
const HEADER_LENGTH_AT = 0x14;
const CODEPAGE_AT = 0x1c;
const FULL_NAME_OFFSET_AT = 0x54;
const FULL_NAME_LENGTH_AT = 0x58;

const MOBI_MAGIC = "MOBI";
const EXTH_MAGIC = "EXTH";

/** The EXTH block's own header: the magic, its length, and a record count. */
const EXTH_HEADER_BYTES = 12;

/** One EXTH record's header: a type number and a length that includes both. */
const EXTH_RECORD_HEADER_BYTES = 8;

/**
 * The EXTH record types this reads.
 *
 * **Every number here was read off a real file rather than off a table**, which
 * is what the ticket asked for and is the reason each carries its count. Two
 * independent implementations, `libmobi` and KindleUnpack, name the same
 * numbers; agreement between two readers of the same specification is one
 * instrument twice, so the counts below are the evidence and the agreement is
 * only a check on it.
 *
 * | type | field | carried by |
 * |---|---|---|
 * | 100 | author | 69 of 69 |
 * | 101 | publisher | 17 of 69 |
 * | 103 | description | 7 of 69 |
 * | 104 | ISBN | 4 of 69 |
 * | 106 | publication date | 67 of 69 |
 * | 503 | title | 61 of 69 |
 * | 524 | language | 65 of 69 |
 *
 * **104 is the one the ticket was written for, and it pays.** All 4 files
 * carrying it are publisher produced, and they spell the value three different
 * ways: `978-1-61016-605-8`, `9781593276850` and `0615445675`. An identifier
 * arriving as a typed record rather than as a string to be sniffed still has to
 * go through `parseIsbn`, which is what turns those three into one.
 *
 * **What is deliberately not read**, each with the reason it was dropped:
 *
 * * **113, which the format calls the ASIN.** 61 of 69 files carry it and not
 *   one holds an Amazon identifier: Calibre writes its own library uuid there
 *   and Standard Ebooks a content hash. It identifies the production of the
 *   file rather than the book, and a wrong scheme on a right looking value is
 *   worse than no identifier at all.
 * * **112, `dc:source`.** 60 of 69 carry it, and it is a provenance URL or a
 *   `calibre:` uuid. Same reason.
 * * **108, which the format calls the contributor.** 63 of 69 files carry it.
 *   54 of those name the toolchain (`calibre (9.5.0)`, `Smashwords, Inc.`) and
 *   9 name the person who produced the edition, one of whom appears in 6 of
 *   those 9. Neither is the author, and a reader taking it for one would file
 *   six books under the same typesetter.
 * * **105, the subject.** 62 of 69 carry it, usually several records. There is
 *   nowhere for it to go: `FileMetadata` has no tags and the scan page's draft
 *   sends none.
 */
const AUTHOR = 100;
const PUBLISHER = 101;
const DESCRIPTION = 103;
const ISBN = 104;
const PUBLISHED = 106;
const UPDATED_TITLE = 503;
const LANGUAGE = 524;

/**
 * A `DataView` read that answers `null` past the end rather than throwing.
 *
 * The whole of the bounding, and it is structural: **there is no offset in this
 * module that reaches a byte without going through `u16`, `u32`, `ascii` or
 * `slice`**, so a field added later cannot be the one that forgot. That is a
 * property of the code rather than a discipline, and it is the reason `slice`
 * exists at all: two reads used to do their own arithmetic and hand it to
 * `new Uint8Array(buffer, offset, length)`, which throws the one thing this
 * module promises never happens.
 *
 * **Big endian, which is the opposite of `lib/zip.ts`'s pair of the same
 * name.** A Palm Database is big endian throughout and a zip is little endian
 * throughout; the two modules read different formats and neither number is a
 * default worth sharing.
 */
function u16(view: DataView, at: number): number | null {
  return at >= 0 && at + 2 <= view.byteLength ? view.getUint16(at) : null;
}

function u32(view: DataView, at: number): number | null {
  return at >= 0 && at + 4 <= view.byteLength ? view.getUint32(at) : null;
}

/** The bytes at an offset the file supplied, or `null` when they do not fit. */
function slice(view: DataView, at: number, length: number): Uint8Array | null {
  if (at < 0 || length < 0 || at + length > view.byteLength) return null;
  return new Uint8Array(view.buffer, view.byteOffset + at, length);
}

/** ASCII at a fixed offset, or `null` when it does not fit. */
function ascii(view: DataView, at: number, length: number): string | null {
  if (at < 0 || at + length > view.byteLength) return null;
  let out = "";
  for (let index = 0; index < length; index += 1) {
    out += String.fromCharCode(view.getUint8(at + index));
  }
  return out;
}

/**
 * Which decoder reads this file's text.
 *
 * Mobipocket declares one of two code pages and nothing else is legal.
 * Measured: 68 of 69 files declare 65001 and 1 declares 1252, so both arms are
 * exercised by a real file rather than only by the specification.
 *
 * **Anything else falls to windows-1252 rather than to UTF-8**, because the
 * files that get this wrong are old ones and windows-1252 maps every byte, so
 * the fallback cannot throw and cannot lose a record. A `TextDecoder` for a
 * label a runtime does not know throws on construction, which is why even this
 * is guarded.
 */
const UTF8_CODEPAGE = 65001;

function decoderFor(codepage: number | null): TextDecoder {
  if (codepage === UTF8_CODEPAGE) return new TextDecoder("utf-8");
  try {
    return new TextDecoder("windows-1252");
  } catch {
    return new TextDecoder("utf-8");
  }
}

/**
 * One EXTH block, as the values it carried, keyed by type.
 *
 * A `Map` of arrays rather than one value per type, because a type may repeat
 * and one of them means something when it does: 1 of the 69 files carries two
 * author records, which is how the format says two authors, and taking the
 * first would have filed that book under one of them.
 */
type ExthRecords = ReadonlyMap<number, readonly Uint8Array[]>;

/**
 * Read the EXTH block, or an empty map when the file has none.
 *
 * **The magic decides whether there is a block, and the flag at 0x80 is not
 * read at all.** The specification says a bit there announces the block; the
 * magic four bytes at `16 + headerLength` say the same thing and are the bytes
 * that would have to be right anyway. Measured: the two agree in 69 of 69 real
 * files, so the flag is a second offset that can be wrong for no gain, and one
 * test is a smaller surface than two.
 *
 * **The declared block length bounds the walk, and so does the record.** Six of
 * the 69 files consume 1 to 3 bytes fewer than they declare, which is padding
 * to a four byte boundary; none consumes more. So the declared length is a
 * usable end and never a reason to keep reading past the buffer, and the walk
 * stops at whichever comes first.
 *
 * A record whose own length does not advance the cursor ends the walk. Written
 * as "does not fit" rather than as an arm per way of being wrong: a length
 * below the eight byte header and a length running past the end are the same
 * fault, and enumerating them is how the third one gets missed.
 */
function readExth(record: DataView, at: number): ExthRecords {
  const found = new Map<number, Uint8Array[]>();
  if (ascii(record, at, 4) !== EXTH_MAGIC) return found;

  const declared = u32(record, at + 4);
  const count = u32(record, at + 8);
  if (declared === null || count === null) return found;

  // The block ends where it says it does or where the record does, whichever
  // is sooner. `at + declared` can overflow no bound here: both are `uint32`
  // and JavaScript numbers hold the sum exactly.
  const end = Math.min(at + declared, record.byteLength);

  let cursor = at + EXTH_HEADER_BYTES;
  for (let index = 0; index < count; index += 1) {
    const type = u32(record, cursor);
    const length = u32(record, cursor + 4);
    if (type === null || length === null) break;
    if (length < EXTH_RECORD_HEADER_BYTES) break;
    if (cursor + length > end) break;

    // **Unreachable, and kept because it is what makes the bounding local.**
    // The two checks above already give `cursor + length <= end` and
    // `length >= 8`, and `end` is at most the record's length, so `slice`
    // cannot refuse here. Driven over a corpus of 224,769 malformed and fuzzed
    // inputs, `slice` returned null 1,605 times and every one of them came from
    // `readTitle`; this call took none. Over well formed files it never refuses
    // at all, from either site. So it is not a guard, and no test can cover it.
    // What it buys is that this line reads correctly on its own, without the
    // reader having to carry two earlier checks in their head to see that the
    // bytes exist.
    const value = slice(
      record,
      cursor + EXTH_RECORD_HEADER_BYTES,
      length - EXTH_RECORD_HEADER_BYTES,
    );
    if (value === null) break;
    const values = found.get(type) ?? [];
    values.push(value);
    found.set(type, values);
    cursor += length;
  }
  return found;
}

/** One EXTH value as text, or `null` when it says nothing. */
function text(
  exth: ExthRecords,
  type: number,
  decode: TextDecoder,
): string | null {
  const [first] = exth.get(type) ?? [];
  return first === undefined ? null : clean(decode.decode(first));
}

/**
 * A decoded value with its padding taken off, or `null` when nothing is left.
 *
 * **Every NUL is removed, wherever it is, rather than trimmed off the ends.**
 * An EXTH value is length prefixed rather than NUL terminated, so a NUL in the
 * middle of one is padding a producer left behind rather than a mark where the
 * text stopped, and cutting there would throw away the rest of the value. The
 * test that pins this apart from an ends only strip passes `A\0B` and expects
 * `AB`; the padded cases every real file has cannot tell the two apart.
 *
 * **An empty record answers `null` and never `""`.** `FileMetadata` says every
 * field is absent rather than empty, and a caller reading `record.title` to
 * decide whether the file named one would take `""` for a title. The reader
 * that produced it is what has to hold that up.
 */
function clean(value: string): string | null {
  const trimmed = value.replaceAll("\0", "").trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * The authors, separately and in the order the file gave them.
 *
 * One record is one author. **Nothing here splits a record**, and that is the
 * measurement rather than a preference: the file carrying two authors carries
 * two records, so a splitter would only ever be guessing at a name that
 * contains its own separator. Joining them onto the one line the API takes is
 * `ScanPage/types.ts`, which is where the destination is known.
 *
 * **A `Set` beside the array, and it is the only place in this module where how
 * a thing is written is load bearing.** `Array.includes` inside the loop is a
 * linear scan, and how many author records there are is the file's choice: a
 * 1 MiB record 0, which is what `MAX_RECORD_ZERO_BYTES` allows, holds 95,301
 * of them. That is quadratic work on a member supplied number, on the thread
 * the page runs on and with the files read one after another, so a picked
 * folder is a frozen tab rather than a slow one.
 * `mobi.test.ts` bounds it in wall clock rather than describing it.
 */
function readAuthors(exth: ExthRecords, decode: TextDecoder): string[] {
  const authors: string[] = [];
  const seen = new Set<string>();
  for (const value of exth.get(AUTHOR) ?? []) {
    const name = clean(decode.decode(value));
    if (name === null || seen.has(name)) continue;
    seen.add(name);
    authors.push(name);
  }
  return authors;
}

/**
 * The title.
 *
 * Two places carry it and **the typed record is preferred**, which is the
 * ticket's own rule: EXTH 503 is a record read by its type, and the header's
 * full name is an offset and a length that a malformed file can walk off the
 * end of. Both are bounded here, so the preference costs nothing either way.
 *
 * Measured: 61 of 69 files carry 503, and where both are present they are the
 * same string in 61 of 61. So the order is a choice about which read is safer
 * and not a claim that one is more accurate.
 *
 * **The Palm Database's own name at the front of the file is not a candidate.**
 * It is 31 bytes with the spaces replaced, so it truncates every long title and
 * mangles every short one.
 */
function readTitle(
  record: DataView,
  exth: ExthRecords,
  decode: TextDecoder,
): string | null {
  const updated = text(exth, UPDATED_TITLE, decode);
  if (updated !== null) return updated;

  const at = u32(record, FULL_NAME_OFFSET_AT);
  const length = u32(record, FULL_NAME_LENGTH_AT);
  if (at === null || length === null) return null;
  const value = slice(record, at, length);
  return value === null ? null : clean(decode.decode(value));
}

/**
 * The year, when the declared date carries a plausible one.
 *
 * The value is an ISO date in most files and a bare `YYYY-MM-DD` in some, so
 * the leading four digits are read and the rest ignored. **Plausible rather
 * than storable**: `bookBounds.plausibleYear` holds the window, and the value
 * out of these 69 files that made one necessary.
 */
function readYear(exth: ExthRecords, decode: TextDecoder): number | null {
  const raw = text(exth, PUBLISHED, decode);
  const match = raw === null ? null : /^(\d{4})/.exec(raw);
  return match === null ? null : plausibleYear(Number(match[1]));
}

/**
 * The ISBN, from the record whose type says it is one.
 *
 * **No fallback onto another record's text**, which is where this differs from
 * `opf.ts` and it differs because the measurement differs. An EPUB's ISBN
 * arrives undeclared, so that reader has to try every identifier; here it
 * arrives typed, and across the 69 files no record outside 104 holds a value
 * `parseIsbn` would accept. One does strip to thirteen digits: a Kindle
 * resolution string, `2400x3840:0-119|`, which fails its check digit. A
 * fallback would add no ISBN and one way to invent one.
 */
function readIsbn(exth: ExthRecords, decode: TextDecoder): string | null {
  return parseIsbn(text(exth, ISBN, decode));
}

function readIdentifiers(
  exth: ExthRecords,
  decode: TextDecoder,
): FileIdentifier[] {
  const isbn = text(exth, ISBN, decode);
  return isbn === null ? [] : [{ scheme: "ISBN", value: isbn }];
}

/**
 * Where record 0 sits, or a failure.
 *
 * **Two entries of the offset table are read and never the whole of it.** The
 * table is eight bytes per record and a Palm Database may declare 65,535 of
 * them, so walking it to find record 0 would read half a megabyte to learn two
 * numbers. Record 0 starts at the first entry and ends where the second begins,
 * and a file with one record ends where the file does.
 *
 * The bounds, each of which a real file satisfies and a crafted one need not:
 * the first record starts after the table that describes it, both offsets are
 * inside the file, and the second is after the first. Measured over 69 files,
 * record 0 begins exactly two bytes after the table ends in every one, so the
 * "after the table" bound has never been near a real file.
 */
function recordZeroExtent(
  head: DataView,
  size: number,
): { from: number; to: number } | MobiFailure {
  if (ascii(head, PDB_TYPE_AT, 8) !== PDB_TYPE_AND_CREATOR) return "not-a-mobi";

  const records = u16(head, RECORD_COUNT_AT);
  if (records === null || records < 1) return "not-a-mobi";

  const from = u32(head, PDB_HEADER_BYTES);
  if (from === null) return "damaged";
  if (from < PDB_HEADER_BYTES + records * PDB_ENTRY_BYTES) return "damaged";
  if (from >= size) return "damaged";

  if (records === 1) return { from, to: size };

  const to = u32(head, PDB_HEADER_BYTES + PDB_ENTRY_BYTES);
  if (to === null || to <= from || to > size) return "damaged";
  return { from, to };
}

/**
 * Read one Kindle or Mobipocket file's metadata.
 *
 * Never throws for anything the file did, which is the contract
 * `fileReaders.FileReader` states for every reader, along with the reason it is
 * worth stating. Nothing in this function catches: every read is bounded
 * instead, so there is no arm here to turn a bug into a bad file.
 */
export async function readMobi(file: Blob): Promise<MobiReading> {
  const head = new DataView(
    await file.slice(0, PDB_HEADER_BYTES + 2 * PDB_ENTRY_BYTES).arrayBuffer(),
  );

  const extent = recordZeroExtent(head, file.size);
  if (typeof extent === "string") return { ok: false, failure: extent };

  const length = extent.to - extent.from;
  if (length > MAX_RECORD_ZERO_BYTES) return { ok: false, failure: "damaged" };

  const record = new DataView(
    await file.slice(extent.from, extent.to).arrayBuffer(),
  );
  // **Asserted on what arrived, not on what was asked for.** A `Blob` whose
  // backing file shrank under it yields a shorter slice rather than an error,
  // and a record 0 too short to hold a header is a MOBI that is broken rather
  // than a file of some other kind: the container already said which it was.
  // Everything past here reads inside this buffer.
  if (record.byteLength < MIN_RECORD_ZERO_BYTES) {
    return { ok: false, failure: "damaged" };
  }

  // **Before the magic**, so that a DRM bound file is told apart from a file of
  // some other kind. Both are refusals; only one of them is worth a member
  // going to look for a different copy.
  const encryption = u16(record, ENCRYPTION_AT);
  if (encryption === null) return { ok: false, failure: "damaged" };
  if (encryption !== 0) return { ok: false, failure: "protected" };

  if (ascii(record, MOBI_MAGIC_AT, 4) !== MOBI_MAGIC) {
    return { ok: false, failure: "not-a-mobi" };
  }

  const headerLength = u32(record, HEADER_LENGTH_AT);
  if (headerLength === null) return { ok: false, failure: "damaged" };

  const decode = decoderFor(u32(record, CODEPAGE_AT));
  const exth = readExth(record, MOBI_MAGIC_AT + headerLength);

  return {
    ok: true,
    metadata: {
      title: readTitle(record, exth, decode),
      subtitle: null,
      authors: readAuthors(exth, decode),
      identifiers: readIdentifiers(exth, decode),
      isbn: readIsbn(exth, decode),
      publisher: text(exth, PUBLISHER, decode),
      year: readYear(exth, decode),
      language: text(exth, LANGUAGE, decode),
      // **Passed through as the file wrote it, tags and all.** 1 of the 7 files
      // carrying a description carries HTML in it. `opf.ts` does the same with
      // `dc:description`, which reaches the same column and is HTML as often;
      // a stripper here would make the two readers disagree about one field,
      // and the member reviews the draft before it is committed.
      description: text(exth, DESCRIPTION, decode),
      seriesName: null,
      seriesIndex: null,
    },
  };
}
