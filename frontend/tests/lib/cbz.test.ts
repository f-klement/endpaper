/**
 * @vitest-environment jsdom
 *
 * jsdom for the reason `tests/lib/opf.test.ts` gives at length: happy-dom's
 * `DOMParser` does not parse every real document and jsdom's does. jsdom's
 * `Blob` has no `stream()`, which is why `lib/zip.ts` builds its own
 * `ReadableStream` rather than borrowing one from a Blob.
 */
/**
 * Tests for src/lib/cbz.ts.
 *
 * Two halves. The mapping, which is where the decisions are: what an issue is
 * called, what a collected volume is called, and which of the schema's people
 * is the author. And the refusals, because a member's archive is untrusted
 * input and what a hostile or broken one has to produce is one named outcome.
 *
 * **The ordinary comic carries no `ComicInfo.xml` at all**, so the cases that
 * assert an empty record are the common path rather than the edge.
 */

import { describe, expect, it } from "vitest";

import { readCbz, readComicInfo } from "../../src/lib/cbz";
import { buildZip, bytes, STORED, type EntrySpec } from "../zipFixtures";

/** A ComicInfo document holding whatever elements a case needs. */
function comicInfo(elements: string): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">${elements}</ComicInfo>`;
}

/** An issue of Saga, with every element this reader looks at. */
const WHOLE = comicInfo(
  `<Title>The Will</Title><Series>Saga</Series><Number>12</Number>` +
    `<Writer>Brian K. Vaughan</Writer><Publisher>Image Comics</Publisher>` +
    `<Year>2013</Year><LanguageISO>en</LanguageISO>` +
    `<Summary>Marko and Alana keep running.</Summary>`,
);

/** A whole archive: pages, and a `ComicInfo.xml` where a case wants one. */
async function buildCbz(
  spec: { info?: string; infoAt?: string; extra?: EntrySpec[] } = {},
): Promise<Blob> {
  const entries: EntrySpec[] = [
    { name: "page-001.jpg", data: "not really a jpeg" },
    { name: "page-002.jpg", data: "nor is this one" },
  ];
  if (spec.info !== undefined) {
    entries.push({ name: spec.infoAt ?? "ComicInfo.xml", data: spec.info });
  }
  entries.push(...(spec.extra ?? []));
  return new Blob([await buildZip({ entries })]);
}

/**
 * A **valid** ComicInfo carrying a mebibyte of padding, so the whole document
 * is over the reader's mebibyte cap by the length of its own wrapper.
 *
 * Valid rather than a truncated `<ComicInfo>`, and that is the point of it: an
 * unparseable payload reads as `read: null` if a bound stops working, which is
 * the exact string three other cases in this file assert as a pass, so a lost
 * bound would be indistinguishable from a document that is not a ComicInfo.
 * This one reads as `read: Saga #12`, which names itself.
 */
const OVER_THE_CAP = comicInfo(
  `<Series>Saga</Series><Number>12</Number>` +
    `<Summary>${" ".repeat(1024 * 1024)}</Summary>`,
);

/** The failure, or the title, so one assertion covers both arms. */
function outcome(reading: Awaited<ReturnType<typeof readCbz>>): string {
  return reading.ok ? `read: ${reading.metadata.title}` : reading.failure;
}

