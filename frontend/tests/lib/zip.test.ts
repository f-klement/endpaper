/**
 * @vitest-environment node
 *
 * Bytes and streams, no DOM. `DecompressionStream` and `Blob.slice` are node
 * globals, so building one costs more than this file spends running.
 */
/**
 * Tests for src/lib/zip.ts.
 *
 * Half of these are malformed archives, which is the half that matters: a
 * member's file is untrusted input, and what a broken or hostile one has to
 * produce is one named refusal rather than a hung tab. Every arm names the
 * `ZipFailure` it expects, so a refusal moving from one reason to another is a
 * failure rather than a still-green test.
 *
 * The last block is the prefix read, and what it is written against is the one
 * mistake that read makes available: answering "this is all I needed" with the
 * refusal that means "this file will not open". Every ceiling the whole read
 * enforces has its own arm there, read as a prefix, because a bound relaxed by
 * a new door is a bound gone rather than moved.
 */

import { describe, expect, it } from "vitest";

import { openZip, ZipError } from "../../src/lib/zip";
import {
  buildZip,
  bytes,
  DEFLATED,
  STORED,
  type ArchiveSpec,
} from "../zipFixtures";

async function open(spec: ArchiveSpec) {
  return openZip(new Blob([await buildZip(spec)]));
}

/** The failure a read produced, or the string that says it did not fail. */
async function failureOf(run: () => Promise<unknown>): Promise<string> {
  try {
    await run();
    return "no failure";
  } catch (error) {
    return error instanceof ZipError ? error.failure : `other: ${error}`;
  }
}

/**
 * Data deflate cannot shrink, so its compressed size is about its own size.
 *
 * xorshift32, whose period is 2^32 minus one, rather than a modular sequence.
 * **The first version of this was `(at * K) % 251`, which repeats every 251
 * bytes**: deflate found the period and shrank 64 KiB to a few hundred bytes,
 * and both tests below then passed with the bound they exist for deleted. Every
 * caller asserts the compressed size it got, so the premise is checked rather
 * than assumed.
 */
function incompressible(size: number): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(size);
  let state = 0x12345678;
  for (let at = 0; at < size; at += 1) {
    state ^= state << 13;
    state >>>= 0;
    state ^= state >>> 17;
    state ^= state << 5;
    state >>>= 0;
    out[at] = state & 0xff;
  }
  return out;
}

/**
 * A blob that records the largest slice asked of it.
 *
 * `openZip` only ever calls `size` and `slice`, so a stand in for the two says
 * how many bytes a read actually allocated. **That is the only observable
 * difference between refusing before a slice and refusing after one**, and both
 * refuse with the same reason, so a test asserting on the reason alone would
 * pass either way. Cast rather than subclassed because `Blob` is not the
 * contract here: those two members are.
 */
function watchedBlob(data: Uint8Array<ArrayBuffer>) {
  const real = new Blob([data]);
  let biggest = 0;
  const blob = {
    size: real.size,
    slice: (start: number, end: number) => {
      biggest = Math.max(biggest, end - start);
      return real.slice(start, end);
    },
  } as unknown as Blob;
  return {
    blob,
    largestSlice: () => biggest,
    forget: () => {
      biggest = 0;
    },
  };
}

const HELLO: ArchiveSpec = {
  entries: [
    { name: "one.txt", data: "hello", method: STORED },
    { name: "two.txt", data: "goodbye", method: DEFLATED },
  ],
};

