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

import * as epub from "../../src/lib/epub";
import {
  MAX_CONTAINER_BYTES,
  MAX_PACKAGE_BYTES,
  readEpub,
  type EpubReading,
} from "../../src/lib/epub";
import { holds, PROFILE, PROPERTY, witness } from "../property";
import {
  buildEpub,
  buildZip,
  bytes,
  CONTAINER_XML,
  epubSpec,
  FAR_PAST,
  isBomb,
  packageDocument,
  STORED,
  type EpubSpec,
} from "../zipFixtures";
import {
  expectNamedOutcome,
  hostile,
  overrunBreach,
  stoppedAt,
  type Door,
  type Hostile,
  type Measured,
} from "./readerContract";
import { withoutDecompressionStream } from "./withoutDecompression";

async function read(spec: EpubSpec = {}) {
  return readEpub(new Blob([await buildEpub(spec)]));
}

/** The failure, or the metadata's title, so one assertion covers both arms. */
function verdict(reading: Awaited<ReturnType<typeof readEpub>>): string {
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
    expect(verdict(reading)).toBe("read: Dune");
  });

  it("resolves a percent escaped path", async () => {
    const reading = await read({
      packagePath: "OEBPS/my%20book.opf",
      storedAt: "OEBPS/my book.opf",
    });
    expect(verdict(reading)).toBe("read: Dune");
  });

  it("prefers an exact match over the unescaped one", async () => {
    // A literal percent in a filename is not an escape, and unescaping first
    // would stop such an entry matching at all.
    const reading = await read({
      packagePath: "OEBPS/100%25.opf",
      storedAt: "OEBPS/100%25.opf",
    });
    expect(verdict(reading)).toBe("read: Dune");
  });
});

describe("a file that is not an EPUB", () => {
  it("refuses something that is not an archive", async () => {
    const reading = await readEpub(new Blob([bytes("just some text")]));
    expect(verdict(reading)).toBe("not-an-epub");
  });

  it("refuses a zip with no container document", async () => {
    // A CBZ lands here, which is the point of saying "not an EPUB" rather than
    // "damaged": nothing is wrong with the file.
    const zip = await buildZip({
      entries: [{ name: "page-001.jpg", data: "not really a jpeg" }],
    });
    expect(verdict(await readEpub(new Blob([zip])))).toBe("not-an-epub");
  });

  it("refuses a container that names a package document the archive lacks", async () => {
    const reading = await read({
      packagePath: "EPUB/package.opf",
      storedAt: "EPUB/somewhere-else.opf",
    });
    expect(verdict(reading)).toBe("not-an-epub");
  });

  it("refuses a container that is not a container document", async () => {
    const reading = await read({ container: "<html><body>nope</body></html>" });
    expect(verdict(reading)).toBe("not-an-epub");
  });

  it("refuses a container naming no rootfile", async () => {
    const reading = await read({
      container: `<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles/></container>`,
    });
    expect(verdict(reading)).toBe("not-an-epub");
  });

  it("refuses a container that declares its own entities", async () => {
    // The container is parsed by the same engine and is the same exposure as
    // the package document. See `xmlEntities.declaresEntities`.
    const reading = await read({
      container: `<?xml version="1.0"?>
<!DOCTYPE container [<!ENTITY p "OEBPS/content.opf">]>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="&p;" media-type="application/oebps-package+xml"/></rootfiles></container>`,
    });
    expect(verdict(reading)).toBe("not-an-epub");
  });

  it("refuses a package document that is not one", async () => {
    const reading = await read({ opf: "<html><body>nope</body></html>" });
    expect(verdict(reading)).toBe("not-an-epub");
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
    expect(verdict(await readEpub(new Blob([zip])))).toBe("protected");
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
    expect(verdict(await readEpub(new Blob([zip])))).toBe("damaged");
  });

  it("says unsupported for a zip64 archive", async () => {
    const zip = await buildZip({
      entries: [{ name: "META-INF/container.xml", data: CONTAINER_XML() }],
      centralDirectoryOffset: 0xffffffff,
    });
    expect(verdict(await readEpub(new Blob([zip])))).toBe("unsupported");
  });

  it("says damaged for a directory pointing past the end of the file", async () => {
    const zip = await buildZip({
      entries: [{ name: "META-INF/container.xml", data: CONTAINER_XML() }],
      centralDirectorySize: 500_000,
    });
    expect(verdict(await readEpub(new Blob([zip])))).toBe("damaged");
  });

  it("says too large for a package document over the cap", async () => {
    // The cap is 4 MiB against a measured largest of 253,032 bytes over 79 real
    // files, so reaching it means something other than a book's metadata.
    const padding = "<dc:subject>x</dc:subject>".repeat(200_000);
    const reading = await read({
      opf: packageDocument(`<dc:title>Dune</dc:title>${padding}`),
    });
    expect(verdict(reading)).toBe("too-large");
  });

  it("fails as one file rather than throwing at the caller", async () => {
    // The whole reason this returns a union instead of throwing: a folder of
    // three hundred files must not end at the first bad one.
    const reading = await readEpub(new Blob([bytes("nope")]));
    expect(reading.ok).toBe(false);
  });

  it("says the browser cannot inflate, not that the book is damaged", async () => {
    // **The sentence a member reads is the point of this arm.** Every other
    // failure here is about the file they picked, and this one is about the
    // browser they picked it in: `ScanPage` renders `file.noInflate` for it and
    // `damaged` for a broken archive, so a reader answering the wrong one of
    // the two sends somebody looking at a book that is fine.
    //
    // The archive is the ordinary one, deflated as `buildZip` writes it, so
    // what changed is the runtime and nothing else.
    const reading = await withoutDecompressionStream(() => read());

    expect(verdict(reading)).toBe("no-inflate");
  });
});

