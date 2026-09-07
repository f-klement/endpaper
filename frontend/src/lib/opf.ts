/**
 * What an OPF package document says about a book.
 *
 * The metadata half of every EPUB, and the same Dublin Core that sits beside a
 * book in a Calibre library as `metadata.opf`. Pure: it takes the XML and
 * returns a record, and it knows nothing about zips, files or the API.
 *
 * **EPUB 2 and EPUB 3 say the same things differently and both are in the
 * wild.** Measured over 79 real files, 20 were EPUB 2.0 and 59 EPUB 3.0, so
 * reading one spelling is reading half a library. Each rule below names both.
 *
 * **What those 79 files are. Every figure anywhere in this repository that says
 * 79 files means this corpus**, which is stated here rather than listed at each
 * site, because a list of the sites that quote it is the thing that goes stale
 * when a tenth one is written. 20 Project Gutenberg books fetched in
 * both their EPUB 2 and EPUB 3 renderings, and 40 publisher produced files from
 * the IDPF `epub3-samples` set. **It is a proxy and not somebody's library**:
 * the corpus these rules were meant to be checked against was a real Calibre
 * library, which was not reachable from where this was written. So the counts
 * describe two producers, and a file from a retailer or a self publishing tool
 * is exactly what they do not describe. That is the caveat to carry into any
 * of them, and the reason the declared ISBN spellings are still read even
 * though nothing here used them.
 *
 * **`DOMParser` rather than a library.** It is native, it is already in every
 * browser this app runs in, and the alternative is an XML parser in the bundle
 * for two small documents. What it costs is that the parse happens inside the
 * engine, before any code here runs, so `declaresEntities` refuses the one
 * thing this module could not otherwise bound: see its docstring.
 *
 * Everything else about a hostile document is handled by reading it leniently.
 * A parse error yields a document whose root is `parsererror`, which is not a
 * package, and every read below is optional, so a document that is merely wrong
 * yields a thin record or `null` rather than a throw.
 *
 * **This reports what the file says.** Bounding the values against what the API
 * will accept is `bookBounds.ts`, and joining authors onto one line is
 * `ScanPage/types.ts`, because both are about the destination rather than about
 * the file.
 */

import { parseIsbn } from "./isbn";

const OPF_NAMESPACE = "http://www.idpf.org/2007/opf";

/** One `dc:identifier`, with whatever the file said it was. */
export interface OpfIdentifier {
  /** `opf:scheme` in EPUB 2, the `identifier-type` refinement in EPUB 3. */
  readonly scheme: string | null;
  readonly value: string;
}

/** What one package document asserts. Every field is absent rather than empty. */
export interface OpfRecord {
  /** The `package` element's own `version`. `"2.0"` or `"3.0"` in practice. */
  readonly version: string | null;
  readonly title: string | null;
  readonly subtitle: string | null;
  /**
   * Separate values, in document order.
   *
   * **Not one string.** A creator is one person and the file already separates
   * them, so joining here would throw away a fact the file supplied and make
   * every later reader guess it back.
   */
  readonly authors: readonly string[];
  readonly identifiers: readonly OpfIdentifier[];
  /** Canonical ISBN-13, from whichever of the three spellings carried one. */
  readonly isbn: string | null;
  readonly publisher: string | null;
  readonly year: number | null;
  readonly language: string | null;
  readonly description: string | null;
  readonly seriesName: string | null;
  readonly seriesIndex: number | null;
}

/** Children of `parent` whose local name matches, in document order. */
function childrenNamed(parent: Element, local: string): Element[] {
  // **A sibling walk, not a spread of `parent.children`.** That collection is
  // live, and indexing one is not required to be constant time: spreading it
  // costs whatever the host's implementation charges per index, which for a
  // list the file's own length decides is a cost the file chooses. Measured
  // 2026-09-07 under this file's jsdom: 4 times the creators took 14.8 times
  // the wall clock, which is the quadratic signature, and the walk below took
  // it to linear. A browser may charge less; the point is that this does not
  // depend on which.
  const found: Element[] = [];
  for (
    let child = parent.firstElementChild;
    child !== null;
    child = child.nextElementSibling
  ) {
    if (child.localName === local) found.push(child);
  }
  return found;
}