describe("reading a whole comic archive", () => {
  it("yields what the ComicInfo document carried", async () => {
    const reading = await readCbz(await buildCbz({ info: WHOLE }));

    expect(reading.ok && reading.metadata).toMatchObject({
      authors: ["Brian K. Vaughan"],
      publisher: "Image Comics",
      year: 2013,
      language: "en",
      description: "Marko and Alana keep running.",
      seriesName: "Saga",
      seriesIndex: 12,
    });
  });

  it("lets the file's own title be the title", async () => {
    // **Not `Saga #12`.** The series and the number go to the series columns,
    // which the library list, the table's series column and the book page all
    // already print beside the title, so composing them into it as well prints
    // the same two facts twice on three surfaces.
    const reading = await readCbz(await buildCbz({ info: WHOLE }));

    expect(reading.ok && reading.metadata.title).toBe("The Will");
    expect(reading.ok && reading.metadata.seriesName).toBe("Saga");
    expect(reading.ok && reading.metadata.seriesIndex).toBe(12);
    // ComicInfo has no subtitle field, so there is nothing to put here.
    expect(reading.ok && reading.metadata.subtitle).toBeNull();
  });

  it("names an issue after its series and number when it gave no title", async () => {
    // Most single issues. Here the series and the number are the only name the
    // object has, and it is what a comic catalogue calls it.
    const reading = await readCbz(
      await buildCbz({
        info: comicInfo(`<Series>Saga</Series><Number>12</Number>`),
      }),
    );

    expect(outcome(reading)).toBe("read: Saga #12");
  });

  it("gives a collected volume exactly the same shape as an issue", async () => {
    // The ticket asked what happens to each, and this is the answer asserted
    // rather than only written down: ComicInfo carries no field that separates
    // them, so both become a row in one series at one index and the published
    // volume title is the title, exactly as a story title is.
    const reading = await readCbz(
      await buildCbz({
        info: comicInfo(
          `<Series>Saga</Series><Number>1</Number>` +
            `<Title>Saga, Volume One</Title><Format>TPB</Format>`,
        ),
      }),
    );

    expect(reading.ok && reading.metadata).toMatchObject({
      title: "Saga, Volume One",
      seriesName: "Saga",
      seriesIndex: 1,
    });
  });

  it("uses the story title when the file names no series", async () => {
    const reading = await readCbz(
      await buildCbz({ info: comicInfo(`<Title>Maus</Title>`) }),
    );

    expect(outcome(reading)).toBe("read: Maus");
    expect(reading.ok && reading.metadata.seriesName).toBeNull();
  });

  it("names a series with no number after the series alone", async () => {
    const reading = await readCbz(
      await buildCbz({ info: comicInfo(`<Series>Sandman</Series>`) }),
    );

    expect(outcome(reading)).toBe("read: Sandman");
  });

  it("keeps an issue number that is not a number in the title only", async () => {
    // `Number` is a string in this schema. An annual has no place on a numeric
    // axis, so the series index is blank rather than guessed, and the composed
    // title still says what the file said.
    const reading = await readCbz(
      await buildCbz({
        info: comicInfo(`<Series>Saga</Series><Number>Annual 1</Number>`),
      }),
    );

    expect(outcome(reading)).toBe("read: Saga #Annual 1");
    expect(reading.ok && reading.metadata.seriesIndex).toBeNull();
  });
});

describe("finding the metadata entry", () => {
  it("reads one sitting under a folder", async () => {
    // 40 of the 81 archives the module's docstring surveys wrap every entry in
    // a folder, and a writer that wraps its pages wraps this with them. A root
    // only match would read nothing in one of those and say nothing about why.
    const reading = await readCbz(
      await buildCbz({ info: WHOLE, infoAt: "Saga 012/ComicInfo.xml" }),
    );

    expect(outcome(reading)).toBe("read: The Will");
  });

  it("does not mind how the entry is cased", async () => {
    const reading = await readCbz(
      await buildCbz({ info: WHOLE, infoAt: "comicinfo.xml" }),
    );

    expect(outcome(reading)).toBe("read: The Will");
  });

  it("takes the first of two in central directory order", async () => {
    // So an archive carrying two answers the same way on every reader rather
    // than on whichever one a scan happened to reach.
    const reading = await readCbz(
      await buildCbz({
        info: WHOLE,
        extra: [
          {
            name: "extras/ComicInfo.xml",
            data: comicInfo("<Title>Nope</Title>"),
          },
        ],
      }),
    );

    expect(outcome(reading)).toBe("read: The Will");
  });

  it("is not answered by an entry that merely ends in the name", async () => {
    // `not-ComicInfo.xml` is a different entry, and a substring match on the
    // path would take it. The basename is compared, not the tail.
    const reading = await readCbz(
      await buildCbz({ info: WHOLE, infoAt: "not-ComicInfo.xml" }),
    );

    expect(outcome(reading)).toBe("read: null");
  });
});

