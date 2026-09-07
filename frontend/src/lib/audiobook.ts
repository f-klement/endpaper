/**
 * What one audio file's own tags say, read in the member's own browser.
 *
 * Same custody rule as `lib/epub.ts`, which states it in full: the bytes are
 * read here and only what the file said is ever sent. An audiobook makes that
 * rule matter more rather than less, because the file is the largest thing a
 * member owns and there is no version of this feature where it travels.
 *
 * **This module answers what a file says, never which book it is part of.**
 * That second question is `lib/audiobookGroups.ts`, and it is the harder one:
 * for every other format one file is one book, and for an audiobook a book is
 * usually a folder of chapter files.
 *
 * **A seek walk, not a prefix read, and it was measured rather than assumed.**
 * Over the three LibriVox M4Bs of the corpus the `moov` atom is 3.7 MB to 5.0
 * MB and `udta` sits at its end, past the sample tables: the tags of a 193 MB
 * Robinson Crusoe begin at byte 4,248,408. Any fixed prefix small enough to read
 * per file across a folder is far too small to reach them, so each level is
 * walked by reading box headers and skipping the bodies. `covr` is 141,427
 * bytes in one of the same files and is never read at all.
 *
 * **A member's own browser is not a trusted producer**, so every read is
 * bounded against the blob's length, the walk has no recursion in it, and the
 * budget below bounds a file that is hostile rather than merely odd.
 *
 * ## What is read, and the exclusions are the point
 *
 * Album, artist and this file's own title. Nothing else, and three omissions
 * are deliberate:
 *
 * **The album artist is not a second author.** Measured: LibriVox writes the
 * narrator there. `shortstory029_diarymadman_add.mp3` carries
 * `TPE1='Guy de Maupassant'` beside `TPE2='Alan Davis Drake  '`, who is the
 * reader. Taking `TPE2`, or `aART`, would file a narrator as an author on every
 * such file.
 *
 * **The narrator is not read at all**, because there is no column for one:
 * `BookCreate` has no such field, so the choice is between dropping it and
 * putting a reader's name in the author line.
 *
 * **The year is not read.** It is the year of the recording, not of the book.
 * Measured: Defoe's Robinson Crusoe carries `TYER 2006` and Mommsen's Römische
 * Geschichte carries `©day 2008`, wrong by 287 and by 152 years. A year in the
 * file **name** is still believed, by `lib/fileName.ts`, which is looking at
 * something a person wrote about the book.
 */

/** What one audio file said about itself. */
export interface AudioTags {
  /** The book, usually. `TALB` or `©alb`. */
  album: string | null;
  /** The author, usually. `TPE1` or `©ART`. Never the album artist. */
  artists: string[];
  /** This file's own title, which for a chapter file is the chapter. */
  title: string | null;
}

/**
 * Why a file said nothing, in the two sentences a member can act on.
 *
 * Closed, so a reason added here without a message beside it is a compile
 * error in `ScanPage/hooks.ts` rather than a file reported with the last arm's.
 */
export type AudioFailure =
  /** A file with no tag block in it. Ordinary: plenty of MP3s carry none. */
  | "no-tags"
  /** A tag block that contradicts itself, or one too tangled to walk. */
  | "unreadable";

export type AudioReading =
  | { readonly ok: true; readonly tags: AudioTags }
  | { readonly ok: false; readonly failure: AudioFailure };

/**
 * The two extensions this reads, and what one file of each is.
 *
 * **The second list, and it is asserted equal to the first rather than said to
 * agree with it.** `fileName.FORMAT_FOR_EXTENSION` decides which extensions the
 * grouping rule owns; this one answers what a container is, which that map has
 * no way to say. `tests/lib/fileName.test.ts` compares the two sets in both
 * directions, because an extension in that map and not in this one would be
 * routed to a reader with no arm for it.
 */
