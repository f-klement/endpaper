/**
 * @vitest-environment jsdom
 *
 * jsdom for `tests/lib/epub.test.ts`'s reason: the reader ends in a package
 * document parse, and happy-dom's `DOMParser` does not parse every real one.
 * The sidecar is parsed as HTML, which both environments do.
 */
/**
 * Tests for src/lib/takeout.ts.
 *
 * **Nothing here came out of the archive it was written against**, which is one
 * member's own library. `takeoutFixtures.ts` states what was taken from it: the
 * structure, on 2026-09-10, and no content.
 *
 * What is worth asserting is which of the archive's own lies the reader
 * believes. It is handed files named `.pdf` that are EPUBs, two books in one
 * folder, a folder name in a language it cannot read, and one book whose
 * signature is two bytes wrong.
 */

import { describe, expect, it } from "vitest";

import { readTakeoutArchive } from "../../src/lib/takeout";
import {
  buildEpub,
  buildZip,
  bytes,
  CONTAINER_XML,
  STORED,
  type EntrySpec,
} from "../zipFixtures";
import {
  A_VOLUME_ID,
  FINISHED_SENTENCE,
  hugePackage,
  LIBRARY_FOLDER,
  padding,
  sidecar,
  takeoutFile,
  type BookSpec,
} from "./takeoutFixtures";

async function read(books: BookSpec[] = [{}], extra: EntrySpec[] = []) {
  return readTakeoutArchive(await takeoutFile(books, extra));
}

/** The library, or a failure named, so one assertion covers both arms. */
function library(reading: Awaited<ReturnType<typeof readTakeoutArchive>>) {
  if (!reading.ok) throw new Error(`refused the archive: ${reading.failure}`);
  return reading.library;
}

describe("reading the library out of an archive", () => {
  it("reads a book whose file is named .pdf and is an EPUB", async () => {
    // The whole shape of this reader in one assertion: 24 of the 24 books in
    // the export it was written against are named `.pdf` and every one is a
    // zip whose mimetype says `application/epub+zip`. A reader deciding by the
    // suffix reads none of them.
    const found = library(await read());
    expect(found.books).toHaveLength(1);
    expect(found.books[0]?.metadata.title).toBe("Dune");
  });

  it("reads a book whose file is named .epub", async () => {
    // What Google correcting the extension would produce. The sniff asks the
    // bytes, so the day that happens costs nothing.
    const found = library(await read([{ suffix: ".epub" }]));
    expect(found.books).toHaveLength(1);
  });

  it("carries the volume id, which is the only identifier the archive has", async () => {
    const found = library(await read());
    expect(found.books[0]?.volumeId).toBe(A_VOLUME_ID);
    expect(found.books[0]?.metadata.isbn).toBeNull();
  });

  it("keeps two books that share a folder and differ by a suffixed name", async () => {
    // Measured in that export: two titles appear twice, the second file named
    // `Title(1)`, and the two carry different volume ids. Anything keyed on the
    // folder, or on the title, files them as one book and loses an edition.
    const found = library(
      await read([
        { name: "Dune", sidecar: { volumeId: "aaaaaaaaaaaa" } },
        {
          name: "Dune(1)",
          sidecar: { title: "Dune", volumeId: "bbbbbbbbbbbb" },
        },
      ]),
    );
    expect(found.books.map((book) => book.volumeId)).toEqual([
      "aaaaaaaaaaaa",
      "bbbbbbbbbbbb",
    ]);
  });

  it("finds the library whatever language the folder name is in", async () => {
    // Takeout localises its folder names, so the signature is the pair and the
    // volume id in it rather than the words `Google Play Books`.
    const zip = await buildZip({
      entries: [
        { name: "Takeout/Google Play Bücher/Dune/Dune.html", data: sidecar() },
        {
          name: "Takeout/Google Play Bücher/Dune/Dune.pdf",
          data: await buildEpub(),
        },
      ],
    });
    const found = library(await readTakeoutArchive(new Blob([zip])));
    expect(found.books).toHaveLength(1);
    expect(found.books[0]?.volumeId).toBe(A_VOLUME_ID);
  });
});