describe("an archive that says nothing about itself", () => {
  it("is not a failure, because it is the ordinary comic", async () => {
    // 6 of the 81 archives the module's docstring surveys carry the document
    // at all. A refusal would report most of a member's collection as broken.
    const reading = await readCbz(await buildCbz());

    expect(reading.ok).toBe(true);
    expect(reading.ok && reading.metadata).toMatchObject({
      title: null,
      authors: [],
      identifiers: [],
      seriesName: null,
    });
  });

  it("answers the same way for a zip that is not a comic at all", async () => {
    // Deliberately not a refusal. The entries are never checked for being
    // images, because the set of image formats is open and refusing one
    // nobody listed would refuse a real comic.
    const zip = new Blob([
      await buildZip({ entries: [{ name: "notes.txt", data: "hello" }] }),
    ]);

    expect(outcome(await readCbz(zip))).toBe("read: null");
  });

  it("answers the same way for a document that is not a ComicInfo", async () => {
    const reading = await readCbz(
      await buildCbz({ info: "<html><body>nope</body></html>" }),
    );

    expect(outcome(reading)).toBe("read: null");
  });

  it("answers the same way for a document that will not parse", async () => {
    const reading = await readCbz(await buildCbz({ info: "<ComicInfo>" }));

    expect(outcome(reading)).toBe("read: null");
  });
});

describe("a file that is not an archive", () => {
  it("is the one thing this reader calls a failure", async () => {
    expect(outcome(await readCbz(new Blob([bytes("just some text")])))).toBe(
      "not-a-comic",
    );
  });

  it("reports an encrypted entry as protected rather than as damaged", async () => {
    // DRM is out of scope and it is a different sentence to a member than a
    // broken file. `lib/zip.ts` decides which; this asserts the mapping.
    const zip = new Blob([
      await buildZip({
        entries: [{ name: "page-001.jpg", data: "sealed", flags: 0x1 }],
      }),
    ]);

    expect(outcome(await readCbz(zip))).toBe("protected");
  });

  it("reports a truncated archive as damaged", async () => {
    // On the metadata entry rather than on a page, because a page is never
    // opened: a broken entry this reader does not read is not a failure it can
    // report, and a fixture that broke one would assert nothing at all.
    const zip = new Blob([
      await buildZip({
        entries: [
          {
            name: "ComicInfo.xml",
            data: WHOLE,
            centralCompressedSize: 1024 * 1024,
          },
        ],
      }),
    ]);

    expect(outcome(await readCbz(zip))).toBe("damaged");
  });

  it("reports a compression method it cannot read as unsupported", async () => {
    const zip = new Blob([
      await buildZip({
        entries: [
          {
            name: "ComicInfo.xml",
            data: WHOLE,
            method: STORED,
            centralMethod: 99,
          },
        ],
      }),
    ]);

    expect(outcome(await readCbz(zip))).toBe("unsupported");
  });

  it("refuses a metadata entry that declares more than it will read", async () => {
    // **A small document that claims two mebibytes**, so only the declared
    // size can refuse it. `lib/zip.ts` checks the claim before it reads,
    // because it is free. With a document that is genuinely over the cap this
    // case passes on the output bound as well and stops watching its own arm.
    const reading = await readCbz(
      await buildCbz({
        extra: [
          {
            name: "ComicInfo.xml",
            data: WHOLE,
            centralUncompressedSize: 2 * 1024 * 1024,
          },
        ],
      }),
    );

    expect(outcome(reading)).toBe("too-large");
  });

  it("refuses one that lies about its size and inflates past it anyway", async () => {
    // **The arm the honest fixture above cannot reach**, and the one the
    // module's docstring claims: the cap is on OUTPUT, so an archive declaring
    // a ten byte entry that expands to a megabyte is stopped by what came out.
    // Without this case the claim rests on `lib/zip.ts`'s own test, and a
    // reader here would take the arm above as evidence of it.
    const reading = await readCbz(
      await buildCbz({
        extra: [
          {
            name: "ComicInfo.xml",
            data: OVER_THE_CAP,
            centralUncompressedSize: 10,
          },
        ],
      }),
    );

    expect(outcome(reading)).toBe("too-large");
  });
});

