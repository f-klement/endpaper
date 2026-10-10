/**
 * @vitest-environment jsdom
 *
 * happy-dom 20's `DOMParser` falls back to HTML parsing when the XML is not
 * well formed, which is exactly the case the XMP packet's entity guard turns
 * on. `opf.test.ts` states the same reason and pays the same cost.
 */
/**
 * Tests for src/lib/pdf.ts.
 *
 * **Most of this file is a file doing something no writer does**, which is the
 * balance the format deserves: reading six fields out of a well formed document
 * is the small half, and a PDF is an object graph a member supplied, so the
 * risk is a cycle, a nest, a length that lies and a stream that inflates
 * forever. A crash here eats somebody's import, so "does not throw" is
 * asserted over a sweep rather than only where somebody thought to look.
 */

import { describe, expect, it, vi } from "vitest";

import * as pdf from "../../src/lib/pdf";
import {
  MAX_BUDGET_BYTES,
  MAX_INFLATED_BYTES,
  readPdf,
  type PdfReading,
} from "../../src/lib/pdf";
import { holds, PROFILE, PROPERTY, witness } from "../property";
import {
  buildPdf,
  classicPdf,
  concat,
  deflate,
  isOverBudget,
  latin,
  object,
  pdfSpec,
  predict,
  streamObject,
  streamPdf,
  text,
  xmpPacket,
  type PdfSpec,
} from "../pdfFixtures";
import {
  expectNamedOutcome,
  hostile,
  overrunBreach,
  type Door,
  type Hostile,
} from "./readerContract";
import { withoutDecompressionStream } from "./withoutDecompression";
// One module's text from the armed corpus, which refuses a name the tree does
// not hold. The glob this replaced took the first value of its own result and
// cast it, so a rename handed the assertion below `undefined`.
import { sourceText } from "../sourceModules";

/**
 * How long a sweep of malformed files may take.
 *
 * **This catches a sweep that got slow and it cannot catch one that never
 * finishes**, which is stated because the defect it was written after was the
 * second kind: a cross reference table whose subsection header was a delimiter
 * spun `classicTable` synchronously and forever, and an assertion after a
 * synchronous loop never runs, nor can `--testTimeout` interrupt one. The
 * suite hung on this file for 600 seconds rather than failing it, twice. What
 * refuses that is the cursor progress check inside `classicTable` itself, and
 * this ceiling is the weaker guard beside it.
 *
 * Measured on `builder`: the two sweeps below take 39 ms and 60 ms.
 */
const SWEEP_CEILING_MS = 30_000;

/**
 * How many reads of the file an object stream that refers to itself may cost.
 *
 * **The only thing that observes this guard, and it is counted rather than
 * timed.** Registering the object stream in the cache before its bytes are read
 * rather than after changes no answer at all: the file is `damaged` either way.
 * What it changes is the cost, because `/Length` resolving back into the same
 * stream re-enters it until the total fetch budget runs out.
 *
 * A wall clock ceiling was written here first and was wrong: it was tuned at
 * 3 ms against 3,738 ms on the machine this repository is developed on, and the
 * suite runs on a worker node roughly three times faster, which puts the defect
 * under the ceiling on the machine that would have to catch it. **A count of
 * `Blob.prototype.slice` calls is the same observation with no machine in it**,
 * and it is four orders of magnitude sharper. Measured on the fixture below:
 * **5 reads with the cache registered early**, and with it put back where it
 * was, **92,183 by one route and 98,690 by another**, the two mutations being
 * written independently by the implementer and the security seat. A band rather
 * than a point, which is what two instruments give. 64 is 12.8 times the
 * healthy run and at least 1,440 times below the defect.
 *
 * An ordinary object stream costs the same 5 reads, so the ceiling is not
 * measuring this fixture's shape.
 *
 * The spy is on the prototype and not on an instance, which is what
 * `tests/setup.ts` says about `Storage` for the same reason: a restore reaches
 * the prototype and does not reach an instance.
 */
const OUROBOROS_READ_CEILING = 64;

async function read(bytes: Uint8Array<ArrayBuffer>) {
  return readPdf(new Blob([bytes]));
}

/**
 * Where a built file says its cross reference begins.
 *
 * Through `text`, which is a byte for byte inverse, rather than a decoder: the
 * fixture module says what a decoder does to the high bytes.
 */
function startxrefOf(bytes: Uint8Array): number {
  return Number(/startxref\s+(\d+)/.exec(text(bytes.subarray(-64)))![1]);
}

/** A type 1 row's first two fields under `/W [1 4 ...]`, high byte first. */
function typeAndOffset(offset: number): number[] {
  return [
    1,
    (offset >>> 24) & 0xff,
    (offset >>> 16) & 0xff,
    (offset >>> 8) & 0xff,
    offset & 0xff,
  ];
}

/** The failure or the title, so one assertion covers both arms. */
function verdict(reading: Awaited<ReturnType<typeof readPdf>>): string {
  return reading.ok ? `read: ${reading.metadata.title}` : reading.failure;
}

/** A document whose information dictionary is object 1 and catalogue object 2. */
function withInfo(info: string, extra: readonly string[] = []) {
  return classicPdf(
    [
      object(1, `<< ${info} >>`),
      object(2, "<< /Type /Catalog >>"),
      ...extra.map((body, index) => object(3 + index, body)),
    ],
    "/Info 1 0 R /Root 2 0 R",
  );
}

describe("reading a PDF that carries what a publisher wrote", () => {
  it("yields the information dictionary's fields", async () => {
    const reading = await read(
      withInfo(
        "/Title (Designing Data-Intensive Applications) /Author (Martin Kleppmann) /Subject (A book about data)",
      ),
    );

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.title).toBe(
      "Designing Data-Intensive Applications",
    );
    expect(reading.metadata.authors).toEqual(["Martin Kleppmann"]);
    expect(reading.metadata.description).toBe("A book about data");
  });

  it("says which fields the format has no place for", async () => {
    // The exclusion the formats epic asks each reader to state. These are
    // absent because a PDF has nowhere to put them, not because they are
    // unread, so a change making one of them non null is a change of design.
    const reading = await read(withInfo("/Title (Tidy Data)"));

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.subtitle).toBeNull();
    expect(reading.metadata.seriesName).toBeNull();
    expect(reading.metadata.seriesIndex).toBeNull();
  });
});

