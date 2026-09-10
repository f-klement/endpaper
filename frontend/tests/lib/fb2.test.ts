/**
 * Tests for src/lib/fb2.ts.
 *
 * **This file runs under the suite's own happy-dom and that is a claim being
 * tested, not a convenience.** `tests/lib/opf.test.ts` opts into jsdom because
 * happy-dom's `DOMParser` falls back to HTML parsing on a single quoted XML
 * declaration; `fb2.ts` removes the declaration before parsing, for its own
 * reason, and `parses a document whose declaration is single quoted` below is
 * the arm that fails if that removal ever goes. Deleting the `.replace` in
 * `headerDocument` fails that test and no other.
 *
 * Structured around the two things a first FB2 implementation drops: several
 * `<author>` elements and several `<sequence>` elements, both legal, both in
 * the corpus. The corpus is named in `src/lib/fb2.ts`.
 */

import { describe, expect, it } from "vitest";

import { readFb2, readFb2Archive, readFb2Description } from "../../src/lib/fb2";
import { buildZip, bytes } from "../zipFixtures";

const DECLARATION = '<?xml version="1.0" encoding="utf-8"?>';

const OPEN =
  '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">';

/**
 * A FictionBook whose `<description>` is what the test is about.
 *
 * The body is included and is deliberately long enough to matter: every read
 * here has to stop at `</description>`, and a fixture with no body could not
 * tell a reader that stops from one that does not.
 */
function fb2(description: string, declaration = DECLARATION): string {
  return `${declaration}${OPEN}<description>${description}</description><body><section><p>${"nothing to see here. ".repeat(200)}</p></section></body></FictionBook>`;
}

/** The `title-info` of a book with everything, so a test can vary one part. */
function titleInfo(inner: string): string {
  return `<title-info><genre>sf</genre>${inner}<lang>ru</lang></title-info>`;
}

const DOCUMENT_INFO =
  "<document-info><author><nickname>the converter</nickname></author><id>abc</id><version>1.0</version></document-info>";

/** A whole ordinary file: one author, one series, a publisher and an ISBN. */
const ORDINARY = fb2(
  `${titleInfo(
    "<author><first-name>Александр</first-name><middle-name>Юрьевич</middle-name><last-name>Санфиров</last-name></author>" +
      '<book-title>Назад в юность</book-title><annotation><p>Первая\n  книга.</p></annotation><sequence name="Назад в юность" number="1"/>',
  )}${DOCUMENT_INFO}<publish-info><publisher>Альфа-книга</publisher><year>2013</year><isbn>978-5-9922-1663-9</isbn></publish-info>`,
);

/** The record, or the reason there is none, so one assertion covers both arms. */
function outcome(reading: Awaited<ReturnType<typeof readFb2>>): string {
  return reading.ok ? `read: ${reading.metadata.title}` : reading.failure;
}

function read(xml: string) {
  return readFb2Description(xml);
}