/**
 * Dublin Core children of `<metadata>`, by local name and **not by namespace**.
 *
 * Not laziness: files exist that declare no `dc:` prefix, and files exist whose
 * `<metadata>` sits under a default OPF namespace so that a bare `<title>`
 * inherits the wrong one. Requiring the namespace loses the whole record over a
 * declaration, and matching without it costs nothing here, because the element
 * names OPF itself puts inside `<metadata>` are `meta`, `link`, `dc-metadata`
 * and `x-metadata`, and not one of them collides with a Dublin Core name.
 *
 * The exclusion: an OEB 1.2 style `<dc-metadata>` wrapper puts the Dublin Core
 * elements one level deeper, where this does not look. Measured over 79 real
 * files: none used it.
 */
function dcChildren(metadata: Element, local: string): Element[] {
  return childrenNamed(metadata, local);
}

function text(element: Element | undefined): string | null {
  const value = element?.textContent?.trim();
  return value ? value : null;
}

/** An OPF attribute, whether the file prefixed it or not. */
function opfAttribute(element: Element, name: string): string | null {
  return (
    element.getAttributeNS(OPF_NAMESPACE, name) ?? element.getAttribute(name)
  );
}

/**
 * The EPUB 3 refinement index: which `<meta property>` values point at which id.
 *
 * EPUB 3 says everything about an element through a second element pointing
 * back at it, so a title's type, a creator's role and an identifier's scheme
 * are all one lookup away rather than an attribute. EPUB 2 says the same things
 * as attributes and reaches none of this.
 */
type Refinements = Map<string, Map<string, string>>;

function indexRefinements(metas: Element[]): Refinements {
  const index: Refinements = new Map();
  for (const meta of metas) {
    const refines = meta.getAttribute("refines");
    const property = meta.getAttribute("property");
    const value = meta.textContent?.trim();
    if (!refines || !property || !value) continue;
    if (!refines.startsWith("#")) continue;
    const target = refines.slice(1);
    const properties = index.get(target) ?? new Map<string, string>();
    // First one wins, so a document repeating a property does not flip on the
    // reader's iteration order.
    if (!properties.has(property)) properties.set(property, value);
    index.set(target, properties);
  }
  return index;
}

function refinement(
  index: Refinements,
  element: Element,
  property: string,
): string | null {
  const id = element.getAttribute("id");
  if (!id) return null;
  return index.get(id)?.get(property) ?? null;
}

/**
 * The title, and the subtitle when the file separates them.
 *
 * EPUB 3 may carry several `dc:title` elements distinguished by a `title-type`
 * refinement: `main`, `subtitle`, `expanded` and `short`. EPUB 2 has one title
 * and no notion of a subtitle, so a document with several is read in order.
 *
 * **`expanded` is not the title**, which is why the first element is the
 * fallback rather than the longest: an expanded title is the main title with
 * the subtitle already glued on, so preferring it would put the subtitle in
 * both fields.
 */
function readTitles(
  metadata: Element,
  index: Refinements,
): { title: string | null; subtitle: string | null } {
  const titles = dcChildren(metadata, "title");
  const byType = (wanted: string) =>
    titles.find(
      (element) => refinement(index, element, "title-type") === wanted,
    );

  const main = byType("main");
  return {
    title: text(main ?? titles[0]),
    subtitle: text(byType("subtitle")),
  };
}

/**
 * The authors, separately.
 *
 * A `dc:creator` may declare a role: `opf:role` as an attribute in EPUB 2, a
 * `role` refinement in EPUB 3, both carrying a MARC relator. **A declared role
 * that is not `aut` is excluded and an undeclared one is kept**: an illustrator
 * or an editor filed as the author is a wrong fact, while most files declare no
 * role at all and dropping those would leave most books authorless.
 */
function readAuthors(metadata: Element, index: Refinements): string[] {
  // **A `Set` and not an array scan, because the count is the file's choice.**
  // `authors.includes(name)` inside this loop is quadratic in a number a member
  // supplied file decides: a minimal `dc:creator` is 26 bytes and
  // `MAX_PACKAGE_BYTES` is 4 MiB, so 161,319 of them fit inside every bound this
  // reader declares. Measured 2026-09-07 on builder: 50,000 distinct names took
  // 57,863 ms of frozen main thread against 16 ms for this, and the shape is
  // quadratic, so the bound's own ceiling is minutes rather than seconds.
  //
  // Found by the MOBI reader's review, which had the identical defect and a
  // tighter bound. The insertion order is still the file's, which is what the
  // array was for; the `Set` only answers whether a name has been seen.
  const seen = new Set<string>();
  const authors: string[] = [];
  for (const creator of dcChildren(metadata, "creator")) {
    const role =
      opfAttribute(creator, "role") ?? refinement(index, creator, "role");
    if (role !== null && role.trim().toLowerCase() !== "aut") continue;
    const name = text(creator);
    if (name !== null && !seen.has(name)) {
      seen.add(name);
      authors.push(name);
    }
  }
  return authors;
}

