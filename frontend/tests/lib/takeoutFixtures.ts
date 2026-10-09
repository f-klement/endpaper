/**
 * Building Google Takeout archives for the tests that read them.
 *
 * **Constructed from the shape, never captured.** The archive this was written
 * against is one member's own library, so nothing out of it is here: no book,
 * no sidecar, no passage from a bookmark. What is here is the structure that
 * archive was recorded as having on 2026-09-10, an export of 37,684,641 bytes
 * over 48 entries, written out again with invented titles, invented authors and
 * invented volume ids. `kobo.test.ts`'s fixtures were built the same way, from
 * a published driver rather than from a device.
 *
 * The template below is the sidecar's own element structure, which is what the
 * reader queries: `h1`, `div.author`, `div.meta-entry`, `div.annotation`.
 *
 * **Three strings here are the export's own and they are all labels**: `Volume
 * ID`, `by` and `Last modified on`. They are reproduced because the reader's
 * independence from them is the thing to test, since it reads the line under a
 * label without reading the label, and a fixture that invented them would test
 * nothing. Nothing else here is the export's: every title, author, volume id,
 * date and timezone below is made up.
 *
 * Support code, so it mirrors nothing. `zipFixtures.ts` builds the zips and the
 * EPUBs; this builds what Google puts around them.
 */

import fc from "fast-check";

import { MAX_CONTAINER_BYTES, MAX_PACKAGE_BYTES } from "../../src/lib/epub";
import {
  MAX_BOOK_BYTES,
  MAX_INFLATION_RATIO,
  MAX_SIDECAR_BYTES,
} from "../../src/lib/takeout";
import {
  around,
  buildEpub,
  buildZip,
  entrySpec,
  STORED,
  zeroesAt,
  type EntrySpec,
  type Payload,
} from "../zipFixtures";
import { type Ceilings } from "./meter";
import { sometimes, spelled, type Repeated, type Total } from "../property";

/** What Takeout named the folder in that export. Localised, so never matched. */
export const LIBRARY_FOLDER = "Takeout/Google Play Books";

/** A volume id of the shape all 24 measured had: twelve URL safe characters. */
export const A_VOLUME_ID = "aB3-dE6_gH9j";

export interface SidecarSpec {
  title?: string;
  /** The line under `by`. Empty is the case one book in that export had. */
  author?: string;
  /** The line under `Volume ID`. `null` writes no such block at all. */
  volumeId?: string | null;
  /**
   * The second metadata entry, where the export carried one.
   *
   * A reading state sentence in all 24 measured, which is one line and so
   * carries no value `labelled` can read. A test pinning what the volume id
   * rule refuses writes a label and a value here instead, which is the shape
   * the volume id entry itself has.
   */
  state?: string | null;
  /** One entry per annotation: the note the member wrote, often empty. */
  annotations?: string[];
  /** The store link's text, for a fixture testing what is not selected. */
  storeLink?: string;
}

/**
 * One sidecar, as Google writes it.
 *
 * The `<a class="meta-entry">` store link is here with the empty `href` the
 * export actually carries, and it is in every fixture **because the reader must
 * not select it**: `readSidecar` asks for `div.meta-entry`, so widening that
 * selector by one character takes the link's text as a metadata line. It is the
 * only record of that anywhere, so a test gives it a volume id shaped body and
 * asserts both halves of what would then go wrong.
 */
export function sidecar(spec: SidecarSpec = {}): string {
  const title = spec.title ?? "Dune";
  const author = spec.author ?? "Frank Herbert";
  const volumeId = spec.volumeId === undefined ? A_VOLUME_ID : spec.volumeId;
  const notes = (spec.annotations ?? [])
    .map(
      (note) =>
        `<div class="annotation"><div class="book-text">a passage</div>` +
        `<div class="annotation-text">${note}</div>` +
        // The label and the three line shape are Google's template, which the
        // reader has to not read. The timezone is written as a name because
        // that is the shape, and the name here is a neutral one: the export's
        // own is the owner's locale and does not belong in this tree.
        `<div class="last-modified-date">Last modified on\n` +
        `1 Jan 2020, 10:00:00\nCoordinated Universal Time</div></div>`,
    )
    .join("\n");
  return `<?xml version="1.0" ?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>${title}</title></head>
<body><div class="content"><div class="header"><h1>${title}</h1>
<div class="author">by
${author}

</div></div>
<div class="book-meta-information">
${volumeId === null ? "" : `<div class="meta-entry">Volume ID\n${volumeId}</div>`}
<a class="meta-entry" href="">${spec.storeLink ?? "View in the Google Play store"}</a>
${spec.state === null || spec.state === undefined ? "" : `<div class="meta-entry">${spec.state}</div>`}
</div>
${notes === "" ? "" : `<div class="annotations"><h2>Notes</h2>${notes}</div>`}
</div></body></html>`;
}

