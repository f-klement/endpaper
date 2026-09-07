/**
 * Reading named entries out of a zip, in the browser, with no dependency.
 *
 * **The seam every zip based format here reuses.** EPUB, CBZ and `.fb2.zip` are
 * all a zip plus one interesting entry, so what varies between them is which
 * entry and how to read it, not how to get at it. This module knows nothing
 * about books.
 *
 * **It walks the central directory and inflates one entry**, rather than
 * expanding the archive. An EPUB needs two entries out of a median 30 and a
 * measured maximum of 2,020 over the 79 file corpus `opf.ts` describes, and the
 * two together are under 300 KB against archives up to 31,662,348 bytes, so
 * inflating the rest would be the whole cost of the feature for nothing.
 *
 * **The platform supplies the inflater.** `DecompressionStream("deflate-raw")`
 * is native in Chrome 103, Firefox 113 and Safari 16.4 and later. A library
 * would buy support for browsers older than that and cost a bundle on every
 * one that does not need it, so the absence of the global is reported as
 * `no-inflate` and the caller says so rather than being silently wrong.
 *
 * **A member's file is untrusted input.** Every offset read here is checked
 * against the length of the thing it points into, and every inflate is capped
 * by the caller against the bytes it actually produces rather than against the
 * size the archive claims: a zip bomb declares a small entry. What a hostile
 * or broken archive gets is a `ZipError` naming one entry, never a hung tab.
 */

/** Why a read stopped. Closed, because each one is a different thing to say. */
export type ZipFailure =
  /** No end of central directory record, so this is not a zip at all. */
  | "not-a-zip"
  /** A zip64 archive. Out of bounds here: see `MAX_ENTRIES`. */
  | "zip64"
  /** The entry is encrypted, so its bytes cannot be read without a password. */
  | "encrypted"
  /** Spanned across disks, or compressed by a method this does not implement. */
  | "unsupported"
  /**
   * An offset or a length points past the end of the file, or an entry's bytes
   * are not the stream its header says they are.
   */
  | "truncated"
  /** The entry produced more bytes than the caller allowed. */
  | "too-large"
  /** This browser has no `DecompressionStream("deflate-raw")`. */
  | "no-inflate";

export class ZipError extends Error {
  readonly failure: ZipFailure;

  constructor(failure: ZipFailure, message: string) {
    super(message);
    this.name = "ZipError";
    this.failure = failure;
  }
}

/** Little endian readers. A zip is little endian throughout. */
function u16(view: DataView, at: number): number {
  return view.getUint16(at, true);
}

function u32(view: DataView, at: number): number {
  return view.getUint32(at, true);
}

const EOCD_SIGNATURE = 0x06054b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const LOCAL_SIGNATURE = 0x04034b50;

/** The fixed part of an end of central directory record. */
const EOCD_BYTES = 22;

/** The fixed part of one central directory header. */
const CENTRAL_HEADER_BYTES = 46;

/** The fixed part of one local file header. */
const LOCAL_HEADER_BYTES = 30;

/**
 * The zip archive comment is a `u16` length, so the record can sit at most this
 * far from the end of the file.
 */
const MAX_COMMENT_BYTES = 0xffff;

/**
 * The most entries a non zip64 archive can hold, because the count in the end
 * of central directory record is a `u16`.
 *
 * The sentinel it cannot exceed is what identifies a zip64 archive, which this
 * module refuses rather than parses: a zip64 EPUB or CBZ would be an archive
 * over 4 GB or over 65,535 entries, and neither is a book. Refusing names the
 * case; parsing it would be a second header format carried for nothing.
 */
const MAX_ENTRIES = 0xffff;

/**
 * How much central directory this will read into memory.
 *
 * Derived rather than picked: `MAX_ENTRIES` headers at 128 bytes each, which is
 * the 46 byte header plus a name and extra field of ordinary length. An archive
 * declaring more than this has declared more directory than its own entry count
 * can justify.
 */
const MAX_CENTRAL_DIRECTORY_BYTES = MAX_ENTRIES * 128;

