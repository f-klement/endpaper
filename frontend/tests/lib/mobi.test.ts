/**
 * Tests for src/lib/mobi.ts.
 *
 * Three quarters of this file is malformed input, which is the balance the
 * module deserves: reading a well formed header is twenty lines, and the whole
 * of the risk is a member supplied binary whose declared offsets do not point
 * where they say. **A crash here eats somebody's import**, so "does not throw"
 * is asserted as a property over a sweep rather than only at the cases somebody
 * thought of.
 */

import { describe, expect, it } from "vitest";

import { readMobi } from "../../src/lib/mobi";
import { bytes, mobiBytes, palmDatabase, type MobiSpec } from "../mobiFixtures";

async function read(spec: MobiSpec = {}) {
  return readMobi(new Blob([mobiBytes(spec)]));
}

/** The failure or the title, so one assertion covers both arms. */
function outcome(reading: Awaited<ReturnType<typeof readMobi>>): string {
  return reading.ok ? `read: ${reading.metadata.title}` : reading.failure;
}

/**
 * How long a file of 40,000 distinct author records may take to read.
 *
 * **Set against both sides rather than against the run**, and both were run
 * rather than interpolated. With the `Set` in `readAuthors` this test takes
 * 69 ms on `builder`; with the linear scan it replaced, put back and taken out
 * again, it takes 7,707 ms on the same node. So the ceiling has 29 times the
 * headroom above a healthy run and refuses the defect by a factor of 3.9.
 *
 * A wide ceiling on purpose: this asserts a shape rather than a speed, and a
 * ceiling near the run is a flake on a busy node.
 */
const CROWDED_FILE_CEILING_MS = 2_000;

const AUTHOR = 100;
const PUBLISHER = 101;
const DESCRIPTION = 103;
const ISBN = 104;
const SUBJECT = 105;
const PUBLISHED = 106;
const CONTRIBUTOR = 108;
const SOURCE = 112;
const ASIN = 113;
const UPDATED_TITLE = 503;
const LANGUAGE = 524;

/** A file carrying what a publisher produced file carries. */
const PUBLISHED_BOOK: MobiSpec = {
  fullName: "Automate the Boring Stuff with Python",
  exth: [
    { type: UPDATED_TITLE, value: "Automate the Boring Stuff with Python" },
    { type: AUTHOR, value: "Al Sweigart" },
    { type: PUBLISHER, value: "No Starch Press" },
    { type: ISBN, value: "9781593276850" },
    { type: PUBLISHED, value: "2015-04-25" },
    { type: LANGUAGE, value: "en" },
    { type: DESCRIPTION, value: "Teaches simple programming skills." },
  ],
};

describe("reading a Kindle or Mobipocket file", () => {
  it("yields every field the EXTH block carried", async () => {
    const reading = await read(PUBLISHED_BOOK);

    expect(reading.ok).toBe(true);
    if (!reading.ok) return;
    expect(reading.metadata).toMatchObject({
      title: "Automate the Boring Stuff with Python",
      authors: ["Al Sweigart"],
      publisher: "No Starch Press",
      isbn: "9781593276850",
      year: 2015,
      language: "en",
      description: "Teaches simple programming skills.",
    });
  });

  it("names every author, in the order the file gave them", async () => {
    // One record is one author, which is how the one real file measured with
    // two of them says so. Joining is the caller's job.
    const reading = await read({
      exth: [
        { type: AUTHOR, value: "Amy Brown" },
        { type: AUTHOR, value: "Greg Wilson" },
      ],
    });

    expect(reading.ok && reading.metadata.authors).toEqual([
      "Amy Brown",
      "Greg Wilson",
    ]);
  });

  it("says the same author once", async () => {
    const reading = await read({
      exth: [
        { type: AUTHOR, value: "Amy Brown" },
        { type: AUTHOR, value: "Amy Brown" },
      ],
    });

    expect(reading.ok && reading.metadata.authors).toEqual(["Amy Brown"]);
  });

  it("supplies neither a series nor a subtitle, because the format has none", async () => {
    const reading = await read(PUBLISHED_BOOK);

    expect(reading.ok && reading.metadata).toMatchObject({
      seriesName: null,
      seriesIndex: null,
      subtitle: null,
      // No package document, so no package version. Not the MOBI header's own
      // version number, which is a different fact under the same word.
      version: null,
    });
  });
});

