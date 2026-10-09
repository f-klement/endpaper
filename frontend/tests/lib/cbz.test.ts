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

import fc from "fast-check";
import { describe, expect, it } from "vitest";

import * as cbz from "../../src/lib/cbz";
import {
  MAX_COMIC_INFO_BYTES,
  readCbz,
  readComicInfo,
  type CbzReading,
} from "../../src/lib/cbz";
import { holds, PROFILE, PROPERTY, witness, type Repeated } from "../property";
import {
  aimedArchive,
  archiveSpec,
  buildZip,
  bytes,
  entrySpec,
  isBomb,
  STORED,
  zeroesAt,
  type ArchiveSpec,
  type EntrySpec,
  type Payload,
} from "../zipFixtures";
import {
  expectAnswer,
  expectNamedOutcome,
  hostile,
  overrunBreach,
  stoppedAt,
  type Door,
  type ValueDoor,
} from "./readerContract";
import {
  declares,
  COMIC_INFO,
  render as renderXml,
  xmlDocument,
  type XmlDocument,
} from "./xmlArbitrary";
import type { FileMetadata } from "../../src/lib/fileReaders";

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
const OVER_THE_CAP: Repeated = (() => {
  const [before, after] = comicInfo(
    "<Series>Saga</Series><Number>12</Number><Summary>\u0000</Summary>",
  ).split("\u0000");
  // A spec rather than the string, so a counterexample carrying it prints as
  // four fields and not as a mebibyte of spaces.
  return {
    before: before!,
    unit: " ",
    times: MAX_COMIC_INFO_BYTES,
    after: after!,
  };
})();

/** The failure, or the title, so one assertion covers both arms. */
function verdict(reading: Awaited<ReturnType<typeof readCbz>>): string {
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

    expect(verdict(reading)).toBe("read: Saga #12");
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

    expect(verdict(reading)).toBe("read: Maus");
    expect(reading.ok && reading.metadata.seriesName).toBeNull();
  });

  it("names a series with no number after the series alone", async () => {
    const reading = await readCbz(
      await buildCbz({ info: comicInfo(`<Series>Sandman</Series>`) }),
    );

    expect(verdict(reading)).toBe("read: Sandman");
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

    expect(verdict(reading)).toBe("read: Saga #Annual 1");
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

    expect(verdict(reading)).toBe("read: The Will");
  });

  it("does not mind how the entry is cased", async () => {
    const reading = await readCbz(
      await buildCbz({ info: WHOLE, infoAt: "comicinfo.xml" }),
    );

    expect(verdict(reading)).toBe("read: The Will");
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

    expect(verdict(reading)).toBe("read: The Will");
  });

  it("is not answered by an entry that merely ends in the name", async () => {
    // `not-ComicInfo.xml` is a different entry, and a substring match on the
    // path would take it. The basename is compared, not the tail.
    const reading = await readCbz(
      await buildCbz({ info: WHOLE, infoAt: "not-ComicInfo.xml" }),
    );

    expect(verdict(reading)).toBe("read: null");
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

    expect(verdict(await readCbz(zip))).toBe("read: null");
  });

  it("answers the same way for a document that is not a ComicInfo", async () => {
    const reading = await readCbz(
      await buildCbz({ info: "<html><body>nope</body></html>" }),
    );

    expect(verdict(reading)).toBe("read: null");
  });

  it("answers the same way for a document that will not parse", async () => {
    const reading = await readCbz(await buildCbz({ info: "<ComicInfo>" }));

    expect(verdict(reading)).toBe("read: null");
  });
});

