/** Tests for src/lib/audiobook.ts. */

import { afterEach, describe, expect, it, vi } from "vitest";

import { readAudioTags } from "../../src/lib/audiobook";
import {
  box,
  brokenBox,
  id3v1,
  id3v2,
  ilstEntry,
  latin1,
  longBox,
  m4b,
  mp3,
  plainFrame,
  synchronise,
  textFrame,
  utf16,
} from "../audioFixtures";

const utf8 = new TextEncoder();

async function tagsOf(file: Blob, extension: ".m4b" | ".mp3" = ".mp3") {
  const reading = await readAudioTags(file, extension);
  return reading.ok ? reading.tags : null;
}

async function failureOf(file: Blob, extension: ".m4b" | ".mp3" = ".mp3") {
  const reading = await readAudioTags(file, extension);
  return reading.ok ? null : reading.failure;
}

describe("an ID3 tagged MP3", () => {
  it("reads the album, the artist and the file's own title", async () => {
    // The mapping the corpus shows: `TALB` is the book, `TPE1` the author and
    // `TIT2` this file's chapter.
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          frames: [
            plainFrame("TALB", "Robinson Crusoe"),
            plainFrame("TPE1", "Daniel Defoe"),
            plainFrame("TIT2", "Chapter 1 - Start in Life"),
          ],
        }),
      }),
    );

    expect(tags).toEqual({
      album: "Robinson Crusoe",
      artists: ["Daniel Defoe"],
      title: "Chapter 1 - Start in Life",
    });
  });

  it("does not read the album artist, which is the narrator", async () => {
    // Measured on `shortstory029_diarymadman_add.mp3`, which carries
    // `TPE1='Guy de Maupassant'` beside `TPE2='Alan Davis Drake  '`, the
    // LibriVox reader. Taking the second would file a narrator as an author.
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          frames: [
            plainFrame("TPE1", "Guy de Maupassant"),
            plainFrame("TPE2", "Alan Davis Drake  "),
          ],
        }),
      }),
    );

    expect(tags?.artists).toEqual(["Guy de Maupassant"]);
  });

  it("does not read the year, which is when the recording was made", async () => {
    // Defoe's Robinson Crusoe carries `TYER 2006`. There is nowhere for a
    // recording year to go that would not read as the book's.
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          frames: [
            plainFrame("TALB", "Robinson Crusoe"),
            plainFrame("TYER", "2006"),
          ],
        }),
      }),
    );

    expect(Object.keys(tags ?? {})).toEqual(["album", "artists", "title"]);
    expect(JSON.stringify(tags)).not.toContain("2006");
  });

  it("takes the padding a real writer leaves off a value", async () => {
    // Both halves are from the corpus: a trailing NUL on every 2.3 latin-1
    // value, and two trailing spaces on one narrator's name.
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          frames: [plainFrame("TALB", "Robinson Crusoe  \u0000")],
        }),
      }),
    );

    expect(tags?.album).toBe("Robinson Crusoe");
  });

  it("reads a 2.2 tag, whose frame names are three characters", async () => {
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          major: 2,
          frames: [
            plainFrame("TAL", "Dune"),
            plainFrame("TP1", "Frank Herbert"),
          ],
        }),
      }),
    );

    expect(tags).toMatchObject({ album: "Dune", artists: ["Frank Herbert"] });
  });

  it("takes several artists out of one NUL separated 2.4 frame", async () => {
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          major: 4,
          frames: [
            textFrame(
              "TPE1",
              new Uint8Array([
                3,
                ...utf8.encode("Ursula K. Le Guin\u0000Kate Chopin"),
              ]),
            ),
          ],
        }),
      }),
    );

    expect(tags?.artists).toEqual(["Ursula K. Le Guin", "Kate Chopin"]);
  });

  it("decodes UTF-16 whichever way round the byte order mark says", async () => {
    for (const bigEndian of [false, true]) {
      const tags = await tagsOf(
        mp3({
          head: id3v2({
            frames: [
              textFrame(
                "TALB",
                new Uint8Array([1, ...utf16("Römische Geschichte", bigEndian)]),
              ),
            ],
          }),
        }),
      );

      expect(tags?.album).toBe("Römische Geschichte");
    }
  });

  it("undoes unsynchronisation before it reads any size", async () => {
    // The flag inserts a zero after every 0xFF, including inside the frame
    // sizes. A reader that walks the tag as written lands mid frame.
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          unsynchronised: true,
          frames: [plainFrame("TALB", "ÿ  Sound and Fury")],
        }),
      }),
    );

    expect(tags?.album).toBe("ÿ Sound and Fury");
  });

  it("undoes it per frame when a 2.4 frame asks for it", async () => {
    const body = new Uint8Array([0, ...latin1("ÿ Dune")]);
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          major: 4,
          frames: [{ id: "TALB", body: synchronise(body), flags: 0x0002 }],
        }),
      }),
    );

    expect(tags?.album).toBe("ÿ Dune");
  });

  it("skips a compressed frame rather than reading its bytes as text", async () => {
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          frames: [
            {
              id: "TALB",
              body: new Uint8Array([0, 1, 2, 3, 4]),
              flags: 0x0080,
            },
            plainFrame("TPE1", "Zane Grey"),
          ],
        }),
      }),
    );

    expect(tags).toMatchObject({ album: null, artists: ["Zane Grey"] });
  });

  it("steps over the extended header each version spells differently", async () => {
    // 2.3 counts the bytes after the length; 2.4 counts itself as well. Getting
    // it wrong by four bytes puts the walk inside the first frame.
    const three = await tagsOf(
      mp3({
        head: id3v2({
          major: 3,
          extendedHeader: new Uint8Array([0, 0, 0, 6, 0, 0, 0, 0, 0, 0]),
          frames: [plainFrame("TALB", "Dune")],
        }),
      }),
    );
    const four = await tagsOf(
      mp3({
        head: id3v2({
          major: 4,
          extendedHeader: new Uint8Array([0, 0, 0, 6, 1, 0]),
          frames: [plainFrame("TALB", "Dune")],
        }),
      }),
    );

    expect(three?.album).toBe("Dune");
    expect(four?.album).toBe("Dune");
  });

  it("stops at the padding rather than reading it as frames", async () => {
    const tags = await tagsOf(
      mp3({
        head: id3v2({ frames: [plainFrame("TALB", "Dune")], padding: 512 }),
      }),
    );

    expect(tags?.album).toBe("Dune");
  });

  it("refuses a tag length that is not synchsafe", async () => {
    // A high bit set here means the real length is not the one this would
    // compute, and reading the difference as frames walks into the audio.
    expect(
      await failureOf(
        mp3({
          // Long enough that the length's low byte carries a high bit, which
          // is the difference between a plain integer and a synchsafe one.
          head: id3v2({
            plainSize: true,
            padding: 200,
            frames: [plainFrame("TALB", "Dune")],
          }),
          audio: new Uint8Array(200),
        }),
      ),
    ).toBe("no-tags");
  });

  it("stops at a frame that claims more than the tag holds", async () => {
    const tag = id3v2({ frames: [plainFrame("TALB", "Dune")] });
    // The frame's own length, four bytes into its ten byte header, made huge.
    new DataView(tag.buffer).setUint32(10 + 4, 0xffff);

    expect(await tagsOf(mp3({ head: tag }))).toBeNull();
  });

  it("reads the tail tag when there is no head one", async () => {
    // Measured: 3 of 3 of the Internet Archive's own 64 kbps derivatives of the
    // LibriVox chapters carry no ID3v2 at all, and the one whose tail was
    // fetched carried a complete ID3v1.
    const tags = await tagsOf(
      mp3({
        tail: id3v1({
          title: "Chapter 1 - Start in Life",
          artist: "Daniel Defoe",
          album: "Robinson Crusoe",
        }),
      }),
    );

    expect(tags).toEqual({
      album: "Robinson Crusoe",
      artists: ["Daniel Defoe"],
      title: "Chapter 1 - Start in Life",
    });
  });

  it("reads the tail tag when the head one named nothing wanted", async () => {
    const tags = await tagsOf(
      mp3({
        head: id3v2({ frames: [plainFrame("TENC", "iTunes v6.0.2")] }),
        tail: id3v1({ album: "Robinson Crusoe" }),
      }),
    );

    expect(tags?.album).toBe("Robinson Crusoe");
  });

  it("cuts a value the length of the tag it came in", async () => {
    // A member's queue keeps every file's tags for the life of the run, so a
    // megabyte in one string is a megabyte per file in a folder pick. The cut
    // is far above `TEXT_CEILINGS.title`, so nothing a column would have kept
    // is lost here.
    const tags = await tagsOf(
      mp3({
        head: id3v2({ frames: [plainFrame("TALB", "a".repeat(50_000))] }),
      }),
    );

    expect(tags?.album).toHaveLength(1000);
  });

  it("cuts it on a code point, never between the halves of a pair", async () => {
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          major: 4,
          frames: [
            textFrame(
              "TALB",
              new Uint8Array([3, ...utf8.encode("\u{1F4DA}".repeat(2000))]),
            ),
          ],
        }),
      }),
    );

    // A lone surrogate is a string no encoder will emit, and the server answers
    // 422 for the whole book rather than for the field. **Not a match against
    // the surrogate range**, which every well formed astral string is made of:
    // the round trip is what a lone one fails, by encoding to U+FFFD.
    const album = tags?.album ?? "";
    expect([...album]).toHaveLength(1000);
    expect(new TextDecoder().decode(new TextEncoder().encode(album))).toBe(
      album,
    );
  });

  it("keeps a bounded number of values out of one frame", async () => {
    // A 2.4 frame separates its values with a NUL and a hostile one carries half
    // a million. Measured before the bound: 5.07 MB retained from one 977 KB
    // file, and 101.4 MB from twenty of them.
    const tags = await tagsOf(
      mp3({
        head: id3v2({
          major: 4,
          frames: [
            textFrame(
              "TPE1",
              new Uint8Array([3, ...utf8.encode("A\u0000".repeat(50_000))]),
            ),
          ],
        }),
      }),
    );

    expect(tags?.artists).toHaveLength(32);
  });

  it("cannot be made to read more than its bounds allow", async () => {
    // The other half of the module's ceiling, and it was asserted nowhere: the
    // MP3 path reads a 10 byte header, at most `MAX_ID3_BYTES` of declared tag,
    // and the 128 byte tail, which is 1,048,714. A tag declaring more than the
    // cap is where that is reached.
    const slice = Blob.prototype.slice;
    let taken = 0;
    vi.spyOn(Blob.prototype, "slice").mockImplementation(function (
      this: Blob,
      start?: number,
      end?: number,
    ) {
      taken += (end ?? this.size) - (start ?? 0);
      return slice.call(this, start, end);
    });

    const head = id3v2({
      frames: [plainFrame("TALB", "Dune")],
      padding: 2 * 1024 * 1024,
    });
    const failure = await failureOf(mp3({ head }));

    // The wanted frame is inside the first mebibyte, so this reads the cap and
    // answers, rather than failing: the assertion is the cost, not the outcome.
    expect(failure).toBeNull();
    expect(taken).toBeLessThanOrEqual(1_048_714);
    // And it really did meet the cap rather than stopping at a short tag.
    expect(taken).toBeGreaterThan(1_000_000);
    // **Both arms bite, checked by moving the bound rather than by reading
    // them**: the lower fails at a cap of 512 KiB or below, the upper at 2 MiB.
    // This input takes 1,048,586, which is one tail read short of the upper arm,
    // because a read that succeeds never reaches the tail.
  });

  it("says a file with neither carries no tags", async () => {
    expect(await failureOf(mp3({ audio: new Uint8Array(4096) }))).toBe(
      "no-tags",
    );
  });
});

