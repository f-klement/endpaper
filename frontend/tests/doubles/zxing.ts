/**
 * A stand-in for `@zxing/library`, resolved in place of it for the whole suite.
 *
 * **Aliased in `vite.config.ts` under `test.alias`, not mocked with `vi.mock`,
 * and the difference is the whole point of this file.** A `vi.mock` is a claim
 * one test file makes about a module, and under `isolate: false` it loses to
 * whichever file evaluated that module first. `tests/app/App.test.tsx` renders
 * the route table, `src/app/routes.tsx` imports `ScanPage` eagerly, and that
 * reaches the real `BrowserMultiFormatReader` through `BarcodeScanner.tsx`. So
 * with a `vi.mock` here the scanner's own tests got the real decoder whenever
 * the shuffle put those two files in one worker in that order: measured at one
 * shuffled seed in eight, fifteen tests failing at once with
 * `createObjectURL expects a Blob object` from inside `BrowserCodeReader.js`.
 *
 * An alias has no such ordering, because there is no real module to lose to:
 * every importer resolves here, cached or not, first or last.
 *
 * `test.alias` rather than `resolve.alias`, so the application build resolves
 * the real library. And nothing checks that from inside the suite, by
 * construction: a test that could see the real one would defeat the alias.
 * `frontend/tests/houseRules.test.ts` reads the config text instead.
 *
 * Nothing here decodes. There is no camera in a test environment, so what is
 * worth testing is the ISBN filter, what the reader is asked for, and the
 * lifecycle, all of which are observed through the three spies below.
 */
import { vi } from "vitest";

/** The reader's `decodeFromStream`. Its third argument is the frame callback. */
export const decodeFromStream = vi.fn();

/** The reader's `reset`, which is how the component releases ZXing's track. */
export const reset = vi.fn();

/** The constructor's arguments: the decode hints, then the frame interval. */
export const readerArgs = vi.fn();

/**
 * Thrown by the real library on every frame that holds no barcode.
 *
 * A class rather than a plain object because the component tells it apart from
 * a genuine fault with `instanceof`, so an object shaped like it would be
 * logged as an error on every frame that missed.
 */
export class NotFoundException extends Error {}

export class BrowserMultiFormatReader {
  decodeFromStream = decodeFromStream;
  reset = reset;

  constructor(hints?: unknown, interval?: number) {
    readerArgs(hints, interval);
  }
}

/**
 * Strings, where the real library uses a numeric enum.
 *
 * The component only ever passes these through into the hints map and the
 * assertions only ever read them back out, so the values need to be distinct
 * rather than accurate. Strings say which format failed when one does.
 */
export const BarcodeFormat = {
  EAN_13: "EAN_13",
  EAN_8: "EAN_8",
  UPC_A: "UPC_A",
  UPC_E: "UPC_E",
  QR_CODE: "QR_CODE",
};

export const DecodeHintType = {
  POSSIBLE_FORMATS: "POSSIBLE_FORMATS",
  TRY_HARDER: "TRY_HARDER",
};

/**
 * Reset all three spies.
 *
 * **Called from `tests/setup.ts`, not from a test file.** The alias is always
 * in force, so any file that renders a scanner reaches these spies whether or
 * not it knows this module exists, and a file that does not know cannot
 * remember to reset them.
 */
export function resetZxingDouble(): void {
  decodeFromStream.mockReset().mockResolvedValue(undefined);
  reset.mockReset();
  readerArgs.mockReset();
}

/**
 * The frame callback the component most recently handed to `decodeFromStream`.
 *
 * The **last** call rather than the first: `ScanPage` mounts a scanner in
 * ordinary mode and another in rapid mode, and a remount leaves the earlier
 * call in the spy's history. Reading `[0]` there hands back a callback whose
 * component has unmounted, which does nothing visible and looks like a page
 * that ignored a barcode.
 */
function frameCallback(): (
  result: { getText: () => string } | null,
  error: Error | null,
) => void {
  const call = decodeFromStream.mock.calls.at(-1);
  if (!call) {
    throw new Error(
      "No scanner is decoding: open the camera before emitting a barcode.",
    );
  }
  return call[2] as (
    result: { getText: () => string } | null,
    error: Error | null,
  ) => void;
}

/** Deliver a barcode to whichever scanner is currently mounted. */
export function emitBarcode(text: string): void {
  frameCallback()({ getText: () => text }, null);
}

/** Deliver a decode error, which is how ZXing reports a frame it could not read. */
export function emitScannerError(error: Error): void {
  frameCallback()(null, error);
}