export const AUDIO_EXTENSIONS = {
  /** One file is one book. */
  ".m4b": "book",
  /** One file is one track, which is why the grouping rule exists. */
  ".mp3": "track",
} as const;

export type AudioExtension = keyof typeof AUDIO_EXTENSIONS;

export function isAudioExtension(
  extension: string | null,
): extension is AudioExtension {
  return extension !== null && extension in AUDIO_EXTENSIONS;
}

/**
 * How many slices one file may cost, whatever it claims about itself.
 *
 * **One bound, and the two that stood beside it were deleted because neither
 * could fire.** `MAX_SLICE_BYTES` refused a slice over a mebibyte and no call
 * site can ask for one: the four are 16 bytes, 10 bytes, 128 bytes and the two
 * ceilings below. `MAX_TOTAL_BYTES` was two mebibytes against a reachable
 * ceiling of 1,049,600. A bound that cannot fire is not a bound, and leaving
 * two of them here would have read as three defences where there is one.
 *
 * **What is left is bounded at the call sites and asserted rather than
 * restated.** This one refuses a tree of ten thousand empty boxes, which is
 * small on disk and unbounded to walk; `MAX_ENTRY_BYTES` and `MAX_ID3_BYTES`
 * bound the only two reads that are not a fixed header. The total those three
 * make reachable is measured by `tests/lib/audiobook.test.ts`, which builds the
 * file that costs the most and reads the figure off it.
 *
 * **Measured by running this module over the real files**, counting slices,
 * rather than by reading the walk: four of the six M4Bs, 1.5 MB to 232 MB, took
 * **20 to 21 reads and 369 to 406 bytes**, and three of the nine MP3s took **2
 * reads** and 138 to 4,096 bytes, the last being a 10 byte header plus the
 * largest tag in the corpus.
 *
 * So `MAX_READS` is six times the widest real walk. **What makes six safe is
 * the consequence rather than the multiple**: a file past the budget is
 * reported as unreadable and still becomes a candidate under its own name, so a
 * bound set too low costs a name instead of a tag, never the file.
 */
const MAX_READS = 128;

/** A budget exhausted, or a structure that contradicts itself. */
class AudioError extends Error {
  constructor(readonly failure: AudioFailure) {
    super(failure);
    this.name = "AudioError";
  }
}

/**
 * Reading slices of one file, under a budget.
 *
 * **Every read is bounded against the blob's own length before it is made**, so
 * an offset a file computed for itself can never reach past its end. A read
 * that would is `null` rather than a throw: walking off the end is what a
 * malformed box does, and the walk above treats it as the level ending.
 */
function reader(file: Blob) {
  let reads = 0;

  return async function read(
    offset: number,
    length: number,
  ): Promise<DataView | null> {
    if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(length)) {
      return null;
    }
    if (offset < 0 || length <= 0 || offset + length > file.size) return null;
    reads += 1;
    if (reads > MAX_READS) throw new AudioError("unreadable");
    const buffer = await file.slice(offset, offset + length).arrayBuffer();
    // A slice may come back short of what was asked for if the blob was backed
    // by a file that changed under it, which is a thing a member can do.
    return buffer.byteLength === length ? new DataView(buffer) : null;
  };
}

type Read = ReturnType<typeof reader>;

/** Read one file's tags, dispatched on the extension the walk already knows. */
export async function readAudioTags(
  file: Blob,
  extension: AudioExtension,
): Promise<AudioReading> {
  try {
    const read = reader(file);
    const tags =
      extension === ".m4b"
        ? await readMp4(read, file.size)
        : await readMp3(read, file);
    if (tags === null) return { ok: false, failure: "no-tags" };
    return { ok: true, tags };
  } catch (error) {
    if (error instanceof AudioError) {
      return { ok: false, failure: error.failure };
    }
    // A bug in this module rather than anything the file did, and turning one
    // into "no tags" would hide it behind a folder of files that read fine.
    throw error;
  }
}

// ── MPEG-4, which is M4B ──────────────────────────────────────────────────

