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
 * **Two ways to read one entry, because they are two questions.** `read` wants
 * the whole entry and refuses one bigger than the caller allowed. `readPrefix`
 * wants the head of it and stops there, which is what a metadata reader wants
 * when the entry it is after is the book itself rather than a small member of a
 * large archive. Conflating them is how a refusal becomes a silent truncation,
 * so a prefix read says whether it stopped early.
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

/**
 * How much of an entry to read, when the head of it is all the caller wants.
 *
 * Two numbers because they answer two questions. `limit` is the ceiling: an
 * entry declaring or holding more than this is refused, which is the archive
 * being told no. `prefix` is how much of an entry under that ceiling is wanted,
 * which is the caller saying enough. Named fields rather than two positional
 * numbers: swapping those type checks, and would read the ceiling.
 *
 * **Both are required to be finite.** A read with no bound is refused rather
 * than performed: see the guard at the top of `readEntry`. Stated here rather
 * than on either field, because it is a fact about the pair and a note on one
 * of them is invisible to a caller filling in the other.
 */
export interface ZipBounds {
  /** Stop after this many bytes of output and return what arrived. */
  readonly prefix: number;
  /**
   * Refuse an entry declaring or holding more than this. A deflated entry read
   * as a prefix is not measured past `prefix`, so this is what the entry says
   * and what its compressed bytes come to, which is the phrasing `fb2.ts` uses
   * of the same number. Also clamps a `prefix` above it.
   */
  readonly limit: number;
}

/**
 * What a prefix read returned.
 *
 * **`partial` is not the `truncated` failure, and conflating the two is the
 * mistake this type exists to make impossible.** `truncated` says the archive
 * is broken and there is nothing to read; `partial` says the entry is longer
 * than the caller asked for, which for a reader after a header is the ordinary
 * case. "This is all I needed" and "this file will not open" are answered by
 * different members, not by a byte count a caller has to interpret.
 */
export interface ZipPrefix {
  readonly bytes: Uint8Array<ArrayBuffer>;
  /** True when the entry holds bytes past the ones returned. */
  readonly partial: boolean;
}

export class ZipError extends Error {
  readonly failure: ZipFailure;

  constructor(failure: ZipFailure, message: string) {
    super(message);
    this.name = "ZipError";
    this.failure = failure;
  }
}

/**
 * What a `ZipFailure` becomes in a format's own union, for the arms a format
 * does not choose.
 *
 * `damaged`, `protected` and `too-large` are the names `lib/fileReaders.ts`
 * argues every reader should share: a damaged archive is damaged whichever
 * format claimed it, and only "this is a different kind of file" is per format,
 * because that is the one sentence telling a member to look at what they
 * picked. `unsupported` and `no-inflate` are this seam's own words, and
 * `lib/pdf.ts` carries the second for the same reason.
 *
 * **It is still nothing about books**, which is what the module docstring above
 * claims: these say what happened to a file, and the name for what the file
 * turned out not to be is the word its reader supplies.
 */
export type ZipSharedFailure =
  "damaged" | "protected" | "too-large" | "unsupported" | "no-inflate";

/**
 * The answer for every arm but the one a reader has to supply.
 *
 * Total over `ZipFailure` less `not-a-zip`, so a member added to that union is
 * a compile error here, which is where the totality the three copies had went.
 */
const SHARED_ANSWER: Record<
  Exclude<ZipFailure, "not-a-zip">,
  ZipSharedFailure
> = {
  zip64: "unsupported",
  encrypted: "protected",
  unsupported: "unsupported",
  truncated: "damaged",
  "too-large": "too-large",
  "no-inflate": "no-inflate",
};

