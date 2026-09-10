/**
 * An EPUB's metadata, read in the member's own browser.
 *
 * **Endpaper never takes custody of a member's book file**, and the rule is
 * about custody rather than about where bytes travel. Stated as "no bytes reach
 * the server" it proves too much, because `POST /api/books/{id}/cover` takes an
 * uploaded image today and is meant to. Stated as custody it refuses what it
 * was written to refuse: a transient endpoint that reads a book and discards it,
 * and equally a browser that hands the file to somebody else's host, which a
 * rule about the server would not reach at all.
 *
 * Reading here and sending only what the file said is the shape with no such
 * route in it, which is the point of doing the parse in the browser rather than
 * a preference about where code runs.
 *
 * Two entries out of the archive and nothing else. `META-INF/container.xml`
 * names the package document, and the package document is the metadata.
 * Measured over the 79 file corpus `opf.ts` describes, including what it is a
 * proxy for and what it is not: the container is at most 269 bytes and the
 * package document at most 253,032, against files up to 31,662,348 bytes.
 *
 * **Lazy loaded.** Nothing here is imported at the top of a module the shell
 * pulls in: `ScanPage`'s file panel imports it with `await import` when a member
 * picks a file, so a session that never opens the scan page never pays for the
 * zip walk, the parser or the bounds table.
 *
 * **A member's own browser is not a trusted producer.** The file is somebody
 * else's data whatever route it took to the disk it is on, so every read is
 * bounded and every failure is one file's failure. `bookBounds.ts` is the other
 * half: what comes out of here is bounded again before it can become a request.
 */

import { type FileMetadata } from "./fileReaders";
import { declaresEntities } from "./xmlEntities";
import { readOpf } from "./opf";
import {
  openZip,
  ZipError,
  zipFailureAs,
  type ZipArchive,
  type ZipEntry,
} from "./zip";

/**
 * How much `META-INF/container.xml` may inflate to.
 *
 * Measured at 269 bytes over 79 real files, median 252. 64 KiB is 243 times the
 * largest seen, which leaves room for a producer that indents strangely and
 * still refuses anything that is not a container document.
 */
const MAX_CONTAINER_BYTES = 64 * 1024;

/**
 * How much the package document may inflate to.
 *
 * Measured at 253,032 bytes over the same 79 files, median 4,943; the largest is
 * a 2,020 entry Mahabharata whose manifest is most of it. 4 MiB is sixteen times
 * that, and it is a bound on **output**, so a package document claiming to be
 * small and inflating to gigabytes is stopped by this rather than by the claim.
 */
const MAX_PACKAGE_BYTES = 4 * 1024 * 1024;

const CONTAINER_PATH = "META-INF/container.xml";
const CONTAINER_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:container";
const PACKAGE_MEDIA_TYPE = "application/oebps-package+xml";

/**
 * Why a file yielded nothing. Closed, because each one is a different sentence
 * to a member holding a file that did not work.
 */
export type EpubFailure =
  /** Not a zip, or a zip that carries no EPUB container or package document. */
  | "not-an-epub"
  /** A zip whose own offsets do not agree with its length. */
  | "damaged"
  /** Encrypted, which here means DRM, and DRM is out of scope. */
  | "protected"
  /** An entry inflates past what this will read. */
  | "too-large"
  /** Zip64, spanned, or a compression method this does not implement. */
  | "unsupported"
  /** This browser has no `DecompressionStream("deflate-raw")`. */
  | "no-inflate";

export type EpubReading =
  | { readonly ok: true; readonly metadata: FileMetadata }
  | { readonly ok: false; readonly failure: EpubFailure };

const utf8 = new TextDecoder("utf-8");

/**
 * Where `container.xml` says the package document is, or `null`.
 *
 * The first rootfile declaring the OPF media type, and the first rootfile at all
 * as a fallback: a container may list several renditions, and one that names no
 * media type is still naming the only package document it has.
 */
function packagePath(xml: string): string | null {
  // The container is parsed by the same engine and is the same exposure. See
  // `declaresEntities`.
  if (declaresEntities(xml)) return null;
  const document = new DOMParser().parseFromString(xml, "application/xml");
  const root = document.documentElement;
  if (!root || root.localName !== "container") return null;

  const rootfiles = [
    ...root.getElementsByTagNameNS(CONTAINER_NAMESPACE, "rootfile"),
  ];
  const all =
    rootfiles.length > 0
      ? rootfiles
      : [...root.getElementsByTagName("rootfile")];
  const chosen =
    all.find(
      (element) => element.getAttribute("media-type") === PACKAGE_MEDIA_TYPE,
    ) ?? all[0];
  const path = chosen?.getAttribute("full-path")?.trim();
  return path ? path : null;
}

