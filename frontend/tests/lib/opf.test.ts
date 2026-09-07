/**
 * @vitest-environment jsdom
 *
 * **jsdom rather than the suite's happy-dom, and this is not a preference.**
 * happy-dom 20's `DOMParser` silently falls back to HTML parsing when the XML
 * declaration is spelled with single quotes, so `documentElement.localName`
 * comes back as `html` and a perfectly ordinary package document reads as no
 * package document at all. **41 of 79 real EPUB files measured carry exactly
 * that declaration** in `container.xml`, and 40 carry it in the package document;
 * every Project Gutenberg one is among them. Real browsers parse it,
 * and so does jsdom, which is why this file opts into the slower environment
 * and `should parse a single quoted declaration` below is the arm that would
 * catch it coming back.
 */
/**
 * Tests for src/lib/opf.ts.
 *
 * Structured as pairs: each fact a book has is asserted in its EPUB 2 spelling
 * and in its EPUB 3 spelling, because the failure this module exists to avoid
 * is reading one and quietly not the other. Measured over 79 real files, 20
 * were EPUB 2.
 */

import { describe, expect, it } from "vitest";

import { readOpf } from "../../src/lib/opf";

function epub2(metadata: string): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata>${metadata}</metadata>
</package>`;
}

function epub3(metadata: string): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0" unique-identifier="pub-id">
  <metadata>${metadata}</metadata>
</package>`;
}

describe("what it refuses to read", () => {
  it("is null for a document that is not a package", () => {
    expect(readOpf("<container/>")).toBeNull();
  });

  it("is null for a package with no metadata", () => {
    expect(
      readOpf(`<package xmlns="http://www.idpf.org/2007/opf" version="3.0"/>`),
    ).toBeNull();
  });

  it("is null for something that is not XML at all", () => {
    expect(readOpf("<<<")).toBeNull();
  });

  it("is null for a document that declares its own entities", () => {
    // Expansion happens inside the engine before this module sees a node, so a
    // nested declaration is measured in what it expands to and the caller's cap
    // on the entry's bytes does not reach it. 0 of 79 real files carry one.
    const xml = `<?xml version="1.0"?>
<!DOCTYPE package [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">&b;</dc:title></metadata></package>`;
    expect(readOpf(xml)).toBeNull();
  });

  it("reads a document carrying a DOCTYPE that declares nothing", () => {
    // An external DOCTYPE is not the hazard: browsers do not fetch it. Refusing
    // it too would lose a record over a line that does nothing.
    const xml = `<?xml version="1.0"?>
<!DOCTYPE package>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><metadata><dc:title>Alice</dc:title></metadata></package>`;
    expect(readOpf(xml)?.title).toBe("Alice");
  });

  it("parses a single quoted xml declaration", () => {
    // Every Project Gutenberg EPUB writes this form. See the environment note
    // at the top of this file: it is the one thing happy-dom gets wrong here.
    const xml = `<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><metadata><dc:title>Alice</dc:title></metadata></package>`;
    expect(readOpf(xml)?.title).toBe("Alice");
  });
});

describe("the title", () => {
  it("is the only one, in EPUB 2", () => {
    const record = readOpf(epub2(`<dc:title>Dune</dc:title>`));
    expect(record?.title).toBe("Dune");
    expect(record?.subtitle).toBeNull();
  });

  it("is the one refined as main, in EPUB 3", () => {
    const record = readOpf(
      epub3(`
        <dc:title id="expanded">Dune: A Novel</dc:title>
        <meta refines="#expanded" property="title-type">expanded</meta>
        <dc:title id="main">Dune</dc:title>
        <meta refines="#main" property="title-type">main</meta>
        <dc:title id="sub">A Novel</dc:title>
        <meta refines="#sub" property="title-type">subtitle</meta>`),
    );
    // The expanded title comes first in the document and is the longest, and it
    // is neither the title nor the subtitle: it is both, already joined.
    expect(record?.title).toBe("Dune");
    expect(record?.subtitle).toBe("A Novel");
  });

  it("falls back to the first title when nothing is refined", () => {
    const record = readOpf(
      epub3(`<dc:title>Dune</dc:title><dc:title>Messiah</dc:title>`),
    );
    expect(record?.title).toBe("Dune");
  });
});