/**
 * The path the tags sit on, and it is the whole of the recursion.
 *
 * **Written as a path rather than as a tree walk**, which is what makes a depth
 * bound unnecessary rather than merely satisfied: there are four levels here
 * because there are four names here, and a file cannot add a fifth by nesting
 * one atom inside another.
 */
const ILST_PATH = ["moov", "udta", "meta", "ilst"] as const;

/**
 * How long a tag value may be, and how many values one frame may carry.
 *
 * **Bounds on what is kept, not on what a request takes.** `bookBounds` cuts
 * again on the way to the API; these stop a file from putting a megabyte of one
 * string, or half a million artists out of one NUL separated frame, into the
 * queue's state for the rest of the session, once per file in a folder pick.
 * Measured before they existed: one 977 KB MP3 whose `TPE1` held 500,000 values
 * retained 5.07 MB, and twenty of it retained 101.4 MB. After them the same
 * twenty retain 0.6 MB.
 *
 * **Both sit above the bound that decides the value**, so neither changes what
 * a member sees: `TEXT_CEILINGS.author` and `.title` are 500 code points, and
 * `audiobookGroups.MAX_AUTHORS` keeps 20 artists per group.
 */
const MAX_VALUE_POINTS = 1000;
const MAX_VALUES = 32;

/** How much of one `ilst` entry is read, once its key is one that is wanted. */
const MAX_ENTRY_BYTES = 16 * 1024;

/**
 * The iTunes keys read, and their four character names begin with U+00A9.
 *
 * `aART` is absent for the reason the module docstring gives: it holds the
 * narrator in every file measured that has one.
 */
const MP4_ALBUM = "©alb";
const MP4_ARTIST = "©ART";
const MP4_TITLE = "©nam";
const MP4_KEYS = [MP4_ALBUM, MP4_ARTIST, MP4_TITLE];

interface Box {
  readonly type: string;
  /** Where this box's children or payload begin. */
  readonly body: number;
  /** One past this box's last byte. */
  readonly end: number;
}

/**
 * The box at `at`, or `null` when there is not a well formed one there.
 *
 * **A box that claims more than its parent holds is `null`**, which is the one
 * bound doing the work: it makes every child strictly inside its parent, so a
 * walk cannot leave the region it was given however the sizes are written.
 *
 * `size` 1 means the real size follows as 64 bits, and `size` 0 means the box
 * runs to the end of its parent, which is legal only for the last one and is
 * treated as exactly that.
 */
async function boxAt(read: Read, at: number, to: number): Promise<Box | null> {
  if (at + 8 > to) return null;
  const header = await read(at, Math.min(16, to - at));
  if (header === null) return null;

  let size = header.getUint32(0);
  const type = fourCharacters(header, 4);
  let head = 8;
  if (size === 1) {
    if (header.byteLength < 16) return null;
    const high = header.getUint32(8);
    const low = header.getUint32(12);
    // Above this the size is past what a double counts exactly, and a blob
    // that large does not exist: either way the arithmetic below would lie.
    if (high > 0x001fffff) return null;
    size = high * 2 ** 32 + low;
    head = 16;
  } else if (size === 0) {
    size = to - at;
  }
  if (size < head || at + size > to) return null;
  return { type, body: at + head, end: at + size };
}

/** The first child of this region with the given type, or `null`. */
async function childNamed(
  read: Read,
  from: number,
  to: number,
  type: string,
): Promise<Box | null> {
  let at = from;
  while (at < to) {
    const box = await boxAt(read, at, to);
    if (box === null) return null;
    if (box.type === type) return box;
    // `boxAt` refuses a size below the header, so this always advances and the
    // loop cannot be made to stand still by a box that says it is empty.
    at = box.end;
  }
  return null;
}