describe("what the sidecar says", () => {
  it("takes the author from the line under the label", async () => {
    const found = library(
      await read([{ sidecar: { author: "Ursula K. Le Guin" } }]),
    );
    expect(found.books[0]?.author).toBe("Ursula K. Le Guin");
  });

  it("reports no author where the sidecar's author line is empty", async () => {
    // One book in 24 had this, and its title named the scanner rather than a
    // person. Reading an author out of a title would have invented one.
    const found = library(
      await read([{ sidecar: { author: "", title: "Scanned by a library" } }]),
    );
    expect(found.books[0]?.author).toBeNull();
    expect(found.books[0]?.title).toBe("Scanned by a library");
  });

  it("says a book was finished where the sidecar says so", async () => {
    const found = library(
      await read([{ sidecar: { state: FINISHED_SENTENCE } }]),
    );
    expect(found.books[0]?.finished).toBe(true);
  });

  it("says a book was not finished where the sidecar says nothing", async () => {
    expect(library(await read()).books[0]?.finished).toBe(false);
  });

  it("says nothing about a reading state it could not read", async () => {
    // The sentence is prose in the language the export was taken in. An export
    // this reader cannot read the state out of is not an export saying the
    // member did not finish the book.
    const found = library(
      await read([{ sidecar: { state: "Du hast dieses Buch beendet." } }]),
    );
    expect(found.books[0]?.finished).toBeNull();
  });

  it("counts annotations without carrying a word of them", async () => {
    const found = library(
      await read([{ sidecar: { annotations: ["", "my own note"] } }]),
    );
    expect(found.books[0]?.annotations).toBe(2);
    expect(JSON.stringify(found.books[0])).not.toContain("my own note");
    expect(JSON.stringify(found.books[0])).not.toContain("a passage");
  });

  it("does not read the store link, which is an anchor and not a div", async () => {
    // The link carries `class="meta-entry"` too, so `readSidecar` asking for
    // `div.meta-entry` is the only thing keeping it out. Given a body of the
    // shape a volume id has, widening that selector by one character would
    // take this as the id of a second book and, failing that, as an
    // unidentified metadata line that turns `finished` into `null`. Both are
    // asserted, because the first alone passes on the second going wrong.
    const found = library(
      await read([{ sidecar: { storeLink: "Volume ID\nzzzzzzzzzzzz" } }]),
    );
    expect(found.books[0]?.volumeId).toBe(A_VOLUME_ID);
    expect(found.books[0]?.finished).toBe(false);
  });
});

describe("deciding what a file is by its content", () => {
  it("refuses a mimetype entry carrying a trailing newline", async () => {
    // 1 of the 24 measured. OCF asks for that entry stored, first and exact,
    // and this is the one book in that export this reader does not take.
    const found = library(
      await read([{ mimetype: "application/epub+zip\r\n" }]),
    );
    expect(found.books).toHaveLength(0);
    expect(found.refused).toEqual([
      {
        path: `${LIBRARY_FOLDER}/Dune/Dune`,
        title: "Dune",
        failure: "not-an-epub",
      },
    ]);
  });

  it("refuses a mimetype entry that is deflated rather than stored", async () => {
    const found = library(await read([{ deflateMimetype: true }]));
    expect(found.refused[0]?.failure).toBe("not-an-epub");
  });

  it("refuses a mimetype entry that is not the first in the archive", async () => {
    const found = library(await read([{ entryBeforeMimetype: true }]));
    expect(found.refused[0]?.failure).toBe("not-an-epub");
  });

  it("refuses a file with no mimetype entry at all", async () => {
    const found = library(await read([{ mimetype: null }]));
    expect(found.refused[0]?.failure).toBe("not-an-epub");
  });

  it("refuses a file that is not an archive", async () => {
    // What an audiobook or a member's uploaded document arrives as: the sidecar
    // template is the same for all three and does not say which this is.
    const found = library(await read([{ file: "%PDF-1.4 not a zip at all" }]));
    expect(found.refused[0]?.failure).toBe("not-an-epub");
  });
});

describe("an entry that cannot be read is one refused book", () => {
  it("imports the other books and names the one it refused", async () => {
    const found = library(
      await read([
        { name: "Dune", sidecar: { volumeId: "aaaaaaaaaaaa" } },
        {
          name: "Neuromancer",
          sidecar: { title: "Neuromancer", volumeId: "bbbbbbbbbbbb" },
          mimetype: "application/epub+zip\r\n",
        },
        { name: "Solaris", sidecar: { volumeId: "cccccccccccc" } },
      ]),
    );
    expect(found.books).toHaveLength(2);
    expect(found.refused.map((one) => one.title)).toEqual(["Neuromancer"]);
  });

  it("answers a library with no books rather than refusing the archive", async () => {
    // `kobo.ts`'s distinction. An export whose every file was refused is a
    // library with nothing readable in it, which is a different sentence from
    // a zip that is not an export at all.
    const reading = await read([{ mimetype: null }]);
    expect(reading.ok).toBe(true);
    expect(library(reading).books).toEqual([]);
    expect(library(reading).refused).toHaveLength(1);
  });
});