/**
 * ONIX code list 5 values that mean an ISBN, which is how EPUB 3 spells the
 * scheme: `<meta refines="#id" property="identifier-type"
 * scheme="onix:codelist5">15</meta>`.
 */
const ONIX_ISBN_CODES = new Set(["02", "15"]);

function isIsbnScheme(scheme: string | null): boolean {
  if (scheme === null) return false;
  const value = scheme.trim().toLowerCase();
  return value === "isbn" || ONIX_ISBN_CODES.has(value);
}

function readIdentifiers(
  metadata: Element,
  index: Refinements,
): OpfIdentifier[] {
  return dcChildren(metadata, "identifier")
    .map((element) => ({
      scheme:
        opfAttribute(element, "scheme") ??
        refinement(index, element, "identifier-type"),
      value: text(element) ?? "",
    }))
    .filter((identifier) => identifier.value !== "");
}

/**
 * The ISBN, from whichever spelling carried one.
 *
 * Three routes, and **the third is the one that pays**. Measured over 79 real
 * files: 4 carried an ISBN, and the declared spellings carried none of them.
 * Zero used `opf:scheme="ISBN"`, the EPUB 2 spelling. One had an
 * `identifier-type` refinement, the EPUB 3 spelling, and it named the same
 * element that already spelled the value `urn:isbn:`. All 4 arrive as the
 * identifier's own text, 2 prefixed `urn:isbn:` and 2 bare. A reader
 * implementing only the two documented spellings would have found nothing.
 *
 * The declared ones are still tried first and still matter: they are what a
 * file carrying several identifiers uses to say which one is the ISBN, and
 * falling straight to the text would take whichever happened to parse.
 *
 * Everything goes through `parseIsbn`, so a value that is not a Bookland
 * number with a holding check digit is not an ISBN however it was labelled.
 */
function readIsbn(identifiers: readonly OpfIdentifier[]): string | null {
  const declared = identifiers.filter((one) => isIsbnScheme(one.scheme));
  for (const candidate of [...declared, ...identifiers]) {
    // `urn:isbn:` is the EPUB 3 spelling of the same fact. `parseIsbn` strips
    // punctuation but not letters, so the prefix has to come off first.
    const bare = candidate.value.replace(/^urn:isbn:/i, "");
    const isbn = parseIsbn(bare);
    if (isbn !== null) return isbn;
  }
  return null;
}

/**
 * The year the book was published.
 *
 * EPUB 2 carries several `dc:date` elements distinguished by `opf:event`, and
 * taking the first is how a reader ends up filing every Project Gutenberg book
 * under the year it was converted: those files carry a `publication` date and a
 * `conversion` date, in that order in the ones measured but in no order the
 * format guarantees. EPUB 3 allows one `dc:date`, the publication date, and
 * puts the last modification in a `dcterms:modified` meta where this cannot
 * reach it.
 */
function readYear(metadata: Element): number | null {
  const dates = dcChildren(metadata, "date");
  const withEvent = (wanted: string) =>
    dates.find(
      (element) => opfAttribute(element, "event")?.toLowerCase() === wanted,
    );

  const chosen =
    withEvent("publication") ??
    withEvent("original-publication") ??
    dates.find((element) => opfAttribute(element, "event") === null) ??
    dates[0];

  const match = /^(\d{4})/.exec(text(chosen) ?? "");
  return match ? Number(match[1]) : null;
}

/** A `<meta name="..." content="...">`, which is how EPUB 2 says everything. */
function namedMeta(metas: Element[], name: string): string | null {
  const found = metas.find((meta) => meta.getAttribute("name") === name);
  const content = found?.getAttribute("content")?.trim();
  return content ? content : null;
}

function toNumber(raw: string | null): number | null {
  if (raw === null) return null;
  const value = Number(raw.trim());
  return Number.isFinite(value) ? value : null;
}