describe("reading a FictionBook's description", () => {
  it("yields every field the file carried", () => {
    expect(read(ORDINARY)).toEqual({
      title: "Назад в юность",
      subtitle: null,
      authors: ["Александр Юрьевич Санфиров"],
      identifiers: [{ scheme: "isbn", value: "978-5-9922-1663-9" }],
      isbn: "9785992216639",
      publisher: "Альфа-книга",
      year: 2013,
      language: "ru",
      description: "Первая книга.",
      seriesName: "Назад в юность",
      seriesIndex: 1,
    });
  });

  it("joins one author's parts and never two authors", () => {
    const record = read(
      fb2(
        titleInfo(
          "<author><first-name>Аркадий</first-name><last-name>Стругацкий</last-name></author>" +
            "<author><first-name>Борис</first-name><last-name>Стругацкий</last-name></author>" +
            "<book-title>Пикник на обочине</book-title>",
        ),
      ),
    );

    expect(record?.authors).toEqual(["Аркадий Стругацкий", "Борис Стругацкий"]);
  });

  it("keeps an author who has only a nickname", () => {
    // 1 of 18 corpus files carries one, beside a fully named author. Dropping
    // it is an author list one short rather than a visible failure.
    const record = read(
      fb2(
        titleInfo(
          "<author><last-name>Черчилль</last-name></author>" +
            "<author><nickname>vovchik</nickname><email>v@example.com</email></author>" +
            "<book-title>Вторая мировая война</book-title>",
        ),
      ),
    );

    expect(record?.authors).toEqual(["Черчилль", "vovchik"]);
  });

  it("names the same person once", () => {
    const record = read(
      fb2(
        titleInfo(
          "<author><last-name>Гоголь</last-name></author>" +
            "<author><last-name>Гоголь</last-name></author>" +
            "<book-title>Мёртвые души</book-title>",
        ),
      ),
    );

    expect(record?.authors).toEqual(["Гоголь"]);
  });

  it("does not read the author who made the file", () => {
    // `document-info` sits beside `title-info` and names whoever produced the
    // FB2 rather than whoever wrote the book. A reader asking the document for
    // `author` files the converter as a co-author of every book.
    expect(read(ORDINARY)?.authors).toEqual(["Александр Юрьевич Санфиров"]);
  });

  it("does not read the original language title", () => {
    // `src-title-info` holds the same fields for the untranslated work, in 3 of
    // 18 corpus files, and a reader taking whichever came first would file a
    // translation under two different titles depending on the producer.
    const record = read(
      fb2(
        `<src-title-info><book-title>The Graveyard Book</book-title><author><last-name>Gaiman</last-name></author></src-title-info>` +
          titleInfo(
            "<author><last-name>Гейман</last-name></author><book-title>История с кладбищем</book-title>",
          ),
      ),
    );

    expect(record).toMatchObject({
      title: "История с кладбищем",
      authors: ["Гейман"],
    });
  });
});

describe("the series, which FB2 carries as a typed field", () => {
  it("reads the name and the number out of the attributes", () => {
    expect(read(ORDINARY)).toMatchObject({
      seriesName: "Назад в юность",
      seriesIndex: 1,
    });
  });

  it("keeps a series that names no position", () => {
    // A sequence with a name and no number is ordinary: a book known to be in a
    // series at an unknown place in it. `fb2.ts` carries the count.
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Как Маркиз вернул своё пальто</book-title><sequence name="Никогде"/>',
        ),
      ),
    );

    expect(record).toMatchObject({
      seriesName: "Никогде",
      seriesIndex: null,
    });
  });

  it("takes the first of several sequences", () => {
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Вторая мировая война</book-title><sequence xml:lang="ru" name="Книга, чё" number="1"/><sequence xml:lang="ru-KZ" name="Зачем это нужно" number="2"/>',
        ),
      ),
    );

    expect(record).toMatchObject({
      seriesName: "Книга, чё",
      seriesIndex: 1,
    });
  });

  it("passes over a sequence that names nothing", () => {
    // A malformed first element must not hide a good second one.
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Вторая мировая война</book-title><sequence number="1"/><sequence name="Кибериада" number="7"/>',
        ),
      ),
    );

    expect(record).toMatchObject({
      seriesName: "Кибериада",
      seriesIndex: 7,
    });
  });

  it("does not read a sub series", () => {
    // A nested `<sequence>` is a series inside a series, and two columns cannot
    // hold both. The outer one is what arrives.
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Вторая мировая война</book-title><sequence name="Книга, чё" number="1"><sequence name="Подсерия" number="9"/></sequence>',
        ),
      ),
    );

    expect(record).toMatchObject({
      seriesName: "Книга, чё",
      seriesIndex: 1,
    });
  });

  it("reads no series at all from a sub series alone", () => {
    // **The arm above cannot see a reader that flattens**, because a document
    // order flatten still puts the outer sequence first. This one can: the
    // outer names nothing, so a flattening reader answers with the sub series
    // and this reader answers with no series, which is the behaviour chosen.
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Вторая мировая война</book-title><sequence><sequence name="Подсерия" number="9"/></sequence>',
        ),
      ),
    );

    expect(record).toMatchObject({ seriesName: null, seriesIndex: null });
  });

  it("reads a fractional position", () => {
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Между двух</book-title><sequence name="Цикл" number="2.5"/>',
        ),
      ),
    );

    expect(record?.seriesIndex).toBe(2.5);
  });

  it("reads no position from a number that is not one", () => {
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Между двух</book-title><sequence name="Цикл" number="вторая"/>',
        ),
      ),
    );

    expect(record).toMatchObject({ seriesName: "Цикл", seriesIndex: null });
  });
});