describe("the text a string carries", () => {
  it("reads a UTF-16 string by its byte order mark", async () => {
    const bytes = concat("<< /Title <FEFF00440061007300200042007500630068> >>");
    const reading = await read(
      classicPdf(
        [object(1, bytes), object(2, "<< /Type /Catalog >>")],
        "/Info 1 0 R /Root 2 0 R",
      ),
    );

    expect(verdict(reading)).toBe("read: Das Buch");
  });

  it("falls back for a runtime that has no utf-16be", async () => {
    // Why the construction sits inside `decodeText` is `decodeText`'s own
    // docstring. What this asserts is the half of it that is observable here:
    // the string falls back rather than the read failing.
    //
    // The stand-in refuses that one label and passes everything else to the
    // real constructor, so nothing else in the process is changed while it is
    // installed. `tests/setup.ts` takes it off again after the test.
    const real = globalThis.TextDecoder;
    class WithoutUtf16Be extends real {
      constructor(label?: string, options?: TextDecoderOptions) {
        if (label?.toLowerCase() === "utf-16be") {
          throw new RangeError(`unsupported label: ${label}`);
        }
        super(label, options);
      }
    }
    vi.stubGlobal("TextDecoder", WithoutUtf16Be);

    const bytes = concat("<< /Title <FEFF00440061007300200042007500630068> >>");
    const reading = await read(
      classicPdf(
        [object(1, bytes), object(2, "<< /Type /Catalog >>")],
        "/Info 1 0 R /Root 2 0 R",
      ),
    );

    // The bytes fall to PDFDocEncoding, which is what they would have been read
    // as with no byte order mark: the mark itself becomes two Latin-1
    // characters and each NUL becomes the space that `clean` collapses. Stated
    // in full rather than as "not the title", because a fallback that produced
    // nothing at all would also satisfy that.
    expect(verdict(reading)).toBe("read: þÿ D a s B u c h");
  });

  it("reads the 32 bytes where PDFDocEncoding is not Latin-1", async () => {
    // Measured in the household's 123: reading these as Latin-1 was wrong in 3
    // of the 71 titles, which is the whole reason the table exists. \x92 is a
    // trademark sign and \x85 an en dash; Latin-1 makes both control
    // characters, which `clean` would then remove without trace.
    const reading = await read(
      withInfo("/Title (VBA Developer's Handbook\x92 Second\x85Edition)"),
    );

    // The expectation is written in escapes, which is what it is about: this
    // asserts that byte 0x92 becomes U+2122 and byte 0x85 becomes U+2013, and a
    // literal in the source says that less exactly. It also keeps this file
    // clear of a dash, which `tests/houseRules.test.ts` reads `src/` for and
    // the writing rule asks of everything.
    expect(verdict(reading)).toBe(
      "read: VBA Developer's Handbook\u2122 Second\u2013Edition",
    );
  });

  it("reads a string that escapes its own parentheses", async () => {
    const reading = await read(withInfo("/Title (Think Bayes \\(2nd\\))"));

    expect(verdict(reading)).toBe("read: Think Bayes (2nd)");
  });

  it("reads an octal escape", async () => {
    const reading = await read(withInfo("/Title (Caf\\351)"));

    expect(verdict(reading)).toBe("read: Café");
  });

  // Each escape's answer is told apart from the backslash being dropped: a
  // control character comes out of `clean` as a space, and a continuation as
  // nothing at all.
  it.each([
    ["the five single letter escapes", "A\\nB\\rC\\tD\\bE\\fF", "A B C D E F"],
    ["a continuation before CR LF", "Line\\\r\nBreak", "LineBreak"],
    ["a continuation before a lone CR", "Line\\\rBreak", "LineBreak"],
    ["a continuation before a lone LF", "Line\\\nBreak", "LineBreak"],
    ["an octal escape cut short by an 8", "A\\618", "A18"],
  ])("reads %s", async (_, title, expected) => {
    const reading = await read(withInfo(`/Title (${title})`));

    expect(verdict(reading)).toBe(`read: ${expected}`);
  });
});

describe("a title the file carries but this reader will not use", () => {
  it("answers null for a title that is the empty string", async () => {
    // Not a failure. The scan page reads a null title as "use the filename",
    // which for this format is the ordinary path rather than the exception.
    const reading = await read(withInfo("/Title () /Author (Anon)"));

    expect(verdict(reading)).toBe("read: null");
  });

  it("refuses a title that names a file", async () => {
    for (const junk of [
      "453777_1_En_Print.indd",
      "0534243126.djvu",
      "Algebra_Cheat_Sheet.doc",
      "Sammelmappe1.pdf",
    ]) {
      expect(verdict(await read(withInfo(`/Title (${junk})`)))).toBe(
        "read: null",
      );
    }
  });

  it("keeps a filename whose stem is one word, which it cannot tell apart", async () => {
    // The exclusion stated rather than discovered: the signal separating these
    // from a title is the file's own name, which `readPdf` takes a `Blob` and
    // never sees. Pinned so the next person changing the rule is told what it
    // accepts, and so a rule that started refusing `Node.js` to catch these
    // would fail here as well as there.
    for (const kept of ["thesis.pdf", "manuscript.docx", "untitled.indd"]) {
      expect(verdict(await read(withInfo(`/Title (${kept})`)))).toBe(
        `read: ${kept}`,
      );
    }
  });

  it("keeps a title that is a name with a dot in it", async () => {
    // The clause that separates these from the four above is that the part
    // before the dot is one run of letters. Dropping it would throw away titles
    // this very library is full of.
    for (const real of ["Node.js", "ASP.NET", "Vue.js"]) {
      expect(verdict(await read(withInfo(`/Title (${real})`)))).toBe(
        `read: ${real}`,
      );
    }
  });

  it("refuses an author with no letter in it", async () => {
    const reading = await read(withInfo("/Title (A Book) /Author (0007855)"));

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.authors).toEqual([]);
  });

  it("keeps the scanner operator, which it cannot tell from an author", async () => {
    // Stated as a test rather than only in prose, because it is the ticket's
    // own point: nothing in the file says `zywei` is not the writer, and a
    // reader that guessed would throw away real authors to catch this one.
    const reading = await read(withInfo("/Title (A Book) /Author (zywei)"));

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.authors).toEqual(["zywei"]);
  });

  it("never splits one author field into several", async () => {
    // All three separators appear in the corpus and one of them is also how a
    // single name is written surname first, so splitting would file
    // `Bruce, Peter` as two people.
    const reading = await read(
      withInfo("/Title (A Book) /Author (Peter Bruce;Andrew Bruce)"),
    );

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.authors).toEqual(["Peter Bruce;Andrew Bruce"]);
  });
});