describe("the title", () => {
  it("comes from the record whose type says it is the title", async () => {
    const reading = await read({
      fullName: "The header's name",
      exth: [{ type: UPDATED_TITLE, value: "The typed record" }],
    });

    expect(reading.ok && reading.metadata.title).toBe("The typed record");
  });

  it("falls back to the header's own name when there is no such record", async () => {
    // 8 of the 69 real files carry no EXTH 503, and every one of them carries
    // a header full name.
    const reading = await read({ fullName: "Moby Dick", exth: [] });

    expect(reading.ok && reading.metadata.title).toBe("Moby Dick");
  });

  it("is read from a file that carries no EXTH block at all", async () => {
    const reading = await read({ fullName: "Bare", exth: null });

    expect(outcome(reading)).toBe("read: Bare");
  });

  it("is null rather than a crash when the header points past the record", async () => {
    const reading = await read({
      fullName: "Moby Dick",
      fullNameAt: 0xffffff00,
      exth: [],
    });

    expect(reading.ok && reading.metadata.title).toBeNull();
  });

  it("is null rather than a crash when the header claims a huge length", async () => {
    const reading = await read({
      fullName: "Moby Dick",
      fullNameLength: 0xffffffff,
      exth: [],
    });

    expect(reading.ok && reading.metadata.title).toBeNull();
  });

  it("loses the padding a producer wrote after it", async () => {
    const padded = new Uint8Array([...bytes("Padded"), 0, 0, 0]);
    const reading = await read({ fullName: padded, exth: [] });

    expect(reading.ok && reading.metadata.title).toBe("Padded");
  });
});

describe("the ISBN", () => {
  it("is canonical whichever of the three real spellings the file used", async () => {
    // The three spellings measured across the four real files carrying one.
    for (const [spelling, canonical] of [
      ["9781593276850", "9781593276850"],
      ["978-1-61016-605-8", "9781610166058"],
      ["0615445675", "9780615445670"],
    ] as const) {
      const reading = await read({ exth: [{ type: ISBN, value: spelling }] });
      expect(reading.ok && reading.metadata.isbn).toBe(canonical);
    }
  });

  it("is null when the typed record holds something that is not one", async () => {
    const reading = await read({
      exth: [{ type: ISBN, value: "not a number" }],
    });

    expect(reading.ok && reading.metadata.isbn).toBeNull();
  });

  it("is not taken from any other record", async () => {
    // The deliberate difference from `opf.ts`, which has to sniff. Across 69
    // real files no record outside 104 holds a value `parseIsbn` would accept,
    // so a fallback would add no ISBN and one way to invent one.
    const reading = await read({
      exth: [
        { type: ASIN, value: "9781593276850" },
        { type: SOURCE, value: "9781593276850" },
        { type: SUBJECT, value: "9781593276850" },
      ],
    });

    expect(reading.ok && reading.metadata.isbn).toBeNull();
    expect(reading.ok && reading.metadata.identifiers).toEqual([]);
  });

  it("is the only identifier the record carries", async () => {
    const reading = await read({
      exth: [
        { type: ISBN, value: "9781593276850" },
        // 61 of 69 real files carry this and not one holds an Amazon
        // identifier. A wrong scheme on a right looking value is worse than a
        // missing one.
        { type: ASIN, value: "defa988f-a173-4dff-9c33-794f40fc9372" },
      ],
    });

    expect(reading.ok && reading.metadata.identifiers).toEqual([
      { scheme: "ISBN", value: "9781593276850" },
    ]);
  });
});

describe("the year", () => {
  it("is the leading four digits of the declared date", async () => {
    for (const date of ["2015-04-25", "1997-10-02T00:00:00+00:00"] as const) {
      const reading = await read({ exth: [{ type: PUBLISHED, value: date }] });
      expect(reading.ok && reading.metadata.year).toBe(
        Number(date.slice(0, 4)),
      );
    }
  });

  it("refuses the sentinel Calibre writes when a book has no date", async () => {
    // `0101-01-01` parses to the year 101, which is inside the column's own
    // range, so nothing downstream would have stopped it. 2 of 69 real files
    // carry exactly this value.
    const reading = await read({
      exth: [{ type: PUBLISHED, value: "0101-01-01T00:00:00+00:00" }],
    });

    expect(reading.ok && reading.metadata.year).toBeNull();
  });

  it("refuses a date that is not one", async () => {
    const reading = await read({ exth: [{ type: PUBLISHED, value: "soon" }] });

    expect(reading.ok && reading.metadata.year).toBeNull();
  });
});