describe("the year, which the format says twice", () => {
  it("prefers the year the edition was published", () => {
    // The two disagree in 8 of the 10 corpus files carrying both, and they are
    // different facts: `title-info/date` is when the book was written.
    const record = read(
      fb2(
        `${titleInfo(
          '<book-title>Евгений Онегин</book-title><date value="1833-01-01">1833</date>',
        )}<publish-info><year>2023</year></publish-info>`,
      ),
    );

    expect(record?.year).toBe(2023);
  });

  it("falls back to the date the book was written", () => {
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Онегин</book-title><date value="1833-01-01">1833</date>',
        ),
      ),
    );

    expect(record?.year).toBe(1833);
  });

  it("prefers the date's ISO attribute to whatever a person typed in it", () => {
    // `25/08/2014` and `1948-53` are both in the corpus in this position.
    const record = read(
      fb2(
        titleInfo(
          '<book-title>Отверженные</book-title><date value="1862-04-03">25/08/2014</date>',
        ),
      ),
    );

    expect(record?.year).toBe(1862);
  });

  it("finds a year inside a typed date when there is no attribute", () => {
    const record = read(
      fb2(
        titleInfo(
          "<book-title>Вторая мировая война</book-title><date>1948-53</date>",
        ),
      ),
    );

    expect(record?.year).toBe(1948);
  });

  it("reads a typed date whose year is not the first thing in it", () => {
    // `25/08/2014` is corpus data, and it is where the difference between the
    // match and the group shows: the match carries the delimiter that anchored
    // it, so reading the whole of it gives `Number("/2014")`, which is `NaN`.
    // The window refuses a `NaN`, so this would answer null rather than a wrong
    // year, and null is still the wrong answer for a date the reader can read.
    const record = read(
      fb2(
        titleInfo(
          "<book-title>Отверженные</book-title><date>25/08/2014</date>",
        ),
      ),
    );

    expect(record?.year).toBe(2014);
  });

  it("does not read a year out of the digits in an identifier", () => {
    // `<date>` text is whatever a person typed, and one thing people type there
    // is the ISBN. A four digit run with no anchor takes `0022` out of
    // `5-17-002238-0` and files the book under the year 22, which is a
    // plausible looking number that survives every bound after this one.
    const record = read(
      fb2(
        titleInfo(
          "<book-title>Мастер и Маргарита</book-title><date>ISBN 5-17-002238-0, 2001</date>",
        ),
      ),
    );

    expect(record?.year).toBe(2001);
  });

  it("reads no year from a date carrying none", () => {
    const record = read(
      fb2(titleInfo("<book-title>Другие люди</book-title><date></date>")),
    );

    expect(record?.year).toBeNull();
  });

  it("reads no year no book could have been published in", () => {
    // The window is `bookBounds.plausibleYear`'s, and this is the arm that says
    // which values it refuses here: the caller scan in
    // `tests/lib/bookBounds.test.ts` reads neither end of the window, so it
    // cannot tell this door applying it from this door widening it.
    //
    // `0101` is the undefined date its producer writes where a book has none,
    // and it is inside `NUMBER_RANGES.year`, so nothing downstream reports it.
    // Asserted in both typed fields, because either can be the one read.
    expect(
      read(
        fb2(
          `${titleInfo("<book-title>Ничего</book-title>")}<publish-info><year>0101</year></publish-info>`,
        ),
      )?.year,
    ).toBeNull();
    expect(
      read(
        fb2(
          titleInfo(
            '<book-title>Ничего</book-title><date value="0101-01-01">0101</date>',
          ),
        ),
      )?.year,
    ).toBeNull();
    // **The point immediately outside each end, and that choice is the arm.**
    // A floor is half a window and every other year asserted in this file is
    // below the ceiling, so a ceiling removed for this reader alone leaves the
    // caller scan green and every arm above green. A number far outside, `2199`
    // say, catches a reader that drops the window and nothing else; a reader
    // keeping a second, wider window of its own answers from that one for a
    // contiguous band, and any contiguous widening of an end has to contain the
    // point just outside it. So these two catch that whole family. Found by the
    // seat that did not write this arm, against a mutation the first version of
    // it passed.
    expect(
      read(
        fb2(
          `${titleInfo("<book-title>Ничего</book-title>")}<publish-info><year>1449</year></publish-info>`,
        ),
      )?.year,
    ).toBeNull();
    expect(
      read(
        fb2(
          `${titleInfo("<book-title>Ничего</book-title>")}<publish-info><year>2101</year></publish-info>`,
        ),
      )?.year,
    ).toBeNull();
  });

  it("falls through to the written date when the published year is not one", () => {
    // The window sits in `yearIn` rather than at the end of `readYear`, so an
    // implausible `publish-info/year` is absent rather than final and the
    // preference between the two fields is unchanged: this file would answer
    // 101 with the window at the other site, and null with the whole read
    // abandoned on the first candidate.
    const record = read(
      fb2(
        `${titleInfo(
          '<book-title>Война и мир</book-title><date value="1869-01-01">1869</date>',
        )}<publish-info><year>0101</year></publish-info>`,
      ),
    );

    expect(record?.year).toBe(1869);
  });
});