/**
 * `readEpub` as a door, its charge held against what the meter saw inflate.
 *
 * **The charge is the promise `takeout.ts` stands on**: a caller keeping a
 * total can only see what this reports, so a read inflating more than it is
 * charged is a budget spent in silence. A read that ended is charged what it
 * inflated, and a read the reader stopped is charged its ceiling while its
 * inflater was allowed the chunk that crossed it, so the slack is one chunk
 * per stopped read and nothing for the rest.
 *
 * **The per inflater bound is the package document's**, the larger of the
 * two, because the meter cannot tell which entry an inflater serves. The
 * container's own ceiling is held by the property's reach instead: a
 * container bomb must be seen stopped within a chunk of it.
 */
const door: Door<EpubSpec, EpubReading> = {
  module: epub,
  ceilings: () => ({
    perInflate: MAX_PACKAGE_BYTES,
    inflated: MAX_CONTAINER_BYTES + MAX_PACKAGE_BYTES,
    refusesEntities: true,
  }),
  build: buildEpub,
  open: async (file, meter) => {
    let charged = 0;
    const reading = await readEpub(file, (spent) => {
      charged += spent;
    });
    const { inflated, ended, largestChunk } = meter.counted;
    const stopped = ended.filter((one) => !one).length;
    meter.require(
      charged + stopped * largestChunk >= inflated,
      `charged ${charged} bytes for ${inflated} inflated, ${stopped} of the reads stopped`,
    );
    return reading;
  },
};

/**
 * The same door held to the container's ceiling alone, for the named case
 * where the container is the only read. **A function of its own**, so its
 * control and its case share it, which is how `doorLedger.ts` pairs them.
 */
const containerOnly: Door<EpubSpec, EpubReading> = {
  ...door,
  ceilings: () => ({
    perInflate: MAX_CONTAINER_BYTES,
    refusesEntities: true,
  }),
};

/** An answer of `too-large`, which is how both bombs end. */
const tooLarge = (outcome: Measured<EpubReading>["outcome"]) =>
  "answered" in outcome &&
  !outcome.answered.ok &&
  outcome.answered.failure === "too-large";

/**
 * Whether a drawn EPUB hides a bomb behind the read of `name`. Reached only
 * where the real document is out of the way: the package moved aside, or no
 * container written, since the first entry of a name is the one read.
 */
const reached =
  (name: string, bound: number) =>
  ({ spec, patches }: Hostile<EpubSpec>) =>
    patches.length === 0 &&
    (name === "META-INF/container.xml"
      ? spec.container === null
      : spec.storedAt !== undefined && spec.storedAt !== name) &&
    (spec.extra ?? []).some(
      (entry) => entry.name === name && isBomb(entry, bound),
    );

