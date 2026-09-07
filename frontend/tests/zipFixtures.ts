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

export interface EntrySpec {
  name: string;
  data: Uint8Array<ArrayBuffer> | string;
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

export async function buildZip(
  spec: ArchiveSpec,
): Promise<Uint8Array<ArrayBuffer>> {
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;

  for (const entry of spec.entries) {
    const raw = typeof entry.data === "string" ? bytes(entry.data) : entry.data;
    const method = entry.method ?? DEFLATED;
    const stored = method === DEFLATED ? await deflateRaw(raw) : raw;
    const name = bytes(entry.name);
    const localExtra = entry.localExtra ?? new Uint8Array(0);
    const centralExtra = entry.centralExtra ?? new Uint8Array(0);
    const flags = entry.flags ?? 0;
    const crc = crc32(raw);

    const local = new Uint8Array(30 + name.length + localExtra.length);
    const localView = new DataView(local.buffer);
    localView.setUint32(0, LOCAL_SIGNATURE, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(6, flags, true);
    localView.setUint16(8, method, true);
    localView.setUint32(14, crc, true);
    localView.setUint32(18, stored.length, true);
    localView.setUint32(22, raw.length, true);
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
    headerView.setUint32(24, entry.centralUncompressedSize ?? raw.length, true);
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
  opf?: string;
  /** Where the container says the package document is. */
  packagePath?: string;
  /** Where the package document actually is, when it should differ. */
  storedAt?: string;
  /** The container document, when it should not be the ordinary one. */
  container?: string | null;
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