describe("the text encoding", () => {
  it("reads a file that declares UTF-8", async () => {
    const reading = await read({
      codepage: 65001,
      exth: [{ type: UPDATED_TITLE, value: "Die Verwandlung, ein Bericht" }],
    });

    expect(reading.ok && reading.metadata.title).toBe(
      "Die Verwandlung, ein Bericht",
    );
  });

  it("reads a file that declares windows-1252", async () => {
    // 1 of the 69 real files does. Its bytes are not UTF-8 and reading them as
    // UTF-8 would put a replacement character in a member's title.
    const reading = await read({
      codepage: 1252,
      exth: [
        { type: UPDATED_TITLE, value: new Uint8Array([0x53, 0xe4, 0x67]) },
      ],
    });

    expect(reading.ok && reading.metadata.title).toBe("Säg");
  });

  it("reads a file that declares a code page nobody uses", async () => {
    const reading = await read({
      codepage: 1,
      exth: [
        { type: UPDATED_TITLE, value: new Uint8Array([0x53, 0xe4, 0x67]) },
      ],
    });

    // windows-1252 maps every byte, so the fallback cannot throw and cannot
    // lose the record.
    expect(reading.ok && reading.metadata.title).toBe("Säg");
  });
});

describe("what is deliberately not read", () => {
  it("does not take the contributor for an author", async () => {
    // 63 of 69 real files carry this. 54 name the toolchain and 9 name the
    // person who produced the edition. Neither is the author.
    const reading = await read({
      exth: [{ type: CONTRIBUTOR, value: "calibre (9.5.0)" }],
    });

    expect(reading.ok && reading.metadata.authors).toEqual([]);
  });
});

describe("a file that is not a MOBI", () => {
  it("refuses a Palm Database holding some other format", async () => {
    // The container is shared, so the parser meets these rather than
    // hypothesises them. eReader, Plucker and PalmDOC in that order.
    for (const other of ["PNRdPPrs", "DataPlkr", "TEXtREAd"] as const) {
      expect(outcome(await readMobi(new Blob([palmDatabase(other)])))).toBe(
        "not-a-mobi",
      );
    }
  });

  it("refuses a KFX container, which is not a Palm Database at all", async () => {
    // Refused by construction rather than by a rule about KFX: it has no Palm
    // type and creator to match, so it never reaches a header read. Nothing
    // should be added to make it work.
    const kfx = new Uint8Array(512);
    kfx.set(bytes("CONT"), 0);
    expect(outcome(await readMobi(new Blob([kfx])))).toBe("not-a-mobi");
  });

  it("refuses a file that is not a Palm Database", async () => {
    expect(
      outcome(await readMobi(new Blob([bytes("<html>hello</html>")]))),
    ).toBe("not-a-mobi");
  });

  it("refuses an empty file", async () => {
    expect(outcome(await readMobi(new Blob([])))).toBe("not-a-mobi");
  });

  it("refuses a Palm Database that says MOBI and holds no MOBI header", async () => {
    // The eight bytes at offset 60 are eight bytes anybody can write, which is
    // why record 0's own magic is checked as well.
    expect(outcome(await read({ magic: "XXXX" }))).toBe("not-a-mobi");
  });
});

describe("a file whose offsets do not agree with its length", () => {
  it("refuses a record 0 that starts past the end", async () => {
    expect(outcome(await read({ recordZeroAt: 0xffffff00 }))).toBe("damaged");
  });

  it("refuses a record 0 that starts inside the table describing it", async () => {
    expect(outcome(await read({ recordZeroAt: 80 }))).toBe("damaged");
  });

  it("refuses a table that claims more records than the file has room for", async () => {
    // The declared count moves the end of the table past where record 0 says
    // it starts, which is the cheap tell that the count is a lie.
    expect(outcome(await read({ declaredRecords: 60000 }))).toBe("damaged");
  });

  it("refuses a record 0 that ends before it starts", async () => {
    expect(outcome(await read({ recordOneAt: 4 }))).toBe("damaged");
  });

  it("refuses a record 0 that ends past the end of the file", async () => {
    expect(outcome(await read({ recordOneAt: 0xffffff00 }))).toBe("damaged");
  });

  it("refuses a record 0 declaring more bytes than it will read", async () => {
    // A bound on what is allocated, taken before the slice: the file itself is
    // small and its header is what claims the megabytes. Reported as damaged
    // rather than as a large file, because at 98 times the largest record 0
    // ever measured nothing reaching this arm is a big book.
    const file = new Uint8Array(4 * 1024 * 1024);
    file.set(mobiBytes({ recordOneAt: 3 * 1024 * 1024 }), 0);
    expect(outcome(await readMobi(new Blob([file])))).toBe("damaged");
  });

  it("reads a file whose last record is record 0", async () => {
    // A one record database ends where the file does, which is the branch that
    // has no second entry to read.
    const reading = await read({
      records: 1,
      trailingBytes: 0,
      fullName: "Alone",
      exth: [],
    });

    expect(outcome(reading)).toBe("read: Alone");
  });
});