/** The sentence 2 of the 24 measured sidecars carried. */
export const FINISHED_SENTENCE = "You have finished this book.";

export interface BookSpec {
  /** The folder and file stem, which in that export are the title. */
  name?: string;
  /** The file's own extension. `.pdf` is what Google writes for an EPUB. */
  suffix?: string;
  sidecar?: SidecarSpec;
  /** The book file's bytes, for when it should not be an EPUB at all. */
  file?: Payload;
  /** The title inside the EPUB, which need not be the sidecar's. */
  epubTitle?: string;
  /** The EPUB's package document, when it should not be the ordinary one. */
  opf?: Payload;
  /** Further entries inside the EPUB, for a book whose text dwarfs it. */
  inside?: EntrySpec[];
  /** The mimetype entry's bytes, when they should not be the exact ones. */
  mimetype?: string | null;
  /** Store the mimetype deflated, which OCF forbids. */
  deflateMimetype?: boolean;
  /** Put another entry before the mimetype, which OCF also forbids. */
  entryBeforeMimetype?: boolean;
  /**
   * What the central directory claims the book file inflates to.
   *
   * A declared size is checked before a byte is read, so a ceiling measured in
   * tens of megabytes is testable without a fixture that large.
   */
  declaredSize?: number;
}

/** The two entries of one book, under the library folder. */
export async function bookEntries(spec: BookSpec = {}): Promise<EntrySpec[]> {
  const name = spec.name ?? "Dune";
  const stem = `${LIBRARY_FOLDER}/${name}/${name}`;
  const entries: EntrySpec[] = [
    { name: `${stem}.html`, data: sidecar(spec.sidecar) },
  ];
  const file = spec.file ?? (await epubBytes(spec));
  entries.push({
    name: `${stem}${spec.suffix ?? ".pdf"}`,
    data: file,
    centralUncompressedSize: spec.declaredSize,
  });
  return entries;
}

/** An EPUB, with whatever the spec asks be wrong with its signature. */
async function epubBytes(spec: BookSpec): Promise<Uint8Array<ArrayBuffer>> {
  const title = spec.epubTitle ?? spec.sidecar?.title ?? "Dune";
  const signed =
    spec.mimetype === undefined &&
    !spec.deflateMimetype &&
    !spec.entryBeforeMimetype;
  if (signed) {
    return buildEpub({
      opf: spec.opf ?? packageFor(title),
      extra: spec.inside,
    });
  }
  // `buildEpub` writes the signature the format asks for, so an archive that
  // should carry a wrong one is built entry by entry instead: the entry's
  // length and its position are both what the sniff asks about, and patching
  // bytes in place can change only one of them.
  return rebuild(spec, title);
}

async function rebuild(
  spec: BookSpec,
  title: string,
): Promise<Uint8Array<ArrayBuffer>> {
  const mimetype: EntrySpec[] =
    spec.mimetype === null
      ? []
      : [
          {
            name: "mimetype",
            data: spec.mimetype ?? "application/epub+zip",
            method: spec.deflateMimetype ? undefined : STORED,
          },
        ];
  const rest: EntrySpec[] = [
    {
      name: "META-INF/container.xml",
      data: `<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>`,
    },
    { name: "OEBPS/content.opf", data: packageFor(title) },
  ];
  return buildZip({
    entries: spec.entryBeforeMimetype
      ? [rest[0]!, ...mimetype, rest[1]!]
      : [...mimetype, ...rest],
  });
}