describe("the ISBN, which sits in publish-info", () => {
  it("reads one", () => {
    expect(read(ORDINARY)?.isbn).toBe("9785992216639");
  });

  it("reads the first of a joint edition's two", () => {
    // 2 of the 10 corpus files with an `<isbn>` hold two of them. `parseIsbn`
    // strips punctuation, so an unsplit pair reaches it as one 26 character
    // number and parses as nothing at all.
    const record = read(
      fb2(
        `${titleInfo("<book-title>История с кладбищем</book-title>")}<publish-info><isbn>978-5-17-061649-7, 978-5-271-25002-6</isbn></publish-info>`,
      ),
    );

    expect(record).toMatchObject({
      isbn: "9785170616497",
      identifiers: [
        { scheme: "isbn", value: "978-5-17-061649-7" },
        { scheme: "isbn", value: "978-5-271-25002-6" },
      ],
    });
  });

  it("reads no ISBN out of an instruction to type one", () => {
    // Which is what one corpus file has in that element, verbatim.
    const record = read(
      fb2(
        `${titleInfo("<book-title>Война и мир</book-title>")}<publish-info><isbn>Тут пишем ISBN код книги, если есть</isbn></publish-info>`,
      ),
    );

    expect(record?.isbn).toBeNull();
  });
});