/** A `u32` field holding this is zip64's "look in the extra field" sentinel. */
const ZIP64_SENTINEL_32 = 0xffffffff;

/** Bit 0 of the general purpose flags: the entry is encrypted. */
const FLAG_ENCRYPTED = 0x1;

const METHOD_STORED = 0;
const METHOD_DEFLATE = 8;

/** One entry, as the central directory describes it. */
export interface ZipEntry {
  readonly name: string;
  /** 0 stored, 8 deflate. Anything else is refused at read time. */
  readonly method: number;
  readonly compressedSize: number;
  /** What the directory claims. Never trusted as a bound: see `read`. */
  readonly uncompressedSize: number;
  readonly headerOffset: number;
}

export interface ZipArchive {
  /** In central directory order, which is the order the archive was written. */
  readonly entries: readonly ZipEntry[];
  /** Exact match on the full path. Zip paths are `/` separated and not rooted. */
  find: (name: string) => ZipEntry | undefined;
  /**
   * The entry's bytes, refusing at `limit` bytes of **output**.
   *
   * `limit` is the caller's business because the seam has no opinion about what
   * an entry is for: a package document is measured in kilobytes and a comic
   * page in megabytes.
   */
  read: (entry: ZipEntry, limit: number) => Promise<Uint8Array>;
}

async function bytesAt(
  blob: Blob,
  start: number,
  end: number,
): Promise<Uint8Array<ArrayBuffer>> {
  return new Uint8Array(await blob.slice(start, end).arrayBuffer());
}

/**
 * Where the end of central directory record starts, or `null`.
 *
 * Scanned backwards from the end, and the comment length is checked against the
 * bytes actually left: the four signature bytes occur inside ordinary file data
 * often enough that finding them is not on its own evidence of anything, and
 * taking the first match from the front would let a crafted entry name a
 * directory of its own.
 */
function findEndOfCentralDirectory(
  tail: Uint8Array,
  tailStart: number,
  fileSize: number,
): number | null {
  const view = new DataView(tail.buffer, tail.byteOffset, tail.byteLength);
  for (let at = tail.length - EOCD_BYTES; at >= 0; at -= 1) {
    if (u32(view, at) !== EOCD_SIGNATURE) continue;
    const commentLength = u16(view, at + 20);
    if (tailStart + at + EOCD_BYTES + commentLength === fileSize) return at;
  }
  return null;
}

/**
 * Read the archive's directory. The entries' bytes are not touched.
 *
 * Rejects rather than throwing a bare `Error`: every refusal here is a
 * `ZipError` carrying a `ZipFailure`, so a caller can say which of the seven
 * things went wrong without matching on a message.
 */
