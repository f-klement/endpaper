/**
 * Building tagged audio files byte by byte, for the tests that read them.
 *
 * Support code, so it mirrors nothing: the mirrored files are the `*.test.ts`
 * ones. The same choice `zipFixtures.ts` makes and for the same reason, and it
 * matters more here: an audiobook chapter is tens of megabytes, so a checked in
 * one would be larger than the whole repository, and half of what is worth
 * testing is a file that is malformed on purpose.
 *
 * **What these are checked against.** The shapes below were read off real
 * files, none of which is checked in here: **three LibriVox M4Bs and nine
 * LibriVox chapter MP3s**, which that collection publishes as public domain by
 * its own policy, and **three enhanced podcasts by other producers**, read for
 * the shape of the container and carrying no licence claim either way. Both
 * were fetched from the Internet Archive, which hosts them and grants nothing.
 *
 * **Every count below says which of those it is about.** What was measured is
 * written down where it decides a default:
 *
 * * all six M4Bs put `moov` second, after `ftyp` and before `mdat`
 * * in all three LibriVox M4Bs `udta` sat at the **end** of `moov`, past sample
 *   tables of several megabytes: the tags of a 193 MB file begin at byte
 *   4,248,408
 * * `covr` reached 141,427 bytes in one of those three
 * * six of the nine MP3s carried a head tag, all ID3v2.3.0 with text encoding
 *   0, between 199 and 4,086 bytes long; the other three carried none
 * * `©alb` and `TALB` named the book, `©ART` and `TPE1` the author, `©nam` and
 *   `TIT2` the part
 * * `TPE2` named the **narrator**, which is why nothing reads it
 */

const encoder = new TextEncoder();

