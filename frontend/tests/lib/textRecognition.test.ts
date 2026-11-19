/**
 * Tests for src/lib/textRecognition.ts, the real module rather than the
 * double the rest of the suite is aliased to: this specifier, from this depth,
 * is not one of the alias keys in `vite.config.ts`.
 *
 * A test DOM has no worker and no `OffscreenCanvas`, so both are stood in on
 * the global for the test, and `tests/setup.ts` takes them off after it. The
 * worker is driven through its messages, the seam the module already talks
 * through; what runs inside it is `textRecognition.worker.test.ts`.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  openTextRecogniser,
  type FrameRegion,
} from "../../src/lib/textRecognition";

/** The worker the module starts: what it was asked, and a way to answer. */
class FakeWorker extends EventTarget {
  static started: FakeWorker[] = [];
  readonly asked: { request: unknown; transfer: Transferable[] }[] = [];
  readonly terminate = vi.fn<() => void>();

  constructor() {
    super();
    FakeWorker.started.push(this);
  }

  postMessage(request: unknown, transfer: Transferable[]): void {
    this.asked.push({ request, transfer });
  }

  reply(data: unknown): void {
    this.dispatchEvent(new MessageEvent("message", { data }));
  }

  die(message: string): void {
    this.dispatchEvent(
      Object.assign(new Event("error", { cancelable: true }), { message }),
    );
  }
}

/** What the canvas was made at and drew. Its picture is `PICTURE`. */
const drawn: {
  size: number[];
  source: unknown[];
  target: unknown[];
} = { size: [], source: [], target: [] };
const PICTURE = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);

class FakeCanvas {
  constructor(width: number, height: number) {
    drawn.size = [width, height];
  }

  getContext() {
    return {
      drawImage: (...args: unknown[]) => {
        drawn.source = args.slice(1, 5);
        drawn.target = args.slice(5);
      },
    };
  }

  convertToBlob(options: { type: string }): Promise<Blob> {
    return Promise.resolve(new Blob([PICTURE], options));
  }
}

const REGION: FrameRegion = { left: 0.1, top: 0.35, width: 0.8, height: 0.3 };

function frame(videoWidth: number, videoHeight: number): HTMLVideoElement {
  return { videoWidth, videoHeight } as HTMLVideoElement;
}

/** Let the module's awaits run, so the worker has been asked. */
const settled = () => new Promise((resolve) => setTimeout(resolve, 0));

/** Open a recogniser whose worker answered the open. */
async function opened() {
  const recogniser = openTextRecogniser(new AbortController().signal);
  const worker = FakeWorker.started.at(-1)!;
  worker.reply({ kind: "opened" });
  return { recogniser: await recogniser, worker };
}

beforeEach(() => {
  FakeWorker.started = [];
  vi.stubGlobal("Worker", FakeWorker);
  vi.stubGlobal("OffscreenCanvas", FakeCanvas);
});

describe("openTextRecogniser", () => {
  it("opens the engine in a worker and reads the region of the frame as a PNG", async () => {
    const { recogniser, worker } = await opened();
    expect(worker.asked[0]!.request).toEqual({ kind: "open" });

    const text = recogniser.read(frame(1000, 500), REGION);
    await settled();
    const { request, transfer } = worker.asked[1]!;
    expect(drawn.size).toEqual([800, 150]);
    expect(drawn.source).toEqual([100, 175, 800, 150]);
    expect(drawn.target).toEqual([0, 0, 800, 150]);
    expect(request).toMatchObject({ kind: "read" });
    const image = (request as { image: ArrayBuffer }).image;
    expect(new Uint8Array(image)).toEqual(PICTURE);
    expect(transfer).toEqual([image]);

    worker.reply({ kind: "read", text: "ISBN 978-3-16-148410-0" });
    expect(await text).toBe("ISBN 978-3-16-148410-0");
  });

  it("rejects the request in flight with the reason the worker died for", async () => {
    const { recogniser, worker } = await opened();
    const text = recogniser.read(frame(1000, 500), REGION);
    await settled();
    worker.die("out of memory");
    await expect(text).rejects.toThrow("out of memory");
  });

  it("stops listening for the reader to close once the engine is open", async () => {
    const closing = new AbortController();
    const added = vi.spyOn(closing.signal, "addEventListener");
    const removed = vi.spyOn(closing.signal, "removeEventListener");
    const recogniser = openTextRecogniser(closing.signal);
    FakeWorker.started.at(-1)!.reply({ kind: "opened" });
    await recogniser;
    expect(added).toHaveBeenCalledOnce();
    expect(removed).toHaveBeenCalledWith("abort", added.mock.calls[0]![1]);
  });

  it("refuses a frame the camera has not filled, without asking the worker", async () => {
    const { recogniser, worker } = await opened();
    await expect(recogniser.read(frame(0, 0), REGION)).rejects.toThrow(
      "the camera has no frame to read",
    );
    expect(worker.asked).toHaveLength(1);
  });

  it("rejects a read with the reason the worker failed it", async () => {
    const { recogniser, worker } = await opened();
    const text = recogniser.read(frame(1000, 500), REGION);
    await settled();
    worker.reply({ kind: "failed", message: "the picture did not decode" });
    await expect(text).rejects.toThrow("the picture did not decode");
  });

  it("rejects the request in flight when the worker dies without a reason", async () => {
    const { recogniser, worker } = await opened();
    const text = recogniser.read(frame(1000, 500), REGION);
    await settled();
    worker.die("");
    await expect(text).rejects.toThrow("the reader stopped");
  });

  it("ends the worker when the engine will not open", async () => {
    const recogniser = openTextRecogniser(new AbortController().signal);
    const worker = FakeWorker.started.at(-1)!;
    worker.reply({ kind: "failed", message: "the engine refused its model" });
    await expect(recogniser).rejects.toThrow("the engine refused its model");
    expect(worker.terminate).toHaveBeenCalledOnce();
  });

  it("ends the worker, mid load, when the reader closes", async () => {
    const closing = new AbortController();
    const recogniser = openTextRecogniser(closing.signal);
    closing.abort(new Error("closed"));
    await expect(recogniser).rejects.toThrow("closed");
    expect(FakeWorker.started.at(-1)!.terminate).toHaveBeenCalledOnce();
  });

  it("starts no worker for a reader already closed", async () => {
    await expect(
      openTextRecogniser(AbortSignal.abort(new Error("closed"))),
    ).rejects.toThrow("closed");
    expect(FakeWorker.started).toEqual([]);
  });

  it("ends the worker when the reader closes it", async () => {
    const { recogniser, worker } = await opened();
    recogniser.close();
    expect(worker.terminate).toHaveBeenCalledOnce();
  });
});