async function readMp4(read: Read, size: number): Promise<AudioTags | null> {
  let from = 0;
  let to = size;
  for (const name of ILST_PATH) {
    const box: Box | null =
      name === "meta"
        ? await metaChildren(read, from, to)
        : await childNamed(read, from, to, name);
    if (box === null) return null;
    from = box.body;
    to = box.end;
  }
  return await readIlst(read, from, to);
}

/**
 * `meta`'s children, whether or not it declares a version and flags.
 *
 * **Two attempts, and the second is defensive rather than measured**: every
 * file in the corpus writes `meta` as a full box, with four bytes of version
 * and flags before its children, which is what iTunes and every tagger derived
 * from it do. QuickTime's own `meta` has no such prefix, and a reader that
 * assumes one finds nothing in it and says the file carries no tags.
 */
async function metaChildren(
  read: Read,
  from: number,
  to: number,
): Promise<Box | null> {
  const meta = await childNamed(read, from, to, "meta");
  if (meta === null) return null;
  const asFullBox = { ...meta, body: meta.body + 4 };
  if (asFullBox.body > meta.end) return meta;
  const ilst = await childNamed(read, asFullBox.body, meta.end, "ilst");
  return ilst === null ? meta : asFullBox;
}

/**
 * The three wanted values out of an `ilst`, reading only the entries that carry
 * them.
 *
 * A cover is an entry here like any other and is up to 141 KB in this corpus,
 * so an entry whose key is not wanted has its header read and its body skipped.
 */
async function readIlst(
  read: Read,
  from: number,
  to: number,
): Promise<AudioTags | null> {
  const found = new Map<string, string>();
  let at = from;
  while (at < to && found.size < MP4_KEYS.length) {
    const entry = await boxAt(read, at, to);
    if (entry === null) break;
    if (MP4_KEYS.includes(entry.type) && !found.has(entry.type)) {
      const value = await readEntryValue(read, entry);
      if (value !== null) found.set(entry.type, value);
    }
    at = entry.end;
  }

  const album = found.get(MP4_ALBUM) ?? null;
  const artist = found.get(MP4_ARTIST) ?? null;
  const title = found.get(MP4_TITLE) ?? null;
  if (album === null && artist === null && title === null) return null;
  return { album, artists: artist === null ? [] : [artist], title };
}

/** The text of the first readable `data` box inside one `ilst` entry. */
async function readEntryValue(read: Read, entry: Box): Promise<string | null> {
  const length = Math.min(entry.end - entry.body, MAX_ENTRY_BYTES);
  if (length <= 0) return null;
  const view = await read(entry.body, length);
  if (view === null) return null;

  let at = 0;
  while (at + 16 <= view.byteLength) {
    const size = view.getUint32(at);
    const type = fourCharacters(view, at + 4);
    if (size < 16 || at + size > view.byteLength) break;
    if (type === "data") {
      // The low 24 bits of the type field say what the payload is. 1 is UTF-8
      // and 2 is UTF-16BE; 0 means the key decides, and for a text key it is
      // UTF-8. Everything else is a picture, a number or a private blob.
      const kind = view.getUint32(at + 8) & 0xffffff;
      const payload = new Uint8Array(
        view.buffer,
        view.byteOffset + at + 16,
        size - 16,
      );
      if (kind === 0 || kind === 1) return clean(utf8.decode(payload));
      if (kind === 2) return clean(decodeUtf16(payload, true));
      return null;
    }
    at += size;
  }
  return null;
}

// ── ID3, which is MP3 ─────────────────────────────────────────────────────

/**
 * How much of a declared ID3v2 tag is read.
 *
 * The whole tag in one slice, because its frames are not in a defined order and
 * a cover picture is a frame like any other: the title may sit after a megabyte
 * of JPEG. Measured over the corpus the largest real tag is 4,086 bytes, so
 * this is 256 times it and is a bound on a stranger's file rather than on any
 * of these.
 */
const MAX_ID3_BYTES = 1024 * 1024;

/** The last 128 bytes, which is the whole of an ID3v1 tag. */
const ID3V1_BYTES = 128;