function packageFor(title: string): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0" unique-identifier="pub-id">
  <metadata><dc:identifier id="pub-id">urn:uuid:1</dc:identifier><dc:title>${title}</dc:title><dc:creator>Frank Herbert</dc:creator><dc:language>en</dc:language></metadata>
  <manifest/>
  <spine/>
</package>`;
}

/**
 * An entry that makes the archive itself large, stored so that it does.
 *
 * The inflation budget is a ratio of the archive's own size, so a per entry
 * ceiling is only the binding one in an archive big enough to allow it. This is
 * what puts a fixture on the right side of that.
 */
export function padding(size: number): EntrySpec {
  return { name: "Takeout/pad.bin", data: "y".repeat(size), method: STORED };
}

/**
 * A package document that inflates to about `size` bytes and deflates to few.
 *
 * Repeated subjects rather than one long string, so what comes out is a
 * document `readOpf` walks rather than one it refuses, and the bytes are inside
 * the EPUB's own zip where only the inner read pays for them.
 */
export function hugePackage(size: number): string {
  return spelled(hugePackageSpec(size));
}

/**
 * The same document as a spec, for an arbitrary: it prints as its parts, so a
 * counterexample carrying one is a literal a person can read.
 */
export function hugePackageSpec(size: number): Repeated {
  const unit = "<dc:subject>a subject</dc:subject>";
  return {
    before: `<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0" unique-identifier="pub-id">
  <metadata><dc:identifier id="pub-id">urn:uuid:1</dc:identifier><dc:title>Dune</dc:title><dc:language>en</dc:language>`,
    unit,
    times: Math.ceil(size / unit.length),
    after: `</metadata>
  <manifest/>
  <spine/>