describe("the XMP packet", () => {
  async function withXmp(
    packet: string,
    info = "/Title (Big Data) /Author (Saswat Sarangi)",
  ) {
    return read(
      classicPdf(
        [
          object(1, `<< ${info} >>`),
          object(2, "<< /Type /Catalog /Metadata 3 0 R >>"),
          streamObject(3, "<< /Type /Metadata /Subtype /XML >>", latin(packet)),
        ],
        "/Info 1 0 R /Root 2 0 R",
      ),
    );
  }

  it("supplies the four fields the information dictionary has no place for", async () => {
    const reading = await withXmp(
      xmpPacket({
        publisher: "Taylor & Francis",
        language: "en",
        date: "2019-04-01",
        identifier: "9781000650792",
      }),
    );

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.publisher).toBe("Taylor & Francis");
    expect(reading.metadata.language).toBe("en");
    expect(reading.metadata.year).toBe(2019);
    expect(reading.metadata.isbn).toBe("9781000650792");
  });

  it("refuses a year no book could have been published in", async () => {
    // The window is `year.plausibleYear`'s, shared with every other
    // reader that takes a year out of a file, and this is the arm that notices
    // this one letting go of it: a mutation dropping the call went unreported
    // before it existed. The value is Calibre's undefined date, which is what
    // bought the window; 101 is inside `NUMBER_RANGES.year`, so nothing
    // downstream reports it.
    const reading = await withXmp(xmpPacket({ date: "0101-01-01T00:00:00Z" }));

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.year).toBeNull();
  });

  it("labels an identifier that is not an ISBN with no scheme", async () => {
    // 2 of the 3 identifiers in the corpus are DOIs. Calling one an ISBN
    // because it arrived in the identifier field is worse than leaving it
    // unlabelled, which is why `parseIsbn` decides and not the field's name.
    const reading = await withXmp(
      xmpPacket({ identifier: "doi:10.1007/978-3-030-45574-3" }),
    );

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.isbn).toBeNull();
    expect(reading.metadata.identifiers).toEqual([
      { scheme: null, value: "doi:10.1007/978-3-030-45574-3" },
    ]);
  });

  it("does not override a title the information dictionary carried", async () => {
    // Measured over the 123: the packet adds 0 titles the dictionary does not
    // already have, so preferring it would only ever swap one for another.
    const reading = await withXmp(xmpPacket({ title: "A Different Title" }));

    expect(verdict(reading)).toBe("read: Big Data");
  });

  it("supplies a title when the information dictionary has none", async () => {
    const reading = await withXmp(xmpPacket({ title: "Fluent React" }), "");

    expect(verdict(reading)).toBe("read: Fluent React");
  });

  it("expands no entity, because the document it parses has no prolog", async () => {
    // The guard is that the packet is cut down to its root element, so there
    // is nowhere a declaration could sit. Deleting the cut makes this test
    // report the expanded value or an XXE, depending on the parser.
    //
    // `raw` because the fixture escapes by default, as a producer does, and
    // that escaping once made this test pass on a literal `&secret;` with the
    // guard never reached. The reference has to survive into the packet for
    // there to be anything for the guard to refuse.
    const reading = await withXmp(
      xmpPacket(
        { publisher: "&secret;" },
        {
          raw: true,
          doctype:
            '<!DOCTYPE rdf:RDF [ <!ENTITY secret "leaked from the prolog"> ]>',
        },
      ),
    );

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.publisher).toBeNull();
  });

  it("keeps every name a creator sequence holds", async () => {
    // One file in the corpus names five. The dictionary's `/Author` is left out
    // here, because it wins when it is there and would hide this.
    const reading = await withXmp(
      xmpPacket({ creator: ["Michael R. Berthold", "Christian Borgelt"] }),
      "/Title (Guide to Intelligent Data Science)",
    );

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.authors).toEqual([
      "Michael R. Berthold",
      "Christian Borgelt",
    ]);
  });

  it("reads a packet whose RDF prefix is not rdf", async () => {
    const reading = await withXmp(
      xmpPacket({ language: "de" }, { prefix: "r" }),
    );

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.language).toBe("de");
  });

  it("reads a value written straight into its element rather than in a list", async () => {
    // The specification wraps every one of these in a list, and a producer
    // that does not is still telling the truth about the book.
    const packet =
      `<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n` +
      `<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">` +
      `<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">` +
      `<dc:publisher>Chilton</dc:publisher>` +
      `</rdf:Description></rdf:RDF>\n<?xpacket end="w"?>`;

    const reading = await withXmp(packet);

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.publisher).toBe("Chilton");
  });
});

describe("an array longer than anything real", () => {
  /**
   * An information dictionary carrying an array of `count` numbers, packed in
   * an object stream, because a plain object is read through a window far
   * shorter than the bound. A classic trailer, read through the grown cross
   * reference window, reaches it too.
   */
  async function withArrayOf(count: number) {
    return read(
      await streamPdf(
        [
          object(1, `<< /Title (Wide) /Keywords [${"0 ".repeat(count)}] >>`),
          object(2, "<< /Type /Catalog >>"),
        ],
        "/Info 1 0 R /Root 2 0 R",
        { packed: [[1]] },
      ),
    );
  }

  it("is read at exactly half a million members, so the refusal below is the array's", async () => {
    // At the bound rather than well under it, so a lowered bound reds here.
    expect(verdict(await withArrayOf(500_000))).toBe("read: Wide");
  });

  it("is refused past half a million members, taking its object with it", async () => {
    expect(verdict(await withArrayOf(500_001))).toBe("read: null");
  });
});

describe("a cross reference this reader has to follow", () => {
  const objects = [
    object(1, "<< /Title (Learning Spark) /Author (Jules S. Damji) >>"),
    object(2, "<< /Type /Catalog >>"),
  ];
  const trailer = "/Info 1 0 R /Root 2 0 R";

  it("reads a cross reference stream under a PNG predictor", async () => {
    // 46 of the household's 123 declare one and all 46 declare /Predictor 12.
    // Without the row filter the offsets come out as differences, which reads
    // as a file carrying no metadata rather than as an error.
    expect(verdict(await read(await streamPdf(objects, trailer)))).toBe(
      "read: Learning Spark",
    );
  });

  it("reads a cross reference stream with no predictor", async () => {
    expect(
      verdict(
        await read(await streamPdf(objects, trailer, { predictor: false })),
      ),
    ).toBe("read: Learning Spark");
  });

  it("reads an information dictionary inside a compressed object stream", async () => {
    // The measurement that decided this reader's shape: 39 of the 123 keep the
    // information dictionary there, and a byte scanning reader found 41 titles
    // against this one's 71.
    expect(
      verdict(await read(await streamPdf(objects, trailer, { packed: [[1]] }))),
    ).toBe("read: Learning Spark");
  });

  it("follows a hybrid file's /XRefStm before its /Prev", async () => {
    // A hybrid table deliberately omits the objects that live in object
    // streams, so a reader skipping /XRefStm finds the catalogue and no title.
    // The catalogue is object 4 rather than 2 because the inner file's own
    // object stream is 2: a collision would let the classic table answer for it
    // first and the test would pass for the wrong reason.
    const inner = await streamPdf(
      [object(1, "<< /Title (Kafka: The Definitive Guide) >>")],
      "",
      { packed: [[1]] },
    );
    const innerXref = startxrefOf(inner);
    const outer = classicPdf(
      [object(4, "<< /Type /Catalog >>")],
      `/Info 1 0 R /Root 4 0 R /XRefStm ${innerXref}`,
      { prefix: inner },
    );

    expect(verdict(await read(outer))).toBe(
      "read: Kafka: The Definitive Guide",
    );
  });

  it("lets the newest section win over an older one it points back to", async () => {
    const original = classicPdf(
      [
        object(1, "<< /Title (First Edition) >>"),
        object(2, "<< /Type /Catalog >>"),
      ],
      "/Info 1 0 R /Root 2 0 R",
    );
    const updated = classicPdf(
      [object(1, "<< /Title (Second Edition) >>")],
      `/Info 1 0 R /Root 2 0 R /Prev ${startxrefOf(original)}`,
      { prefix: original },
    );

    expect(verdict(await read(updated))).toBe("read: Second Edition");
  });
});

/**
 * **Why these are examples and not more draws of the property below.** The
 * property asserts that a file is read or refused by name within budget, so a
 * reader that decodes one of these shapes wrongly and still names an outcome is
 * green there whether or not a draw reaches it. Each arm below asserts the
 * answer instead.
 *
 * Reach is the smaller half, and it is rarity rather than impossibility. Every
 * file `buildPdf` makes writes its cross reference stream in one shape: `/W
 * [1 4 2]`, no `/Index`, one `/Filter` named directly, `/DecodeParms` a
 * dictionary, and every row under filter 0. A single byte patch does reach a
 * few of these arms, a stream keyword's newline turned to a space or a
 * predictor digit changed, but as a draw among many and never with its answer
 * checked.
 */
function rewritten(
  bytes: Uint8Array,
  from: string | RegExp,
  to: string,
): Uint8Array<ArrayBuffer> {
  const before = text(bytes);
  const after = before.replace(from, to);
  // A rewrite that matched nothing would test the unrewritten file and pass
  // for the wrong reason.
  if (after === before) throw new Error(`nothing matched ${String(from)}`);
  return latin(after);
}

/** A document with a metadata stream, as object 3, written from `stream`. */
function withMetadataObject(body: Uint8Array | string) {
  return classicPdf(
    [
      object(1, "<< /Title (Packet) >>"),
      object(2, "<< /Type /Catalog /Metadata 3 0 R >>"),
      object(3, body),
    ],
    "/Info 1 0 R /Root 2 0 R",
  );
}

/** The language a reading found, or its failure. */
function language(reading: Awaited<ReturnType<typeof readPdf>>): string {
  return reading.ok
    ? `read: ${String(reading.metadata.language)}`
    : reading.failure;
}