function concat(parts: readonly Uint8Array[]): Uint8Array<ArrayBuffer> {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

function be32(value: number): Uint8Array {
  const out = new Uint8Array(4);
  new DataView(out.buffer).setUint32(0, value);
  return out;
}

/** Latin-1, which is one byte per character and is what ID3 writes by default. */
export function latin1(text: string): Uint8Array {
  const out = new Uint8Array(text.length);
  for (let at = 0; at < text.length; at += 1)
    out[at] = text.charCodeAt(at) & 0xff;
  return out;
}

export function utf16(
  text: string,
  bigEndian: boolean,
  bom = true,
): Uint8Array {
  const units = [...text].flatMap((character) => {
    const code = character.codePointAt(0)!;
    if (code <= 0xffff) return [code];
    const offset = code - 0x10000;
    return [0xd800 + (offset >> 10), 0xdc00 + (offset & 0x3ff)];
  });
  if (bom) units.unshift(0xfeff);
  const out = new Uint8Array(units.length * 2);
  const view = new DataView(out.buffer);
  units.forEach((unit, index) => view.setUint16(index * 2, unit, !bigEndian));
  return out;
}

// ── MPEG-4 ────────────────────────────────────────────────────────────────

/** One box: its length, its four character name, and its payload. */
export function box(
  type: string,
  ...payload: readonly Uint8Array[]
): Uint8Array {
  const body = concat(payload);
  return concat([be32(body.length + 8), latin1(type), body]);
}

/** A box carrying its length as 64 bits, which the `size === 1` form means. */
export function longBox(
  type: string,
  ...payload: readonly Uint8Array[]
): Uint8Array {
  const body = concat(payload);
  const size = new Uint8Array(8);
  new DataView(size.buffer).setBigUint64(0, BigInt(body.length + 16));
  return concat([be32(1), latin1(type), size, body]);
}

/** A box whose declared length is whatever the test wants it to be. */
export function brokenBox(
  type: string,
  declared: number,
  ...payload: readonly Uint8Array[]
): Uint8Array {
  return concat([be32(declared), latin1(type), concat(payload)]);
}

/** One `ilst` entry: an iTunes key and a typed value. */
export function ilstEntry(
  key: string,
  value: string | Uint8Array,
  kind = 1,
): Uint8Array {
  const payload = typeof value === "string" ? encoder.encode(value) : value;
  return box(key, box("data", be32(kind), be32(0), payload));
}

export interface Mp4Options {
  /** The `ilst` entries, in order. */
  entries?: readonly Uint8Array[];
  /** Extra children of `moov`, before `udta`, as a real file has. */
  moovChildren?: readonly Uint8Array[];
  /** Top level boxes before `moov`, which is where an `mdat` sits. */
  before?: readonly Uint8Array[];
  /** False writes `meta` without the version and flags QuickTime omits. */
  metaIsFullBox?: boolean;
  /** Leave out `udta` entirely. */
  withoutTags?: boolean;
}

/** One M4B, laid out the way the measured files are. */
export function m4b(options: Mp4Options = {}): Blob {
  const {
    entries = [ilstEntry("©alb", "Robinson Crusoe")],
    moovChildren = [],
    before = [],
    metaIsFullBox = true,
    withoutTags = false,
  } = options;

  const meta = box(
    "meta",
    ...(metaIsFullBox ? [new Uint8Array(4)] : []),
    box("hdlr", new Uint8Array(20)),
    box("ilst", ...entries),
  );
  const moov = box(
    "moov",
    box("mvhd", new Uint8Array(100)),
    ...moovChildren,
    ...(withoutTags ? [] : [box("udta", meta)]),
  );
  return new Blob([
    box("ftyp", latin1("M4A mp42")),
    ...before,
    moov,
  ] as BlobPart[]);
}

// ── ID3 ───────────────────────────────────────────────────────────────────

export interface Id3Frame {
  id: string;
  /** The payload after the frame header, encoding byte included. */
  body: Uint8Array;
  /** The two frame flag bytes, which exist from 2.3 onwards. */
  flags?: number;
}

/** A text frame: one encoding byte, then the text. */
export function textFrame(id: string, body: Uint8Array, flags = 0): Id3Frame {
  return { id, body, flags };
}

/** The ordinary case: latin-1 text, which is what every measured file writes. */
export function plainFrame(id: string, value: string, flags = 0): Id3Frame {
  return { id, body: concat([new Uint8Array([0]), latin1(value)]), flags };
}

function synchsafe(value: number): Uint8Array {
  return new Uint8Array([
    (value >> 21) & 0x7f,
    (value >> 14) & 0x7f,
    (value >> 7) & 0x7f,
    value & 0x7f,
  ]);
}

export interface Id3Options {
  major?: number;
  frames?: readonly Id3Frame[];
  /** Set the whole tag unsynchronisation flag and insert the padding bytes. */
  unsynchronised?: boolean;
  /** An extended header, which sets the flag that says there is one. */
  extendedHeader?: Uint8Array;
  /** Zero bytes after the frames, which every real writer leaves. */
  padding?: number;
  /** Write the tag length as a plain integer rather than a synchsafe one. */
  plainSize?: boolean;
}

/** One ID3v2 tag, header included. */
export function id3v2(options: Id3Options = {}): Uint8Array<ArrayBuffer> {
  const {
    major = 3,
    frames = [],
    unsynchronised = false,
    extendedHeader,
    padding = 0,
    plainSize = false,
  } = options;

  const written = frames.map((frame) => {
    if (major === 2) {
      const size = frame.body.length;
      return concat([
        latin1(frame.id.padEnd(3, " ").slice(0, 3)),
        new Uint8Array([(size >> 16) & 0xff, (size >> 8) & 0xff, size & 0xff]),
        frame.body,
      ]);
    }
    const size =
      major === 4 ? synchsafe(frame.body.length) : be32(frame.body.length);
    const flags = new Uint8Array(2);
    new DataView(flags.buffer).setUint16(0, frame.flags ?? 0);
    return concat([
      latin1(frame.id.padEnd(4, " ").slice(0, 4)),
      size,
      flags,
      frame.body,
    ]);
  });

  let body = concat([
    ...(extendedHeader ? [extendedHeader] : []),
    ...written,
    new Uint8Array(padding),
  ]);
  if (unsynchronised) body = synchronise(body);

  let flags = 0;
  if (unsynchronised) flags |= 0x80;
  if (extendedHeader) flags |= 0x40;

  return concat([
    latin1("ID3"),
    new Uint8Array([major, 0, flags]),
    plainSize ? be32(body.length) : synchsafe(body.length),
    body,
  ]);
}

/** A zero inserted after every 0xFF, which is what unsynchronisation is. */
export function synchronise(body: Uint8Array): Uint8Array<ArrayBuffer> {
  const out: number[] = [];
  for (const byte of body) {
    out.push(byte);
    if (byte === 0xff) out.push(0x00);
  }
  return new Uint8Array(out);
}

export interface Id3v1Fields {
  title?: string;
  artist?: string;
  album?: string;
  year?: string;
}

/** The 128 byte tail tag, which has no length fields in it at all. */
export function id3v1(fields: Id3v1Fields = {}): Uint8Array<ArrayBuffer> {
  const field = (value: string, width: number) => {
    const out = new Uint8Array(width);
    out.set(latin1(value).subarray(0, width));
    return out;
  };
  return concat([
    latin1("TAG"),
    field(fields.title ?? "", 30),
    field(fields.artist ?? "", 30),
    field(fields.album ?? "", 30),
    field(fields.year ?? "", 4),
    field("", 30),
    new Uint8Array([255]),
  ]);
}

/** One MP3: a head tag, some bytes standing in for audio, and a tail tag. */
export function mp3(
  parts: {
    head?: Uint8Array;
    audio?: Uint8Array;
    tail?: Uint8Array;
  } = {},
): Blob {
  const {
    head = new Uint8Array(0),
    // Two frame syncs, which is what the front of an untagged MP3 looks like.
    audio = new Uint8Array([0xff, 0xfb, 0x90, 0x00, 0xff, 0xfb, 0x90, 0x00]),
    tail = new Uint8Array(0),
  } = parts;
  return new Blob([head, audio, tail] as BlobPart[]);
}
