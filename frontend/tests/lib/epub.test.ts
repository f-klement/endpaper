/**
 * @vitest-environment jsdom
 *
 * jsdom for the reason `tests/lib/opf.test.ts` gives at length: happy-dom's
 * `DOMParser` does not parse every real package document, and jsdom's does.
 * jsdom's `Blob` has no `stream()`, which is why `lib/zip.ts` builds its own
 * `ReadableStream` rather than borrowing one from a Blob.
 */
/**
 * Tests for src/lib/epub.ts.
 *
 * The glue: two entries out of an archive and a parse. What is worth asserting
 * is the failures, because every one of them is a member holding a file that
 * did not work and being told which of six things happened.
 */

import { describe, expect, it } from "vitest";

import { readEpub } from "../../src/lib/epub";
import {
  buildEpub,
  buildZip,
  bytes,
  CONTAINER_XML,
  packageDocument,
  STORED,
  type EpubSpec,
} from "../zipFixtures";

async function read(spec: EpubSpec = {}) {
  return readEpub(new Blob([await buildEpub(spec)]));
}

/** The failure, or the metadata's title, so one assertion covers both arms. */
function outcome(reading: Awaited<ReturnType<typeof readEpub>>): string {
  return reading.ok ? `read: ${reading.metadata.title}` : reading.failure;
}

describe("reading a whole EPUB", () => {
  it("yields the metadata the package document carried", async () => {
    const reading = await read();
    expect(reading.ok && reading.metadata).toMatchObject({
      title: "Dune",
      authors: ["Frank Herbert"],
      language: "en",
    });
  });

  it("follows the container to wherever the package document is", async () => {
    // The path is not fixed and is not guessable: measured over 79 real files
    // it took eight different values, `OEBPS/content.opf` in 42 of them and
    // something else in the other 37.
    const reading = await read({ packagePath: "EPUB/package.opf" });
    expect(outcome(reading)).toBe("read: Dune");
  });

  it("resolves a percent escaped path", async () => {
    const reading = await read({
      packagePath: "OEBPS/my%20book.opf",
      storedAt: "OEBPS/my book.opf",
    });
    expect(outcome(reading)).toBe("read: Dune");
  });

  it("prefers an exact match over the unescaped one", async () => {
    // A literal percent in a filename is not an escape, and unescaping first
    // would stop such an entry matching at all.
    const reading = await read({
      packagePath: "OEBPS/100%25.opf",
      storedAt: "OEBPS/100%25.opf",
    });
    expect(outcome(reading)).toBe("read: Dune");
  });
});

describe("a file that is not an EPUB", () => {
  it("refuses something that is not an archive", async () => {
    const reading = await readEpub(new Blob([bytes("just some text")]));
    expect(outcome(reading)).toBe("not-an-epub");
  });

  it("refuses a zip with no container document", async () => {
    // A CBZ lands here, which is the point of saying "not an EPUB" rather than
    // "damaged": nothing is wrong with the file.
    const zip = await buildZip({
      entries: [{ name: "page-001.jpg", data: "not really a jpeg" }],
    });
    expect(outcome(await readEpub(new Blob([zip])))).toBe("not-an-epub");
  });

  it("refuses a container that names a package document the archive lacks", async () => {
    const reading = await read({
      packagePath: "EPUB/package.opf",
      storedAt: "EPUB/somewhere-else.opf",
    });
    expect(outcome(reading)).toBe("not-an-epub");
  });

  it("refuses a container that is not a container document", async () => {
    const reading = await read({ container: "<html><body>nope</body></html>" });
    expect(outcome(reading)).toBe("not-an-epub");
  });

  it("refuses a container naming no rootfile", async () => {
    const reading = await read({
      container: `<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles/></container>`,
    });
    expect(outcome(reading)).toBe("not-an-epub");
  });

  it("refuses a container that declares its own entities", async () => {
    // The container is parsed by the same engine and is the same exposure as
    // the package document. See `opf.declaresEntities`.
    const reading = await read({
      container: `<?xml version="1.0"?>
<!DOCTYPE container [<!ENTITY p "OEBPS/content.opf">]>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="&p;" media-type="application/oebps-package+xml"/></rootfiles></container>`,
    });
    expect(outcome(reading)).toBe("not-an-epub");
  });

  it("refuses a package document that is not one", async () => {
    const reading = await read({ opf: "<html><body>nope</body></html>" });
    expect(outcome(reading)).toBe("not-an-epub");
  });
});

describe("a file that cannot be read", () => {
  it("says protected for an encrypted entry, because that is DRM", async () => {
    const zip = await buildZip({
      entries: [
        { name: "mimetype", data: "application/epub+zip", method: STORED },
        { name: "META-INF/container.xml", data: CONTAINER_XML(), flags: 0x1 },
      ],
    });
    expect(outcome(await readEpub(new Blob([zip])))).toBe("protected");
  });

  it("says damaged for an entry whose bytes are not a deflate stream", async () => {
    // Reaches this module as a `TypeError` from the inflater rather than as a
    // named failure, so without the read loop's guard it escapes `readEpub`
    // entirely and no caller's `ok: false` ever sees it.
    const zip = await buildZip({
      entries: [
        {
          name: "META-INF/container.xml",
          data: "this is not deflate",
          method: STORED,
          centralMethod: 8,
        },
      ],
    });
    expect(outcome(await readEpub(new Blob([zip])))).toBe("damaged");
  });

  it("says unsupported for a zip64 archive", async () => {
    const zip = await buildZip({
      entries: [{ name: "META-INF/container.xml", data: CONTAINER_XML() }],
      centralDirectoryOffset: 0xffffffff,
    });
    expect(outcome(await readEpub(new Blob([zip])))).toBe("unsupported");
  });

  it("says damaged for a directory pointing past the end of the file", async () => {
    const zip = await buildZip({
      entries: [{ name: "META-INF/container.xml", data: CONTAINER_XML() }],
      centralDirectorySize: 500_000,
    });
    expect(outcome(await readEpub(new Blob([zip])))).toBe("damaged");
  });

  it("says too large for a package document over the cap", async () => {
    // The cap is 4 MiB against a measured largest of 253,032 bytes over 79 real
    // files, so reaching it means something other than a book's metadata.
    const padding = "<dc:subject>x</dc:subject>".repeat(200_000);
    const reading = await read({
      opf: packageDocument(`<dc:title>Dune</dc:title>${padding}`),
    });
    expect(outcome(reading)).toBe("too-large");
  });

  it("fails as one file rather than throwing at the caller", async () => {
    // The whole reason this returns a union instead of throwing: a folder of
    // three hundred files must not end at the first bad one.
    const reading = await readEpub(new Blob([bytes("nope")]));
    expect(reading.ok).toBe(false);
  });
});