describe("a cross reference stream under each PNG row filter", () => {
  const objects = [
    object(1, "<< /Title (Learning Spark) >>"),
    object(2, "<< /Type /Catalog >>"),
  ];
  const trailer = "/Info 1 0 R /Root 2 0 R";

  it.each([
    { filter: 1, name: "Sub" },
    { filter: 2, name: "Up" },
    { filter: 3, name: "Average" },
    { filter: 4, name: "Paeth" },
  ])("undoes the $name filter", async ({ filter }) => {
    const bytes = await streamPdf(objects, trailer, {
      rowFilter: () => filter,
    });

    expect(verdict(await read(bytes))).toBe("read: Learning Spark");
  });

  it("undoes a different filter on each row, as an encoder choosing per row writes", async () => {
    const bytes = await streamPdf(objects, trailer, {
      rowFilter: (row) => row % 5,
    });

    expect(verdict(await read(bytes))).toBe("read: Learning Spark");
  });

  it("refuses a row filter PNG does not define", async () => {
    const bytes = await streamPdf(objects, trailer, {
      rowFilter: (row) => (row === 1 ? 5 : 0),
    });

    expect(verdict(await read(bytes))).toBe("damaged");
  });
});

describe("a cross reference stream's own layout", () => {
  const objects = [
    object(1, "<< /Title (Layout) >>"),
    object(2, "<< /Type /Catalog >>"),
  ];
  const trailer = "/Info 1 0 R /Root 2 0 R";
  const plain = () => streamPdf(objects, trailer, { predictor: false });

  it.each(["7", "[1 -4 2]", "[1 (4) 2]", "[0 0 0]"])(
    "reads no entry through a /W of %s",
    async (widths) => {
      // Not a guess at what was meant: a width the format does not allow, or
      // a record of no bytes, describes no row, so the section contributes no
      // entry and the file has no cross reference this reader can use. For
      // `[0 0 0]` that is the answer only: the zero record check it reaches is
      // a bound on work, which no verdict sees.
      const bytes = rewritten(await plain(), "/W [1 4 2]", `/W ${widths}`);

      expect(verdict(await read(bytes))).toBe("not-a-pdf");
    },
  );

  // **The rows are written at the shape the /W claims**, so a reader that
  // took the claim would read them and find the title. Rewriting a /W over
  // rows of the default shape cannot tell the guard from its absence: an
  // unguarded reader misreads those rows and finds nothing either.
  it("refuses a width past eight bytes, over rows written that wide", async () => {
    const bytes = await streamPdf(objects, trailer, {
      predictor: false,
      widths: [1, 9, 2],
    });

    expect(verdict(await read(bytes))).toBe("not-a-pdf");
  });

  it("refuses a /W of four entries, over rows of the first three", async () => {
    const bytes = rewritten(await plain(), "/W [1 4 2]", "/W [1 4 2 0]");

    expect(verdict(await read(bytes))).toBe("not-a-pdf");
  });

  it("refuses a fractional width, over rows the next whole width would read", async () => {
    // The two fractions sum to a whole record, so a reader taking them steps
    // from row to row exactly and reads each type and offset whole. With one
    // fraction alone its cursor leaves the rows and it finds nothing either.
    const bytes = rewritten(
      await streamPdf(objects, trailer, {
        predictor: false,
        widths: [1, 5, 2],
      }),
      "/W [1 5 2]",
      "/W [1 4.5 2.5]",
    );

    expect(verdict(await read(bytes))).toBe("not-a-pdf");
  });

  it("reads every row as type 1 when /W gives the type no bytes", async () => {
    // The format's default for a zero width first field, and the only way to
    // write it: there is no byte to say anything else.
    const bytes = await streamPdf(objects, trailer, { widths: [0, 4, 2] });

    expect(verdict(await read(bytes))).toBe("read: Layout");
  });

  it("numbers each run an explicit /Index names from that run's own start", async () => {
    // Two runs, the second starting at 1, so the title's row is numbered by
    // its run's start rather than by its place in the stream. A split after
    // it would leave the title in a run starting at 0 and number it right
    // either way.
    const whole = await plain();
    const size = Number(/\/Size (\d+)/.exec(text(whole))![1]);

    const bytes = rewritten(
      whole,
      "/W [1 4 2]",
      `/Index [0 1 1 ${size - 1}] /W [1 4 2]`,
    );

    expect(verdict(await read(bytes))).toBe("read: Layout");
  });

  it("reads the rows a stream holds when /Index promises more", async () => {
    // The answer only. The rows past the end are bounded by the end of data
    // check in `crossReferenceStream`, which also decides the case below; what
    // this row reaches there is work, which no verdict can see.
    const bytes = rewritten(
      await plain(),
      "/W [1 4 2]",
      "/Index [0 900] /W [1 4 2]",
    );

    expect(verdict(await read(bytes))).toBe("read: Layout");
  });

  it.each([
    [2, "read: Layout"],
    [1, "read: null"],
  ])(
    "reads the last row only when the stream holds all of it: %i generation bytes",
    async (generation, expected) => {
      // Written by hand, unfiltered, so the information dictionary's row can
      // come last and be cut. Cut inside its generation field, its type and
      // offset are whole, and a reader without the end of data check takes
      // them. The whole row is the control: the file is sound, and only the
      // cut changes the answer.
      const header = "%PDF-1.5\n";
      const info = concat("1 0 obj\n<< /Title (Layout) >>\nendobj\n");
      const catalog = concat("2 0 obj\n<< /Type /Catalog >>\nendobj\n");
      const infoAt = latin(header).length;
      const catalogAt = infoAt + info.length;
      const xrefAt = catalogAt + catalog.length;
      const data = new Uint8Array([
        ...typeAndOffset(catalogAt),
        0,
        0,
        ...typeAndOffset(infoAt),
        ...Array.from({ length: generation }, () => 0),
      ]);
      const xref = streamObject(
        3,
        "<< /Type /XRef /Size 4 /W [1 4 2] /Index [2 1 1 1] /Info 1 0 R /Root 2 0 R >>",
        data,
      );
      const bytes = concat(
        header,
        info,
        catalog,
        "3 0 obj\n",
        xref.body,
        "\nendobj\n",
        `startxref\n${xrefAt}\n%%EOF\n`,
      );

      expect(verdict(await read(bytes))).toBe(expected);
    },
  );

  it("is written by a fixture that refuses a row its /W cannot hold", async () => {
    // The free row's generation is 65535, which one byte would write as 255.
    // The fixture throws rather than hand a test a number it did not ask for.
    await expect(
      streamPdf(objects, trailer, { widths: [1, 4, 1] }),
    ).rejects.toThrow("does not fit a /W width of 1");
  });

  it.each(["[0 -1]", "[0 900000]", "[0 /Many]", "[-1 3]"])(
    "refuses an /Index of %s as damaged",
    async (index) => {
      // A run a file put in a parsed array, so unlike a classic table's header
      // it can be negative, huge or not a number at all.
      const bytes = rewritten(
        await plain(),
        "/W [1 4 2]",
        `/Index ${index} /W [1 4 2]`,
      );

      expect(verdict(await read(bytes))).toBe("damaged");
    },
  );

  it("stops at a run that is not a whole number", async () => {
    const bytes = rewritten(
      await plain(),
      "/W [1 4 2]",
      "/Index [0 2.5] /W [1 4 2]",
    );

    expect(verdict(await read(bytes))).toBe("not-a-pdf");
  });

  it("reads no entry when /Size is not a number and no /Index says otherwise", async () => {
    const bytes = rewritten(await plain(), /\/Size \d+/, "/Size (many)");

    expect(verdict(await read(bytes))).toBe("not-a-pdf");
  });
});

