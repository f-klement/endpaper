/**
 * A stand-in for the camera, because no test environment has one.
 *
 * **Shared rather than written into each test file, for the same reason the
 * ZXing double is aliased**: `navigator.mediaDevices` is installed with
 * `Object.defineProperty`, which no vitest restore undoes, so a file that
 * installs its own leaves it behind for every file that follows. Under
 * `isolate: false` that is a leak rather than a curiosity: the next file to
 * render a scanner gets a `getUserMedia` belonging to a suite that has
 * finished, reset to return `undefined`, and the camera never opens.
 *
 * `tests/setup.ts` puts `navigator.mediaDevices` back after every test, which
 * is what makes calling `installCamera()` in one file safe for the next.
 */
import { vi } from "vitest";

/** The track's `stop`. This is how a test sees the camera being released. */
export const stopTrack = vi.fn();

/** `navigator.mediaDevices.getUserMedia`. */
export const getUserMedia = vi.fn();

/**
 * A stream with one video track.
 *
 * `capabilities` is what `getCapabilities()` reports, which is how the
 * component decides whether to offer the torch: a camera with no `torch` key
 * has no light, and the control must not appear.
 */
export function fakeStream(
  capabilities: Record<string, unknown> = {},
): MediaStream {
  const track = {
    stop: stopTrack,
    getCapabilities: () => capabilities,
    applyConstraints: vi.fn().mockResolvedValue(undefined),
  };
  return {
    getTracks: () => [track],
    getVideoTracks: () => [track],
  } as unknown as MediaStream;
}

/** Install a working camera. Call it from `beforeEach`, not once per file. */
export function installCamera(
  capabilities: Record<string, unknown> = {},
): void {
  stopTrack.mockReset();
  getUserMedia.mockReset().mockResolvedValue(fakeStream(capabilities));
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
}
