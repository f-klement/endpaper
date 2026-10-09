/**
 * Building zips and EPUBs byte by byte, for the tests that read them.
 *
 * Support code, so it mirrors nothing: the mirrored files are the `*.test.ts`
 * ones. A builder rather than a checked-in binary because half of what is worth
 * testing is a malformed archive, and a malformed archive is easier to describe
 * than to keep as bytes nobody can read in a diff.
 *
 * Every override below exists for one test: a header field that a real writer
 * would never get wrong is exactly what a hostile file gets wrong on purpose.
 *
 * **`CompressionStream("deflate-raw")` does the compressing**, which is the
 * inverse of what `lib/zip.ts` uses, so a fixture is never inflated by the same
 * code that produced it.
 *
 * **Fixtures spell their XML declaration with double quotes.** happy-dom 20's
 * `DOMParser` silently falls back to HTML parsing on a single quoted
 * declaration, so an EPUB carrying one reads as "not an EPUB" under that
 * environment and reads correctly in every real browser. **41 of 79 real files
 * measured spell their `container.xml` declaration that way**, and 40 spell the
 * package document's that way; every Project Gutenberg file in that corpus is
 * among them. `tests/lib/opf.test.ts` covers the form under jsdom, whose parser
 * does not have the fault.
 */

import fc from "fast-check";

import { MAX_CONTAINER_BYTES, MAX_PACKAGE_BYTES } from "../src/lib/epub";
import { sometimes, spelled, type Repeated, type Total } from "./property";

const LOCAL_SIGNATURE = 0x04034b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const EOCD_SIGNATURE = 0x06054b50;

export const STORED = 0;
export const DEFLATED = 8;

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (const byte of bytes) c = CRC_TABLE[(c ^ byte) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

export function bytes(value: string): Uint8Array<ArrayBuffer> {
  return new TextEncoder().encode(value);
}

async function deflateRaw(
  input: Uint8Array<ArrayBuffer>,
): Promise<Uint8Array<ArrayBuffer>> {
  // A plain `ArrayBuffer` and not `ArrayBufferLike`: the stream's writable
  // takes a `BufferSource`, which a view over a `SharedArrayBuffer` is not.
  const source = new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      controller.enqueue(input);
      controller.close();
    },
  });
  const reader = source
    .pipeThrough(new CompressionStream("deflate-raw"))
    .getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    total += value.length;
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.length;
  }
  return out;
}

/**
 * A run of zeroes, named rather than spelled.
 *
 * **The shape of every deflate bomb**: zeroes deflate about a thousandfold, so
 * a file of a few kilobytes declares a small entry and inflates to megabytes.
 * Named so a property can draw one at a reader's own bound, one under it and
 * one over it, and so a counterexample carrying one prints as a literal
 * somebody can read rather than as sixteen mebibytes. `encode` builds the
 * bytes once per length and keeps them.
 */
export interface Zeroes {
  readonly zeroes: number;
}

/** What an entry holds: text, bytes, or a named run of zeroes or of text. */
export type Payload = Uint8Array<ArrayBuffer> | string | Zeroes | Repeated;

export interface EntrySpec {
  name: string;
  data: Payload;
  /** `STORED` or `DEFLATED`. Defaults to deflate, which is what writers use. */
  method?: number;
  /** Written to both headers. Bit 0 is the encrypted flag. */
  flags?: number;
  /** Extra field on the local header only, so a reader taking the central
   *  directory's length lands in the wrong place. */
  localExtra?: Uint8Array<ArrayBuffer>;
  /** Extra field on the central header only, for the same reason inverted. */
  centralExtra?: Uint8Array<ArrayBuffer>;
  /** What the central directory claims, when that should differ from the truth. */
  centralCompressedSize?: number;
  centralUncompressedSize?: number;
  centralHeaderOffset?: number;
  /** The method written to the central directory, when it should differ. */
  centralMethod?: number;
}

export interface ArchiveSpec {
  entries: EntrySpec[];
  /** The archive comment, which sits after the end of central directory record. */
  comment?: Uint8Array<ArrayBuffer>;
  /** What the record claims, when that should differ from the truth. */
  totalEntries?: number;
  centralDirectorySize?: number;
  centralDirectoryOffset?: number;
  disk?: number;
}