describe("the document itself", () => {
  it("refuses one that declares its own entities", () => {
    // The same exposure the package document has and the same refusal, through
    // `xmlEntities.declaresEntities`: expansion happens inside the engine's
    // parser, before any code here has a node to bound.
    const hostile = `<?xml version="1.0"?>
<!DOCTYPE ComicInfo [<!ENTITY s "Saga">]>
<ComicInfo><Series>&s;</Series><Number>12</Number></ComicInfo>`;

    expect(readComicInfo(hostile)).toBeNull();
  });

  it("does not read a year the schema means as unknown", () => {
    // ComicRack writes -1 into its numeric fields where nothing is known, and
    // a reader taking that at face value files a comic in the year minus one.
    const record = readComicInfo(
      comicInfo(`<Series>Saga</Series><Year>-1</Year>`),
    );

    expect(record?.year).toBeNull();
  });

  it("does not read a year no comic could have been published in", () => {
    // The window is `year.plausibleYear`'s, and this is the arm that says
    // which values it refuses here: the caller scan in
    // `tests/lib/bookBounds.test.ts` reads neither end of the window, so it
    // cannot tell this door applying it from this door widening it.
    //
    // `101` is the value that bought the window and it is inside
    // `NUMBER_RANGES.year`, so nothing downstream reports it. The comparison it
    // replaced was `> 0`, which closed one end and let it through.
    expect(
      readComicInfo(comicInfo(`<Series>Saga</Series><Year>101</Year>`))?.year,
    ).toBeNull();

    // **The point immediately outside each end, and that choice is the arm.**
    // A number far outside, `2199` say, catches a reader that drops the window
    // and nothing else; a reader keeping a second, wider window of its own
    // answers from that one for a contiguous band, and any contiguous widening
    // of an end has to contain the point just outside it. So these two catch
    // that whole family. Found by the seat that did not write this arm, against
    // a mutation the first version of it passed.
    expect(
      readComicInfo(comicInfo(`<Series>Saga</Series><Year>1449</Year>`))?.year,
    ).toBeNull();
    expect(
      readComicInfo(comicInfo(`<Series>Saga</Series><Year>2101</Year>`))?.year,
    ).toBeNull();
  });

  it("separates the writers and keeps the file's order", () => {
    const record = readComicInfo(
      comicInfo(`<Writer>Alan Moore, Dave Gibbons, Alan Moore</Writer>`),
    );

    expect(record?.authors).toEqual(["Alan Moore", "Dave Gibbons"]);
  });

  it("reads nobody but the writer", () => {
    // This tree has one author field, and an illustrator filed as the author
    // is a wrong fact. The same rule `opf.readAuthors` states at its own site.
    const record = readComicInfo(
      comicInfo(
        `<Writer>Alan Moore</Writer><Penciller>Dave Gibbons</Penciller>` +
          `<Colorist>John Higgins</Colorist><Editor>Len Wein</Editor>`,
      ),
    );

    expect(record?.authors).toEqual(["Alan Moore"]);
  });

  it("takes an ISBN out of the barcode field and refuses a barcode", () => {
    // `GTIN` carries an ISBN on a collected volume and an ordinary product
    // code on an issue. The check digit decides which, never the label.
    const isbn = readComicInfo(comicInfo(`<GTIN>9781607066019</GTIN>`));
    const barcode = readComicInfo(comicInfo(`<GTIN>0761941220116</GTIN>`));

    expect(isbn?.isbn).toBe("9781607066019");
    expect(isbn?.identifiers).toEqual([
      { scheme: "GTIN", value: "9781607066019" },
    ]);
    expect(barcode?.isbn).toBeNull();
    expect(barcode?.identifiers).toEqual([
      { scheme: "GTIN", value: "0761941220116" },
    ]);
  });

  it("is not answered from inside the page list", () => {
    // The page block holds one element per page and a reader searching the
    // whole subtree would let a crafted one answer for a field it does not
    // own. Only children of the root are read.
    // **The page block comes first**, which is the half that makes this a
    // guard: with the real `<Series>` before it a subtree search returns
    // "Saga" anyway and only the `authors` line below is watching anything.
    const record = readComicInfo(
      comicInfo(
        `<Pages><Page Image="0"/><Series>Not Saga</Series>` +
          `<Writer>Nobody</Writer></Pages>` +
          `<Series>Saga</Series>`,
      ),
    );

    expect(record?.seriesName).toBe("Saga");
    expect(record?.authors).toEqual([]);
  });
});