/**
 * The frames read, in the two spellings ID3 has for each.
 *
 * `TPE2` is absent, and `TCOM` with it: the first holds the narrator in this
 * corpus and the second holds one in commercial audiobooks. See the module
 * docstring.
 */
const ID3_ALBUM = ["TALB", "TAL"];
const ID3_ARTIST = ["TPE1", "TP1"];
const ID3_TITLE = ["TIT2", "TT2"];

async function readMp3(read: Read, file: Blob): Promise<AudioTags | null> {
  return (await readId3v2(read)) ?? (await readId3v1(read, file));
}

async function readId3v2(read: Read): Promise<AudioTags | null> {
  const header = await read(0, 10);
  if (header === null) return null;
  if (fourCharacters(header, 0).slice(0, 3) !== "ID3") return null;

  const major = header.getUint8(3);
  // 2, 3 and 4 are the versions that exist. A tag claiming a later one is not
  // one this can read, and guessing at its layout is how a walk goes off the
  // end of a frame. `null` rather than a failure, so the v1 tail is still tried.
  if (major < 2 || major > 4) return null;
  const flags = header.getUint8(5);
  const declared = synchsafe(header, 6);
  if (declared === null || declared === 0) return null;

  const view = await read(10, Math.min(declared, MAX_ID3_BYTES));
  if (view === null) return null;
  let body = new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
  // Unsynchronisation, which for 2.2 and 2.3 is applied to the whole tag: every
  // 0xFF is followed by an inserted 0x00 so that nothing inside the tag looks
  // like the start of an audio frame. Undone here, before any size is read,
  // because the sizes were written against the undone form.
  if (major < 4 && (flags & 0x80) !== 0) body = desynchronise(body);

  let at = 0;
  if ((flags & 0x40) !== 0) {
    const extended = extendedHeaderLength(body, major);
    if (extended === null) return null;
    at = extended;
  }

  const found = readFrames(body, at, major);
  const album = pick(found, ID3_ALBUM)[0] ?? null;
  const artists = pick(found, ID3_ARTIST);
  const title = pick(found, ID3_TITLE)[0] ?? null;
  if (album === null && artists.length === 0 && title === null) return null;
  return { album, artists, title };
}

function extendedHeaderLength(body: Uint8Array, major: number): number | null {
  if (body.length < 4) return null;
  const view = new DataView(body.buffer, body.byteOffset, body.byteLength);
  if (major === 4) {
    // 2.4 counts the four size bytes inside the size.
    const size = synchsafe(view, 0);
    return size === null || size > body.length ? null : size;
  }
  // In 2.2 that flag means the whole tag is compressed, by a scheme the
  // specification never defined. Nothing can read one, so nothing tries.
  if (major === 2) return null;
  // 2.3 counts everything after the four size bytes rather than including them.
  const size = view.getUint32(0);
  return size > body.length - 4 ? null : 4 + size;
}