describe("a document that is not a FictionBook", () => {
  it("refuses text that is not XML", () => {
    expect(read("just some text")).toBeNull();
  });

  it("refuses XML that is something else", () => {
    expect(read("<package><description></description></package>")).toBeNull();
  });

  it("refuses a FictionBook with no description", () => {
    expect(read(`${DECLARATION}${OPEN}<body/></FictionBook>`)).toBeNull();
  });

  it("refuses a description with no title-info", () => {
    expect(read(fb2(DOCUMENT_INFO))).toBeNull();
  });

  it("refuses a document that declares its own entities", () => {
    // Expansion happens inside the engine before any code here runs, so no byte
    // cap this module states can reach it. 0 of 18 corpus files carry one.
    const hostile = `<?xml version="1.0"?><!DOCTYPE FictionBook [<!ENTITY a "boom">]>${OPEN}<description>${titleInfo("<book-title>&a;</book-title>")}</description></FictionBook>`;

    expect(read(hostile)).toBeNull();
  });

  it("refuses a document that only mentions an entity declaration", () => {
    // **The arm above does not test the refusal and this one does.** Measured:
    // deleting the `declaresEntities` call failed nothing at all, because a
    // document carrying a DTD internal subset is refused by the engine's own
    // parser and the guard never had to fire. `declaresEntities` is a plain
    // substring test, refusing the string even inside a comment, which is the
    // exclusion `xmlEntities.declaresEntities` states; putting it in a comment
    // is what makes the refusal the only difference between these two
    // documents.
    const ordinary = fb2(titleInfo("<book-title>Онегин</book-title>"));
    expect(read(ordinary)?.title).toBe("Онегин");

    const mentioned = ordinary.replace(
      "<description>",
      '<!-- <!ENTITY a "boom"> --><description>',
    );
    expect(read(mentioned)).toBeNull();
  });
});

describe("the declaration, which is removed before parsing", () => {
  it("parses a document whose declaration is single quoted", () => {
    // **This file runs under happy-dom**, whose `DOMParser` falls back to HTML
    // parsing on exactly this spelling: see `tests/lib/opf.test.ts`, where 41 of
    // 79 real EPUB files carry it. Removing the declaration is what takes this
    // reader out of the way of that, and this arm is what notices it coming
    // back.
    const record = read(
      fb2(
        titleInfo("<book-title>Онегин</book-title>"),
        "<?xml version='1.0' encoding='utf-8'?>",
      ),
    );

    expect(record?.title).toBe("Онегин");
  });

  it("parses a document with no declaration at all", () => {
    const record = read(fb2(titleInfo("<book-title>Онегин</book-title>"), ""));

    expect(record?.title).toBe("Онегин");
  });
});

/** Encode as windows-1251, which covers Cyrillic in one contiguous run. */
function cp1251(value: string): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(value.length);
  for (let at = 0; at < value.length; at += 1) {
    const code = value.charCodeAt(at);
    // U+0410 to U+044F map to 0xC0 to 0xFF, which is every letter used here.
    out[at] = code >= 0x410 && code <= 0x44f ? code - 0x410 + 0xc0 : code;
  }
  return out;
}

