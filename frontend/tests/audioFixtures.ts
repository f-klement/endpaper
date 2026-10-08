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

import fc from "fast-check";

import {
  MAX_ENTRY_BYTES,
  MAX_ID3_BYTES,
  MAX_READS,
} from "../src/lib/audiobook";
import { edges, sometimes, type Total } from "./property";
import { around, type Zeroes } from "./zipFixtures";

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

// --- specs and arbitraries over the builders above ---------------------------
//
// The builders take bytes, so a property drawing bytes would print bytes. These
// specs describe the same files as data, render through the builders above, and
// print as literals a named case can be written in.

/** One box as data: a name, what it claims, and zero bytes inside. */
export interface BoxSpec {
  readonly type: string;
  /** A length to declare instead of the true one. */
  readonly declared: number | undefined;
  /** Carry the length as 64 bits, which a size of 1 means. */
  readonly long: boolean | undefined;
  /** How many zero bytes it holds. */
  readonly payload: number | undefined;
}

function renderBox(spec: BoxSpec): Uint8Array {
  const payload = new Uint8Array(spec.payload ?? 0);
  if (spec.declared !== undefined) {
    return brokenBox(spec.type, spec.declared, payload);
  }
  return spec.long === true
    ? longBox(spec.type, payload)
    : box(spec.type, payload);
}

/** One `ilst` entry as data. A run of zeroes is the value too large to read. */
export interface IlstEntrySpec {
  readonly key: string;
  readonly value: string | Zeroes;
  readonly kind: number | undefined;
}

/** An M4B as data, laid out by `m4b`. */
export interface Mp4Spec {
  readonly entries: readonly IlstEntrySpec[];
  readonly moovChildren: readonly BoxSpec[];
  readonly before: readonly BoxSpec[];
  /**
   * How many empty boxes sit before `moov`, all alike. **A crowd is what a
   * slice budget is for**: small on disk and one read each to walk.
   */
  readonly crowd: number;
  readonly metaIsFullBox: boolean | undefined;
  readonly withoutTags: boolean | undefined;
}

export async function buildM4b(
  spec: Mp4Spec,
): Promise<Uint8Array<ArrayBuffer>> {
  const free = box("free");
  const blob = m4b({
    entries: spec.entries.map((entry) =>
      ilstEntry(
        entry.key,
        typeof entry.value === "string"
          ? entry.value
          : new Uint8Array(entry.value.zeroes),
        entry.kind,
      ),
    ),
    moovChildren: spec.moovChildren.map(renderBox),
    before: [
      ...Array.from({ length: spec.crowd }, () => free),
      ...spec.before.map(renderBox),
    ],
    metaIsFullBox: spec.metaIsFullBox,
    withoutTags: spec.withoutTags,
  });
  return new Uint8Array(await blob.arrayBuffer());
}

/** One ID3 frame as data: its id, its encoding byte and latin-1 text. */
export interface Id3FrameSpec {
  readonly id: string;
  readonly encoding: number;
  readonly text: string;
  readonly flags: number | undefined;
}

/** An MP3 as data: a head tag, a tail tag, either absent. */
export interface Mp3Spec {
  readonly head:
    | {
        readonly major: number | undefined;
        readonly frames: readonly Id3FrameSpec[];
        readonly unsynchronised: boolean | undefined;
        /** Zero bytes of extended header, which sets the flag. */
        readonly extendedHeader: number | undefined;
        readonly padding: number | undefined;
        readonly plainSize: boolean | undefined;
      }
    | undefined;
  readonly tail: Id3v1Fields | undefined;
}

export async function buildMp3(
  spec: Mp3Spec,
): Promise<Uint8Array<ArrayBuffer>> {
  const head =
    spec.head === undefined
      ? undefined
      : id3v2({
          major: spec.head.major,
          frames: spec.head.frames.map((frame) =>
            textFrame(
              frame.id,
              concat([new Uint8Array([frame.encoding]), latin1(frame.text)]),
              frame.flags,
            ),
          ),
          unsynchronised: spec.head.unsynchronised,
          extendedHeader:
            spec.head.extendedHeader === undefined
              ? undefined
              : new Uint8Array(spec.head.extendedHeader),
          padding: spec.head.padding,
          plainSize: spec.head.plainSize,
        });
  const blob = mp3({
    head,
    tail: spec.tail === undefined ? undefined : id3v1(spec.tail),
  });
  return new Uint8Array(await blob.arrayBuffer());
}

const boxSpec = fc.record({
  type: fc.constantFrom(
    "free",
    "moov",
    "udta",
    "meta",
    "ilst",
    "mdat",
    "\u0000\u0000\u0000\u0000",
  ),
  declared: sometimes(fc.constantFrom(0, 1, 7, 8, 0xffffffff)),
  long: sometimes(fc.boolean()),
  payload: sometimes(fc.constantFrom(0, 8, 64)),
} satisfies Total<BoxSpec>);