/**
 * A zip's refusal in the words a member needs, given the one word this seam
 * cannot supply.
 *
 * **The answer and not the table, because a table can be copied and a copy can
 * be wrong.** Each reader held its own total `Record<ZipFailure, XFailure>`,
 * identical but for `"not-a-zip"`, so the author of a fourth copied every
 * decision in order to make one and a copy carrying `truncated: "unsupported"`
 * compiled and shipped. Handing that table back rather than declaring it moves
 * the fault one rung and no further: a caller can spread it and override an
 * arm, and where an arm's key is also its answer, no test in this tree would
 * notice. A reader handed the answer has no table to copy or to spread.
 *
 * **What it is still free to do is rewrite the answer where it stands**, and
 * nothing here refuses that: measured, `said === "unsupported" ? "damaged" :
 * said` at a reader's own catch passes the compiler and every test in this
 * tree. It is one line at one site rather than a table, which is the shape
 * somebody copies without reading.
 *
 * **If a new arm's answer is a name outside `ZipSharedFailure`** it is a
 * compile error at every caller as well as here, where the answer becomes that
 * caller's own failure, because no reader's union carries that name yet.
 *
 * **The supplied word may not be one of the shared names.** Without the
 * constraint, `zipFailureAs(error, "protected")` type checks, because that name
 * is a member of the caller's own union, and every file that is not a zip is
 * then reported to a member as DRM. The table this replaced put the key in
 * front of its author and a call does not, so the constraint carries that back.
 *
 * A helper a fourth reader simply does not call would leave the hole open, so
 * `tests/zipFailureVocabulary.test.ts` is the half of this that no type says.
 */
export function zipFailureAs<N extends string>(
  error: ZipError,
  notAZip: N extends ZipSharedFailure ? never : N,
): ZipSharedFailure | N {
  return error.failure === "not-a-zip"
    ? // The parameter's type is the constraint rather than `N` itself, and a
      // conditional type is not resolved until `N` is. The cast is over a value
      // the caller passed, from which the compiler has already refused every
      // name it may not be.
      (notAZip as N)
    : SHARED_ANSWER[error.failure];
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
  /**
   * The first `bounds.prefix` bytes of the entry, stopping rather than failing.
   *
   * **A third question, and it replaces neither of the other two.**
   * `bounds.limit` is still checked against what the directory declares and
   * against how many compressed bytes the entry holds, so an entry too large to
   * be the thing the caller is looking for is still `too-large`. What changes is
   * what happens at `bounds.prefix`: the inflater is cancelled and the bytes so
   * far come back with `partial` set, rather than the read being refused.
   *
   * **It bounds the inflate and the output, not the compressed read.** The
   * entry's compressed bytes are still sliced whole, because the smallest slice
   * certain to yield `prefix` bytes out is not knowable from deflate's worst
   * case: that bound is the worst case for expansion, and an encoder emitting
   * many small blocks yields fewer bytes than it. A read cut short there arrives
   * as `truncated`, so bounding the input would report a good file as a damaged
   * one. What this removes is inflating and buffering everything past `prefix`.
   *
   * **A stored entry over `limit` is still refused here and a deflated one is
   * not**, because the first costs nothing to notice and the second costs
   * inflating the rest, which is the read this exists to avoid. Both are caught
   * before that by the declared size, so the two differ only for an archive
   * whose directory lies, where refusing is the safer of the two answers.
   */
  readPrefix: (entry: ZipEntry, bounds: ZipBounds) => Promise<ZipPrefix>;
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
    read: async (entry, limit) => {
      // The whole entry, so the ceiling and the stop are the same number and
      // stopping early is the refusal. This is the one place the two questions
      // meet, and the refusal lives here rather than as a flag threaded through
      // `readEntry`, so that neither read has to ask which kind it is.
      const whole = await readEntry(blob, entry, limit, limit);
      if (whole.partial) {
        throw new ZipError(
          "too-large",
          `${entry.name} holds more than ${limit}`,
        );
      }
      return whole.bytes;
    },
    readPrefix: (entry, bounds) =>
      readEntry(blob, entry, bounds.limit, bounds.prefix),
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

/**
 * One entry's bytes: refused above `limit`, stopped at `prefix`.
 *
 * `limit` is the ceiling every check here is made against and the stop is where
 * the output ends, which is why a partial result is returned rather than
 * refused: only the caller knows whether stopping early was the point.
 */
async function readEntry(
  blob: Blob,
  entry: ZipEntry,
  limit: number,
  prefix: number,
): Promise<ZipPrefix> {
  // **A bound that is not a number is no bound at all, and this is the only
  // place that can say so.** Every comparison below is against `limit` or
  // against the stop derived from it, and a comparison with `NaN` is false, so
  // `NaN` does not loosen the cap, it removes it: the stored path returns the
  // whole entry saying `partial: false`, and the inflater accumulates the
  // entire output and then answers `new Uint8Array(NaN)`, which is no bytes,
  // also saying `partial: false`. Measured on a 64 MiB entry declaring 2 KiB:
  // 262,144 bytes and 0.0 MiB of heap at a finite prefix against 0 bytes and
  // 15.8 MiB at `NaN`. `too-large` because an unbounded read is the one this
  // module exists to refuse, and no other member of the union fits.
  if (!Number.isFinite(limit) || !Number.isFinite(prefix)) {
    throw new ZipError(
      "too-large",
      `${entry.name} was asked for with no bound`,
    );
  }
  // **The invariant the rest of this function assumes, held where it is
  // stated.** Above the ceiling it would hand back more than the caller's own
  // limit; below zero the stored path returns a plausible wrong answer and the
  // deflated one throws a bare `RangeError` out of `new Uint8Array`, which is
  // not a `ZipError` and so escapes what this module promises about refusals.
  // Here rather than at the call site, because a second door would have to
  // remember it.
  const stop = Math.max(0, Math.min(prefix, limit));
  // The claim, checked first because it is free. The bytes are bounded again as
  // they arrive, by `stop`, and that is the bound that matters because a bomb
  // understates this one. A prefix read makes it stricter rather than weaker:
  // `stop` is at most `limit`, so less comes out and never more.
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
    // The ceiling and not the stop: an entry the archive was not allowed to
    // hold is a refusal whatever the caller asked to read of it.
    if (raw.length > limit) {
      throw new ZipError("too-large", `${entry.name} is larger than ${limit}`);
    }
    // **A copy and not a `subarray`, when there is anything to cut off.** A
    // view keeps the whole entry alive behind it and hands back every byte past
    // the prefix through `.buffer`, which is the opposite of what `prefix`
    // promises. The condition is what keeps it free: neither `read` nor a
    // prefix that fits ever copies.
    return raw.length > stop
      ? { bytes: raw.slice(0, stop), partial: true }
      : { bytes: raw, partial: false };
  }
  if (entry.method !== METHOD_DEFLATE) {
    throw new ZipError(
      "unsupported",
      `${entry.name} uses method ${entry.method}`,
    );
  }
  return inflateRaw(raw, stop, entry.name);
}