describe("reading a .fb2 off the disk", () => {
  it("yields what the file said", async () => {
    const reading = await readFb2(new Blob([bytes(ORDINARY)]));

    expect(reading.ok && reading.metadata.authors).toEqual([
      "Александр Юрьевич Санфиров",
    ]);
  });

  it("decodes a file that declares windows-1251", async () => {
    // **3 of 18 corpus files declare it**, and reading one as UTF-8 does not
    // fail: it yields a record whose every Cyrillic value is mojibake and
    // reaches the confirm step looking like data.
    const xml = fb2(
      titleInfo(
        "<author><last-name>Пушкин</last-name></author><book-title>Евгений Онегин</book-title>",
      ),
      '<?xml version="1.0" encoding="windows-1251"?>',
    );
    const reading = await readFb2(new Blob([cp1251(xml)]));

    expect(reading.ok && reading.metadata).toMatchObject({
      title: "Евгений Онегин",
      authors: ["Пушкин"],
    });
  });

  it("reads a UTF-8 file that starts with a byte order mark", async () => {
    const raw = bytes(fb2(titleInfo("<book-title>Онегин</book-title>")));
    const withMark = new Uint8Array(raw.length + 3);
    withMark.set([0xef, 0xbb, 0xbf]);
    withMark.set(raw, 3);

    expect(outcome(await readFb2(new Blob([withMark])))).toBe("read: Онегин");
  });

  it("falls back to UTF-8 for an encoding this engine has never heard of", async () => {
    // `TextDecoder` throws a `RangeError` for an unknown label, and an
    // unguarded one would turn a file naming a dead codepage into a crash
    // rather than into a thin record.
    const xml = fb2(
      titleInfo("<book-title>Onegin</book-title>"),
      '<?xml version="1.0" encoding="x-mac-cyrillic-1987"?>',
    );

    expect(outcome(await readFb2(new Blob([bytes(xml)])))).toBe("read: Onegin");
  });

  it("says too large for a description longer than it reads", async () => {
    // The bound is on the front of the file, so a header past it is a refusal
    // rather than a truncated parse. **The refusal has to be the one that fits**:
    // this is a FictionBook, so telling a member it is not one is telling them
    // something false.
    const padding = `<annotation><p>${"я".repeat(300_000)}</p></annotation>`;
    const xml = fb2(titleInfo(`<book-title>Онегин</book-title>${padding}`));

    expect(outcome(await readFb2(new Blob([bytes(xml)])))).toBe("too-large");
  });

  it("still says not a FictionBook about a large file that is not one", async () => {
    // **One arm per condition of that discriminator, and this is the first of
    // three.** Measured: with only this one, two of the three conditions could
    // be replaced by `true` and the suite stayed green. Here it is the
    // `<description` that is missing.
    const noise = new Blob([bytes("x".repeat(300_000))]);

    expect(outcome(await readFb2(noise))).toBe("not-an-fb2");
  });

  it("still says not a FictionBook about a short broken one", async () => {
    // The second condition: the read did not fill its bound, so nothing was cut
    // off and the document is simply malformed. Without this arm, dropping the
    // length test calls every unreadable file too large.
    const cut = '<?xml version="1.0"?><FictionBook><description><title-info>';

    expect(outcome(await readFb2(new Blob([bytes(cut)])))).toBe("not-an-fb2");
  });

  it("still says not a FictionBook about a large feed that closes its description", async () => {
    // The third: `<description>` is not FictionBook's alone. RSS and OPML both
    // have one, and a large feed opens and closes it inside the prefix, so
    // nothing was cut off and "too large" would be the wrong sentence.
    const feed = `<?xml version="1.0"?><rss><channel><description>a feed</description><item>${"a".repeat(300_000)}</item></channel></rss>`;

    expect(outcome(await readFb2(new Blob([bytes(feed)])))).toBe("not-an-fb2");
  });

  it("reads a description whose end tag carries a space", async () => {
    // `ETag ::= '</' Name S? '>'`, so this is well formed and a literal match
    // misses it. No corpus file spells it this way; the reader accepts it
    // because refusing a whole file over the space would be an exclusion worth
    // stating and this is cheaper than stating it.
    const xml = fb2(titleInfo("<book-title>Онегин</book-title>")).replace(
      "</description>",
      "</description >",
    );

    expect(outcome(await readFb2(new Blob([bytes(xml)])))).toBe("read: Онегин");
  });

  it("still says not a FictionBook about a broken one ending at the bound", async () => {
    // **The fourth shape of that discriminator, and the one a length test gets
    // wrong.** This file fills the read exactly and nothing is cut off, so it
    // is malformed rather than too long. Whether there is more is a fact about
    // the file and is asked of it, not inferred from how much came back.
    const opening =
      '<?xml version="1.0"?><FictionBook><description><title-info>';
    const exact = opening + "x".repeat(256 * 1024 - opening.length);
    // The premise: one byte either way and this arm is one of the two above.
    expect(exact.length).toBe(256 * 1024);

    expect(outcome(await readFb2(new Blob([bytes(exact)])))).toBe("not-an-fb2");
  });

  it("refuses a file that is not one", async () => {
    expect(outcome(await readFb2(new Blob([bytes("just some text")])))).toBe(
      "not-an-fb2",
    );
  });
});