const ilstEntrySpec = fc.record({
  key: fc.constantFrom("\u00a9alb", "\u00a9ART", "\u00a9nam", "covr", "aART"),
  value: fc.oneof(
    { arbitrary: fc.string({ maxLength: 24 }), weight: 3 },
    {
      arbitrary: fc
        .constantFrom(...around(MAX_ENTRY_BYTES))
        .map((zeroes): Zeroes => ({ zeroes })),
      weight: 1,
    },
  ),
  kind: sometimes(fc.constantFrom(0, 1, 2, 13, 21)),
} satisfies Total<IlstEntrySpec>);

/**
 * The file that costs the reader most, as `audiobook.test.ts` builds it by
 * hand: entries carrying a wanted key and a value it will not decode, so the
 * walk never finds its three and never stops early.
 */
const costliest = fc.record({
  entries: fc.constant(
    Array.from({ length: 200 }, () => ({
      key: "\u00a9alb",
      value: { zeroes: 20_000 },
      kind: 13,
    })),
  ),
  moovChildren: fc.constant([]),
  before: fc.constant([]),
  crowd: fc.constant(0),
  metaIsFullBox: fc.constant(undefined),
  withoutTags: fc.constant(undefined),
} satisfies Total<Mp4Spec>);

/** An M4B: any structure drawn, or the costliest walk there is. */
export function m4bSpec(): fc.Arbitrary<Mp4Spec> {
  const any = fc.record({
    entries: fc.array(ilstEntrySpec, { maxLength: 4 }),
    moovChildren: fc.array(boxSpec, { maxLength: 3 }),
    before: fc.array(boxSpec, { maxLength: 3 }),
    crowd: fc.oneof(
      { arbitrary: fc.constant(0), weight: 3 },
      { arbitrary: fc.constantFrom(...edges(MAX_READS), 10_000), weight: 1 },
    ),
    metaIsFullBox: sometimes(fc.boolean()),
    withoutTags: sometimes(fc.boolean()),
  } satisfies Total<Mp4Spec>);
  return fc.oneof(
    { arbitrary: any, weight: 5 },
    { arbitrary: costliest, weight: 1 },
  );
}

const frameSpec = fc.record({
  id: fc.constantFrom(
    "TALB",
    "TPE1",
    "TIT2",
    "TAL",
    "TP1",
    "TT2",
    "APIC",
    "\u0000\u0000\u0000\u0000",
  ),
  encoding: fc.constantFrom(0, 1, 2, 3, 0xff),
  text: fc.string({ maxLength: 24 }),
  flags: sometimes(fc.constantFrom(0x0040, 0x0002, 0xffff)),
} satisfies Total<Id3FrameSpec>);

/** An MP3: either tag, or both, drawn, with a head tag at its read ceiling. */
export function mp3Spec(): fc.Arbitrary<Mp3Spec> {
  const head = fc.record({
    major: sometimes(fc.constantFrom(2, 3, 4, 5)),
    frames: fc.array(frameSpec, { maxLength: 4 }),
    unsynchronised: sometimes(fc.boolean()),
    extendedHeader: sometimes(fc.constantFrom(0, 4, 10)),
    padding: sometimes(
      fc.oneof(
        { arbitrary: fc.constantFrom(0, 16), weight: 3 },
        { arbitrary: fc.constantFrom(...around(MAX_ID3_BYTES)), weight: 1 },
      ),
    ),
    plainSize: sometimes(fc.boolean()),
  } satisfies Total<NonNullable<Mp3Spec["head"]>>);
  // **A tag past its ceiling, composed**, so a run from any seed draws one: as
  // an override among overrides it landed on a few runs in a hundred, measured.
  const longTag = head.map((drawn) => ({
    ...drawn,
    padding: MAX_ID3_BYTES + 1,
  }));
  return fc.record({
    // Mostly present, unlike an override: the head tag is what is read first.
    head: fc.oneof(
      { arbitrary: head, weight: 3 },
      { arbitrary: longTag, weight: 1 },
      { arbitrary: fc.constant(undefined), weight: 1 },
    ),
    tail: sometimes(
      fc.record({
        title: sometimes(fc.string({ maxLength: 40 })),
        artist: sometimes(fc.string({ maxLength: 40 })),
        album: sometimes(fc.string({ maxLength: 40 })),
        year: sometimes(fc.string({ maxLength: 6 })),
      } satisfies Total<Id3v1Fields>),
    ),
  } satisfies Total<Mp3Spec>);
}