export async function openZip(blob: Blob): Promise<ZipArchive> {
  const size = blob.size;
  if (size < EOCD_BYTES) {
    throw new ZipError("not-a-zip", "too short to hold a zip directory");
  }

  const tailStart = Math.max(0, size - (EOCD_BYTES + MAX_COMMENT_BYTES));
  const tail = await bytesAt(blob, tailStart, size);
  const eocd = findEndOfCentralDirectory(tail, tailStart, size);
  if (eocd === null) {
    throw new ZipError("not-a-zip", "no end of central directory record");
  }

  const view = new DataView(tail.buffer, tail.byteOffset, tail.byteLength);
  const thisDisk = u16(view, eocd + 4);
  const directoryDisk = u16(view, eocd + 6);
  const total = u16(view, eocd + 10);
  const directorySize = u32(view, eocd + 12);
  const directoryOffset = u32(view, eocd + 16);

  if (
    total === MAX_ENTRIES ||
    directorySize === ZIP64_SENTINEL_32 ||
    directoryOffset === ZIP64_SENTINEL_32
  ) {
    throw new ZipError("zip64", "zip64 archives are out of bounds here");
  }
  if (thisDisk !== 0 || directoryDisk !== 0) {
    throw new ZipError("unsupported", "spanned archive");
  }
  if (directorySize > MAX_CENTRAL_DIRECTORY_BYTES) {
    throw new ZipError("too-large", "central directory is implausibly large");
  }
  if (directoryOffset + directorySize > size) {
    throw new ZipError("truncated", "central directory runs past the file");
  }

  const directory = await bytesAt(
    blob,
    directoryOffset,
    directoryOffset + directorySize,
  );
  const headers = new DataView(
    directory.buffer,
    directory.byteOffset,
    directory.byteLength,
  );
  const names = new TextDecoder("utf-8");

  const entries: ZipEntry[] = [];
  let at = 0;
  while (entries.length < total) {
    if (at + CENTRAL_HEADER_BYTES > directory.length) {
      throw new ZipError("truncated", "central directory ends mid header");
    }
    if (u32(headers, at) !== CENTRAL_SIGNATURE) {
      throw new ZipError("not-a-zip", "central directory header not found");
    }
    const flags = u16(headers, at + 8);
    const method = u16(headers, at + 10);
    const compressedSize = u32(headers, at + 20);
    const uncompressedSize = u32(headers, at + 24);
    const nameLength = u16(headers, at + 28);
    const extraLength = u16(headers, at + 30);
    const commentLength = u16(headers, at + 32);
    const headerOffset = u32(headers, at + 42);

    if ((flags & FLAG_ENCRYPTED) !== 0) {
      throw new ZipError("encrypted", "an entry is encrypted");
    }
    if (
      compressedSize === ZIP64_SENTINEL_32 ||
      uncompressedSize === ZIP64_SENTINEL_32 ||
      headerOffset === ZIP64_SENTINEL_32
    ) {
      throw new ZipError("zip64", "zip64 archives are out of bounds here");
    }
    const nameAt = at + CENTRAL_HEADER_BYTES;
    if (nameAt + nameLength > directory.length) {
      throw new ZipError("truncated", "central directory ends mid name");
    }
    // Decoded as UTF-8 whatever the language encoding flag says. The two paths
    // this seam's callers ask for are `META-INF/container.xml` and whatever
    // `container.xml` names, which the EPUB specification requires to be a
    // relative path in ASCII; a CP437 name outside that is mis-decoded and
    // simply does not match, which is a miss rather than a wrong entry.
    const name = names.decode(directory.subarray(nameAt, nameAt + nameLength));

    entries.push({
      name,
      method,
      compressedSize,
      uncompressedSize,
      headerOffset,
    });
    at = nameAt + nameLength + extraLength + commentLength;
  }

  return {
    entries,
    find: (name) => entries.find((entry) => entry.name === name),
    read: (entry, limit) => readEntry(blob, entry, limit),
  };
}

/**
 * The most compressed bytes that could legitimately produce `limit` bytes out.
 *
 * Deflate's worst case is a run of stored blocks, five bytes of header per
 * 65,535 of data, so an entry holding more than this cannot be an entry of at
 * most `limit` bytes however it was written.
 *
 * **This bounds what is read into memory, which is a different question from
 * what is produced.** Without it a hostile archive declares a small entry and a
 * large compressed size, and the slice below allocates the whole of it before
 * the inflater has emitted a single byte for the output cap to count.
 */
function maxCompressedFor(limit: number): number {
  return limit + (Math.ceil(limit / 65535) + 1) * 5;
}