describe("openZip", () => {
  it("lists the entries in central directory order", async () => {
    const archive = await open(HELLO);
    expect(archive.entries.map((entry) => entry.name)).toEqual([
      "one.txt",
      "two.txt",
    ]);
  });

  it("finds an entry by its exact path", async () => {
    const archive = await open(HELLO);
    expect(archive.find("two.txt")?.method).toBe(DEFLATED);
    expect(archive.find("Two.txt")).toBeUndefined();
  });

  it("reads a stored entry", async () => {
    const archive = await open(HELLO);
    const read = await archive.read(archive.find("one.txt")!, 1024);
    expect(new TextDecoder().decode(read)).toBe("hello");
  });

  it("reads a deflated entry", async () => {
    const archive = await open(HELLO);
    const read = await archive.read(archive.find("two.txt")!, 1024);
    expect(new TextDecoder().decode(read)).toBe("goodbye");
  });

  it("skips the local header's own extra field, not the directory's", async () => {
    // The two headers carry independent extra fields and writers pad them
    // differently. Taking the directory's length here lands the read seven
    // bytes short of the data, which for a deflated entry is a stream that
    // does not start where it says.
    const archive = await open({
      entries: [
        {
          name: "one.txt",
          data: "hello",
          method: DEFLATED,
          localExtra: new Uint8Array(7),
          centralExtra: new Uint8Array(0),
        },
      ],
    });
    const read = await archive.read(archive.find("one.txt")!, 1024);
    expect(new TextDecoder().decode(read)).toBe("hello");
  });

  it("takes the last end of central directory record, not one inside the file", async () => {
    // The four signature bytes occur in ordinary data, so finding them is not
    // evidence of anything. What decides it is that the comment length has to
    // account for exactly the bytes left after the record. This archive carries
    // a decoy whose comment length does not, so a reader that only matched the
    // signature would read a directory that is not there.
    const decoy = new Uint8Array(22);
    new DataView(decoy.buffer).setUint32(0, 0x06054b50, true);
    new DataView(decoy.buffer).setUint16(20, 5, true);

    const archive = await open({ ...HELLO, comment: decoy });
    expect(archive.entries.map((entry) => entry.name)).toEqual([
      "one.txt",
      "two.txt",
    ]);
  });
});

describe("a zip that cannot be trusted", () => {
  it("refuses a file that is not a zip", async () => {
    expect(
      await failureOf(() => openZip(new Blob([bytes("not a zip at all")]))),
    ).toBe("not-a-zip");
  });

  it("refuses a file too short to hold a directory record", async () => {
    expect(await failureOf(() => openZip(new Blob([bytes("hi")])))).toBe(
      "not-a-zip",
    );
  });

  it("refuses a zip64 archive rather than misreading it", async () => {
    // The sentinel is what identifies zip64, and reading past it would take a
    // 32 bit field that says "look in the extra field" as an offset.
    expect(
      await failureOf(() =>
        open({ ...HELLO, centralDirectoryOffset: 0xffffffff }),
      ),
    ).toBe("zip64");
  });

  it("refuses an archive whose entry count is the zip64 sentinel", async () => {
    expect(
      await failureOf(() => open({ ...HELLO, totalEntries: 0xffff })),
    ).toBe("zip64");
  });

  // Each field in turn, and each on its own, because a directory header carries
  // three of these and a guard covering one of the three passes every test
  // written for another. Found by mutation: with the whole per entry check
  // deleted the file was green, because the only zip64 arms here read the end
  // of central directory record.
  it.each([
    ["the entry's local header offset", { centralHeaderOffset: 0xffffffff }],
    ["the entry's compressed size", { centralCompressedSize: 0xffffffff }],
    ["the entry's uncompressed size", { centralUncompressedSize: 0xffffffff }],
  ])("refuses a zip64 sentinel in %s", async (_name, override) => {
    expect(
      await failureOf(() =>
        open({
          entries: [{ name: "one.txt", data: "hello", ...override }],
        }),
      ),
    ).toBe("zip64");
  });

  it("refuses a spanned archive", async () => {
    expect(await failureOf(() => open({ ...HELLO, disk: 1 }))).toBe(
      "unsupported",
    );
  });

  it("refuses a directory that runs past the end of the file", async () => {
    expect(
      await failureOf(() => open({ ...HELLO, centralDirectorySize: 100_000 })),
    ).toBe("truncated");
  });

  it("refuses an encrypted entry", async () => {
    expect(
      await failureOf(() =>
        open({ entries: [{ name: "one.txt", data: "hello", flags: 0x1 }] }),
      ),
    ).toBe("encrypted");
  });
});