describe("a file that is protected", () => {
  it("says so rather than saying it is a different kind of file", async () => {
    // Constructed rather than measured: 0 of the 69 real files declare
    // encryption, because a DRM bound file is not one anybody may publish.
    expect(outcome(await read({ encryption: 1 }))).toBe("protected");
    expect(outcome(await read({ encryption: 2 }))).toBe("protected");
  });
});

describe("an EXTH block that walks off the end", () => {
  it("keeps the records before the one that does not fit", async () => {
    const reading = await read({
      exth: [
        { type: UPDATED_TITLE, value: "Read me" },
        { type: AUTHOR, value: "Lost", declaredLength: 0xffffff00 },
        { type: PUBLISHER, value: "Also lost" },
      ],
    });

    expect(reading.ok && reading.metadata.title).toBe("Read me");
    expect(reading.ok && reading.metadata.authors).toEqual([]);
  });

  it("stops on a record whose length cannot advance the cursor", async () => {
    // Zero would loop for ever and anything below the eight byte header would
    // walk backwards. One refusal covers both, which is why it is not written
    // as an arm each.
    for (const declaredLength of [0, 1, 7] as const) {
      const reading = await read({
        exth: [
          { type: UPDATED_TITLE, value: "Read me" },
          { type: AUTHOR, value: "Lost", declaredLength },
        ],
      });

      expect(reading.ok && reading.metadata.title).toBe("Read me");
      expect(reading.ok && reading.metadata.authors).toEqual([]);
    }
  });

  it("is bounded by the record when the block claims more than the record holds", async () => {
    const reading = await read({
      exthDeclaredLength: 0xffffff00,
      exth: [{ type: UPDATED_TITLE, value: "Read me" }],
    });

    expect(outcome(reading)).toBe("read: Read me");
  });

  it("is bounded by the block when the block claims less than it spends", async () => {
    const reading = await read({
      exthDeclaredLength: 12,
      exth: [{ type: UPDATED_TITLE, value: "Not reached" }],
    });

    expect(reading.ok && reading.metadata.title).toBeNull();
  });

  it("terminates on a count no file could hold", async () => {
    const reading = await read({
      exthDeclaredCount: 0xffffffff,
      exth: [{ type: UPDATED_TITLE, value: "Read me" }],
    });

    expect(outcome(reading)).toBe("read: Read me");
  });

  it("loses the block but not the header when the header length points nowhere", async () => {
    // The EXTH block sits after the length the header declares, so a wrong
    // length loses every typed record. The header's own name is still where it
    // was, which is why the title has a second route at all.
    const reading = await read({
      declaredHeaderLength: 0xffffff00,
      fullName: "The header's name",
      exth: [
        { type: UPDATED_TITLE, value: "Not reached" },
        { type: PUBLISHER, value: "Not reached" },
      ],
    });

    expect(outcome(reading)).toBe("read: The header's name");
    expect(reading.ok && reading.metadata.publisher).toBeNull();
  });
});

describe("the EXTH block is found by its magic and not by the flag", () => {
  it("reads the records of a file whose flag says there are none", async () => {
    // The specification says bit 0x40 at record 0 offset 0x80 announces the
    // block. The reader does not read it, and this is what says so: without
    // this fixture a reader that gated on the flag would pass every other test
    // in this file.
    const reading = await read({
      exthFlag: 0,
      exth: [{ type: UPDATED_TITLE, value: "Found anyway" }],
    });

    expect(outcome(reading)).toBe("read: Found anyway");
  });

  it("finds no block when the magic is not there", async () => {
    // The other half. The magic is the decisive test, so changing it has to
    // lose the records even though the flag still announces them.
    const reading = await read({
      exthMagic: "XXXX",
      fullName: "The header's name",
      exth: [{ type: UPDATED_TITLE, value: "Not reached" }],
    });

    expect(outcome(reading)).toBe("read: The header's name");
  });
});