describe("a file that is not an archive", () => {
  it("is the one thing this reader calls a failure", async () => {
    expect(verdict(await readCbz(new Blob([bytes("just some text")])))).toBe(
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

    expect(verdict(await readCbz(zip))).toBe("protected");
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

    expect(verdict(await readCbz(zip))).toBe("damaged");
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

    expect(verdict(await readCbz(zip))).toBe("unsupported");
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

    expect(verdict(reading)).toBe("too-large");
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

    expect(verdict(reading)).toBe("too-large");
  });
});

describe("the document itself", () => {
  it("refuses one that declares its own entities", () => {
    // The same exposure the package document has and the same refusal, through
    // `xmlEntities.declaresEntities`: expansion happens inside the engine's
    // parser, before any code here has a node to bound.
    const declaring = `<?xml version="1.0"?>
<!DOCTYPE ComicInfo [<!ENTITY s "Saga">]>
<ComicInfo><Series>&s;</Series><Number>12</Number></ComicInfo>`;

    expect(readComicInfo(declaring)).toBeNull();
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

  it("reads the genre whole and never splits it on its comma", () => {
    // **The decision this reader had to take and the one a tidy up would
    // reverse**, `Writer` two arms above being split on exactly that comma.
    // The destination decides it: `books.categories` holds values that
    // routinely contain a comma, Google's own subjects being "Fiction,
    // general", which is why the column joins on a semicolon at all. A
    // splitter here would cut the one shape the column exists to hold whole.
    const record = readComicInfo(
      comicInfo(`<Genre>Science Fiction, Space Opera</Genre>`),
    );

    expect(record?.categories).toEqual(["Science Fiction, Space Opera"]);
  });

  it("states no genre for a comic that declared none", () => {
    // The other side, without which the arm above is satisfied by a reader
    // that answers the empty list to everything.
    expect(
      readComicInfo(comicInfo(`<Series>Saga</Series>`))?.categories,
    ).toEqual([]);
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
          `<Writer>Nobody</Writer><Genre>Not A Genre</Genre></Pages>` +
          `<Series>Saga</Series>`,
      ),
    );

    expect(record?.seriesName).toBe("Saga");
    expect(record?.authors).toEqual([]);
    // The field added last, asked the same question: a subtree search would
    // let a crafted page element assert a subject on somebody's book.
    expect(record?.categories).toEqual([]);
  });
});

/** Names a comic archive's entries go by, the ones this reader looks for first. */
const COMIC_NAMES = fc.oneof(
  fc.constantFrom(
    "ComicInfo.xml",
    "Saga 012/comicinfo.XML",
    "page-001.jpg",
    "comicinfo.xml/",
  ),
  fc.string({ maxLength: 10 }),
);

/** Documents the entry holds: whole, over the cap, refusing, and not XML. */
const COMIC_DOCUMENTS: fc.Arbitrary<Payload> = fc.oneof(
  {
    arbitrary: fc.constantFrom<Payload>(WHOLE, OVER_THE_CAP, comicInfo("")),
    weight: 2,
  },
  {
    arbitrary: fc.constantFrom<Payload>(
      `<?xml version="1.0"?><!DOCTYPE c [<!ENTITY e "x">]><ComicInfo>&e;</ComicInfo>`,
      "<ComicInfo",
      "",
    ),
    weight: 1,
  },
  { arbitrary: zeroesAt([MAX_COMIC_INFO_BYTES]), weight: 1 },
);

/**
 * Any archive, or one whose document is a bomb aimed at its ceiling: weighted
 * so a run from any seed draws the bomb, which independent draws reach on a
 * few runs in a hundred.
 */
const comicArchive = fc.oneof(
  {
    arbitrary: archiveSpec(
      entrySpec(COMIC_NAMES, COMIC_DOCUMENTS, [MAX_COMIC_INFO_BYTES]),
    ),
    weight: 3,
  },
  { arbitrary: aimedArchive("ComicInfo.xml", MAX_COMIC_INFO_BYTES), weight: 1 },
);

/**
 * `readCbz` as a door. **The aggregate beside the per inflater bound**,
 * because the PDF defect was a bound on each step and none on the sum: the
 * reader reads one entry today, and a change reading a second matching entry,
 * or falling back to the next on an unreadable one, multiplies what it spends
 * by the entries an archive holds. One inflater costs a correct reader nothing
 * under it.
 */
const door: Door<ArchiveSpec, CbzReading> = {
  module: cbz,
  ceilings: () => ({
    perInflate: MAX_COMIC_INFO_BYTES,
    inflated: MAX_COMIC_INFO_BYTES,
    refusesEntities: true,
  }),
  build: buildZip,
  open: (file) => readCbz(file),
};

/** The entry `readCbz` reads: the first whose basename is the document's. */
function comicInfoEntry(spec: ArchiveSpec): EntrySpec | undefined {
  return spec.entries.find(
    (entry) => entry.name.toLowerCase().split("/").pop() === "comicinfo.xml",
  );
}

describe("any comic archive a member picks", () => {
  it(
    "is read or refused by name, inflating no chunk past the document's ceiling",
    PROPERTY,
    async () => {
      expect(
        await holds(
          hostile(comicArchive),
          async (input) => expectNamedOutcome(door, input),
          {
            "stopped a bomb at the document's ceiling": (_, { counted }) =>
              stoppedAt(counted, MAX_COMIC_INFO_BYTES),
          },
        ),
      ).toBe(PROFILE.runs);
    },
  );

  it("is metered, so the ceiling above is not held over nothing", async () => {
    const { outcome, counted } = await expectNamedOutcome(door, {
      spec: { entries: [{ name: "ComicInfo.xml", data: WHOLE }] },
      patches: [],
    });

    expect(outcome).toMatchObject({
      answered: { ok: true, metadata: { title: "The Will" } },
    });
    expect(counted.inflaters).toBe(1);
    expect(counted.inflated).toBeGreaterThan(0);
  });

  it("declares the ceilings it is held to, so one deleted or loosened reds", async () => {
    expect(
      await overrunBreach(door, {
        ceiling: "perInflate",
        bound: MAX_COMIC_INFO_BYTES,
      }),
    ).toContain(`against a bound of ${MAX_COMIC_INFO_BYTES}`);
    expect(
      await overrunBreach(door, {
        ceiling: "inflated",
        bound: MAX_COMIC_INFO_BYTES,
        each: MAX_COMIC_INFO_BYTES,
      }),
    ).toContain(`inflated against a ceiling of ${MAX_COMIC_INFO_BYTES}`);
    expect(await overrunBreach(door, { ceiling: "refusesEntities" })).toContain(
      "declaring an entity",
    );
  });

  it("draws a bomb where the reader looks for the document", async () => {
    await witness(hostile(comicArchive), {
      "puts a bomb where the reader looks for the document": ({
        spec,
        patches,
      }) => {
        const entry = comicInfoEntry(spec);
        return (
          patches.length === 0 &&
          entry !== undefined &&
          isBomb(entry, MAX_COMIC_INFO_BYTES)
        );
      },
    });
  });
});

/**
 * `readComicInfo` as a door: a document in, a record or `null` out.
 *
 * **Held at the parser door the meter counts**: no XML parse is handed a
 * declaration. What the property draws is a tree over this reader's own
 * names, mostly grafted into one it accepts, so its walk behind the root is
 * reached, and damage no tree can express inserted on top.
 */
const xmlDoor: ValueDoor<XmlDocument, FileMetadata | null> = {
  module: cbz,
  ceilings: () => ({ refusesEntities: true }),
  open: (document) => readComicInfo(renderXml(document)),
};

describe("any ComicInfo document a comic carries", () => {
  it(
    "is read or refused, and never parsed while it declares an entity",
    PROPERTY,
    async () => {
      expect(
        await holds(xmlDocument(COMIC_INFO), async (document) => {
          await expectAnswer(xmlDoor, document);
        }),
      ).toBe(PROFILE.runs);
    },
  );

  it("is metered, so the parse ceilings above are not held over nothing", async () => {
    const { outcome, counted } = await expectAnswer(xmlDoor, {
      declaration: "none",
      root: COMIC_INFO.accepted,
      insertions: [],
      padTo: undefined,
    });

    expect(outcome).toMatchObject({ answered: { title: "Saga #1" } });
    expect(counted.parses).toBe(1);
  });

  it("declares the parse ceiling it is held to, so deleting it reds", async () => {
    // **The positive control for a door handed a value**: a stub hands the
    // meter's parser a declaring document through this door's own ceilings.
    expect(
      await overrunBreach(xmlDoor, { ceiling: "refusesEntities" }),
    ).toContain("declaring an entity");
  });

  it("draws documents it reads, and documents that declare", async () => {
    // **Asked of the reader rather than of the tree**: whether a drawn
    // document is one this reader reads is the reader's to say, and a
    // vocabulary that stopped matching it is what turns this red.
    await witness(xmlDocument(COMIC_INFO), {
      "the reader reads": async (document) => {
        if (document.padTo !== undefined) return false;
        const { outcome } = await expectAnswer(xmlDoor, document);
        return "answered" in outcome && outcome.answered !== null;
      },
      "declares an entity": declares,
    });
  });
});