describe("reading a .fb2.zip", () => {
  async function archive(entries: { name: string; data: string }[]) {
    return readFb2Archive(new Blob([await buildZip({ entries })]));
  }

  it("yields what the entry said", async () => {
    const reading = await archive([{ name: "Sanfirov.fb2", data: ORDINARY }]);

    expect(reading.ok && reading.metadata.seriesName).toBe("Назад в юность");
  });

  it("finds the entry by name and not by position", async () => {
    const reading = await archive([
      { name: "readme.txt", data: "read me first" },
      { name: "Sanfirov.fb2", data: ORDINARY },
    ]);

    expect(outcome(reading)).toBe("read: Назад в юность");
  });

  it("refuses an archive holding no FictionBook", async () => {
    // A CBZ lands here, which is why this says "not a FictionBook" rather than
    // "damaged": nothing is wrong with the file.
    const reading = await archive([
      { name: "page-001.jpg", data: "not really a jpeg" },
    ]);

    expect(outcome(reading)).toBe("not-an-fb2");
  });

  it("refuses an entry that is not a FictionBook", async () => {
    const reading = await archive([{ name: "notes.fb2", data: "just text" }]);

    expect(outcome(reading)).toBe("not-an-fb2");
  });

  it("refuses something that is not an archive", async () => {
    const reading = await readFb2Archive(new Blob([bytes("just some text")]));

    expect(outcome(reading)).toBe("not-an-fb2");
  });

  it("says protected for an encrypted entry", async () => {
    const zip = await buildZip({
      entries: [{ name: "book.fb2", data: ORDINARY, flags: 0x1 }],
    });

    expect(outcome(await readFb2Archive(new Blob([zip])))).toBe("protected");
  });

  it("says too large for an entry declaring more than it will read", async () => {
    // The declared size is checked before a byte is inflated, which is what
    // makes this fixture cheap and is also what makes it a real bound.
    const zip = await buildZip({
      entries: [
        {
          name: "book.fb2",
          data: ORDINARY,
          centralUncompressedSize: 33 * 1024 * 1024,
        },
      ],
    });

    expect(outcome(await readFb2Archive(new Blob([zip])))).toBe("too-large");
  });

  it("reads a book whose body runs past the header bound", async () => {
    // **What the prefix read buys, as behaviour rather than as a cost.** The
    // read stops inside the body, so the entry comes back `partial` and the
    // header is whole. A door conflating "I stopped early" with "this would not
    // open" reports an ordinary book as too large.
    const long = ORDINARY.replace(
      "nothing to see here. ".repeat(200),
      "nothing to see here. ".repeat(20_000),
    );
    // The premise: the body really does run past what is read.
    expect(long.length).toBeGreaterThan(256 * 1024);

    expect(outcome(await archive([{ name: "book.fb2", data: long }]))).toBe(
      "read: Назад в юность",
    );
  });

  it("says too large for an archived description longer than it reads", async () => {
    // The bare door's own arm for this is `says too large for a description
    // longer than it reads`. Both doors read `MAX_HEADER_BYTES` and both answer
    // the same way, which is what having one `fromBytes` is for.
    const padding = `<annotation><p>${"я".repeat(300_000)}</p></annotation>`;
    const xml = fb2(titleInfo(`<book-title>Онегин</book-title>${padding}`));

    expect(outcome(await archive([{ name: "book.fb2", data: xml }]))).toBe(
      "too-large",
    );
  });

  it("still says not a FictionBook about a large entry that is not one", async () => {
    // Stopping early is not on its own evidence of anything: this entry is
    // `partial` too, and it has no `<description` at all.
    const reading = await archive([
      { name: "notes.fb2", data: "x".repeat(300_000) },
    ]);

    expect(outcome(reading)).toBe("not-an-fb2");
  });

  it("says damaged for an archive whose offsets do not agree", async () => {
    const zip = await buildZip({
      entries: [{ name: "book.fb2", data: ORDINARY }],
      centralDirectoryOffset: 999_999,
    });

    expect(outcome(await readFb2Archive(new Blob([zip])))).toBe("damaged");
  });
});