describe("the filter and parameters a stream declares", () => {
  const objects = [
    object(1, "<< /Title (Filters) >>"),
    object(2, "<< /Type /Catalog >>"),
  ];
  const trailer = "/Info 1 0 R /Root 2 0 R";

  it("reads /Filter written as an array of one", async () => {
    const bytes = rewritten(
      await streamPdf(objects, trailer),
      "/Filter /FlateDecode",
      "/Filter [/FlateDecode]",
    );

    expect(verdict(await read(bytes))).toBe("read: Filters");
  });

  it("skips an entry in a filter array that is not a name", async () => {
    const bytes = rewritten(
      await streamPdf(objects, trailer),
      "/Filter /FlateDecode",
      "/Filter [null 5 [/Inner] /FlateDecode]",
    );

    expect(verdict(await read(bytes))).toBe("read: Filters");
  });

  it("reads /DecodeParms written as an array of one", async () => {
    const bytes = rewritten(
      await streamPdf(objects, trailer),
      /\/DecodeParms (<< [^>]* >>)/,
      "/DecodeParms [$1]",
    );

    expect(verdict(await read(bytes))).toBe("read: Filters");
  });

  it("reads an empty /DecodeParms array as no parameters", async () => {
    const bytes = rewritten(
      await streamPdf(objects, trailer, { predictor: false }),
      "/Filter /FlateDecode",
      "/DecodeParms [] /Filter /FlateDecode",
    );

    expect(verdict(await read(bytes))).toBe("read: Filters");
  });

  it("reads /Predictor 1 as the no prediction it means", async () => {
    // Below 10 is not a PNG predictor, and undoing one anyway would turn
    // literal rows into differences.
    const bytes = rewritten(
      await streamPdf(objects, trailer, { predictor: false }),
      "/Filter /FlateDecode",
      "/DecodeParms << /Predictor 1 >> /Filter /FlateDecode",
    );

    expect(verdict(await read(bytes))).toBe("read: Filters");
  });

  it("reads a predictor that names no columns as one column, the format's default", async () => {
    const packet = latin(xmpPacket({ language: "fr" }));
    const bytes = withMetadataObject(
      streamObject(
        3,
        "<< /Type /Metadata /Filter /FlateDecode /DecodeParms << /Predictor 12 >> >>",
        await deflate(predict(packet, 1, () => 2)),
      ).body,
    );

    expect(language(await read(bytes))).toBe("read: fr");
  });

  it("follows a reference written as the one member of a /DecodeParms array", async () => {
    // The parameters kept as an object of their own. Left unresolved, the
    // reference reads as no predictor and the packet comes back still
    // predicted, which is a missing language rather than an error.
    const packet = latin(xmpPacket({ language: "fr" }));
    const bytes = classicPdf(
      [
        object(1, "<< /Title (Packet) >>"),
        object(2, "<< /Type /Catalog /Metadata 3 0 R >>"),
        streamObject(
          3,
          "<< /Type /Metadata /Filter /FlateDecode /DecodeParms [4 0 R] >>",
          await deflate(predict(packet, 1, () => 2)),
        ),
        object(4, "<< /Predictor 12 >>"),
      ],
      "/Info 1 0 R /Root 2 0 R",
    );

    expect(language(await read(bytes))).toBe("read: fr");
  });

  it("undoes Paeth where up and up left tie, which the cross reference arms above never reach", async () => {
    // Paeth's tie order is the format's. `streamPdf` rows can tie up against up
    // left at the right offsets, but no arm above places objects there; a packet
    // at four columns ties without arranging offsets.
    const raw = xmpPacket({ language: "fr" });
    const packet = latin(raw + " ".repeat((4 - (raw.length % 4)) % 4));
    const bytes = withMetadataObject(
      streamObject(
        3,
        "<< /Type /Metadata /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 4 >> >>",
        await deflate(predict(packet, 4, () => 4)),
      ).body,
    );

    expect(language(await read(bytes))).toBe("read: fr");
  });

  it("leaves a stream encoded twice unread, as a field absent rather than a broken file", async () => {
    // The packet is deflated once and declares a second filter after it.
    // Applying the first alone would hand back bytes that look like data.
    const packet = await deflate(latin(xmpPacket({ language: "fr" })));
    const reading = await read(
      withMetadataObject(
        streamObject(
          3,
          "<< /Type /Metadata /Filter [/FlateDecode /ASCIIHexDecode] >>",
          packet,
        ).body,
      ),
    );

    expect(verdict(reading)).toBe("read: Packet");
    expect(language(reading)).toBe("read: null");
  });
});

describe("where a stream's bytes begin and end", () => {
  it("refuses a stream keyword with no line break after it", async () => {
    const bytes = withMetadataObject(
      concat(
        "<< /Type /Metadata /Length 10 >>\nstream ",
        "0123456789",
        "\nendstream",
      ),
    );

    expect(verdict(await read(bytes))).toBe("damaged");
  });

  it("refuses a stream with neither a usable /Length nor an endstream", async () => {
    const bytes = withMetadataObject(
      concat(
        "<< /Type /Metadata >>\nstream\n",
        latin(xmpPacket({ language: "fr" })),
      ),
    );

    expect(verdict(await read(bytes))).toBe("damaged");
  });

  it("reads a stream longer than the window its header was read through", async () => {
    // The object's dictionary is parsed out of a 64 kB window and the stream's
    // own bytes are fetched against `/Length` when they run past it. The
    // packet sits after the padding, so a reader that kept to the window would
    // lose the packet and not only padding.
    const packet = latin(" ".repeat(70 * 1024) + xmpPacket({ language: "fr" }));
    const bytes = withMetadataObject(
      streamObject(3, "<< /Type /Metadata >>", packet).body,
    );

    expect(language(await read(bytes))).toBe("read: fr");
  });
});

describe("a file that is not a PDF", () => {
  it("is refused on its header, before an offset in it is believed", async () => {
    expect(verdict(await read(latin("PK\x03\x04not a pdf at all")))).toBe(
      "not-a-pdf",
    );
  });

  it("is refused when it has a header and no cross reference", async () => {
    expect(verdict(await read(latin("%PDF-1.7\nnothing else here\n")))).toBe(
      "not-a-pdf",
    );
  });

  it("accepts any version, because PDF 2.0 exists", async () => {
    expect(
      verdict(await read(withInfoVersion("%PDF-2.0\n", "/Title (New)"))),
    ).toBe("read: New");
  });
});

function withInfoVersion(header: string, info: string) {
  return classicPdf(
    [object(1, `<< ${info} >>`), object(2, "<< /Type /Catalog >>")],
    "/Info 1 0 R /Root 2 0 R",
    { header },
  );
}

describe("a document that is encrypted", () => {
  it("is refused before a string is decoded", async () => {
    // Under encryption every string is ciphertext, so decoding one would put
    // noise in front of a member as though it were a title.
    const reading = await read(
      classicPdf(
        [
          object(1, "<< /Title (noise) >>"),
          object(2, "<< /Type /Catalog >>"),
          object(3, "<< /Filter /Standard /V 2 /R 3 >>"),
        ],
        "/Info 1 0 R /Root 2 0 R /Encrypt 3 0 R",
      ),
    );

    expect(verdict(reading)).toBe("protected");
  });

  it("is not refused for an /Encrypt that resolves to null", async () => {
    // Measured: 1 of the 123 carries this, a reference left by a revision that
    // removed the encryption, and its title and author are both plaintext and
    // correct. pypdf 6.10.2 fails that file outright.
    const reading = await read(
      classicPdf(
        [
          object(1, "<< /Title (Effective Java) >>"),
          object(2, "<< /Type /Catalog >>"),
        ],
        "/Info 1 0 R /Root 2 0 R /Encrypt null",
      ),
    );

    expect(verdict(reading)).toBe("read: Effective Java");
  });
});