/**
 * Inflate, stopping at `stop` bytes of output.
 *
 * The stop is enforced on what comes out rather than on what the archive said
 * was in there, which is the whole point: a zip bomb declares a modest entry
 * and produces gigabytes. The stream is cancelled there, so the work stops
 * rather than running to completion and being discarded.
 *
 * **Whether stopping is a refusal is not decided here.** It is reported as
 * `partial`, and `read` is the caller that turns it into `too-large`.
 */
async function inflateRaw(
  raw: Uint8Array<ArrayBuffer>,
  stop: number,
  name: string,
): Promise<ZipPrefix> {
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
  let partial = false;
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
      // that cannot fire tells the next reader something here throws one.
      throw new ZipError("truncated", `${name} is not a deflate stream`);
    }
    if (done || value === undefined) break;
    total += value.length;
    chunks.push(value);
    if (total > stop) {
      partial = true;
      // Let go of the inflater without waiting for it, for the reason
      // `lib/pdf.ts`'s `release` states: awaiting the cancel puts this
      // function's own bound at the mercy of the thing it is bounding, and a
      // cancel on a stream that already errored rejects. The bytes asked for
      // are already in `chunks`.
      void reader.cancel().catch(() => {});
      break;
    }
  }

  // Trimmed rather than sized to `total`, because the chunk that crossed the
  // stop is kept whole and is the one that overruns it.
  const out = new Uint8Array(Math.min(total, stop));
  let at = 0;
  for (const chunk of chunks) {
    if (at === out.length) break;
    const take = chunk.subarray(0, out.length - at);
    out.set(take, at);
    at += take.length;
  }
  return { bytes: out, partial };
}