describe("an entry that cannot be read", () => {
  it("refuses one whose local header is not where the directory says", async () => {
    const archive = await open({
      entries: [
        {
          name: "one.txt",
          data: "hello",
          method: STORED,
          centralHeaderOffset: 900_000,
        },
      ],
    });
    expect(await failureOf(() => archive.read(archive.entries[0]!, 1024))).toBe(
      "truncated",
    );
  });

  it("refuses one whose data runs past the end of the file", async () => {
    const archive = await open({
      entries: [
        {
          name: "one.txt",
          data: "hello",
          method: STORED,
          centralCompressedSize: 900_000,
        },
      ],
    });
    expect(await failureOf(() => archive.read(archive.entries[0]!, 1024))).toBe(
      "truncated",
    );
  });

  it("refuses bytes that are not a deflate stream", async () => {
    // The inflater rejects with a `TypeError`, not a `ZipError`, so an
    // unguarded read loop lets one escape past every caller catching the
    // module's own failures. A broken archive is one entry's named failure.
    const archive = await open({
      entries: [
        {
          name: "one.txt",
          data: "this is not deflate",
          method: STORED,
          centralMethod: DEFLATED,
        },
      ],
    });
    expect(await failureOf(() => archive.read(archive.entries[0]!, 1024))).toBe(
      "truncated",
    );
  });

  it("refuses a deflate stream that stops halfway", async () => {
    const archive = await open({
      entries: [
        {
          name: "one.txt",
          data: incompressible(4096),
          method: DEFLATED,
          centralCompressedSize: 40,
        },
      ],
    });
    expect(await failureOf(() => archive.read(archive.entries[0]!, 8192))).toBe(
      "truncated",
    );
  });

  it("refuses a compression method it does not implement", async () => {
    const archive = await open({
      entries: [
        { name: "one.txt", data: "hello", method: STORED, centralMethod: 12 },
      ],
    });
    expect(await failureOf(() => archive.read(archive.entries[0]!, 1024))).toBe(
      "unsupported",
    );
  });

  it("refuses one asked for with a limit that is not a number", async () => {
    // The whole read's half of the same guard. The three ceilings all compare
    // against `limit`, so a `NaN` there passes every one of them.
    const archive = await open(HELLO);

    expect(
      await failureOf(() => archive.read(archive.find("one.txt")!, Number.NaN)),
    ).toBe("too-large");
  });

  it("refuses one that says up front it is over the limit", async () => {
    const archive = await open(HELLO);
    expect(
      await failureOf(() => archive.read(archive.find("one.txt")!, 4)),
    ).toBe("too-large");
  });

  it("refuses a stored entry over the limit", async () => {
    // The declared size is understated here, so this is the copy path's own
    // bound rather than the claim being checked twice.
    const archive = await open({
      entries: [
        {
          name: "one.txt",
          data: "hello",
          method: STORED,
          centralUncompressedSize: 1,
        },
      ],
    });
    expect(await failureOf(() => archive.read(archive.entries[0]!, 2))).toBe(
      "too-large",
    );
  });

  it("never reads more compressed bytes than the limit could need", async () => {
    // **The bound on what is read IN, which the output cap cannot stand in
    // for**: both bounds answer with `too-large`, so the reason is not evidence
    // and the assertion is on the largest slice actually asked of the file. The
    // entry is incompressible, so it holds about 64 KiB whatever it declares,
    // and its declared uncompressed size is understated to get past the check
    // above. Without this bound the whole 64 KiB is allocated before the
    // inflater emits a byte.
    const watched = watchedBlob(
      await buildZip({
        entries: [
          {
            name: "wide",
            data: incompressible(64 * 1024),
            method: DEFLATED,
            centralUncompressedSize: 1,
          },
        ],
      }),
    );
    const archive = await openZip(watched.blob);
    // The premise, checked rather than assumed: the entry really does hold
    // about 64 KiB, so a read that slices it really would allocate that much.
    expect(archive.entries[0]!.compressedSize).toBeGreaterThan(60_000);
    // The directory reads are not what is being measured.
    watched.forget();

    expect(await failureOf(() => archive.read(archive.entries[0]!, 16))).toBe(
      "too-large",
    );
    // The local header and nothing else. 64 KiB would be the whole entry.
    expect(watched.largestSlice()).toBeLessThan(1024);
  });

  it("allows deflate's own worst case expansion", async () => {
    // The bound is not simply the limit: a stored deflate block adds five bytes
    // of header per 65,535, so incompressible data comes out slightly larger
    // than it went in, and a bound of exactly the limit would refuse an entry
    // that is exactly the size it is allowed to be.
    const noise = incompressible(4096);
    const archive = await open({
      entries: [{ name: "noise", data: noise, method: DEFLATED }],
    });
    // The premise: deflate really did make it bigger. Without this the test
    // passes against a bound of exactly the limit and proves nothing.
    expect(archive.entries[0]!.compressedSize).toBeGreaterThan(noise.length);

    const read = await archive.read(archive.entries[0]!, noise.length);
    expect(read.length).toBe(noise.length);
  });

  it("refuses an entry that inflates past the limit however small it claims to be", async () => {
    // **The test the whole bound exists for.** A zip bomb declares a modest
    // entry: 64 KB of zeros deflates to about 80 bytes, and this one says it
    // holds ten. A reader trusting the directory would allocate on the claim
    // and then keep reading.
    const archive = await open({
      entries: [
        {
          name: "bomb",
          data: new Uint8Array(64 * 1024),
          method: DEFLATED,
          centralUncompressedSize: 10,
        },
      ],
    });
    expect(await failureOf(() => archive.read(archive.entries[0]!, 1024))).toBe(
      "too-large",
    );
  });
});