describe("an object graph that does not terminate", () => {
  it("refuses a reference cycle rather than following it", async () => {
    const reading = await read(
      classicPdf(
        [
          object(1, "2 0 R"),
          object(2, "1 0 R"),
          object(3, "<< /Type /Catalog >>"),
        ],
        "/Info 1 0 R /Root 3 0 R",
      ),
    );

    expect(verdict(reading)).toBe("read: null");
  });

  it("refuses a nest deeper than the stack would take", async () => {
    const deep = `${"[".repeat(5_000)}1${"]".repeat(5_000)}`;
    const reading = await read(
      classicPdf(
        [object(1, `<< /Title ${deep} >>`), object(2, "<< /Type /Catalog >>")],
        "/Info 1 0 R /Root 2 0 R",
      ),
    );

    expect(verdict(reading)).toBe("damaged");
  });

  it("refuses an object stream whose own /Length lives inside it", async () => {
    // `/Length` is resolved before the stream is read, so the resolve re-enters
    // the same object stream. Measured before the cache moved: a 349 byte file
    // drove 98,690 reads over 3.7 seconds before the fetch budget stopped it.
    const bytes = await streamPdf(
      [
        object(1, "<< /Title (Ouroboros) >>"),
        object(2, "<< /Type /Catalog >>"),
      ],
      "/Info 1 0 R /Root 2 0 R",
      { packed: [[1]], objStmLength: "1 0 R" },
    );

    const slice = vi.spyOn(Blob.prototype, "slice");
    try {
      const reading = await read(bytes);
      expect(typeof reading.ok).toBe("boolean");
      // **The floor first, and it is not decoration.** A spy that intercepts
      // nothing counts zero, and zero is under any ceiling, so the upper bound
      // alone passes on a `Blob` the reader never touches. This reader takes a
      // header, a tail and a section before it can reach an object at all.
      expect(slice.mock.calls.length).toBeGreaterThanOrEqual(3);
      expect(slice.mock.calls.length).toBeLessThan(OUROBOROS_READ_CEILING);
    } finally {
      // In a `finally`, because a failed expectation above would otherwise
      // leave the spy on the prototype for every later file in the worker:
      // this suite runs `isolate: false`, so the module registry is shared.
      slice.mockRestore();
    }
  });

  it("refuses a reference chain longer than it will follow", async () => {
    // The diagonal that observes `MAX_RESOLVE_STEPS` rather than the visited
    // set beside it: every link here is a distinct object, so a reader with no
    // count and a working `seen` would walk all twenty and find the title.
    const links = Array.from({ length: 20 }, (_, index) =>
      object(
        index + 1,
        index === 19 ? "<< /Title (Chained) >>" : `${index + 2} 0 R`,
      ),
    );
    const reading = await read(
      classicPdf(
        [...links, object(21, "<< /Type /Catalog >>")],
        "/Info 1 0 R /Root 21 0 R",
      ),
    );

    expect(verdict(reading)).toBe("read: null");
  });

  it("refuses a cross reference chain longer than it will walk", async () => {
    // The oldest revision holds the title and 70 newer ones sit in front of it,
    // each pointing back one. A reader with no section count reaches it.
    let file = classicPdf(
      [object(1, "<< /Title (Buried) >>"), object(2, "<< /Type /Catalog >>")],
      "/Info 1 0 R /Root 2 0 R",
    );
    for (let revision = 0; revision < 70; revision += 1) {
      file = classicPdf(
        [object(2, "<< /Type /Catalog >>")],
        `/Info 1 0 R /Root 2 0 R /Prev ${startxrefOf(file)}`,
        { prefix: file },
      );
    }

    expect(verdict(await read(file))).toBe("read: null");
  });

  it("refuses a cross reference chain that points at itself", async () => {
    // `/Prev` naming this section's own offset. Without the visited set this
    // walks until the section count runs out, which is work a crafted file
    // chooses; the entries are all present, so the read still succeeds.
    const original = classicPdf(
      [object(1, "<< /Title (Loop) >>"), object(2, "<< /Type /Catalog >>")],
      "/Info 1 0 R /Root 2 0 R",
    );
    const at = startxrefOf(original);
    const looping = classicPdf(
      [object(1, "<< /Title (Loop) >>"), object(2, "<< /Type /Catalog >>")],
      `/Info 1 0 R /Root 2 0 R /Prev ${at}`,
      { startxref: at },
    );

    expect(verdict(await read(looping))).toBe("read: Loop");
  });
});