describe("what is not a book pair", () => {
  /** A sidecar good enough that only the path can keep its pair out. */
  const escaping = sidecar({ title: "Escaped", volumeId: "eeeeeeeeeeee" });

  it("skips a pair whose sidecar carries no volume id", async () => {
    const found = library(
      await read([
        { name: "Dune" },
        { name: "Notes", sidecar: { volumeId: null } },
      ]),
    );
    expect(found.books).toHaveLength(1);
    expect(found.skipped).toBe(1);
  });

  it("does not read an entry with no sibling of its own name", async () => {
    // Every other Takeout product a member exported that day is this case.
    const found = library(
      await read([{}], [{ name: "Takeout/Mail/all.mbox", data: "from" }]),
    );
    expect(found.books).toHaveLength(1);
    expect(found.skipped).toBe(0);
  });

  it("does not read a name three entries share", async () => {
    const found = library(
      await read(
        [{}],
        [
          { name: "Takeout/Other/x.html", data: "a" },
          { name: "Takeout/Other/x.txt", data: "b" },
          { name: "Takeout/Other/x.csv", data: "c" },
        ],
      ),
    );
    expect(found.books).toHaveLength(1);
    expect(found.skipped).toBe(0);
  });

  it("does not read a group holding two sidecars and one file", async () => {
    // A zip may name one path twice, and taking the first would pick between
    // two titles by directory order. The other arm of that condition, one
    // sidecar and two files, is the test above; this is the arm no fixture
    // reached, and the one a reader relaxing the condition would keep. The
    // ordinary book beside it is what makes the archive a Takeout at all, so
    // the assertion is about the group and not about the answer.
    const twice = sidecar({ volumeId: "bbbbbbbbbbbb" });
    const found = library(
      await read(
        [{ name: "Dune" }],
        [
          { name: "T/Two/Two.html", data: twice },
          { name: "T/Two/Two.html", data: twice },
          { name: "T/Two/Two.pdf", data: await buildEpub() },
        ],
      ),
    );
    expect(found.books.map((book) => book.volumeId)).toEqual([A_VOLUME_ID]);
    expect(found.skipped).toBe(0);
  });

  it("ignores a path that walks out of the directory it names", async () => {
    // Nothing here writes a file, so `../../x` cannot escape onto a disk. What
    // it can do is have this reader report a path outside the archive's own
    // tree back to a member as a book in their export.
    //
    // **The pair below is a readable book in every other respect**, which is
    // the half a first draft of this test left out: a sidecar with its own
    // volume id and a real EPUB beside it. Given rubbish for the file, the
    // path check can be deleted and the entry is still refused, for the wrong
    // reason, and the test passes.
    const found = library(
      await read(
        [{}],
        [
          { name: "Takeout/../../etc/passwd.html", data: escaping },
          { name: "Takeout/../../etc/passwd.pdf", data: await buildEpub() },
        ],
      ),
    );
    expect(found.books.map((book) => book.path)).toEqual([
      `${LIBRARY_FOLDER}/Dune/Dune`,
    ]);
  });

  it("ignores a path escaping with backslashes, which carry no .. segment", async () => {
    // A zip written on Windows separates with backslashes, so `..\..\etc` has
    // no `..` path segment at all and the segment check alone reports it back
    // to a member as a book in their export.
    const found = library(
      await read(
        [{}],
        [
          { name: "Takeout\\..\\..\\etc\\passwd.html", data: escaping },
          { name: "Takeout\\..\\..\\etc\\passwd.pdf", data: await buildEpub() },
        ],
      ),
    );
    expect(found.books.map((book) => book.path)).toEqual([
      `${LIBRARY_FOLDER}/Dune/Dune`,
    ]);
    expect(found.skipped).toBe(0);
  });

  it("ignores a rooted path", async () => {
    const found = library(
      await read(
        [{}],
        [
          { name: "/etc/passwd.html", data: escaping },
          { name: "/etc/passwd.pdf", data: await buildEpub() },
        ],
      ),
    );
    expect(found.books.map((book) => book.path)).toEqual([
      `${LIBRARY_FOLDER}/Dune/Dune`,
    ]);
    expect(found.skipped).toBe(0);
  });
});