/**
 * What a caller may know about what this inflated, and why anything wants to.
 *
 * **Two entries out of an archive is a bound on one file and not on a run.** A
 * caller reading one picked EPUB is done at 4.06 MiB and needs none of this.
 * `takeout.ts` reads one per book out of an archive the member picked, so what
 * bounds it is the total, and every byte inflated here is a byte that total has
 * to see: measured by the security seat, 300 books whose package documents are
 * deflate bombs inflate 1.26 GB out of a 1.5 MB archive, all of it invisible to
 * a caller that can only count the bytes it handed in.
 *
 * **Told rather than asked**, so nothing here can be stopped halfway: the two
 * ceilings above already bound one file, and this reports what they cost. A
 * caller out of budget stops before the next file rather than inside this one.
 *
 * **It is told about a read that failed as well as one that worked**, and that
 * is the half a first draft left out. A read stopped at its ceiling inflated
 * those bytes and threw them away, so a charge taken from what came back
 * charges nothing for the most expensive thing this module can do, and a
 * package document declaring a kilobyte and holding four megabytes repeats it
 * once per file. See `readSpending`.
 */
export type EpubCharge = (bytes: number) => void;

/**
 * One entry, charged whether it arrives or not.
 *
 * **Three rules in four lines, and each of them was bought.** The declared size
 * is asked first, because a refusal there inflated nothing and charging it
 * would make an honestly oversized package document cost a caller its whole
 * allowance. A read that returns is charged what it produced. A read that
 * throws is charged the ceiling, because that is what it may have inflated
 * before it stopped.
 *
 * **The over charge is real and is the safe direction**: an entry refused for
 * a truncated local header inflated nothing and is charged the ceiling anyway.
 * A caller can lose a budget to a broken archive; it cannot lose a tab to a
 * crafted one.
 */
async function readSpending(
  archive: ZipArchive,
  entry: ZipEntry,
  limit: number,
  charge: EpubCharge | undefined,
): Promise<Uint8Array<ArrayBuffer>> {
  if (entry.uncompressedSize > limit) {
    throw new ZipError(
      "too-large",
      `${entry.name} declares more than ${limit}`,
    );
  }
  let bytes: Uint8Array<ArrayBuffer>;
  try {
    bytes = await archive.read(entry, limit);
  } catch (error) {
    charge?.(limit);
    throw error;
  }
  charge?.(bytes.length);
  return bytes;
}

/**
 * Read one EPUB's metadata.
 *
 * Never throws for anything the file did, which is the contract
 * `fileReaders.FileReader` states for every reader, along with the reason it is
 * worth stating. The one thing this does not catch is a bug in this module,
 * which should not be turned into "not an EPUB".
 *
 * **The second parameter is optional and the type still fits `FileReader`**,
 * which takes one argument: a caller with no total to keep passes nothing and
 * pays nothing.
 */
export async function readEpub(
  file: Blob,
  charge?: EpubCharge,
): Promise<EpubReading> {
  try {
    const archive = await openZip(file);

    const container = archive.find(CONTAINER_PATH);
    if (container === undefined) return { ok: false, failure: "not-an-epub" };
    const containerBytes = await readSpending(
      archive,
      container,
      MAX_CONTAINER_BYTES,
      charge,
    );
    const path = packagePath(utf8.decode(containerBytes));
    if (path === null) return { ok: false, failure: "not-an-epub" };

    // The path is a URI reference, so a producer may have escaped a space or a
    // non ASCII character in it; zip entry names carry the character itself.
    // Exact match first, because unescaping a name that was never escaped is
    // how a literal `%20` in a filename stops matching.
    const entry = archive.find(path) ?? archive.find(unescapePath(path));
    if (entry === undefined) return { ok: false, failure: "not-an-epub" };

    const packageBytes = await readSpending(
      archive,
      entry,
      MAX_PACKAGE_BYTES,
      charge,
    );
    const metadata = readOpf(utf8.decode(packageBytes));
    if (metadata === null) return { ok: false, failure: "not-an-epub" };
    return { ok: true, metadata };
  } catch (error) {
    if (error instanceof ZipError) {
      return { ok: false, failure: zipFailureAs(error, "not-an-epub") };
    }
    throw error;
  }
}

function unescapePath(path: string): string {
  try {
    return decodeURIComponent(path);
  } catch {
    // A stray `%` is not an escape. The unescaped form is then the path itself,
    // which has already been tried, so this returns a value that simply misses.
    return path;
  }
}
