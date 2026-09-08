import { describe, expect, it } from "vitest";

import { READERS, readerFor, type FileReader } from "../../src/lib/fileReaders";
import {
  FORMAT_FOR_EXTENSION,
  SUPPORTED_EXTENSIONS,
} from "../../src/lib/fileName";
import { BookFormat } from "../../src/api/generated/model";

/**
 * Every registered extension and the export its module answers with.
 *
 * **The property is that each key opens the function its own module exports**,
 * which is not what a per format `it` asserts. Seven of them stood here, one or
 * two per format, and each asked only that `readerFor` answered *some*
 * function: measured 2026-09-08, `".pdf": async () => (await
 * import("./epub")).readEpub` passed the whole suite at `2967 passed`, and
 * every PDF would open as a zip and be reported "not an EPUB", a sentence
 * `FILE_FAILURES` already has for a member to read.
 *
 * **Total over the registry rather than an arm per format**, so the table is
 * what a ninth registration has to be added to. Its totality is a runtime
 * assertion below and not yet a compile error: `READERS` carries a type
 * annotation, so `keyof typeof READERS` is all ten supported extensions rather
 * than the eight registered. The year band ticket prices the `satisfies`
 * narrowing that would close it.
 *
 * **Resolved by `await import` and not by a static import at the top of this
 * file.** A reader whose module throws while evaluating would, under a static
 * import, take this whole file out of collection rather than fail it, so the
 * count drops and no name is reported.
 *
 * Measured with an evaluation fault injected into `pdf.ts`, its module scope
 * decoder label replaced with one no runtime knows: `tests/lib/pdf.test.ts`
 * collects `0 test` and names nothing, where on an unaltered tree it collects
 * 45 and passes. It holds the same static import this avoids, at its line 21.
 * Resolved here, the same fault fails a named test instead.
 */
async function opensWith(): Promise<Record<string, FileReader>> {
  const [epub, mobi, fb2, cbz, pdf] = await Promise.all([
    import("../../src/lib/epub"),
    import("../../src/lib/mobi"),
    import("../../src/lib/fb2"),
    import("../../src/lib/cbz"),
    import("../../src/lib/pdf"),
  ]);
  return {
    ".epub": epub.readEpub,
    // One container under three names, so all three answer one function.
    ".mobi": mobi.readMobi,
    ".azw": mobi.readMobi,
    ".azw3": mobi.readMobi,
    // Two keys and two functions, which is the pair most able to be wrong: the
    // document and the same document inside an archive.
    ".fb2": fb2.readFb2,
    ".fb2.zip": fb2.readFb2Archive,
    ".cbz": cbz.readCbz,
    ".pdf": pdf.readPdf,
  };
}

describe("which reader opens a picked file", () => {
  it("names every registered extension in the table below", async () => {
    // Without this the table is an inclusion list again: a ninth registration
    // the table does not name is simply not checked by the test that follows.
    expect(Object.keys(await opensWith()).sort()).toEqual(
      Object.keys(READERS).sort(),
    );
  });

  it("opens each registered extension with the function its module exports", async () => {
    const expected = await opensWith();
    const wrong: string[] = [];
    for (const [extension, reader] of Object.entries(expected)) {
      // Named rather than asserted in the loop, so a failure says which
      // extension rather than that one of eight was not a function.
      if ((await readerFor(`book${extension}`)) !== reader)
        wrong.push(extension);
    }

    expect(wrong).toEqual([]);
  });
  it("answers nothing for a supported format with no reader", async () => {
    // Not an error, and audio is the standing case: `.m4b` and `.mp3` are read
    // by `lib/audiobook.ts` on a separate path, because which files are one
    // book is decided before any of them is drafted from.
    expect(await readerFor("chapter.m4b")).toBeNull();
  });

  it("answers nothing for a file the walk does not take", async () => {
    expect(await readerFor("notes.txt")).toBeNull();
  });

  it("registers no extension the walk does not consider", () => {
    // The failure this catches is a reader added under a spelling the picker
    // never offers it, which would look like a reader that silently never runs.
    const registered = Object.keys(READERS);
    expect(registered).not.toHaveLength(0);
    for (const extension of registered) {
      expect(SUPPORTED_EXTENSIONS).toContain(extension);
    }
  });

  it("leaves an extension readerless only where another route takes the file", async () => {
    // The failure this catches is the one every test above is blind to: a
    // format joined to `SUPPORTED_EXTENSIONS` and to the total
    // `FORMAT_FOR_EXTENSION` and never reaching a reader. Those tests name one
    // format each and are written by the ticket that adds the reader, so the
    // format nobody registered is the format nobody wrote a test for. Measured
    // 2026-09-08: a `.prc` added to both of those maps and to no reader
    // typechecks, because `READERS` is a `Partial`, and the whole frontend
    // suite passed while the file took the filename path in silence.
    //
    // **Asked of `readerFor` and never of `READERS`, which is three failures
    // for one assertion.** A missing key, a key whose value is not a reader,
    // and a door that drops an extension the map does carry all come back as
    // one answer here, where reading the map catches the first and needs its
    // own reasoning for each of the others.
    //
    // None of the three is hypothetical. `exactOptionalPropertyTypes` is off in
    // `frontend/tsconfig.json`, so `".prc": undefined` is a legal value rather
    // than an absent key and satisfies `in`. And `.fb2` and `.fb2.zip` are
    // passed to `readerFor` by no other test in this suite, so an early return
    // for either is a format lost in silence that no reading of the map sees.
    //
    // **The exclusion is the routing predicate and not a list of extensions.**
    // `ScanPage/hooks.ts` sends a file to the grouping path when
    // `FORMAT_FOR_EXTENSION` calls it an audiobook, and that is the only route
    // that is not this registry, so it is the only thing that may answer for an
    // absent reader. Asserted in both directions: an audio extension that grows
    // a reader has grown one nothing reaches, because the picker routes the
    // file away before `readerFor` is ever asked.
    //
    // `book.fb2.zip` resolves to the archive because **`.fb2` does not match it
    // at all**: `"book.fb2.zip".endsWith(".fb2")` is false, so `.fb2.zip` is the
    // only member the name ends with. Order decides nothing here and neither
    // does length, which is `fileName.ts`'s own sentence: what would make order
    // matter is one extension being a suffix of another, and none is.
    const answered = await Promise.all(
      SUPPORTED_EXTENSIONS.map((extension) => readerFor(`book${extension}`)),
    );
    const routedElsewhere = SUPPORTED_EXTENSIONS.filter(
      (extension) => FORMAT_FOR_EXTENSION[extension] === BookFormat.audiobook,
    );
    const readerless = SUPPORTED_EXTENSIONS.filter(
      (_, index) => typeof answered[index] !== "function",
    );

    // Two empty lists are equal, which is how an assertion like this passes for
    // ever once the sets it compares stop being populated.
    expect(routedElsewhere.length).toBeGreaterThan(0);
    expect([...readerless].sort()).toEqual([...routedElsewhere].sort());
  });

  it("is case insensitive, because a file picker is not", async () => {
    expect(await readerFor("DRACULA.EPUB")).toBeTypeOf("function");
  });
});