/** Every text frame in the tag, by frame id, in the order they appear. */
function readFrames(
  body: Uint8Array,
  from: number,
  major: number,
): Map<string, string[]> {
  const found = new Map<string, string[]>();
  const view = new DataView(body.buffer, body.byteOffset, body.byteLength);
  const idLength = major === 2 ? 3 : 4;
  const headLength = major === 2 ? 6 : 10;

  let at = from;
  while (at + headLength <= body.length) {
    const id = fourCharacters(view, at).slice(0, idLength);
    // A run of zero bytes is the padding every writer leaves after the frames,
    // and any other unnameable id is a tag this has lost its place in.
    if (!/^[A-Z0-9]+$/.test(id)) break;

    let size: number | null;
    if (major === 2) {
      size = (body[at + 3]! << 16) | (body[at + 4]! << 8) | body[at + 5]!;
    } else if (major === 4) {
      size = synchsafe(view, at + 4);
    } else {
      size = view.getUint32(at + 4);
    }
    if (size === null || size < 0) break;
    let start = at + headLength;
    if (start + size > body.length) break;

    const frameFlags = major === 2 ? 0 : view.getUint16(at + 8);
    at = start + size;

    // Compressed and encrypted frames, in the two spellings the versions use.
    // Neither is implemented, so the frame is skipped rather than decoded as
    // though its bytes were text.
    const squashed = major === 4 ? 0x0008 : 0x0080;
    const locked = major === 4 ? 0x0004 : 0x0040;
    if ((frameFlags & (squashed | locked)) !== 0) continue;

    let length = size;
    // 2.4 puts a four byte length in front of the body of a frame that declares
    // one, and undoes unsynchronisation per frame rather than per tag.
    if (major === 4 && (frameFlags & 0x0001) !== 0) {
      if (length < 4) continue;
      start += 4;
      length -= 4;
    }
    let payload = body.subarray(start, start + length);
    if (major === 4 && (frameFlags & 0x0002) !== 0) {
      payload = desynchronise(payload);
    }

    if (id.startsWith("T") && !found.has(id)) {
      const values = decodeTextFrame(payload);
      if (values.length > 0) found.set(id, values);
    }
  }
  return found;
}

/**
 * ID3v1, which is the last 128 bytes and has no length fields in it at all.
 *
 * **Read when the head said nothing, because for some files it is all there
 * is.** Measured: 3 of 3 of the Internet Archive's own 64 kbps derivatives of
 * the LibriVox chapters carry no ID3v2 at all, and the one whose tail was
 * fetched carried a complete ID3v1.
 */
async function readId3v1(read: Read, file: Blob): Promise<AudioTags | null> {
  if (file.size < ID3V1_BYTES) return null;
  const view = await read(file.size - ID3V1_BYTES, ID3V1_BYTES);
  if (view === null) return null;
  if (fourCharacters(view, 0).slice(0, 3) !== "TAG") return null;

  const at = (offset: number) =>
    clean(latin1(new Uint8Array(view.buffer, view.byteOffset + offset, 30)));
  const title = at(3);
  const artist = at(33);
  const album = at(63);
  if (title === "" && artist === "" && album === "") return null;
  return {
    album: album || null,
    artists: artist ? [artist] : [],
    title: title || null,
  };
}

// ── Shared ────────────────────────────────────────────────────────────────

const utf8 = new TextDecoder("utf-8");

/** Four bytes as characters, which is how every box and frame names itself. */
function fourCharacters(view: DataView, at: number): string {
  let name = "";
  for (let index = 0; index < 4 && at + index < view.byteLength; index += 1) {
    name += String.fromCharCode(view.getUint8(at + index));
  }
  return name;
}

/**
 * A synchsafe integer, which is seven bits per byte, or `null` if it is not one.
 *
 * **The high bit being clear is checked rather than masked away.** A writer that
 * put a plain integer here means a tag whose real length is not the one this
 * would compute, and reading the difference as frames is how a walk ends up
 * inside audio data.
 */
function synchsafe(view: DataView, at: number): number | null {
  if (at + 4 > view.byteLength) return null;
  let value = 0;
  for (let index = 0; index < 4; index += 1) {
    const byte = view.getUint8(at + index);
    if ((byte & 0x80) !== 0) return null;
    value = (value << 7) | byte;
  }
  return value;
}

/** Every inserted 0x00 after an 0xFF taken back out. */
function desynchronise(body: Uint8Array): Uint8Array {
  const out = new Uint8Array(body.length);
  let length = 0;
  for (let index = 0; index < body.length; index += 1) {
    out[length] = body[index]!;
    length += 1;
    if (body[index] === 0xff && body[index + 1] === 0x00) index += 1;
  }
  return out.slice(0, length);
}

/**
 * One text frame's values.
 *
 * The first byte says the encoding. A NUL separates several values of one
 * frame in 2.4 and terminates the single value in 2.3, so splitting on it and
 * dropping the empties is right for both.
 */
