/**
 * @vitest-environment node
 *
 * Bytes and a digest, so this needs no DOM. `Blob` and `node:crypto` are both
 * node's own.
 */
/**
 * Tests for src/lib/fileDigest.ts.
 *
 * **The fixture's digest is computed twice, by two instruments**: once outside
 * this repository, by KOReader's algorithm written out in Python against the
 * offsets read from `frontend/util.lua`, and once here, by `node:crypto` over
 * the windows the offsets name. Either alone would agree with an
 * implementation sharing its mistake about where a window starts.
 */

import { createHash } from "node:crypto";

import { describe, expect, it } from "vitest";

import { md5, PARTIAL_MD5_OFFSETS, partialMd5 } from "../../src/lib/fileDigest";

/** A byte pattern no window can mistake for another window. */
function patterned(length: number): Uint8Array<ArrayBuffer> {
  return Uint8Array.from({ length }, (_, index) => (index * 31 + 7) % 256);
}

const text = (value: string) => new TextEncoder().encode(value);

describe("md5", () => {
  it.each([
    ["", "d41d8cd98f00b204e9800998ecf8427e"],
    ["a", "0cc175b9c0f1b6a831c399e269772661"],
    ["abc", "900150983cd24fb0d6963f7d28e17f72"],
    ["message digest", "f96b697d7cb7938d525a2f31aaf161d0"],
    ["abcdefghijklmnopqrstuvwxyz", "c3fcd3d76192e4007dfb496cca67e13b"],
    [
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
      "d174ab98d277d9f5a5611c2c9f419d9f",
    ],
    [
      "12345678901234567890123456789012345678901234567890123456789012345678901234567890",
      "57edf4a22be3c955ac49da2e2107b67a",
    ],
  ])("gives RFC 1321's digest of %j", (input, digest) => {
    expect(md5(text(input))).toBe(digest);
  });

  it("agrees with node's MD5 across every padding boundary", () => {
    // 55, 56 and 64 bytes are where the length word moves to a second block.
    for (const length of [55, 56, 63, 64, 65, 119, 120, 1000]) {
      const bytes = patterned(length);
      expect(md5(bytes)).toBe(createHash("md5").update(bytes).digest("hex"));
    }
  });
});

describe("partialMd5", () => {
  it("samples where KOReader seeks, the first window at 0 and not 256", () => {
    expect(PARTIAL_MD5_OFFSETS).toEqual([
      0, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864,
      268435456, 1073741824,
    ]);
  });

  it("gives KOReader's digest of a file whose last window is cut short", async () => {
    // 66,000 bytes: four whole windows and 464 bytes of the one at 65,536.
    const bytes = patterned(66_000);
    const windows = [0, 1024, 4096, 16384, 65536].map((offset) =>
      bytes.subarray(offset, offset + 1024),
    );
    const independent = createHash("md5");
    for (const window of windows) independent.update(window);

    const digest = await partialMd5(new Blob([bytes]));

    expect(digest).toBe(independent.digest("hex"));
    expect(digest).toBe("df9c12be74f489b7f7a4870382dc899e");
  });

  it("stops at a window starting exactly at the end", async () => {
    // KOReader's read there returns nothing and its loop breaks.
    expect(await partialMd5(new Blob([patterned(1024)]))).toBe(
      "63b2177a7af739b5cc52ab1d1c714702",
    );
  });

  it("gives the digest of nothing for an empty file", async () => {
    expect(await partialMd5(new Blob([]))).toBe(
      "d41d8cd98f00b204e9800998ecf8427e",
    );
  });

  it("reads twelve windows of a file far past a gigabyte and nothing else", async () => {
    // **The custody half**: the digest costs at most 12 KiB of somebody's
    // book, whatever its size, so the read is affordable at the pick.
    const read: [number, number][] = [];
    const huge = {
      size: 3 * 2 ** 30,
      slice(start: number, end: number) {
        read.push([start, end]);
        return new Blob([new Uint8Array(end - start)]);
      },
    } as unknown as Blob;

    await partialMd5(huge);

    expect(read).toEqual(
      PARTIAL_MD5_OFFSETS.map((offset) => [offset, offset + 1024]),
    );
  });
});