describe("any EPUB a member picks", () => {
  it(
    "is read or refused by name, inflating no chunk past either ceiling and charging what it inflates",
    PROPERTY,
    async () => {
      // **Two reaches, told apart by position**: the container is read first,
      // so a container bomb is the one call whose only inflater stopped at
      // the container's ceiling. That is what holds the smaller ceiling, which
      // the per inflater bound above cannot: a container read with the
      // package's limit inflates its whole bomb and never stops there.
      expect(
        await holds(
          hostile(epubSpec()),
          async (input) => expectNamedOutcome(door, input),
          {
            "stopped a package bomb at the package's ceiling": (
              _,
              { outcome, counted },
            ) => tooLarge(outcome) && stoppedAt(counted, MAX_PACKAGE_BYTES),
            "stopped a container bomb at the container's own ceiling": (
              _,
              { outcome, counted },
            ) =>
              tooLarge(outcome) &&
              counted.inflaters === 1 &&
              stoppedAt(counted, MAX_CONTAINER_BYTES),
          },
        ),
      ).toBe(PROFILE.runs);
    },
  );

  it("is metered, so the ceilings above are not held over nothing", async () => {
    const { outcome, counted } = await expectNamedOutcome(door, {
      spec: {},
      patches: [],
    });

    expect(outcome).toMatchObject({
      answered: { ok: true, metadata: { title: "Dune" } },
    });
    // The container and the package document, both deflated.
    expect(counted.inflaters).toBe(2);
    expect(counted.inflated).toBeGreaterThan(0);
  });

  it("declares the ceilings it is held to, so one deleted or loosened reds", async () => {
    expect(
      await overrunBreach(door, {
        ceiling: "perInflate",
        bound: MAX_PACKAGE_BYTES,
      }),
    ).toContain(`against a bound of ${MAX_PACKAGE_BYTES}`);
    const both = MAX_CONTAINER_BYTES + MAX_PACKAGE_BYTES;
    expect(
      await overrunBreach(door, {
        ceiling: "inflated",
        bound: both,
        each: MAX_PACKAGE_BYTES,
      }),
    ).toContain(`inflated against a ceiling of ${both}`);
    expect(await overrunBreach(door, { ceiling: "refusesEntities" })).toContain(
      "declaring an entity",
    );
  });

  it("holds the container's own door to its ceilings, so one deleted or loosened reds", async () => {
    // The control for the door below, which declares a bound of its own.
    expect(
      await overrunBreach(containerOnly, {
        ceiling: "perInflate",
        bound: MAX_CONTAINER_BYTES,
      }),
    ).toContain(`against a bound of ${MAX_CONTAINER_BYTES}`);
    expect(
      await overrunBreach(containerOnly, { ceiling: "refusesEntities" }),
    ).toContain("declaring an entity");
  });

  it("stops the container's inflater at the container's own ceiling", async () => {
    // **The container's ceiling by example**, beside the reach that holds it
    // in the property: with the container the only read, its inflater is the
    // first and the last, so this door can hold it to its own ceiling.
    // Measured by planting the package limit at the container's read, which
    // reds this.
    const { outcome, counted } = await expectNamedOutcome(containerOnly, {
      spec: {
        container: null,
        extra: [
          {
            name: "META-INF/container.xml",
            data: { zeroes: MAX_CONTAINER_BYTES + FAR_PAST },
            centralUncompressedSize: 1,
          },
        ],
      },
      patches: [],
    });

    expect(outcome).toEqual({ answered: { ok: false, failure: "too-large" } });
    expect(counted.inflaters).toBe(1);
  });

  it("draws a bomb behind each of its two reads", async () => {
    await witness(hostile(epubSpec()), {
      "hides a bomb behind the package's read": reached(
        "OEBPS/content.opf",
        MAX_PACKAGE_BYTES,
      ),
      "hides a bomb behind the container's read": reached(
        "META-INF/container.xml",
        MAX_CONTAINER_BYTES,
      ),
    });
  });
});