/**
 * The series and the position in it.
 *
 * EPUB 2 has no series at all, so Calibre invented `<meta name="calibre:series">`
 * and everything that reads EPUB 2 reads that. EPUB 3 has
 * `belongs-to-collection`, refined by `collection-type` and `group-position`.
 *
 * **A `set` counts as a series here and a `series` outranks it.** The two
 * differ in whether the collection is open ended, which Endpaper's two columns
 * cannot express: both carry a name and a position, and refusing a set would
 * drop the only collection metadata a multi volume work usually has. Measured:
 * the one file of 79 carrying `belongs-to-collection` declares `set`.
 *
 * The Calibre spelling is read first, because a file carrying both was written
 * by Calibre and Calibre's own value is the one its library agrees with.
 */
function readSeries(
  metas: Element[],
  index: Refinements,
): { seriesName: string | null; seriesIndex: number | null } {
  const calibre = namedMeta(metas, "calibre:series");
  if (calibre !== null) {
    return {
      seriesName: calibre,
      seriesIndex: toNumber(namedMeta(metas, "calibre:series_index")),
    };
  }

  const collections = metas.filter(
    (meta) =>
      meta.getAttribute("property") === "belongs-to-collection" &&
      !meta.hasAttribute("refines"),
  );
  const typeOf = (meta: Element) =>
    refinement(index, meta, "collection-type")?.trim().toLowerCase() ?? null;
  const chosen =
    collections.find((meta) => typeOf(meta) === "series") ??
    collections.find((meta) => typeOf(meta) !== "set") ??
    collections[0];
  if (chosen === undefined) return { seriesName: null, seriesIndex: null };

  return {
    seriesName: text(chosen),
    seriesIndex: toNumber(refinement(index, chosen, "group-position")),
  };
}

/**
 * Whether a document declares its own entities.
 *
 * **The one attack this module cannot bound after the fact.** Expansion happens
 * inside the engine's parser, before `readOpf` sees a node, so a document
 * declaring nested entities is measured in what it expands to rather than in
 * what it weighs, and the caller's byte cap on the entry does not reach it.
 * Engines cap expansion themselves, but by how much is theirs to change and is
 * not something this reader can assert.
 *
 * Refusing costs nothing: an EPUB has no use for a DTD internal subset, and
 * **0 of 79 real files measured contain `<!ENTITY` in either document.**
 *
 * A plain substring rather than a regular expression over the prolog, which
 * would need to know where the prolog ends and would then be wrong about a
 * comment containing a tag. The exclusions, stated: an unescaped `<!ENTITY`
 * inside a `CDATA` section or inside a comment is refused as well. 0 of 79
 * files carry a `CDATA` section at all, and being told a file is not an EPUB is
 * a smaller harm than an unbounded parse.
 */
export function declaresEntities(xml: string): boolean {
  return xml.includes("<!ENTITY");
}

/**
 * Read a package document, or `null` when it is not one.
 *
 * `null` rather than a throw, because "this file's package document is not a
 * package document" is an outcome a caller has to report either way, and there
 * is nothing here a caller could do differently for each of the ways it can be
 * malformed.
 */
export function readOpf(xml: string): OpfRecord | null {
  if (declaresEntities(xml)) return null;
  const document = new DOMParser().parseFromString(xml, "application/xml");
  // Both halves are needed. A parse error yields a document whose root is
  // `parsererror`, and a well formed document that is not an OPF yields a root
  // that is simply something else.
  const root = document.documentElement;
  if (!root || root.localName !== "package") return null;

  const metadata = childrenNamed(root, "metadata")[0];
  if (metadata === undefined) return null;

  const metas = childrenNamed(metadata, "meta");
  const index = indexRefinements(metas);
  const identifiers = readIdentifiers(metadata, index);
  const { title, subtitle } = readTitles(metadata, index);
  const { seriesName, seriesIndex } = readSeries(metas, index);

  return {
    version: root.getAttribute("version"),
    title,
    subtitle,
    authors: readAuthors(metadata, index),
    identifiers,
    isbn: readIsbn(identifiers),
    publisher: text(dcChildren(metadata, "publisher")[0]),
    year: readYear(metadata),
    language: text(dcChildren(metadata, "language")[0]),
    description: text(dcChildren(metadata, "description")[0]),
    seriesName,
    seriesIndex,
  };
}