describe("an archive that is not one", () => {
  it("refuses something that is not a zip", async () => {
    const reading = await readTakeoutArchive(new Blob([bytes("hello")]));
    expect(reading.ok === false && reading.failure).toBe("not-an-archive");
  });

  it("refuses a zip that carries no book pair", async () => {
    const zip = await buildZip({
      entries: [{ name: "Takeout/Mail/all.mbox", data: "from" }],
    });
    const reading = await readTakeoutArchive(new Blob([zip]));
    expect(reading.ok === false && reading.failure).toBe("not-a-takeout");
  });

  it("refuses an EPUB handed to it on its own", async () => {
    // A member picking one book rather than the archive. It is a zip, and it
    // holds no pair, so it is not a Takeout.
    const reading = await readTakeoutArchive(new Blob([await buildEpub()]));
    expect(reading.ok === false && reading.failure).toBe("not-a-takeout");
  });

  it("does not open an archive nested inside the archive", async () => {
    // The book half of a pair is opened as an EPUB and never walked as a
    // Takeout of its own, so the nesting this reader does is two deep by
    // construction rather than by a depth counter.
    const inner = await takeoutFile();
    const found = library(
      await read([{ file: new Uint8Array(await inner.arrayBuffer()) }]),
    );
    expect(found.books).toHaveLength(0);
    expect(found.refused[0]?.failure).toBe("not-an-epub");
  });
});

describe("what the archive is allowed to inflate to", () => {
  it("refuses a book entry that inflates far past the archive's own size", async () => {
    // A zip bomb: 8 MiB of zeros deflates to a few kilobytes, so the archive
    // stays small and the entry does not. The bound is a ratio rather than a
    // number of bytes, because a real library's total scales with the number of
    // books in it and a ceiling that a large library does not hit is one no
    // bomb hits either. Measured on that export: 1.009.
    const bomb = new Uint8Array(8 * 1024 * 1024);
    const found = library(await read([{ file: bomb }]));
    expect(found.books).toHaveLength(0);
    expect(found.refused[0]?.failure).toBe("too-large");
  });

  it("refuses a sidecar too large to be a page of metadata", async () => {
    // Measured at 3,643 bytes over 24. The padding is what makes this the
    // sidecar's own ceiling rather than the archive's ratio: without it a
    // fixture this small allows only a few kilobytes in total, and the test
    // would pass with the ceiling deleted. A pair whose sidecar will not come
    // out of the archive has not said it is a book, so it is skipped rather
    // than named as a book that was refused.
    const found = library(
      await read(
        [
          { name: "Dune" },
          {
            name: "Huge",
            sidecar: { title: "x".repeat(400 * 1024), volumeId: A_VOLUME_ID },
          },
        ],
        [padding(4 * 1024 * 1024)],
      ),
    );
    expect(found.books).toHaveLength(1);
    expect(found.skipped).toBe(1);
  });

  it("refuses a book file declaring more than one book's worth of bytes", async () => {
    // Measured at 13,528,679 bytes over the 24, and the ceiling is 32 MiB. A
    // declared size is checked before a byte is read, so this costs a fixture
    // of a few kilobytes rather than one of 33 MiB. The padding again puts the
    // archive's own ratio out of the way.
    const found = library(
      await read(
        [{ declaredSize: 33 * 1024 * 1024 }],
        [padding(4 * 1024 * 1024)],
      ),
    );
    expect(found.books).toHaveLength(0);
    expect(found.refused[0]?.failure).toBe("too-large");
  });

  it("reads an ordinary archive without spending its budget", async () => {
    // The floor under the two tests above: a bound that refuses everything
    // passes both of them. Three books, none refused.
    const found = library(
      await read([
        { name: "Dune", sidecar: { volumeId: "aaaaaaaaaaaa" } },
        { name: "Solaris", sidecar: { volumeId: "bbbbbbbbbbbb" } },
        { name: "Ubik", sidecar: { volumeId: "cccccccccccc" } },
      ]),
    );
    expect(found.books).toHaveLength(3);
    expect(found.refused).toEqual([]);
  });
});

