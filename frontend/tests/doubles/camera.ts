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
export const stopTrack = vi.fn<MediaStreamTrack["stop"]>();

/** `navigator.mediaDevices.getUserMedia`. */
export const getUserMedia = vi.fn<MediaDevices["getUserMedia"]>();

/**
 * What a phone's back camera reports from `getSettings()`.
 *
 * The default, so every scanner test that does not ask about the camera's
 * direction runs on the path a phone takes. A laptop's front camera reports
 * `user`, or nothing: pass `{}` for that.
 */
const REAR_CAMERA: MediaTrackSettings = { facingMode: "environment" };

/**
 * A stream with one video track.
 *
 * `capabilities` is what `getCapabilities()` reports, which is how the
 * component decides whether to offer the torch: a camera with no `torch` key
 * has no light, and the control must not appear. `settings` is what
 * `getSettings()` reports, which is how it decides whether the camera may be
 * facing the member.
 */
export function fakeStream(
  capabilities: Record<string, unknown> = {},
  settings: MediaTrackSettings = REAR_CAMERA,
): MediaStream {
  const track = {
    stop: stopTrack,
    getCapabilities: () => capabilities,
    getSettings: () => settings,
    applyConstraints: vi
      .fn<MediaStreamTrack["applyConstraints"]>()
      .mockResolvedValue(undefined),
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
