/**
 * @vitest-environment node
 *
 * Strings, a JSON schema and one source read. No DOM anywhere in it.
 */
/**
 * Tests for src/lib/fileName.ts.
 *
 * Three things are being pinned and they are different in kind.
 *
 * **What the signals do**, which is ordinary. **What they refuse**, which is the
 * half a filename parser gets wrong: the cases below that assert `null` are the
 * ones that stop this becoming a grammar, and every one of them was reachable
 * before it was written.
 *
 * **And that this module cannot see a file.** It is the mirror of the property
 * `tests/houseRules.test.ts` holds over the readers: those may hold a member's
 * book and may not reach the network, and this one may reach the network,
 * through what it derives, and so may not hold a book. A `File` parameter here
 * would compile and pass every other test in the tree.
 */

import { describe, expect, it } from "vitest";

import { AUDIO_EXTENSIONS } from "../../src/lib/audiobook";
import {
  FORMAT_FOR_EXTENSION,
  plainName,
  QUERY_CEILING,
  readName,
  SUPPORTED_EXTENSIONS,
  queryFor,
  supportedExtension,
} from "../../src/lib/fileName";
import { BookFormat } from "../../src/api/generated/model";

const SOURCE = import.meta.glob("../../src/lib/fileName.ts", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function clues(name: string, folders: string[] = []) {
  return readName({ name, folders });
}

describe("which files the walk considers", () => {
  it("recognises every extension it claims to", () => {
    for (const extension of SUPPORTED_EXTENSIONS) {
      expect(supportedExtension(`a book${extension}`)).toBe(extension);
    }
  });

  it("is not fooled by the case a filesystem happens to use", () => {
    expect(supportedExtension("DUNE.EPUB")).toBe(".epub");
  });

  it("matches a two part extension whole", () => {
    expect(supportedExtension("dune.fb2.zip")).toBe(".fb2.zip");
  });

  it("passes over a format the owner dropped from the epic", () => {
    for (const name of ["dune.cbr", "dune.djvu", "dune.lit", "dune.docx"]) {
      expect(supportedExtension(name)).toBeNull();
    }
  });

  it("takes a tagged MP3, now that a folder of them is one book", () => {
    // Held out until the grouping rule existed, because admitting it before
    // would have filed a two hundred track audiobook as two hundred books.
    // `lib/audiobookGroups.ts` is that rule.
    expect(supportedExtension("chapter 01.mp3")).toBe(".mp3");
  });

  it("passes over a file with no extension at all", () => {
    expect(supportedExtension("dune")).toBeNull();
  });

  it("answers what kind of object every one of them is", () => {
    // A total map, so an extension added without a format is caught here rather
    // than filed as whatever the last arm said.
    for (const extension of SUPPORTED_EXTENSIONS) {
      expect(Object.keys(FORMAT_FOR_EXTENSION)).toContain(extension);
    }
    expect(Object.keys(FORMAT_FOR_EXTENSION)).toHaveLength(
      SUPPORTED_EXTENSIONS.length,
    );
  });

  it("has an audio reader for exactly the extensions it calls audiobooks", () => {
    // **Two lists, so the equality is the guard.** `lib/audiobook.ts` has to
    // answer whether one file of a kind is a whole book or one track of one,
    // which this map cannot say. An extension here and not there is routed to
    // the grouping path and read by nothing; one there and not here is a reader
    // nothing reaches. Asserted both ways, because either alone admits the
    // other, and this file is where a format joins.
    const audio = SUPPORTED_EXTENSIONS.filter(
      (extension) => FORMAT_FOR_EXTENSION[extension] === BookFormat.audiobook,
    );

    expect([...audio].sort()).toEqual(Object.keys(AUDIO_EXTENSIONS).sort());
  });

  it("calls both audio containers audiobooks and a PDF an ebook", () => {
    // This map decides which route a file takes; the test above holds it level
    // with the reader's own set, which decides what a container is. A third
    // audio format answers in both.
    expect(FORMAT_FOR_EXTENSION[".m4b"]).toBe(BookFormat.audiobook);
    expect(FORMAT_FOR_EXTENSION[".mp3"]).toBe(BookFormat.audiobook);
    expect(FORMAT_FOR_EXTENSION[".pdf"]).toBe(BookFormat.ebook);
  });

  it("calls a CBZ a comic", () => {
    // A container written for one kind of object answers this without anything
    // being opened, which is the same evidence `.m4b` is. `backend/enums.py`
    // states what a `BookFormat` member has to be able to do to earn a place.
    expect(FORMAT_FOR_EXTENSION[".cbz"]).toBe(BookFormat.comic);
  });
});

describe("a query built from something that is not a file name", () => {
  it("asks the catalogue for the text it was given", () => {
    expect(queryFor("Robinson Crusoe Daniel Defoe")).toBe(
      "Robinson Crusoe Daniel Defoe",
    );
  });

  it("keeps an initialism whole, which the file name rules would not", () => {
    // **The reason this is not `readName`.** A file name writes a space as a
    // `.` or a `_`; a tag writes a space. Splitting on them would hand the fan
    // out four one letter terms, and the server ANDs the terms it is given.
    expect(queryFor("S.P.Q.R. Mary Beard")).toBe("S.P.Q.R. Mary Beard");
  });

  it("keeps an extension that is part of the title, for the same reason", () => {
    expect(queryFor("Reading a book.epub")).toBe("Reading a book.epub");
  });

  it("takes out what is not text, each half its own way", () => {
    // The split this module makes and the reason for it: a control separates
    // two things and becomes a space, a format control sits inside one word and
    // is deleted. U+200B is the one format control on the other side of it,
    // because it is the only word separator Thai, Khmer, Lao and Burmese have.
    expect(queryFor("Dune\u0000Frank\u200CHerbert")).toBe("Dune FrankHerbert");
    expect(queryFor("Dune\u200BFrank Herbert")).toBe("Dune Frank Herbert");
  });

  it("answers nothing for text below what the endpoint will take", () => {
    // The same floor the search box enforces, which is the API's own.
    expect(queryFor("a")).toBeNull();
    expect(queryFor("   ")).toBeNull();
  });

  it("cuts a long one on a word boundary where there is one in reach", () => {
    // A query cut mid word asks for a term that is not a word. Asserted as the
    // property rather than as the length: the ceiling is `QUERY_CEILING` and a
    // literal here would be a fourth copy of a number this file recomputes.
    const long = queryFor(`${"a".repeat(190)} boundary here`) ?? "";

    expect([...long].length).toBeLessThanOrEqual(QUERY_CEILING);
    expect(long.endsWith("boundary")).toBe(true);
  });

  it("cuts in code points rather than in UTF-16 units", () => {
    // The fault `lib/bookBounds.ts` records costing a whole book to a 422: a
    // cut between the halves of a pair is a lone surrogate no encoder emits.
    const cut = queryFor("\u{1F4DA}".repeat(300)) ?? "";

    expect([...cut]).toHaveLength(200);
    expect(new TextDecoder().decode(new TextEncoder().encode(cut))).toBe(cut);
  });
});

describe("an ISBN in the name", () => {
  it("is found wherever it sits", () => {
    expect(clues("Dune 9780441013593 retail.epub").isbn).toBe("9780441013593");
  });

  it("survives the grouping a publisher prints", () => {
    expect(clues("978-0-441-01359-3 Dune.epub").isbn).toBe("9780441013593");
  });

  it("is canonicalised from an ISBN-10, so the lookup has one form", () => {
    expect(clues("Dune 0441013597.epub").isbn).toBe("9780441013593");
  });

  it("is read out of a longer run of digits when it is a thirteen", () => {
    // A thirteen digit window has to carry a bookland prefix as well as close
    // its check digit, which no ordinary number in a filename does.
    expect(clues("0019780441013593.pdf").isbn).toBe("9780441013593");
  });

  it("is not invented from a date stamp", () => {
    // The refusal that matters: a random ten digit run passes modulus 11 about
    // one time in eleven, so a ten is taken only as a whole token and never
    // from a window slid over a longer number.
    expect(clues("scan 20240115123 page 4.pdf").isbn).toBeNull();
  });

  it("is not taken from a number whose check digit disagrees", () => {
    expect(clues("Dune 9780441013594.epub").isbn).toBeNull();
  });

  it("is not taken from a thirteen that is not a book", () => {
    // A valid EAN-13 with no bookland prefix, which is a barcode for something
    // that is not a book.
    expect(clues("4006381333931 receipt.pdf").isbn).toBeNull();
  });

  it("leaves the digits out of the query, which asks about a title", () => {
    expect(clues("Dune 9780441013593.epub").query).toBe("Dune");
  });
});

describe("a year in the name", () => {
  it("is read when it is plausible", () => {
    expect(clues("The Dispossessed (1974).epub").year).toBe(1974);
  });

  it("prefers the one inside brackets, which is where a name puts it", () => {
    expect(clues("Dune 2 (1969).epub").year).toBe(1969);
  });

  it("refuses a four digit number that could not be a publication year", () => {
    expect(clues("Dune 9999.epub").year).toBeNull();
  });

  it("refuses a number that is only four digits long by accident", () => {
    // Part of a longer run, so it is not a year in the first place.
    expect(clues("Dune 19741975.epub").year).toBeNull();
  });
});

describe("the folder as a signal", () => {
  it("names the author when the file's own name repeats it", () => {
    // Corroboration rather than parsing: two instruments have to agree before
    // anything here is called an author.
    const found = clues("Le Guin, Ursula K. - The Dispossessed.epub", [
      "Le Guin, Ursula K.",
      "The Dispossessed",
    ]);
    expect(found.author).toBe("Le Guin, Ursula K");
    expect(found.title).toBe("The Dispossessed");
  });

  it("takes the outermost that agrees, which is where an author sits", () => {
    // Both folders appear in the name. The one above the book is the author;
    // the one immediately over the file is named for the book itself.
    const found = clues("Le Guin - The Dispossessed.epub", [
      "Le Guin",
      "The Dispossessed",
    ]);
    expect(found.author).toBe("Le Guin");
  });

  it("says nothing when the folder appears nowhere in the name", () => {
    // `Downloads`, `Books` and `to read` are folders too.
    expect(clues("The Dispossessed.epub", ["Downloads"]).author).toBeNull();
  });

  it("refuses a folder that is the whole of the name", () => {
    // An author is what is left beside a title, and this names a book twice.
    const found = clues("The Dispossessed.epub", ["The Dispossessed"]);
    expect(found.author).toBeNull();
    expect(found.title).toBe("The Dispossessed");
  });

  it("ignores a folder too short to corroborate anything", () => {
    expect(clues("A book.epub", ["A"]).author).toBeNull();
  });

  it("is not read for an ISBN, because a folder holds a shelf mark", () => {
    // Calibre numbers its folders, and a folder's number is not a book's.
    expect(clues("Dune.epub", ["Le Guin (9780441013593)"]).isbn).toBeNull();
  });
});

describe("what is handed to the catalogue", () => {
  it("is the whole name, because q takes a title, an author or both", () => {
    // Throwing the author half away to look tidy would cost the match this
    // exists to find.
    expect(
      clues("Le Guin, Ursula K. - The Dispossessed (1974).epub").query,
    ).toBe("Le Guin, Ursula K - The Dispossessed");
  });

  it("is the whole name even when a folder split an author off it", () => {
    const found = clues("Le Guin - The Dispossessed.epub", ["Le Guin"]);
    expect(found.author).toBe("Le Guin");
    expect(found.query).toBe("Le Guin - The Dispossessed");
  });

  it("reads a name that uses underscores and dots for spaces", () => {
    expect(clues("The_Dispossessed.Le.Guin.epub").query).toBe(
      "The Dispossessed Le Guin",
    );
  });

  it("drops what a name puts in brackets, which is never the title", () => {
    expect(clues("Dune [retail] {v2}.epub").query).toBe("Dune");
  });

  it("is cut to what the endpoint will take", () => {
    const long = `${"wide ".repeat(80)}end.epub`;
    const found = clues(long);
    expect([...(found.query ?? "")].length).toBeLessThanOrEqual(QUERY_CEILING);
  });

  it("is cut on a word boundary rather than through a word", () => {
    const long = `${"wide ".repeat(80)}end.epub`;
    expect(clues(long).query?.endsWith("wide")).toBe(true);
  });

  it("carries no control characters, whatever the name carried", () => {
    // A bidirectional override, which renders as nothing and reverses what a
    // reader sees after it. Debris in a name rather than a reason to drop a
    // book, so it is removed rather than refused.
    const found = clues("Du ne‮reversed.epub");
    expect(found.query).not.toMatch(/[\p{Cc}\p{Cf}]/u);
  });

  it("keeps a zero width space, which is a word break in five scripts", () => {
    // **The one format control on the spacing side, and it is measured.** ICU's
    // word segmentation breaks a word at 1 of the 170 code points in the class,
    // and this is it. Thai, Khmer, Lao and Burmese names have no other
    // separator, and the server splits terms on whitespace, so deleting this
    // would hand the fan out one term that matches nothing.
    expect(clues("Dune\u200BMessiah.epub").query).toBe("Dune Messiah");
  });

  it("deletes a zero width non joiner, which sits inside a word", () => {
    // The other 169. Spacing this one splits a Persian or Hindi word into two
    // terms the fan out then ANDs, which finds less rather than more.
    expect(clues("Du\u200Cne.epub").query).toBe("Dune");
  });

  it("is null when the name leaves nothing worth asking about", () => {
    // Below the endpoint's own minimum, so asking would be a 422 rather than a
    // search.
    expect(clues("1.epub").query).toBeNull();
  });

  it("still leaves a title behind for a name that asks nothing", () => {
    // The file is still a book, and a member can still edit the row.
    expect(clues("1.epub").title).toBe("1");
  });
});

describe("a name as it is printed", () => {
  it("keeps the extension, because it names the file and not the book", () => {
    expect(plainName("Dune.pdf")).toBe("Dune.pdf");
  });

  it("carries no control character into the row it is printed in", () => {
    // A bidirectional override renders as nothing and reverses what a reader
    // sees after it. It is printed beside a title that was cleaned.
    expect(plainName("Du‮ne.pdf")).toBe("Dune.pdf");
  });

  it("does not take a name apart the way a query is taken apart", () => {
    // The underscores are the member's file name and this is what they picked.
    expect(plainName("The_Dispossessed (1974).epub")).toBe(
      "The_Dispossessed (1974).epub",
    );
  });
});

describe("the module cannot see a file", () => {
  const source = SOURCE["../../src/lib/fileName.ts"] ?? "";

  it("is reading the module it claims to", () => {
    // A glob that matched nothing would make the two assertions below pass on
    // an empty string forever.
    expect(source).toContain("export function readName");
  });

  it("takes names, never anything that carries bytes", () => {
    // The property is the signature, exactly as it is for `draftFromFile`:
    // taking a `File` here would compile and pass every other test in the tree,
    // and would put a member's book one call away from a query string.
    //
    // **The same literal as `tests/pages/ScanPage/types.test.ts`**, which
    // asserts that it is: a `File` is a `Blob`, and the two guards named
    // different sets for one commit until both critic seats found the gap.
    expect(withoutProse(source)).not.toMatch(
      /\b(?:File|Blob|ArrayBuffer|Uint8Array)\b/,
    );
  });

  it("has no way to read bytes at all", () => {
    expect(withoutProse(source)).not.toMatch(
      /\b(arrayBuffer|FileReader|readAsText|createObjectURL)\b/,
    );
  });
});

/** The source with comments removed, so a rule cannot be satisfied by prose. */
function withoutProse(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");
}
