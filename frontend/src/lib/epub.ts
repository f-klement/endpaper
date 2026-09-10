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

import { declaresEntities, type FileMetadata } from "./fileReaders";
import { readOpf } from "./opf";
import { openZip, ZipError, zipFailureAs } from "./zip";

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
 * Read one EPUB's metadata.
 *
 * Never throws for anything the file did, which is the contract
 * `fileReaders.FileReader` states for every reader, along with the reason it is
 * worth stating. The one thing this does not catch is a bug in this module,
 * which should not be turned into "not an EPUB".
 */
export async function readEpub(file: Blob): Promise<EpubReading> {
  try {
    const archive = await openZip(file);

    const container = archive.find(CONTAINER_PATH);
    if (container === undefined) return { ok: false, failure: "not-an-epub" };
    const path = packagePath(
      utf8.decode(await archive.read(container, MAX_CONTAINER_BYTES)),
    );
    if (path === null) return { ok: false, failure: "not-an-epub" };

    // The path is a URI reference, so a producer may have escaped a space or a
    // non ASCII character in it; zip entry names carry the character itself.
    // Exact match first, because unescaping a name that was never escaped is
    // how a literal `%20` in a filename stops matching.
    const entry = archive.find(path) ?? archive.find(unescapePath(path));
    if (entry === undefined) return { ok: false, failure: "not-an-epub" };

    const metadata = readOpf(
      utf8.decode(await archive.read(entry, MAX_PACKAGE_BYTES)),
    );
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
