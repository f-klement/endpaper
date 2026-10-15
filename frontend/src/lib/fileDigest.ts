/**
 * KOReader's partial MD5 of a member's book file, computed in their browser.
 *
 * **What KOReader's progress sync names a document by**, so a reference
 * carrying it can be matched to what a device sends. It is not a content hash:
 * `util.partialMD5` in KOReader's `frontend/util.lua` hashes twelve 1 KiB
 * windows and nothing else, so the file's length is no input and two files
 * agreeing on those windows collide.
 *
 * **At most twelve slices of 1 KiB are read**, whatever the file's size, and
 * nothing here reaches the network: the digest is a string the caller hands to
 * `lib/digitalReference.ts`, which sends it and never sees a byte. That is the
 * split `tests/houseRules.test.ts` holds between a module naming bytes and one
 * reaching the network.
 */

/** How many bytes each window is, and the base of the offsets. */
const WINDOW = 1024;

/**
 * Where each window starts, in reading order.
 *
 * KOReader seeks to `lshift(1024, 2*i)` for `i` from -1 to 10. LuaJIT's
 * `bit.lshift` takes the shift count modulo 32 and works in 32 bits, so the
 * first, `lshift(1024, -2)`, is `1024 << 30`, which overflows to 0. The rest
 * are 1024 times 4 to the powers 0 to 10, the last at 1 GiB. Reading the first
 * as 256, the arithmetic a reader expects, gives a digest no device sends.
 */
export const PARTIAL_MD5_OFFSETS: readonly number[] = [
  0,
  ...Array.from({ length: 11 }, (_, power) => WINDOW * 4 ** power),
];

/**
 * KOReader's partial MD5 of this file, as 32 lower case hex digits.
 *
 * **Stops at the first window starting at or past the end**, because that is
 * where KOReader's loop breaks: its `file:read` returns nothing there. A window
 * starting inside the file and running past its end contributes what there is.
 * An empty file is therefore the MD5 of nothing.
 */
export async function partialMd5(file: Blob): Promise<string> {
  // The offsets ascend, so keeping those inside the file is the same as
  // KOReader's break. Read together rather than one after another: twelve
  // small reads, joined in offset order whatever order they finish in.
  const windows = await Promise.all(
    PARTIAL_MD5_OFFSETS.filter((offset) => offset < file.size).map(
      async (offset) =>
        new Uint8Array(
          await file
            .slice(offset, Math.min(offset + WINDOW, file.size))
            .arrayBuffer(),
        ),
    ),
  );
  const total = windows.reduce((sum, window) => sum + window.length, 0);
  const sampled = new Uint8Array(total);
  let at = 0;
  for (const window of windows) {
    sampled.set(window, at);
    at += window.length;
  }
  return md5(sampled);
}

/** Per round left rotations, RFC 1321 section 3.4. */
const SHIFTS = [
  7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5,
  9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11,
  16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15,
  21,
];

/** `floor(abs(sin(i + 1)) * 2^32)`, the table RFC 1321 defines. */
const SINES = Array.from(
  { length: 64 },
  (_, index) => Math.floor(Math.abs(Math.sin(index + 1)) * 2 ** 32) >>> 0,
);

/**
 * The MD5 of these bytes, as 32 lower case hex digits.
 *
 * **Written here because WebCrypto has no MD5**, and a dependency for sixty
 * lines would be a supply chain entry for a digest that guards nothing: it is
 * an identifier KOReader chose, not a security property. Checked against the
 * RFC 1321 test suite in `tests/lib/fileDigest.test.ts`.
 */
export function md5(bytes: Uint8Array): string {
  // Padding: a one bit, zeros to 56 mod 64, then the bit length little endian.
  const padded = new Uint8Array((((bytes.length + 8) >>> 6) + 1) * 64);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  const bits = bytes.length * 8;
  view.setUint32(padded.length - 8, bits >>> 0, true);
  view.setUint32(padded.length - 4, Math.floor(bits / 2 ** 32), true);

  let a0 = 0x67452301;
  let b0 = 0xefcdab89;
  let c0 = 0x98badcfe;
  let d0 = 0x10325476;

  for (let block = 0; block < padded.length; block += 64) {
    let a = a0;
    let b = b0;
    let c = c0;
    let d = d0;
    for (let step = 0; step < 64; step++) {
      let f: number;
      let word: number;
      if (step < 16) {
        f = (b & c) | (~b & d);
        word = step;
      } else if (step < 32) {
        f = (d & b) | (~d & c);
        word = (5 * step + 1) % 16;
      } else if (step < 48) {
        f = b ^ c ^ d;
        word = (3 * step + 5) % 16;
      } else {
        f = c ^ (b | ~d);
        word = (7 * step) % 16;
      }
      const sum =
        (a + f + SINES[step]! + view.getUint32(block + word * 4, true)) >>> 0;
      const shift = SHIFTS[step]!;
      a = d;
      d = c;
      c = b;
      b = (b + ((sum << shift) | (sum >>> (32 - shift)))) >>> 0;
    }
    a0 = (a0 + a) >>> 0;
    b0 = (b0 + b) >>> 0;
    c0 = (c0 + c) >>> 0;
    d0 = (d0 + d) >>> 0;
  }

  const out = new DataView(new ArrayBuffer(16));
  [a0, b0, c0, d0].forEach((word, index) =>
    out.setUint32(index * 4, word, true),
  );
  return Array.from(new Uint8Array(out.buffer), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