describe("the entries it reads", () => {
  it("reads the metadata of a book whose text dwarfs it", async () => {
    // The book file is inflated whole, because a zip is read from its end, and
    // only two entries are taken out of it. What that costs is stated at
    // `MAX_BOOK_BYTES`: one book at a time, released before the next.
    const big = "x".repeat(64 * 1024);
    const found = library(
      await read([
        {
          file: await buildEpub({
            extra: [{ name: "OEBPS/chapter1.xhtml", data: big }],
          }),
        },
      ]),
    );
    expect(found.books[0]?.metadata.title).toBe("Dune");
  });

  it("stores nothing about a book that the sidecar did not name", async () => {
    const found = library(await read());
    expect(Object.keys(found.books[0] ?? {}).sort()).toEqual([
      "annotations",
      "author",
      "finished",
      "metadata",
      "path",
      "title",
      "volumeId",
    ]);
  });
});

describe("a stored mimetype entry", () => {
  it("is what the sniff reads, not the file's name", async () => {
    // The inverse of the first test: a file named `.epub` whose bytes are not
    // one is refused, so the name is not consulted in either direction.
    const notAnEpub = await buildZip({
      entries: [{ name: "mimetype", data: "application/pdf", method: STORED }],
    });
    const found = library(await read([{ suffix: ".epub", file: notAnEpub }]));
    expect(found.refused[0]?.failure).toBe("not-an-epub");
  });
});

describe("what the volume id has to look like", () => {
  it("does not take a twelve character run out of a longer line", async () => {
    // The anchors are the whole of the rule: the value under the label is the
    // id or it is not one. Unanchored, the line below yields `not-a-volume`
    // and a book nobody owns.
    const found = library(
      await read([{ sidecar: { volumeId: "not-a-volume-id-at-all" } }]),
    );
    expect(found.books).toEqual([]);
    expect(found.skipped).toBe(1);
  });

  it("refuses a mimetype of the right length and the wrong bytes", async () => {
    // Twenty bytes, so every length check passes and only the comparison of
    // the bytes themselves is left to refuse it. Every other impostor in this
    // file is refused before that line is reached.
    const found = library(await read([{ mimetype: "application/epub+zi9" }]));
    expect(found.books).toEqual([]);
    expect(found.refused[0]?.failure).toBe("not-an-epub");
  });
});

/**
 * The budget accumulates, which is the half no per entry ceiling can hold.
 *
 * Both tests below are one shape: a first book that inflates most of the
 * allowance, then a second whose sidecar is larger than what is left and
 * smaller than `MAX_SIDECAR_BYTES`, so the only thing that can refuse it is the
 * running total. The padding sets the allowance, since it is 20 times the
 * archive's own size and a fixture is otherwise a few kilobytes.
 *
 * **They differ only in where the first book hides its bytes**, and that is
 * what makes each of them observe one charge. A stored entry inside the EPUB
 * makes the inner zip itself large, which the outer read pays for. A large
 * package document deflates inside the inner zip, so the outer read is a
 * kilobyte and the bytes appear only inside `readEpub`.
 */