/** An entry's bytes as the archive holds them, and what they stand for. */
interface Encoded {
  readonly stored: Uint8Array<ArrayBuffer>;
  readonly length: number;
  readonly crc: number;
}

/**
 * Deflated runs of zeroes by length, built once per worker: under
 * `isolate: false` this module is evaluated once per worker, so every file
 * drawing a 32 MiB run shares one deflate of it.
 */
const ZEROES = new Map<number, Encoded>();

/** The CRC of `length` zeroes, without allocating them. */
function crcOfZeroes(length: number): number {
  let c = 0xffffffff;
  for (let at = 0; at < length; at += 1) c = CRC_TABLE[c & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

async function encode(data: Payload, method: number): Promise<Encoded> {
  if (
    typeof data === "string" ||
    data instanceof Uint8Array ||
    "unit" in data
  ) {
    const raw =
      data instanceof Uint8Array
        ? data
        : bytes(spelled(data as string | Repeated));
    return {
      stored: method === DEFLATED ? await deflateRaw(raw) : raw,
      length: raw.length,
      crc: crc32(raw),
    };
  }
  if (method !== DEFLATED) {
    // Stored zeroes cost their own length and are no bomb, so they are not
    // kept: a property drawing one pays for it once.
    const raw = new Uint8Array(data.zeroes);
    return { stored: raw, length: raw.length, crc: crc32(raw) };
  }
  const known = ZEROES.get(data.zeroes);
  if (known) return known;
  const built = {
    stored: await deflateRaw(new Uint8Array(data.zeroes)),
    length: data.zeroes,
    crc: crcOfZeroes(data.zeroes),
  };
  ZEROES.set(data.zeroes, built);
  return built;
}

export async function buildZip(
  spec: ArchiveSpec,
): Promise<Uint8Array<ArrayBuffer>> {
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;

  for (const entry of spec.entries) {
    const method = entry.method ?? DEFLATED;
    const { stored, length, crc } = await encode(entry.data, method);
    const name = bytes(entry.name);
    const localExtra = entry.localExtra ?? new Uint8Array(0);
    const centralExtra = entry.centralExtra ?? new Uint8Array(0);
    const flags = entry.flags ?? 0;

    const local = new Uint8Array(30 + name.length + localExtra.length);
    const localView = new DataView(local.buffer);
    localView.setUint32(0, LOCAL_SIGNATURE, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(6, flags, true);
    localView.setUint16(8, method, true);
    localView.setUint32(14, crc, true);
    localView.setUint32(18, stored.length, true);
    localView.setUint32(22, length, true);
    localView.setUint16(26, name.length, true);
    localView.setUint16(28, localExtra.length, true);
    local.set(name, 30);
    local.set(localExtra, 30 + name.length);

    const header = new Uint8Array(46 + name.length + centralExtra.length);
    const headerView = new DataView(header.buffer);
    headerView.setUint32(0, CENTRAL_SIGNATURE, true);
    headerView.setUint16(4, 20, true);
    headerView.setUint16(6, 20, true);
    headerView.setUint16(8, flags, true);
    headerView.setUint16(10, entry.centralMethod ?? method, true);
    headerView.setUint32(16, crc, true);
    headerView.setUint32(
      20,
      entry.centralCompressedSize ?? stored.length,
      true,
    );
    headerView.setUint32(24, entry.centralUncompressedSize ?? length, true);
    headerView.setUint16(28, name.length, true);
    headerView.setUint16(30, centralExtra.length, true);
    headerView.setUint32(42, entry.centralHeaderOffset ?? offset, true);
    header.set(name, 46);
    header.set(centralExtra, 46 + name.length);

    parts.push(local, stored);
    central.push(header);
    offset += local.length + stored.length;
  }

  const directorySize = central.reduce((sum, one) => sum + one.length, 0);
  const comment = spec.comment ?? new Uint8Array(0);
  const eocd = new Uint8Array(22 + comment.length);
  const eocdView = new DataView(eocd.buffer);
  eocdView.setUint32(0, EOCD_SIGNATURE, true);
  eocdView.setUint16(4, spec.disk ?? 0, true);
  eocdView.setUint16(6, spec.disk ?? 0, true);
  eocdView.setUint16(8, spec.totalEntries ?? spec.entries.length, true);
  eocdView.setUint16(10, spec.totalEntries ?? spec.entries.length, true);
  eocdView.setUint32(12, spec.centralDirectorySize ?? directorySize, true);
  eocdView.setUint32(16, spec.centralDirectoryOffset ?? offset, true);
  eocdView.setUint16(20, comment.length, true);
  eocd.set(comment, 22);

  const all = [...parts, ...central, eocd];
  const total = all.reduce((sum, one) => sum + one.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of all) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

export const CONTAINER_XML = (path = "OEBPS/content.opf") =>
  `<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="${path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>`;

/** A minimal EPUB 3 package document carrying one title and one creator. */
export function packageDocument(metadata: string, version = "3.0"): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="${version}" unique-identifier="pub-id">
  <metadata>${metadata}</metadata>
  <manifest/>
  <spine/>
</package>`;
}

export interface EpubSpec {
  /** The package document. */
  opf?: Payload;
  /** Where the container says the package document is. */
  packagePath?: string;
  /** Where the package document actually is, when it should differ. */
  storedAt?: string;
  /** The container document, when it should not be the ordinary one. */
  container?: Payload | null;
  /** Anything else in the archive. */
  extra?: EntrySpec[];
}

/** A whole EPUB, as bytes. The mimetype entry is stored, as the format asks. */
export async function buildEpub(
  spec: EpubSpec = {},
): Promise<Uint8Array<ArrayBuffer>> {
  const packagePath = spec.packagePath ?? "OEBPS/content.opf";
  const entries: EntrySpec[] = [
    { name: "mimetype", data: "application/epub+zip", method: STORED },
  ];
  if (spec.container !== null) {
    entries.push({
      name: "META-INF/container.xml",
      data: spec.container ?? CONTAINER_XML(packagePath),
    });
  }
  entries.push({
    name: spec.storedAt ?? packagePath,
    data:
      spec.opf ??
      packageDocument(
        `<dc:identifier id="pub-id">urn:uuid:1</dc:identifier><dc:title>Dune</dc:title><dc:creator>Frank Herbert</dc:creator><dc:language>en</dc:language>`,
      ),
  });
  entries.push(...(spec.extra ?? []));
  return buildZip({ entries });
}

/** The same, as the `File` a picker hands over. */
export async function epubFile(
  name = "dune.epub",
  spec: EpubSpec = {},
): Promise<File> {
  const data = await buildEpub(spec);
  return new File([data], name, { type: "application/epub+zip" });
}

// --- arbitraries over the specs above ----------------------------------------
//
// **Specs, never bytes.** A byte arbitrary never passes an end of central
// directory signature, so it tests one refusal and calls it fuzzing; a spec
// shrinks by structure and prints as the literal a named case is written in.
// `tests/lib/readerContract.ts` holds the contract they are driven through,
// and each door's own vocabulary (its entry names, its documents, its bounds)
// lives in its own test file and is composed with these.

/**
 * How far past a bound the far atom reaches: four of the largest chunk any
 * engine here emits, 64 KiB under bun, so a reader that has lost its bound is
 * pulled at least twice after crossing it under either runtime.
 */
export const FAR_PAST = 4 * 64 * 1024;

/**
 * One under a bound, the bound, one over it, and far past it. **For a bound
 * in bytes that an inflater crosses**, because the far atom is in bytes: a
 * bound on a count of reads takes `property.edges` instead.
 *
 * **The three at the edge test the edge and cannot test the bound.** A run one
 * byte over arrives inside the chunk that crosses, and that chunk is allowed,
 * so a reader with no bound at all pulls nothing further and the meter has
 * nothing to see. The far one is what a lost bound is caught by.
 */
export function around(bound: number): number[] {
  return [bound - 1, bound, bound + 1, bound + FAR_PAST].filter(
    (length) => length >= 0,
  );
}

/** A run of zeroes at one of these bounds, which is where a bomb is aimed. */
export function zeroesAt(bounds: readonly number[]): fc.Arbitrary<Zeroes> {
  return fc
    .constantFrom(...bounds.flatMap(around))
    .map((zeroes) => ({ zeroes }));
}

/**
 * A value for a size or offset field: the edges of the field, the bounds a
 * reader declares, and the zip64 sentinel. `fc.nat()` alone stops at
 * `2^31 - 1`, so it never draws `0xFFFFFFFF`, which is the value `zip.ts`
 * refuses by name.
 */
function fieldValue(bounds: readonly number[]): fc.Arbitrary<number> {
  return fc.oneof(
    fc.constantFrom(0, 1, 0xffff, 0xffffffff, ...bounds.flatMap(around)),
    fc.nat(),
  );
}

/**
 * A bomb: deflated zeroes at a bound, behind a directory declaring less.
 *
 * **Its own arbitrary because the fields that make one are four, and
 * independent draws rarely line them up**: deflated, a run past a bound, a
 * declared size under it, and nothing else wrong to refuse it earlier. A
 * generator holding every piece separately almost never builds the thing.
 */
export function bombEntry(
  names: fc.Arbitrary<string>,
  bounds: readonly number[],
): fc.Arbitrary<EntrySpec> {
  return fc.record({
    name: names,
    data: zeroesAt(bounds),
    method: fc.constant(undefined),
    flags: fc.constant(undefined),
    localExtra: fc.constant(undefined),
    centralExtra: fc.constant(undefined),
    centralCompressedSize: fc.constant(undefined),
    centralUncompressedSize: fc.constantFrom(
      0,
      1,
      ...bounds.map((bound) => Math.max(0, bound - 1)),
    ),
    centralHeaderOffset: fc.constant(undefined),
    centralMethod: fc.constant(undefined),
  } satisfies Total<EntrySpec>);
}

/**
 * A bomb aimed at one bound and nothing else: `bombEntry` with only its far
 * size, under one name.
 *
 * **For a witness to hold at any seed, not at one.** `bombEntry` draws four
 * sizes of which one is far enough past a bound for a lost bound to be seen,
 * so composed under two further choices it lands on a few hundredths of the
 * draws, and a property run from a fresh seed missed it on a few runs in a
 * hundred, measured. This is the branch a property weights to make the class
 * a tenth or more of what it draws.
 */
export function aimedBomb(
  name: string,
  bound: number,
): fc.Arbitrary<EntrySpec> {
  return bombEntry(fc.constant(name), [bound]).map((entry) =>
    Object.assign({}, entry, { data: { zeroes: bound + FAR_PAST } }),
  );
}

/** An archive holding nothing but one aimed bomb. */
export function aimedArchive(
  name: string,
  bound: number,
): fc.Arbitrary<ArchiveSpec> {
  return aimedBomb(name, bound).map((entry) => ({ entries: [entry] }));
}

/**
 * Whether an entry is a bomb as `bombEntry` builds one: aimed far enough past
 * `bound` that a reader without the bound is seen pulling past it, and with
 * nothing else wrong that would refuse it before the inflater.
 *
 * **The second half is what makes this a witness.** Without it an encrypted
 * entry or a lying compressed size counts, which independent draws produce
 * often enough to keep a witness green over a generator that has lost its
 * bomb branch: measured, with that branch removed this answered yes for two
 * of three doors at the one seed the suite then ran.
 */
export function isBomb(entry: EntrySpec, bound: number): boolean {
  return (
    typeof entry.data === "object" &&
    "zeroes" in entry.data &&
    entry.data.zeroes >= bound + FAR_PAST &&
    (entry.method ?? DEFLATED) === DEFLATED &&
    (entry.centralMethod ?? DEFLATED) === DEFLATED &&
    ((entry.flags ?? 0) & 1) === 0 &&
    entry.centralCompressedSize === undefined &&
    entry.centralHeaderOffset === undefined &&
    entry.centralUncompressedSize !== undefined &&
    entry.centralUncompressedSize <= bound
  );
}

/** One entry: any override drawn, or a bomb. */
export function entrySpec(
  names: fc.Arbitrary<string>,
  data: fc.Arbitrary<Payload>,
  bounds: readonly number[],
): fc.Arbitrary<EntrySpec> {
  const declared = sometimes(fieldValue(bounds));
  const extra = sometimes(fc.uint8Array({ maxLength: 12 }));
  const any = fc.record({
    name: names,
    data,
    method: sometimes(fc.constantFrom(STORED, DEFLATED, 12, 99)),
    flags: sometimes(fc.constantFrom(1, 8, 0x800, 0xffff)),
    localExtra: extra,
    centralExtra: extra,
    centralCompressedSize: declared,
    centralUncompressedSize: declared,
    centralHeaderOffset: sometimes(fc.constantFrom(0, 1, 0xffffffff)),
    centralMethod: sometimes(fc.constantFrom(STORED, DEFLATED, 99)),
  } satisfies Total<EntrySpec>);
  return fc.oneof(
    { arbitrary: any, weight: 3 },
    { arbitrary: bombEntry(names, bounds), weight: 1 },
  );
}

/** A whole archive of these entries, its own record sometimes lying. */
export function archiveSpec(
  entry: fc.Arbitrary<EntrySpec>,
  bounds: readonly number[] = [],
): fc.Arbitrary<ArchiveSpec> {
  return fc.record({
    entries: fc.array(entry, { maxLength: 4 }),
    // A comment carrying the record's own signature is the shape the backward
    // scan in `zip.ts` exists for.
    comment: sometimes(
      fc.oneof(
        fc.uint8Array({ maxLength: 24 }),
        fc.constant(bytes("PK\x05\x06")),
      ),
    ),
    totalEntries: sometimes(fc.constantFrom(0, 1, 2, 3, 0xffff)),
    centralDirectorySize: sometimes(fieldValue(bounds)),
    centralDirectoryOffset: sometimes(fieldValue(bounds)),
    disk: sometimes(fc.constantFrom(1, 0xffff)),
  } satisfies Total<ArchiveSpec>);
}

/** Paths an EPUB's container may name, the escaped and the escaping among them. */
const EPUB_PATHS = [
  "OEBPS/content.opf",
  "content.opf",
  "OEBPS/content%20one.opf",
  "OEBPS/content one.opf",
  "../content.opf",
  "%",
  "META-INF/container.xml",
  "mimetype",
  "",
];

/** Package documents a reader meets: whole, broken, and refusing ones. */
const PACKAGES = [
  packageDocument(
    `<dc:identifier id="pub-id">urn:uuid:1</dc:identifier><dc:title>Dune</dc:title>`,
  ),
  packageDocument("", "2.0"),
  `<?xml version="1.0"?><!DOCTYPE package [<!ENTITY e "x">]><package>&e;</package>`,
  "<package",
  "",
];

/**
 * An EPUB: any field drawn, or a bomb behind each of the two reads.
 *
 * **The two bombs are composed rather than drawn**, for `entrySpec`'s reason,
 * and they have to be: `buildEpub` writes its own container and package honest
 * about their sizes, so a lying directory is reached by moving the real
 * document aside and putting a lying entry where the container points.
 */
export function epubSpec(): fc.Arbitrary<EpubSpec> {
  const bounds = [MAX_CONTAINER_BYTES, MAX_PACKAGE_BYTES];
  const path = fc.oneof(
    fc.constantFrom(...EPUB_PATHS),
    fc.string({ maxLength: 12 }),
  );
  const data = fc.oneof(
    { arbitrary: fc.constantFrom<Payload>(...PACKAGES), weight: 2 },
    { arbitrary: zeroesAt(bounds), weight: 1 },
  );
  const any = fc.record({
    opf: sometimes(data),
    packagePath: sometimes(path),
    storedAt: sometimes(path),
    container: sometimes(
      fc.oneof(
        fc.constant(null),
        fc.constantFrom<Payload>(
          CONTAINER_XML(),
          CONTAINER_XML("%"),
          "<container/>",
        ),
        zeroesAt([MAX_CONTAINER_BYTES]),
      ),
    ),
    extra: sometimes(fc.array(entrySpec(path, data, bounds), { maxLength: 3 })),
  } satisfies Total<EpubSpec>);
  const packageBomb = fc.record({
    opf: fc.constant(undefined),
    packagePath: fc.constant(undefined),
    storedAt: fc.constant("OEBPS/elsewhere.opf"),
    container: fc.constant(undefined),
    extra: aimedBomb("OEBPS/content.opf", MAX_PACKAGE_BYTES).map((entry) => [
      entry,
    ]),
  } satisfies Total<EpubSpec>);
  const containerBomb = fc.record({
    opf: fc.constant(undefined),
    packagePath: fc.constant(undefined),
    storedAt: fc.constant(undefined),
    container: fc.constant(null),
    extra: aimedBomb("META-INF/container.xml", MAX_CONTAINER_BYTES).map(
      (entry) => [entry],
    ),
  } satisfies Total<EpubSpec>);
  return fc.oneof(
    { arbitrary: any, weight: 3 },
    { arbitrary: packageBomb, weight: 1 },
    { arbitrary: containerBomb, weight: 1 },
  );
}