describe("the authors", () => {
  it("stay separate values", () => {
    const record = readOpf(
      epub3(
        `<dc:creator>Fred Leise</dc:creator><dc:creator>Kate Mertes</dc:creator>`,
      ),
    );
    expect(record?.authors).toEqual(["Fred Leise", "Kate Mertes"]);
  });

  it("keep an EPUB 2 creator with an author role and drop an illustrator", () => {
    const record = readOpf(
      epub2(`
        <dc:creator opf:role="aut" opf:file-as="Herbert, Frank">Frank Herbert</dc:creator>
        <dc:creator opf:role="ill">John Schoenherr</dc:creator>`),
    );
    expect(record?.authors).toEqual(["Frank Herbert"]);
  });

  it("keep an EPUB 3 creator with an author role and drop an editor", () => {
    const record = readOpf(
      epub3(`
        <dc:creator id="a">Frank Herbert</dc:creator>
        <meta refines="#a" property="role" scheme="marc:relators">aut</meta>
        <dc:creator id="b">Somebody Else</dc:creator>
        <meta refines="#b" property="role" scheme="marc:relators">edt</meta>`),
    );
    expect(record?.authors).toEqual(["Frank Herbert"]);
  });

  it("keep a creator that declares no role at all", () => {
    // Most files declare none. Dropping those would leave most books
    // authorless, which is the opposite of the rule's purpose.
    const record = readOpf(epub2(`<dc:creator>Lewis Carroll</dc:creator>`));
    expect(record?.authors).toEqual(["Lewis Carroll"]);
  });

  it("ignore a contributor", () => {
    const record = readOpf(
      epub3(
        `<dc:creator>Matt Garrish</dc:creator><dc:contributor>David Futato</dc:contributor>`,
      ),
    );
    expect(record?.authors).toEqual(["Matt Garrish"]);
  });
});

describe("the ISBN", () => {
  it("reads the EPUB 2 scheme attribute", () => {
    const record = readOpf(
      epub2(
        `<dc:identifier opf:scheme="ISBN">978-0-441-01359-3</dc:identifier>`,
      ),
    );
    expect(record?.isbn).toBe("9780441013593");
  });

  it("reads the EPUB 3 identifier-type refinement", () => {
    const record = readOpf(
      epub3(`
        <dc:identifier id="pub-id">9780441013593</dc:identifier>
        <meta refines="#pub-id" property="identifier-type" scheme="onix:codelist5">15</meta>`),
    );
    expect(record?.isbn).toBe("9780441013593");
  });

  it("reads a bare urn:isbn value, which is how real files carry it", () => {
    // Measured over 79 files: 4 carried an ISBN and none of them declared a
    // scheme that said so. This is the route that actually pays.
    const record = readOpf(
      epub3(
        `<dc:identifier id="pub-id">urn:isbn:9781449328030</dc:identifier>`,
      ),
    );
    expect(record?.isbn).toBe("9781449328030");
  });

  it("prefers the identifier a scheme points at over one that merely parses", () => {
    const record = readOpf(
      epub2(`
        <dc:identifier id="a">9780441013593</dc:identifier>
        <dc:identifier id="b" opf:scheme="ISBN">9781449328030</dc:identifier>`),
    );
    expect(record?.isbn).toBe("9781449328030");
  });

  it("is null for an identifier that is not an ISBN", () => {
    const record = readOpf(
      epub3(
        `<dc:identifier id="pub-id">urn:uuid:12789c52-a84d-47db-959a-a74d3d122225</dc:identifier>`,
      ),
    );
    expect(record?.isbn).toBeNull();
  });

  it("is null for a declared ISBN whose check digit does not hold", () => {
    // A label is not a checksum. Storing this would put a number in the one
    // column the importer matches on that names no book.
    const record = readOpf(
      epub2(`<dc:identifier opf:scheme="ISBN">9780441013594</dc:identifier>`),
    );
    expect(record?.isbn).toBeNull();
  });

  it("converts an ISBN-10 to the canonical thirteen", () => {
    const record = readOpf(
      epub2(`<dc:identifier opf:scheme="ISBN">0441013597</dc:identifier>`),
    );
    expect(record?.isbn).toBe("9780441013593");
  });

  it("reports every identifier the file carried, whatever it was", () => {
    const record = readOpf(
      epub2(`
        <dc:identifier opf:scheme="URI">http://www.gutenberg.org/11</dc:identifier>
        <dc:identifier opf:scheme="ISBN">9780441013593</dc:identifier>`),
    );
    expect(record?.identifiers).toEqual([
      { scheme: "URI", value: "http://www.gutenberg.org/11" },
      { scheme: "ISBN", value: "9780441013593" },
    ]);
  });
});