describe("an M4B", () => {
  it("reads the album, the artist and the file's own title", async () => {
    const tags = await tagsOf(
      m4b({
        entries: [
          ilstEntry("©alb", "Robinson Crusoe"),
          ilstEntry("©ART", "Daniel Defoe"),
          ilstEntry("©nam", "Robinson Crusoe Part 1"),
        ],
      }),
      ".m4b",
    );

    expect(tags).toEqual({
      album: "Robinson Crusoe",
      artists: ["Daniel Defoe"],
      title: "Robinson Crusoe Part 1",
    });
  });

  it("does not read the album artist, for the reason the MP3 does not", async () => {
    const tags = await tagsOf(
      m4b({
        entries: [
          ilstEntry("©ART", "Zane Grey"),
          ilstEntry("aART", "A narrator"),
        ],
      }),
      ".m4b",
    );

    expect(tags?.artists).toEqual(["Zane Grey"]);
  });

  it("finds the tags megabytes into the file without reading it", async () => {
    // The measured layout: `moov` sits after a multi megabyte first box in
    // every real file, and `udta` after the sample tables inside it. A prefix
    // read reaches neither. The bytes actually taken are counted here, because
    // a walk that works by reading the file would pass every other test.
    const slice = Blob.prototype.slice;
    let taken = 0;
    vi.spyOn(Blob.prototype, "slice").mockImplementation(function (
      this: Blob,
      start?: number,
      end?: number,
    ) {
      taken += (end ?? this.size) - (start ?? 0);
      return slice.call(this, start, end);
    });

    const file = m4b({
      before: [box("mdat", new Uint8Array(2 * 1024 * 1024))],
      moovChildren: [box("trak", new Uint8Array(1024 * 1024))],
      entries: [
        ilstEntry("covr", new Uint8Array(141_427), 13),
        ilstEntry("©alb", "Riders of the Purple Sage"),
      ],
    });
    const tags = await tagsOf(file, ".m4b");

    expect(tags?.album).toBe("Riders of the Purple Sage");
    expect(file.size).toBeGreaterThan(3 * 1024 * 1024);
    // Two orders of magnitude below the cover alone, which is the entry sitting
    // immediately before the one that was wanted.
    expect(taken).toBeLessThan(4096);
  });

  it("reads a `meta` written without its version and flags", async () => {
    const tags = await tagsOf(
      m4b({ metaIsFullBox: false, entries: [ilstEntry("©alb", "Dune")] }),
      ".m4b",
    );

    expect(tags?.album).toBe("Dune");
  });

  it("leaves an entry whose value is a picture alone", async () => {
    const tags = await tagsOf(
      m4b({ entries: [ilstEntry("©alb", new Uint8Array([1, 2, 3]), 13)] }),
      ".m4b",
    );

    expect(tags).toBeNull();
  });

  it("reads a box that carries its length as 64 bits", async () => {
    const tags = await tagsOf(
      new Blob([
        box("ftyp", latin1("M4A ")),
        longBox(
          "moov",
          box(
            "udta",
            box(
              "meta",
              new Uint8Array(4),
              box("ilst", ilstEntry("©alb", "Dune")),
            ),
          ),
        ),
      ] as BlobPart[]),
      ".m4b",
    );

    expect(tags?.album).toBe("Dune");
  });

  it("reads a last box that says it runs to the end", async () => {
    // A length of zero is legal for the last box and means exactly that.
    const moov = box(
      "moov",
      box(
        "udta",
        box("meta", new Uint8Array(4), box("ilst", ilstEntry("©alb", "Dune"))),
      ),
    );
    const toTheEnd = new Uint8Array(moov);
    new DataView(toTheEnd.buffer).setUint32(0, 0);

    expect(
      (
        await tagsOf(
          new Blob([box("ftyp", latin1("M4A ")), toTheEnd] as BlobPart[]),
          ".m4b",
        )
      )?.album,
    ).toBe("Dune");
  });

  it("refuses a box that claims more than its parent holds", async () => {
    // The one bound that makes every child strictly inside its parent, so a
    // walk cannot leave the region it was given however the lengths are written.
    const file = new Blob([
      box("ftyp", latin1("M4A ")),
      box("moov", brokenBox("udta", 0x7fffffff, new Uint8Array(16))),
    ] as BlobPart[]);

    expect(await failureOf(file, ".m4b")).toBe("no-tags");
  });

  it("gives up on a tree of empty boxes rather than walking it", async () => {
    // Cheap on disk and unbounded to walk, which is the shape a read budget is
    // for: ten thousand eight byte boxes is eighty kilobytes.
    const junk: Uint8Array[] = [];
    for (let index = 0; index < 10_000; index += 1) junk.push(box("free"));

    expect(
      await failureOf(
        m4b({ moovChildren: junk, entries: [ilstEntry("©alb", "Dune")] }),
        ".m4b",
      ),
    ).toBe("unreadable");
  });

  it("cannot be made to read more than its bounds allow", async () => {
    // **The reachable ceiling, measured rather than restated.** `MAX_READS` is
    // 128 and every entry read is preceded by its own header read, so at most 64
    // entry reads happen, each at most `MAX_ENTRY_BYTES`: 64 x 16,384 plus 64 x
    // 16 is 1,049,600. The entries below carry a wanted key and a value this
    // will not decode, so the walk never finds its three and never stops early.
    const slice = Blob.prototype.slice;
    let taken = 0;
    vi.spyOn(Blob.prototype, "slice").mockImplementation(function (
      this: Blob,
      start?: number,
      end?: number,
    ) {
      taken += (end ?? this.size) - (start ?? 0);
      return slice.call(this, start, end);
    });

    const entries = Array.from({ length: 200 }, () =>
      ilstEntry("\u00a9alb", new Uint8Array(20_000), 13),
    );
    const failure = await failureOf(m4b({ entries }), ".m4b");

    expect(failure).toBe("unreadable");
    expect(taken).toBeLessThanOrEqual(1_049_600);
    // The other half, so this cannot pass by walking nothing at all.
    expect(taken).toBeGreaterThan(500_000);
  });

  it("says a file with no moov carries no tags", async () => {
    expect(await failureOf(m4b({ withoutTags: true }), ".m4b")).toBe("no-tags");
  });

  it("says an MP3 opened as an M4B carries no tags", async () => {
    // A mis-named file is one entry's outcome, never an error page.
    expect(
      await failureOf(
        mp3({ head: id3v2({ frames: [plainFrame("TALB", "Dune")] }) }),
        ".m4b",
      ),
    ).toBe("no-tags");
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});