describe("a number the file supplied that does not agree with the file", () => {
  it("refuses a cross reference run larger than anything real", async () => {
    const bytes = classicPdf(
      [object(1, "<< /Title (A) >>"), object(2, "<< /Type /Catalog >>")],
      "/Info 1 0 R /Root 2 0 R",
    );
    const broken = latin(
      text(bytes).replace("xref\n0 3\n", "xref\n0 4000000000\n"),
    );

    expect(verdict(await read(broken))).toBe("damaged");
  });

  it("refuses an object whose offset points at a different object", async () => {
    // How an incremental update goes wrong, and taking whatever is at the
    // offset would put another book's title on this one.
    const bytes = classicPdf(
      [
        object(1, "<< /Title (The Right Book) >>"),
        object(2, "<< /Type /Catalog >>"),
      ],
      "/Info 1 0 R /Root 2 0 R",
    );
    const table = text(bytes);
    const first = /\n(\d{10}) 00000 n /.exec(table)![1]!;
    const second = /\n\d{10} 00000 n \n(\d{10}) 00000 n /.exec(table)![1]!;
    const swapped = latin(
      table.replace(`\n${first} 00000 n `, `\n${second} 00000 n `),
    );

    expect(verdict(await read(swapped))).toBe("read: null");
  });

  it("refuses an object whose header has no obj keyword", async () => {
    // The keyword blanked to spaces of its own length, so every offset holds
    // and the dictionary after it is still readable to a reader that skipped
    // the check.
    const bytes = rewritten(
      classicPdf(
        [
          object(1, "<< /Title (The Right Book) >>"),
          object(2, "<< /Type /Catalog >>"),
        ],
        "/Info 1 0 R /Root 2 0 R",
      ),
      "1 0 obj",
      "1 0    ",
    );

    expect(verdict(await read(bytes))).toBe("read: null");
  });

  it("refuses a cross reference table whose subsection header is not a number", async () => {
    // The one that hung. `Lexer.token()` answers `""` at a delimiter without
    // moving the cursor, and `Number("")` is 0, which passes every check a
    // count would be given. Driven at each of the four delimiters that reach
    // it: `%` is eaten as a comment and a word fails `Number.isInteger`, so
    // these are the arms that could pass one and not the other.
    for (const delimiter of ["(", "<", "/", "}"]) {
      const bytes = classicPdf(
        [object(1, "<< /Title (A) >>"), object(2, "<< /Type /Catalog >>")],
        "/Info 1 0 R /Root 2 0 R",
      );
      const broken = latin(
        text(bytes).replace("xref\n0 3\n", `xref\n${delimiter} 3\n`),
      );

      expect(verdict(await read(broken))).toBe("not-a-pdf");
    }
  });

  it("refuses a predictor with more columns than there are bytes", async () => {
    // `/Columns` is a number the file chose and `new Uint8Array(columns)`
    // answers a `RangeError`, which is not a `PdfError` and would escape past
    // every caller catching one.
    for (const columns of ["10000000000", "0", "-4", "9".repeat(400)]) {
      const bytes = await streamPdf(
        [
          object(1, "<< /Title (Columns) >>"),
          object(2, "<< /Type /Catalog >>"),
        ],
        "",
        { predictor: false },
      );
      const broken = latin(
        text(bytes).replace(
          "/Filter /FlateDecode",
          `/DecodeParms << /Predictor 12 /Columns ${columns} >> /Filter /FlateDecode`,
        ),
      );

      const reading = await read(broken);
      expect(typeof reading.ok).toBe("boolean");
    }
  });

  it("recovers a stream whose /Length runs past the end of the file", async () => {
    const packet = xmpPacket({ language: "fr" });
    const bytes = classicPdf(
      [
        object(1, "<< /Title (Lengths) >>"),
        object(2, "<< /Type /Catalog /Metadata 3 0 R >>"),
        object(
          3,
          concat(
            "<< /Type /Metadata /Length 999999999 >>\nstream\n",
            latin(packet),
            "\nendstream",
          ),
        ),
      ],
      "/Info 1 0 R /Root 2 0 R",
    );

    const reading = await read(bytes);
    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata.language).toBe("fr");
  });

  it("refuses a stream that inflates past what it will hold", async () => {
    // A compression bomb: 20 MiB of zeroes deflates to a few kilobytes, and the
    // reader has to stop at its ceiling with the stream cancelled rather than
    // find out how big it was.
    const bomb = await deflate(new Uint8Array(20 * 1024 * 1024));
    const bytes = classicPdf(
      [
        object(1, "<< /Title (Bomb) >>"),
        object(2, "<< /Type /Catalog /Metadata 3 0 R >>"),
        streamObject(3, "<< /Type /Metadata /Filter /FlateDecode >>", bomb),
      ],
      "/Info 1 0 R /Root 2 0 R",
    );

    expect(verdict(await read(bytes))).toBe("damaged");
  });

  it("says the browser cannot inflate, not that the stream is broken", async () => {
    // **Two sentences a member could be shown for the same file**, and only one
    // of them is true: `damaged` sends somebody looking for another copy of a
    // book that is fine, where `no-inflate` sends them to their browser. It is
    // the one refusal in this reader whose cause is the runtime.
    //
    // The stream really is deflate, compressed before the inflater is taken
    // away, so what separates this from the arm below is the runtime and
    // nothing about the file.
    const packet = await deflate(latin(xmpPacket({ title: "Dune" })));
    const bytes = classicPdf(
      [
        object(1, "<< /Title (Fine) >>"),
        object(2, "<< /Type /Catalog /Metadata 3 0 R >>"),
        streamObject(3, "<< /Type /Metadata /Filter /FlateDecode >>", packet),
      ],
      "/Info 1 0 R /Root 2 0 R",
    );
    // The same file reads on a runtime that can inflate, which is what says the
    // fixture is not simply broken.
    expect(verdict(await read(bytes))).toBe("read: Fine");

    expect(verdict(await withoutDecompressionStream(() => read(bytes)))).toBe(
      "no-inflate",
    );
  });

  it("reads a stream whose bytes are not deflate as a broken stream", async () => {
    const bytes = classicPdf(
      [
        object(1, "<< /Title (Not Deflate) >>"),
        object(2, "<< /Type /Catalog /Metadata 3 0 R >>"),
        streamObject(
          3,
          "<< /Type /Metadata /Filter /FlateDecode >>",
          latin("this is not compressed at all"),
        ),
      ],
      "/Info 1 0 R /Root 2 0 R",
    );

    expect(verdict(await read(bytes))).toBe("damaged");
  });
});

/**
 * What each object stream in the two files below inflates to.
 *
 * `MAX_INFLATED_BYTES`, the per stream ceiling, read from the module rather
 * than restated. One of these streams is inside the budget
 * and three of them are 16.8 MB past it, which is the pair below: a reader that
 * charges nothing for what a stream inflates to reads them both, since neither
 * file is large and neither stream is over its own ceiling.
 *
 * **What the pair does not distinguish is one total from two.** A reader
 * charging inflation to a second budget of its own refuses the second file too,
 * and `outcome` sees only `damaged` either way. Telling those apart needs a file
 * whose inflation is under the budget on its own and over it once the reads are
 * added, and the reads here are 87,024 bytes against a 33,554,432 byte budget,
 * so the margin such a file would balance on is 0.26%. Stated rather than
 * built: it would be a test that a later edit to the fixture breaks without
 * touching the reader.
 */
const INFLATED_PER_STREAM = MAX_INFLATED_BYTES;

/**
 * A file whose `/Info` is a chain of `links` references, one per object stream.
 *
 * Each link costs a whole stream's worth of inflation and 16 kB of file, which
 * is the shape the budget is about: a crafted file is small, so its reads are
 * cheap however many it forces, and what it spends is what it inflates.
 */
async function chainOfInflatedStreams(links: number) {
  const objects = [];
  for (let index = 1; index <= links; index += 1) {
    objects.push(
      object(
        index,
        index === links ? "<< /Title (Deep) >>" : `${index + 1} 0 R`,
      ),
    );
  }
  objects.push(object(links + 1, "<< /Type /Catalog >>"));
  return await streamPdf(objects, `/Info 1 0 R /Root ${links + 1} 0 R`, {
    packed: objects.slice(0, links).map((item) => [item.num]),
    inflateTo: INFLATED_PER_STREAM,
  });
}

describe("what one file may spend altogether", () => {
  it("reads a file whose one stream inflates to the per stream ceiling", async () => {
    const bytes = await chainOfInflatedStreams(1);

    // 16,777,256 bytes inflated and 37,727 read, measured on `builder`
    // 2026-09-08, against a budget of 33,554,432.
    expect(verdict(await read(bytes))).toBe("read: Deep");
  });

  it("refuses three streams that inflate past the budget together", async () => {
    const bytes = await chainOfInflatedStreams(3);

    // A 49,598 byte file. Uncharged it inflated 50,331,720 bytes and answered
    // `read: Deep` in 33 ms; charged it stops at 33,488,968 with 87,024 read,
    // both measured on `builder` 2026-09-08.
    expect(verdict(await read(bytes))).toBe("damaged");
  });

  it("charges what an object stream's members take to parse", async () => {
    // **Four members, four offsets, each a byte that cannot begin a value**, in
    // a stream that inflates to 12,582,912. A member that fails is charged the
    // rest of the stream, so the second exhausts the budget: 12,582,912 for the
    // inflation, then 12,582,896 and 12,582,894 for the two members, against
    // 33,554,432. Members three and four are never reached. Uncharged, this
    // file answers `ok` with a null title, because every member failing is what
    // an empty object stream looks like.
    //
    // **The failing path only**, which is the arm below for the other one.
    // Moving the charge inside the `try` is what this one catches: that `catch`
    // swallows a `PdfError`, so a charge under it can never fire.
    const bytes = await streamPdf(
      [
        object(1, ")"),
        object(2, ")"),
        object(3, ")"),
        object(4, ")"),
        object(5, "<< /Type /Catalog >>"),
      ],
      "/Info 1 0 R /Root 5 0 R",
      { packed: [[1, 2, 3, 4]], inflateTo: 12 * 1024 * 1024 },
    );

    expect(verdict(await read(bytes))).toBe("damaged");
  });

  it("charges a member that parses, not only one that fails", async () => {
    // **Nine rows in the pairs header, all naming the one member's offset**,
    // which the format does not forbid and which is the shape the charge was
    // written for: one stream is parsed `/N` times for the one inflation it is
    // charged. The member is a 4 MiB literal string, so every parse returns
    // rather than throwing, and a parse that returns is what this arm charges
    // for. The other arm's members all throw, so neither covers the other.
    //
    // Measured on `builder`: a 4,475 byte file, 4,194,383 bytes inflated and
    // 8,762 read, `damaged` in 413 ms. Nine parses put it 8.4 MB past the
    // 33,554,432 budget, so this does not balance on the fixture's own
    // overhead. Uncharged the same file answers `read: null`, and one row
    // rather than nine answers it in 86 ms.
    const string = `(${"z".repeat(4 * 1024 * 1024)})`;
    const bytes = await streamPdf(
      [object(1, string), object(2, "<< /Type /Catalog >>")],
      "/Info 1 0 R /Root 2 0 R",
      {
        packed: [[1]],
        packedHeader: [
          [1, 0],
          [1, 0],
          [1, 0],
          [1, 0],
          [1, 0],
          [1, 0],
          [1, 0],
          [1, 0],
          [1, 0],
        ],
      },
    );

    expect(verdict(await read(bytes))).toBe("damaged");
  });

  it("adds to the running total in exactly one place", () => {
    // **The funnel, which is otherwise only asserted in a docstring.** What it
    // refuses is a spender that adds to `spent` without going through
    // `Source.charge`, which is where the ceiling is compared.
    //
    // **It counts writes to `spent` and nothing else**, so a second total under
    // another name passes it, and so does a path that spends without charging
    // at all. Nothing structural sees either, because the ways of spending are
    // not a closed set; the three that exist are covered by the arms above and
    // by the bomb test further up.
    expect(
      sourceText("lib/pdf.ts").match(/this\.spent\s*[-+*/]?=/g),
    ).toHaveLength(1);
  });
});