describe("what the archive has inflated so far", () => {
  const BIG = 300 * 1024;
  const SECOND_SIDECAR = 70 * 1024;

  /** A second book whose sidecar is too big for a spent budget, and no bigger. */
  const second: BookSpec = {
    name: "Next",
    sidecar: { volumeId: "bbbbbbbbbbbb", title: "y".repeat(SECOND_SIDECAR) },
  };

  it("charges what the book file itself inflated to", async () => {
    const found = library(
      await read(
        [
          {
            name: "Big",
            sidecar: { volumeId: "aaaaaaaaaaaa" },
            inside: [
              {
                name: "OEBPS/text.xhtml",
                data: "x".repeat(BIG),
                method: STORED,
              },
            ],
          },
          second,
        ],
        [padding(16 * 1024)],
      ),
    );
    expect(found.books.map((book) => book.volumeId)).toEqual(["aaaaaaaaaaaa"]);
    expect(found.refused.map((one) => one.failure)).toEqual(["too-large"]);
  });

  it("charges what the package document inside a book inflated to", async () => {
    const found = library(
      await read(
        [
          {
            name: "Big",
            sidecar: { volumeId: "aaaaaaaaaaaa" },
            opf: hugePackage(BIG),
          },
          second,
        ],
        [padding(16 * 1024)],
      ),
    );
    expect(found.books.map((book) => book.volumeId)).toEqual(["aaaaaaaaaaaa"]);
    expect(found.refused.map((one) => one.failure)).toEqual(["too-large"]);
  });

  it("charges a read the archive stopped it finishing", async () => {
    // The entry below declares a hundred bytes and holds six hundred kilobytes,
    // so the read runs to the ceiling the budget granted and is then refused.
    // Those bytes were inflated. Charging what came back charges nothing for
    // them, and a crafted archive repeats it per entry, which is why a read
    // that throws is charged the whole ceiling it was granted. The second book
    // is what makes the difference visible: it survives only if the first was
    // free.
    const found = library(
      await read(
        [
          {
            name: "Liar",
            sidecar: { volumeId: "aaaaaaaaaaaa" },
            declaredSize: 100,
            inside: [
              {
                name: "OEBPS/text.xhtml",
                data: "x".repeat(600 * 1024),
                method: STORED,
              },
            ],
          },
          second,
        ],
        [padding(16 * 1024)],
      ),
    );
    expect(found.books).toEqual([]);
    expect(found.refused.map((one) => one.failure)).toEqual([
      "too-large",
      "too-large",
    ]);
  });

  it("charges a package document read the ceiling stopped", async () => {
    // **The diagonal, and both critic seats had to name it before it existed.**
    // The three tests above cover an outer read that arrived, an outer read
    // that was refused, and an inner read that arrived. This is the fourth
    // corner: an inner read refused at `MAX_PACKAGE_BYTES`, which is the one
    // `readEpub` used to charge nothing for. Measured against the module on the
    // day it did: a 1,006,742 byte archive inflated 852,026,600 bytes and never
    // spent its allowance.
    //
    // The package document declares a byte under the ceiling and holds 64 KiB
    // over it, so every check before the inflate passes and the inflate is what
    // stops. Built entry by entry because that is the only way to make an inner
    // directory lie.
    const inner = await buildZip({
      entries: [
        { name: "mimetype", data: "application/epub+zip", method: STORED },
        { name: "META-INF/container.xml", data: CONTAINER_XML() },
        {
          name: "OEBPS/content.opf",
          data: hugePackage(4 * 1024 * 1024 + 64 * 1024),
          centralUncompressedSize: 4 * 1024 * 1024 - 1,
        },
      ],
    });
    const found = library(
      await read(
        [
          { name: "Liar", sidecar: { volumeId: "aaaaaaaaaaaa" }, file: inner },
          second,
        ],
        [padding(100 * 1024)],
      ),
    );
    expect(found.books).toEqual([]);
    expect(found.refused.map((one) => one.failure)).toEqual([
      "too-large",
      "too-large",
    ]);
  });

  it("charges nothing for a package document that says it is too big", async () => {
    // The other half of the test above, and the reason the ceiling is not
    // charged unconditionally: this package document declares its real size,
    // which is over `MAX_PACKAGE_BYTES`, so it is refused before a byte is
    // inflated. Charging it would make one honestly oversized book spend a
    // small archive's whole allowance and refuse every book after it, which is
    // the second book here.
    const inner = await buildZip({
      entries: [
        { name: "mimetype", data: "application/epub+zip", method: STORED },
        { name: "META-INF/container.xml", data: CONTAINER_XML() },
        {
          name: "OEBPS/content.opf",
          data: hugePackage(4 * 1024 * 1024 + 64 * 1024),
        },
      ],
    });
    const found = library(
      await read(
        [
          {
            name: "Honest",
            sidecar: { volumeId: "aaaaaaaaaaaa" },
            file: inner,
          },
          second,
        ],
        [padding(100 * 1024)],
      ),
    );
    expect(found.books.map((book) => book.volumeId)).toEqual(["bbbbbbbbbbbb"]);
    expect(found.refused.map((one) => one.failure)).toEqual(["too-large"]);
  });

  it("calls a book the budget stopped it reaching refused, not skipped", async () => {
    // The distinction the record's own docstring argues for. A pair the budget
    // stopped short of is a book the export carried; `skipped` would say the
    // archive held less than it did, and nothing downstream could tell.
    const found = library(
      await read(
        [
          {
            name: "Big",
            sidecar: { volumeId: "aaaaaaaaaaaa" },
            opf: hugePackage(BIG),
          },
          second,
        ],
        [padding(16 * 1024)],
      ),
    );
    expect(found.skipped).toBe(0);
    expect(found.refused).toEqual([
      {
        path: `${LIBRARY_FOLDER}/Next/Next`,
        title: null,
        failure: "too-large",
      },
    ]);
  });
});