</package>`,
  };
}

/** A whole Takeout archive: its books, then anything else it holds. */
export interface TakeoutSpec {
  readonly books: readonly BookSpec[];
  readonly extra: readonly EntrySpec[];
}

/** The archive's bytes. */
export async function buildTakeout(
  spec: TakeoutSpec,
): Promise<Uint8Array<ArrayBuffer>> {
  const entries: EntrySpec[] = [];
  for (const book of spec.books) entries.push(...(await bookEntries(book)));
  entries.push(...spec.extra);
  return buildZip({ entries });
}

/** A whole Takeout archive holding these books, as the `File` a picker hands over. */
export async function takeoutFile(
  books: BookSpec[] = [{}],
  extra: EntrySpec[] = [],
): Promise<File> {
  const data = await buildTakeout({ books, extra });
  // A name of the export's own shape and not its name. The real archive's
  // filename is the owner's, and this file's docstring says nothing out of it
  // is here.
  return new File([data], "takeout-20200101T000000Z-1-001.zip", {
    type: "application/zip",
  });
}

// --- arbitraries over the specs above ----------------------------------------

const sidecarSpec = fc.record({
  title: sometimes(fc.string({ maxLength: 12 })),
  author: sometimes(fc.constantFrom("", "Frank Herbert")),
  volumeId: sometimes(
    fc.constantFrom(null, A_VOLUME_ID, "aB3-dE6_gH9", "aB3-dE6_gH9jk"),
  ),
  state: sometimes(
    fc.constantFrom(null, FINISHED_SENTENCE, `Volume ID\n${A_VOLUME_ID}`),
  ),
  annotations: sometimes(
    fc.array(fc.string({ maxLength: 8 }), { maxLength: 3 }),
  ),
  storeLink: sometimes(
    fc.constantFrom("View in the Google Play store", A_VOLUME_ID),
  ),
} satisfies Total<SidecarSpec>);

const bookSpec = fc.record({
  name: sometimes(fc.constantFrom("Dune", "Dune (1)", "../Dune", "a/b")),
  suffix: sometimes(fc.constantFrom(".pdf", ".epub", ".html", "")),
  sidecar: sometimes(sidecarSpec),
  file: sometimes(
    fc.oneof(fc.constant<Payload>("not a book"), zeroesAt([MAX_BOOK_BYTES])),
  ),
  epubTitle: sometimes(fc.string({ maxLength: 8 })),
  opf: sometimes(
    fc.oneof(
      fc.constant<Payload>(hugePackageSpec(64 * 1024)),
      zeroesAt([MAX_PACKAGE_BYTES]),
    ),
  ),
  inside: sometimes(
    fc.array(
      entrySpec(
        fc.constantFrom("OEBPS/content.opf", "META-INF/container.xml", "x"),
        zeroesAt([MAX_CONTAINER_BYTES, MAX_PACKAGE_BYTES]),
        [MAX_CONTAINER_BYTES, MAX_PACKAGE_BYTES],
      ),
      { maxLength: 2 },
    ),
  ),
  mimetype: sometimes(
    fc.constantFrom(null, "application/epub+zip\r\n", "application/epub+zi"),
  ),
  deflateMimetype: sometimes(fc.boolean()),
  entryBeforeMimetype: sometimes(fc.boolean()),
  declaredSize: sometimes(fc.constantFrom(0, 1, ...around(MAX_BOOK_BYTES))),
} satisfies Total<BookSpec>);

/**
 * Several books whose package documents each inflate to just under the
 * EPUB's own ceiling, declared honestly.
 *
 * **The budget's own shape**, composed because independent draws rarely give
 * several books the same expensive document: each one passes every per file
 * gate, so what stops the second is only the archive's total, and that total
 * is what the property is asked to hold.
 */
const budgetSpend: fc.Arbitrary<TakeoutSpec> = fc.record({
  books: fc.integer({ min: 2, max: 4 }).map((count) =>
    Array.from({ length: count }, (_, index) => ({
      name: `Book ${index}`,
      opf: { zeroes: MAX_PACKAGE_BYTES - 1 },
    })),
  ),
  extra: fc.constant([]),
} satisfies Total<TakeoutSpec>);

/**
 * One book whose file inflates past what the directory declared for it, at
 * the book's own ceiling.
 *
 * **Composed so a run from any seed draws it**: as two overrides drawn apart,
 * a file of zeroes and a declared size under it, it landed on a few runs in a
 * hundred, measured.
 */
const lyingBook: fc.Arbitrary<TakeoutSpec> = fc.record({
  books: fc
    .record({
      zeroes: fc.constantFrom(...around(MAX_BOOK_BYTES)),
      declared: fc.constantFrom(0, 1, MAX_BOOK_BYTES - 1),
    })
    .map(({ zeroes, declared }) => [
      {
        name: "Book 0",
        file: { zeroes },
        declaredSize: Math.min(declared, zeroes - 1),
      },
    ]),
  extra: fc.constant([]),
} satisfies Total<TakeoutSpec>);

/** A Takeout archive: any books drawn, or the budget's own shape. */
export function takeoutSpec(): fc.Arbitrary<TakeoutSpec> {
  const any = fc.record({
    books: fc.array(bookSpec, { maxLength: 3 }),
    extra: fc.array(
      entrySpec(
        fc.constantFrom("Takeout/pad.bin", "Takeout/x.html", "x.pdf"),
        fc.oneof(fc.string({ maxLength: 16 }), zeroesAt([MAX_SIDECAR_BYTES])),
        [MAX_SIDECAR_BYTES],
      ),
      { maxLength: 2 },
    ),
  } satisfies Total<TakeoutSpec>);
  return fc.oneof(
    { arbitrary: any, weight: 4 },
    { arbitrary: budgetSpend, weight: 1 },
    { arbitrary: lyingBook, weight: 1 },
  );
}

/**
 * What reading a Takeout archive of `size` bytes may spend, wherever it is
 * read: by its own reader, and by the store opener that hands it over.
 *
 * **The budget is the archive's size times `MAX_INFLATION_RATIO`, plus one
 * book's worth of `readEpub`**: the inner reads are charged after they happen
 * and bounded by the EPUB's own ceilings rather than by what is left, so the
 * overspend is one container and one package document, once. `takeout.ts`
 * states that overspend at the ratio's own docstring, and this is that
 * sentence as a ceiling. And no XML parse is handed a declaration, the rule
 * the EPUBs inside are read under.
 */
export function takeoutCeilings(size: number): Ceilings {
  return {
    perInflate: MAX_BOOK_BYTES,
    inflated:
      size * MAX_INFLATION_RATIO + MAX_CONTAINER_BYTES + MAX_PACKAGE_BYTES,
    refusesEntities: true,
  };
}