describe("no file makes the reader throw", () => {
  it("answers a reading for every truncation of a well formed file", async () => {
    const whole = await streamPdf(
      [
        object(1, "<< /Title (Sweep) /Author (A. Person) >>"),
        object(2, "<< /Type /Catalog /Metadata 3 0 R >>"),
        streamObject(
          3,
          "<< /Type /Metadata >>",
          latin(xmpPacket({ publisher: "Nobody" })),
        ),
      ],
      "/Info 1 0 R /Root 2 0 R",
      { packed: [[1]] },
    );

    // Every cut, not a sample: a truncation is the cheapest malformed file to
    // produce and the offsets it leaves behind are what this reader is bounded
    // against.
    const started = Date.now();
    for (let length = 0; length <= whole.length; length += 1) {
      const reading = await read(whole.subarray(0, length));
      expect(typeof reading.ok).toBe("boolean");
    }
    expect(Date.now() - started).toBeLessThan(SWEEP_CEILING_MS);
  });

  it("answers a reading for every single byte corruption of the trailer", async () => {
    const whole = classicPdf(
      [object(1, "<< /Title (Sweep) >>"), object(2, "<< /Type /Catalog >>")],
      "/Info 1 0 R /Root 2 0 R",
    );
    // **The whole file and not its last 300 bytes.** The cross reference table
    // is where a corrupted byte turns into a loop, and it is not near the end
    // of a file that has objects after it.
    const started = Date.now();
    for (let at = 0; at < whole.length; at += 1) {
      for (const byte of [0x00, 0x28, 0x3c, 0x2f, 0xff]) {
        const copy = new Uint8Array(whole);
        copy[at] = byte;
        const reading = await read(copy);
        expect(typeof reading.ok).toBe("boolean");
      }
    }
    expect(Date.now() - started).toBeLessThan(SWEEP_CEILING_MS);
  });
});

/**
 * `readPdf` as a door, held to its per stream ceiling and its file budget.
 *
 * **The meter is this property's only teeth on the budget.** The reader that
 * charged reads and not inflation answered `ok`, in 801 ms, with nothing
 * thrown, so "never rejects" alone is green on it. What sees it is the count
 * of what came out of the inflater against `MAX_BUDGET_BYTES`, and only for a
 * file with three or more streams at the ceiling, which the witness below
 * asserts by name.
 *
 * **What it does not see**: the parse of an object stream's members, which
 * the reader charges a second time for bytes already inflated. The meter
 * counts what arrives, so its total is at most the reader's and a breach here
 * is a breach there.
 */
const door: Door<PdfSpec, PdfReading> = {
  module: pdf,
  ceilings: () => ({ perInflate: MAX_INFLATED_BYTES, total: MAX_BUDGET_BYTES }),
  build: buildPdf,
  open: (file) => readPdf(file),
};

describe("any PDF a member picks", () => {
  it(
    "is read or refused by name, inflating no chunk past a stream's ceiling or the file's budget",
    PROPERTY,
    async () => {
      // **The reach is asked of the meter**, because a spec can be the
      // budget's combination and still reach no inflater: measured, a header
      // the reader refuses first left a witness over the spec green while no
      // draw was inflated.
      expect(
        await holds(
          hostile(pdfSpec()),
          async (input) => expectNamedOutcome(door, input),
          {
            // Inflated to the stream's ceiling, and not to the budget: the
            // reader also charges the parse of a stream's members, so it
            // refuses the file after the first stream at the ceiling.
            "inflated the budget's combination to a stream's ceiling": (
              { spec, patches },
              { counted },
            ) =>
              patches.length === 0 &&
              isOverBudget(spec, MAX_BUDGET_BYTES) &&
              counted.inflated >= MAX_INFLATED_BYTES - 1,
          },
        ),
      ).toBe(PROFILE.runs);
    },
  );

  it("is metered, so the ceilings above are not held over nothing", async () => {
    const { outcome, counted } = await expectNamedOutcome(door, {
      spec: {
        xref: "stream",
        header: "%PDF-1.5\n",
        links: 1,
        packed: true,
        inflateTo: undefined,
        info: "<< /Title (Deep) >>",
        cycle: false,
        catalog: "",
        trailer: "",
      },
      patches: [],
    });

    expect(outcome).toMatchObject({
      answered: { ok: true, metadata: { title: "Deep" } },
    });
    // The cross reference stream and the object stream.
    expect(counted.inflaters).toBe(2);
    expect(counted.inflated).toBeGreaterThan(0);
    // **Both halves of the total**, which is read plus inflated: a reader
    // reading by a route the meter does not count would hold the total over
    // its inflation alone.
    expect(counted.read).toBeGreaterThan(0);
  });

  it("declares the bounds it is held to, so one deleted or loosened reds", async () => {
    expect(
      await overrunBreach(door, {
        ceiling: "perInflate",
        bound: MAX_INFLATED_BYTES,
      }),
    ).toContain(`against a bound of ${MAX_INFLATED_BYTES}`);
    // The total by each of its halves: read alone, and inflated in streams
    // each inside the per stream bound.
    expect(
      await overrunBreach(door, { ceiling: "total", bound: MAX_BUDGET_BYTES }),
    ).toContain(`read past the total of ${MAX_BUDGET_BYTES}`);
    expect(
      await overrunBreach(door, {
        ceiling: "total",
        bound: MAX_BUDGET_BYTES,
        each: MAX_INFLATED_BYTES,
      }),
    ).toContain(`against a total of ${MAX_BUDGET_BYTES}`);
  });

  it("draws three or more streams at the ceiling, together past the budget", async () => {
    await witness(hostile(pdfSpec()), {
      "puts three or more streams at the ceiling, together past the budget": ({
        spec,
        patches,
      }: Hostile<PdfSpec>) =>
        patches.length === 0 && isOverBudget(spec, MAX_BUDGET_BYTES),
    });
  });
});
