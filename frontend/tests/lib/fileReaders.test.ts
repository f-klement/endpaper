import { describe, expect, it } from "vitest";

import { READERS, readerFor } from "../../src/lib/fileReaders";
import { SUPPORTED_EXTENSIONS } from "../../src/lib/fileName";

describe("which reader opens a picked file", () => {
  it("answers for the format that has one", async () => {
    expect(await readerFor("Dracula.epub")).toBeTypeOf("function");
  });

  it("answers for all three spellings of the Amazon container", async () => {
    // `.mobi`, `.azw` and `.azw3` are one container under three names, so the
    // failure this catches is two of the three quietly falling through to the
    // filename path while the third works.
    for (const name of ["Ventus.mobi", "Ventus.azw", "Ventus.azw3"]) {
      expect(await readerFor(name)).toBeTypeOf("function");
    }
  });

  it("opens those three with the same reader", async () => {
    const readers = await Promise.all(
      ["Ventus.mobi", "Ventus.azw", "Ventus.azw3"].map((name) =>
        readerFor(name),
      ),
    );

    expect(new Set(readers).size).toBe(1);
  });

  it("answers for a comic archive", async () => {
    expect(await readerFor("Saga 012.cbz")).toBeTypeOf("function");
  });

  it("opens a comic with a different reader from an EPUB", async () => {
    // Both are a zip and both go through `lib/zip.ts`, which is exactly why
    // one thunk serving both would look right: what differs is which entry is
    // the metadata, and an EPUB's container is not a `ComicInfo.xml`.
    const [comic, epub] = await Promise.all([
      readerFor("Saga 012.cbz"),
      readerFor("Dracula.epub"),
    ]);

    expect(comic).not.toBe(epub);
  });

  it("answers for the format with the most files and the least metadata", async () => {
    // A PDF has a reader, and its ordinary answer is a record of nulls rather
    // than a failure, which is what hands the file to the filename path.
    expect(await readerFor("scan.pdf")).toBeTypeOf("function");
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

  it("is case insensitive, because a file picker is not", async () => {
    expect(await readerFor("DRACULA.EPUB")).toBeTypeOf("function");
  });
});