describe("reading the head of an entry", () => {
  const NOISE = incompressible(4096);

  /** A bomb: 64 KiB of zeros deflated, declaring that it holds ten bytes. */
  const BOMB: ArchiveSpec = {
    entries: [
      {
        name: "bomb",
        data: new Uint8Array(64 * 1024),
        method: DEFLATED,
        centralUncompressedSize: 10,
      },
    ],
  };

  it("returns the whole entry when it is shorter than the prefix", async () => {
    const archive = await open(HELLO);

    const head = await archive.readPrefix(archive.find("two.txt")!, {
      prefix: 1024,
      limit: 1024,
    });

    expect(new TextDecoder().decode(head.bytes)).toBe("goodbye");
    expect(head.partial).toBe(false);
  });

  it("stops at the prefix and says the entry goes on", async () => {
    const archive = await open({
      entries: [{ name: "noise", data: NOISE, method: DEFLATED }],
    });

    const head = await archive.readPrefix(archive.entries[0]!, {
      prefix: 16,
      limit: 8192,
    });

    expect([...head.bytes]).toEqual([...NOISE.subarray(0, 16)]);
    expect(head.partial).toBe(true);
  });

  it("stops at the prefix in a stored entry too", async () => {
    // The copy path has its own bound and its own answer at the prefix, and it
    // is one line away from the ceiling: a stop written as the ceiling refuses
    // this entry rather than returning the two bytes asked of it.
    const archive = await open(HELLO);

    const head = await archive.readPrefix(archive.find("one.txt")!, {
      prefix: 2,
      limit: 1024,
    });

    expect(new TextDecoder().decode(head.bytes)).toBe("he");
    expect(head.partial).toBe(true);
  });

  it("copies a truncated stored read rather than viewing the entry", async () => {
    // A `subarray` hands back every byte past the prefix through `.buffer` and
    // holds the whole entry alive behind a view of 16 bytes. `prefix` says what
    // a caller gets, and a window over more than that is not it.
    const archive = await open({
      entries: [{ name: "wide", data: incompressible(4096), method: STORED }],
    });

    const head = await archive.readPrefix(archive.entries[0]!, {
      prefix: 16,
      limit: 8192,
    });

    expect(head.bytes.length).toBe(16);
    expect(head.bytes.buffer.byteLength).toBe(16);
  });

  it("reads a stored entry of exactly the prefix whole", async () => {
    // **The equality edge, and it is the off by one this whole seam is about.**
    // An entry of exactly the prefix has nothing past it, so it is whole rather
    // than partial. A stop written `>=` calls it partial here, and on the other
    // door turns an entry of exactly the ceiling into a refusal.
    const archive = await open(HELLO);

    const head = await archive.readPrefix(archive.find("one.txt")!, {
      prefix: 5,
      limit: 1024,
    });

    expect(new TextDecoder().decode(head.bytes)).toBe("hello");
    expect(head.partial).toBe(false);
  });

  it("reads a deflated entry of exactly the prefix whole", async () => {
    // The deflated twin of the arm above: the two paths compare against the
    // stop separately, so one of them being right says nothing about the other.
    const archive = await open(HELLO);

    const head = await archive.readPrefix(archive.find("two.txt")!, {
      prefix: 7,
      limit: 1024,
    });

    expect(new TextDecoder().decode(head.bytes)).toBe("goodbye");
    expect(head.partial).toBe(false);
  });

  it.each(["one.txt", "two.txt"])(
    "reads nothing from %s for a prefix below zero",
    async (name) => {
      // Nonsense in, a `ZipPrefix` out. Unclamped, the deflated path answers a
      // bare `RangeError` from `new Uint8Array(-1)`, which is not a `ZipError`
      // and escapes every caller catching this module's refusals, and the
      // stored path answers four of five bytes, which is worse because it
      // looks like data. Both methods, because the clamp is one line and the
      // two paths that depend on it are not.
      const archive = await open(HELLO);

      const head = await archive.readPrefix(archive.find(name)!, {
        prefix: -1,
        limit: 1024,
      });

      expect(head.bytes.length).toBe(0);
      expect(head.partial).toBe(true);
    },
  );

  it.each(["one.txt", "two.txt"])(
    "refuses %s asked for with a prefix that is not a number",
    async (name) => {
      // **`NaN` removes the cap rather than loosening it**, because every
      // comparison against it is false: the stored path hands back the whole
      // entry and the inflater buffers the whole output, both reporting
      // `partial: false`, which is the silent truncation `ZipPrefix` exists to
      // make impossible. Both methods, because the two paths compare against
      // the stop separately.
      const archive = await open(HELLO);

      expect(
        await failureOf(() =>
          archive.readPrefix(archive.find(name)!, {
            prefix: Number.NaN,
            limit: 1024,
          }),
        ),
      ).toBe("too-large");
    },
  );

  it.each(["one.txt", "two.txt"])(
    "refuses %s asked for with a ceiling that is not a number",
    async (name) => {
      // **The other half of that guard, and it has to be asked for separately.**
      // The whole read passes one number as both, so a fixture going through
      // that door cannot tell the two halves apart: dropping the `limit` arm of
      // the condition left every other test here green.
      const archive = await open(HELLO);

      expect(
        await failureOf(() =>
          archive.readPrefix(archive.find(name)!, {
            prefix: 16,
            limit: Number.NaN,
          }),
        ),
      ).toBe("too-large");
    },
  );

  it("stops the inflater rather than reading to the end of the entry", async () => {
    // **The claim a prefix read makes, in its only observable form.** This
    // entry's deflate stream is cut short, so reaching the end of it is
    // `truncated`: `refuses a deflate stream that stops halfway` above is this
    // same archive read whole. A prefix inside the bytes that did arrive comes
    // back, which it could not do if the rest were inflated first.
    const archive = await open({
      entries: [
        {
          name: "noise",
          data: NOISE,
          method: DEFLATED,
          centralCompressedSize: 40,
        },
      ],
    });

    const head = await archive.readPrefix(archive.entries[0]!, {
      prefix: 16,
      limit: 8192,
    });

    expect([...head.bytes]).toEqual([...NOISE.subarray(0, 16)]);
    expect(head.partial).toBe(true);
    // The premise, so this is not green against an entry that reads cleanly.
    expect(await failureOf(() => archive.read(archive.entries[0]!, 8192))).toBe(
      "truncated",
    );
  });

  it("tells a prefix that stopped apart from an entry that will not open", async () => {
    // **The whole reason the two doors are different doors.** One entry and two
    // questions: read whole against a ceiling of 1,024 it is `too-large` and
    // refused, and read as a prefix it comes back with `partial` set. This is
    // also the exclusion `readPrefix` states, that a deflated entry over the
    // ceiling is not refused there, because noticing costs inflating the rest.
    const archive = await open(BOMB);

    expect(await failureOf(() => archive.read(archive.entries[0]!, 1024))).toBe(
      "too-large",
    );

    const head = await archive.readPrefix(archive.entries[0]!, {
      prefix: 1024,
      limit: 1024,
    });
    expect(head.bytes.length).toBe(1024);
    expect(head.partial).toBe(true);
  });

  it("never returns more than the ceiling however much is asked for", async () => {
    // A prefix above the ceiling is clamped to it. Without the clamp this hands
    // 64 KiB back to a caller that named 1,024 as the most it would take, which
    // is the output bound gone rather than moved.
    const archive = await open(BOMB);

    const head = await archive.readPrefix(archive.entries[0]!, {
      prefix: 100_000,
      limit: 1024,
    });

    expect(head.bytes.length).toBe(1024);
    expect(head.partial).toBe(true);
  });

  it("still refuses an entry that declares more than the ceiling", async () => {
    const archive = await open(HELLO);

    expect(
      await failureOf(() =>
        archive.readPrefix(archive.find("one.txt")!, { prefix: 2, limit: 4 }),
      ),
    ).toBe("too-large");
  });

  it("still refuses a stored entry over the ceiling", async () => {
    // The declared size is understated, so this is the copy path's own bound
    // rather than the claim being checked twice. A prefix read keeps it: the
    // bytes are already in hand, so noticing costs nothing.
    const archive = await open({
      entries: [
        {
          name: "one.txt",
          data: "hello",
          method: STORED,
          centralUncompressedSize: 1,
        },
      ],
    });

    expect(
      await failureOf(() =>
        archive.readPrefix(archive.entries[0]!, { prefix: 2, limit: 2 }),
      ),
    ).toBe("too-large");
  });

  it("still never reads more compressed bytes than the ceiling could need", async () => {
    // The bound on what is read IN, which a new door must not have relaxed.
    // Both bounds answer `too-large`, so the reason is not evidence and the
    // assertion is on the largest slice actually asked of the file.
    const watched = watchedBlob(
      await buildZip({
        entries: [
          {
            name: "wide",
            data: incompressible(64 * 1024),
            method: DEFLATED,
            centralUncompressedSize: 1,
          },
        ],
      }),
    );
    const archive = await openZip(watched.blob);
    // The premise, checked rather than assumed.
    expect(archive.entries[0]!.compressedSize).toBeGreaterThan(60_000);
    watched.forget();

    expect(
      await failureOf(() =>
        archive.readPrefix(archive.entries[0]!, { prefix: 16, limit: 16 }),
      ),
    ).toBe("too-large");
    // The local header and nothing else. 64 KiB would be the whole entry.
    expect(watched.largestSlice()).toBeLessThan(1024);
  });
});