async function readEntry(
  blob: Blob,
  entry: ZipEntry,
  limit: number,
): Promise<Uint8Array<ArrayBuffer>> {
  // The claim, checked first because it is free. The bytes are checked again
  // as they arrive, which is the check that matters: a bomb understates this.
  if (entry.uncompressedSize > limit) {
    throw new ZipError(
      "too-large",
      `${entry.name} declares more than ${limit}`,
    );
  }
  if (entry.headerOffset + LOCAL_HEADER_BYTES > blob.size) {
    throw new ZipError("truncated", `${entry.name} has no local header`);
  }

  const header = await bytesAt(
    blob,
    entry.headerOffset,
    entry.headerOffset + LOCAL_HEADER_BYTES,
  );
  const view = new DataView(
    header.buffer,
    header.byteOffset,
    header.byteLength,
  );
  if (u32(view, 0) !== LOCAL_SIGNATURE) {
    throw new ZipError("not-a-zip", `${entry.name} has no local header`);
  }
  // **The local header's own name and extra lengths, not the directory's.**
  // Writers pad the extra field differently in the two places, so taking the
  // directory's lengths lands the read a few bytes into or before the data.
  const dataStart =
    entry.headerOffset + LOCAL_HEADER_BYTES + u16(view, 26) + u16(view, 28);
  const dataEnd = dataStart + entry.compressedSize;
  if (dataEnd > blob.size) {
    throw new ZipError("truncated", `${entry.name} runs past the file`);
  }

  // **After the truncation checks and before the slice.** After, because an
  // entry pointing past the end of the file is a broken archive whatever its
  // size, and reporting that as too large would name the wrong fault. Before,
  // because this is the line that would otherwise allocate it.
  if (entry.compressedSize > maxCompressedFor(limit)) {
    throw new ZipError(
      "too-large",
      `${entry.name} holds more compressed bytes than ${limit} could need`,
    );
  }

  const raw = await bytesAt(blob, dataStart, dataEnd);
  if (entry.method === METHOD_STORED) {
    if (raw.length > limit) {
      throw new ZipError("too-large", `${entry.name} is larger than ${limit}`);
    }
    return raw;
  }
  if (entry.method !== METHOD_DEFLATE) {
    throw new ZipError(
      "unsupported",
      `${entry.name} uses method ${entry.method}`,
    );
  }
  return inflateRaw(raw, limit, entry.name);
}

/**
 * Inflate, refusing at `limit` bytes of output.
 *
 * The cap is enforced on what comes out rather than on what the archive said
 * was in there, which is the whole point: a zip bomb declares a modest entry
 * and produces gigabytes. The stream is cancelled at the limit, so the work
 * stops rather than running to completion and being discarded.
 */
async function inflateRaw(
  raw: Uint8Array<ArrayBuffer>,
  limit: number,
  name: string,
): Promise<Uint8Array<ArrayBuffer>> {
  if (typeof DecompressionStream === "undefined") {
    throw new ZipError("no-inflate", "this browser cannot inflate");
  }
  let inflater: DecompressionStream;
  try {
    inflater = new DecompressionStream("deflate-raw");
  } catch {
    // The constructor exists and the format does not, which is a real state:
    // "deflate-raw" landed later than "deflate" and "gzip" in every engine.
    throw new ZipError("no-inflate", "this browser cannot inflate raw deflate");
  }

  // A `ReadableStream` over the bytes rather than `new Blob(...).stream()`.
  // The bytes are already in memory, so the Blob buys nothing, and jsdom
  // implements `Blob` without `stream()`, which would make this module
  // untestable in the one environment whose `DOMParser` actually parses XML.
  // Typed to a plain `ArrayBuffer` and not `ArrayBufferLike`, because the
  // stream's writable takes a `BufferSource`, which a view over a
  // `SharedArrayBuffer` is not.
  const source = new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      controller.enqueue(raw);
      controller.close();
    },
  });
  const reader = source.pipeThrough(inflater).getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    // **The read is guarded, because the inflater rejects with a `TypeError`.**
    // Bytes that are not deflate, or that stop halfway, reach here as
    // `TypeError: inflate failed` and `TypeError: unexpected end of file`, and
    // an unguarded loop lets one escape past every caller that is catching
    // `ZipError`. That is a broken archive, which this module promises to
    // report as one entry's named failure.
    let done: boolean;
    let value: Uint8Array | undefined;
    try {
      ({ done, value } = await reader.read());
    } catch {
      // Only the read is inside the try, and the read is the only thing here
      // that can reject with something other than a `ZipError`. A branch
      // rethrowing one was written and deleted: it could not fire, and a guard
      // that cannot fire tells the next reader the throw below is covered.
      throw new ZipError("truncated", `${name} is not a deflate stream`);
    }
    if (done || value === undefined) break;
    total += value.length;
    if (total > limit) {
      await reader.cancel();
      throw new ZipError("too-large", `${name} inflates past ${limit}`);
    }
    chunks.push(value);
  }

  const out = new Uint8Array(total);
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.length;
  }
  return out;
}
