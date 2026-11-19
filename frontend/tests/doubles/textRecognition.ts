/**
 * A stand-in for `src/lib/textRecognition.ts`, resolved in place of it for the
 * whole suite by its specifiers in `test.alias`, for the reason
 * `tests/doubles/README.md` gives.
 *
 * There is no worker, no `OffscreenCanvas` and no WebAssembly engine in a test
 * DOM, and the engine is not what the scan page's tests are about: what is
 * worth testing is what a read's text becomes and what the member sees, all of
 * which this drives through `read` and `opening`.
 */
import { vi } from "vitest";

import type {
  FrameRegion,
  TextRecogniser,
} from "../../src/lib/textRecognition";

/** The open recogniser's `read`. Resolve it with the text a frame held. */
export const read =
  vi.fn<(video: HTMLVideoElement, region: FrameRegion) => Promise<string>>();

/** The open recogniser's `close`, which is how a test sees the worker end. */
export const close = vi.fn<() => void>();

/**
 * Whether the engine opens. A test makes it refuse, or hold it pending with a
 * promise it settles itself, to see the reader's other states. It is handed
 * the signal the caller would abort the load with.
 */
export const opening = vi.fn<(closing: AbortSignal) => Promise<void>>();

export async function openTextRecogniser(
  closing: AbortSignal,
): Promise<TextRecogniser> {
  await opening(closing);
  return { read, close };
}

/** Back to an engine that opens and reads nothing. `tests/setup.ts` calls it. */
export function resetTextRecognitionDouble(): void {
  read.mockReset().mockResolvedValue("");
  close.mockReset();
  opening.mockReset().mockResolvedValue(undefined);
}