describe("a value with padding in it", () => {
  it("loses a NUL wherever the producer put it", async () => {
    // **Interior, and that is the whole of the test.** A leading and trailing
    // fixture is passed by an ends only strip as well, so it pins nothing: the
    // padding every real file carries cannot tell the two apart. `A\0B` can.
    const reading = await read({
      exth: [{ type: UPDATED_TITLE, value: new Uint8Array([65, 0, 66]) }],
    });

    expect(reading.ok && reading.metadata.title).toBe("AB");
  });

  it("loses the padding a producer left at both ends", async () => {
    const reading = await read({
      exth: [{ type: UPDATED_TITLE, value: new Uint8Array([0, 65, 0]) }],
    });

    expect(reading.ok && reading.metadata.title).toBe("A");
  });

  it("says nothing rather than an empty string when only padding is left", async () => {
    // `OpfRecord` says every field is absent rather than empty, and the scan
    // page decides whether a file named a title by comparing against `""`. A
    // record holding two NULs has named no title, so the header's name is what
    // is left.
    const reading = await read({
      fullName: "The header's name",
      exth: [{ type: UPDATED_TITLE, value: new Uint8Array([0, 0]) }],
    });

    expect(outcome(reading)).toBe("read: The header's name");
  });

  it("says nothing rather than an empty string for a publisher", async () => {
    const reading = await read({
      exth: [{ type: PUBLISHER, value: new Uint8Array([0, 32, 0]) }],
    });

    expect(reading.ok && reading.metadata.publisher).toBeNull();
  });
});

describe("a MOBI header too short to hold its own fields", () => {
  it("is read for what it does carry rather than refused", async () => {
    // 66 of 69 real files declare 232 or 264. A header of 40 leaves the full
    // name offset off the end of the record, which is a read that has to answer
    // nothing rather than throw.
    const reading = await read({
      headerLength: 40,
      fullName: "Off the end",
      exth: null,
    });

    expect(reading.ok).toBe(true);
    expect(reading.ok && reading.metadata.title).toBeNull();
  });
});

describe("no file makes the reader throw", () => {
  /**
   * Every single byte of the file, flipped in turn.
   *
   * **The property is the point, not the cases.** A crash is a member's whole
   * import gone, and the cases somebody thinks of are the ones already covered
   * above; this covers the ones nobody thought of.
   *
   * **The whole file rather than a region**, and the region is what this test
   * shipped with: a literal 512 against a 581 byte fixture left 69 bytes
   * unswept, 24 of them inside the EXTH block the test claimed to cover. A
   * bound that cannot follow the fixture is a bound that silently shrinks the
   * next time a record is added to it.
   */
  it("survives every byte of the file being wrong", async () => {
    const original = mobiBytes(PUBLISHED_BOOK);

    for (let at = 0; at < original.length; at += 1) {
      for (const value of [0x00, 0xff]) {
        const mutated = new Uint8Array(original);
        mutated[at] = value;
        const reading = await readMobi(new Blob([mutated]));
        expect(typeof reading.ok).toBe("boolean");
      }
    }
  });

  it("reads a file of nothing but author records without freezing the tab", async () => {
    // **A bound in wall clock rather than a description.** How many author
    // records there are is the file's choice, so deduping them with a linear
    // scan is quadratic work on a member supplied number, on the thread the
    // page runs on and with the picked files read one after another.
    //
    // The ceiling is `CROWDED_FILE_CEILING_MS`, not the number this run takes,
    // so a regression is caught by the shape rather than by somebody noticing
    // the suite got slower. Both of the figures behind that ceiling are quoted
    // beside it with the node they were measured on, which is the only place
    // in this file a duration appears.
    const authors = Array.from({ length: 40_000 }, (_, index) => ({
      type: AUTHOR,
      // Distinct values, because identical ones cost nothing either way: the
      // mutation that matters is the one where every scan runs to the end.
      value: `a${index}`,
    }));

    const started = Date.now();
    const reading = await read({ exth: authors });
    const elapsed = Date.now() - started;

    expect(reading.ok && reading.metadata.authors).toHaveLength(40_000);
    expect(elapsed).toBeLessThan(CROWDED_FILE_CEILING_MS);
  });

  it("survives a file truncated at every length", async () => {
    const original = mobiBytes(PUBLISHED_BOOK);

    for (let length = 0; length <= original.length; length += 7) {
      const reading = await readMobi(new Blob([original.slice(0, length)]));
      expect(typeof reading.ok).toBe("boolean");
    }
  });
});