describe("the series", () => {
  it("reads the Calibre spelling, which is all EPUB 2 has", () => {
    const record = readOpf(
      epub2(`
        <meta name="calibre:series" content="Dune"/>
        <meta name="calibre:series_index" content="1"/>`),
    );
    expect([record?.seriesName, record?.seriesIndex]).toEqual(["Dune", 1]);
  });

  it("reads belongs-to-collection with its group position", () => {
    const record = readOpf(
      epub3(`
        <meta property="belongs-to-collection" id="c">Dune</meta>
        <meta refines="#c" property="collection-type">series</meta>
        <meta refines="#c" property="group-position">2</meta>`),
    );
    expect([record?.seriesName, record?.seriesIndex]).toEqual(["Dune", 2]);
  });

  it("takes a set as a series, because the two columns cannot tell them apart", () => {
    // The one file of 79 carrying a collection declares `set`. Refusing it
    // would drop the only collection metadata a multi volume work usually has.
    const record = readOpf(
      epub3(`
        <meta property="belongs-to-collection" id="c">Shigisan Engi</meta>
        <meta refines="#c" property="collection-type">set</meta>
        <meta refines="#c" property="group-position">1</meta>`),
    );
    expect([record?.seriesName, record?.seriesIndex]).toEqual([
      "Shigisan Engi",
      1,
    ]);
  });

  it("prefers a series over a set when a file declares both", () => {
    const record = readOpf(
      epub3(`
        <meta property="belongs-to-collection" id="boxed">The Boxed Set</meta>
        <meta refines="#boxed" property="collection-type">set</meta>
        <meta property="belongs-to-collection" id="run">Dune</meta>
        <meta refines="#run" property="collection-type">series</meta>`),
    );
    expect(record?.seriesName).toBe("Dune");
  });

  it("prefers the Calibre spelling when a file carries both", () => {
    // A file carrying both was written by Calibre, and Calibre's own value is
    // the one the library it came out of agrees with.
    const record = readOpf(
      epub3(`
        <meta name="calibre:series" content="Dune"/>
        <meta property="belongs-to-collection" id="c">Something Else</meta>`),
    );
    expect(record?.seriesName).toBe("Dune");
  });

  it("is null when the file names no collection", () => {
    expect(readOpf(epub3(`<dc:title>Dune</dc:title>`))?.seriesName).toBeNull();
  });
});

describe("the year", () => {
  it("takes the publication date rather than the conversion date", () => {
    // Every Project Gutenberg file carries both. Taking the first would file
    // the whole library under the year somebody ran the converter.
    const record = readOpf(
      epub2(`
        <dc:date opf:event="publication">1865-11-26</dc:date>
        <dc:date opf:event="conversion">2026-09-01T07:31:56Z</dc:date>`),
    );
    expect(record?.year).toBe(1865);
  });

  it("takes the publication date wherever it sits among the others", () => {
    const record = readOpf(
      epub2(`
        <dc:date opf:event="conversion">2026-09-01</dc:date>
        <dc:date opf:event="publication">1865-11-26</dc:date>`),
    );
    expect(record?.year).toBe(1865);
  });

  it("takes the one undated EPUB 3 date", () => {
    const record = readOpf(epub3(`<dc:date>2012-02-20</dc:date>`));
    expect(record?.year).toBe(2012);
  });

  it("ignores the EPUB 3 modification stamp, which is not a dc:date", () => {
    const record = readOpf(
      epub3(`<meta property="dcterms:modified">2012-10-24T15:30:00Z</meta>`),
    );
    expect(record?.year).toBeNull();
  });

  it("is null for a date with no year in it", () => {
    expect(readOpf(epub3(`<dc:date>undated</dc:date>`))?.year).toBeNull();
  });
});

describe("the rest of the record", () => {
  it("reads publisher, language and description", () => {
    const record = readOpf(
      epub3(`
        <dc:publisher>O'Reilly Media, Inc.</dc:publisher>
        <dc:language>en-US</dc:language>
        <dc:description>  A book about books.  </dc:description>`),
    );
    expect([record?.publisher, record?.language, record?.description]).toEqual([
      "O'Reilly Media, Inc.",
      "en-US",
      "A book about books.",
    ]);
  });

  it("reports the package version, which is how a reader knows which half it read", () => {
    expect(readOpf(epub2(`<dc:title>Alice</dc:title>`))?.version).toBe("2.0");
    expect(readOpf(epub3(`<dc:title>Alice</dc:title>`))?.version).toBe("3.0");
  });

  it("reads a Dublin Core element that inherited the wrong namespace", () => {
    // A bare <title> under a default OPF namespace is in the OPF namespace,
    // not the Dublin Core one. Refusing it would lose a whole record over a
    // declaration, and no OPF element inside <metadata> is called "title".
    const xml = `<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata><title>Alice</title></metadata></package>`;
    expect(readOpf(xml)?.title).toBe("Alice");
  });

  it("leaves an empty element absent rather than empty", () => {
    const record = readOpf(
      epub3(`<dc:title>Dune</dc:title><dc:publisher>   </dc:publisher>`),
    );
    expect(record?.publisher).toBeNull();
  });
});