function decodeTextFrame(payload: Uint8Array): string[] {
  if (payload.length < 1) return [];
  const encoding = payload[0]!;
  const raw = payload.subarray(1);
  let text: string;
  if (encoding === 0) text = latin1(raw);
  else if (encoding === 1) text = decodeUtf16(raw, false);
  else if (encoding === 2) text = decodeUtf16(raw, true);
  else if (encoding === 3) text = utf8.decode(raw);
  else return [];
  return splitValues(text);
}

/**
 * A frame's values, cut to `MAX_VALUES` without building the rest.
 *
 * **Not `split`, which builds every piece before anything can cut it.** A 2.4
 * frame separates its values with a NUL and a hostile one carries half a
 * million, and `text.split()` costs all of them whatever is done next.
 *
 * **`MAX_VALUES` bounds what is built, and `MAX_ID3_BYTES` bounds the scan.** A
 * frame of nothing but separators pushes no value, so the cap never stops it
 * and the length of the tag does: measured, a mebibyte of NUL runs 1,048,565
 * iterations. That is one pass over bytes already read and budgeted, and it
 * still costs under two thirds of what `split` cost for the same input.
 */
function splitValues(text: string): string[] {
  const values: string[] = [];
  let at = 0;
  while (at <= text.length && values.length < MAX_VALUES) {
    const next = text.indexOf("\u0000", at);
    const value = clean(next === -1 ? text.slice(at) : text.slice(at, next));
    if (value !== "") values.push(value);
    if (next === -1) break;
    at = next + 1;
  }
  return values;
}

/** ISO 8859-1, decoded here rather than by name: it is one byte per character. */
function latin1(raw: Uint8Array): string {
  let text = "";
  // In blocks, because spreading a megabyte of bytes into `fromCharCode` is an
  // argument list no engine promises to take.
  for (let at = 0; at < raw.length; at += 4096) {
    text += String.fromCharCode(...raw.subarray(at, at + 4096));
  }
  return text;
}

/**
 * UTF-16, byte swapped when it is big endian rather than decoded by name.
 *
 * `TextDecoder("utf-16be")` needs an ICU build that not every runtime this has
 * to work in ships, and a decoder that is missing throws at construction. The
 * little endian one is required of every runtime.
 */
function decodeUtf16(raw: Uint8Array, bigEndian: boolean): string {
  let bytes = raw;
  let swap = bigEndian;
  if (bytes.length >= 2) {
    if (bytes[0] === 0xff && bytes[1] === 0xfe) {
      swap = false;
      bytes = bytes.subarray(2);
    } else if (bytes[0] === 0xfe && bytes[1] === 0xff) {
      swap = true;
      bytes = bytes.subarray(2);
    }
  }
  if (swap) {
    const swapped = new Uint8Array(bytes.length);
    for (let at = 0; at + 1 < bytes.length; at += 2) {
      swapped[at] = bytes[at + 1]!;
      swapped[at + 1] = bytes[at]!;
    }
    bytes = swapped;
  }
  return new TextDecoder("utf-16le").decode(bytes);
}

/**
 * A tag value as it may be printed.
 *
 * NUL padding, control characters and the trailing spaces a real writer leaves
 * (`'Alan Davis Drake  '`) are not part of the value.
 */
function clean(value: string): string {
  const text = value
    .replace(/[\p{Cc}\p{Zl}\p{Zp}]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  const points = [...text];
  // In code points, never in UTF-16 units: a cut between the halves of a
  // surrogate pair produces a lone surrogate, which is the fault
  // `lib/bookBounds.ts` records costing a whole book to a 422.
  return points.length <= MAX_VALUE_POINTS
    ? text
    : points.slice(0, MAX_VALUE_POINTS).join("");
}

function pick(found: Map<string, string[]>, ids: string[]): string[] {
  for (const id of ids) {
    const values = found.get(id);
    if (values && values.length > 0) return values;
  }
  return [];
}
