/**
 * Read the printed text inside one region of a camera frame, in the member's
 * own browser. **No picture leaves the device**: the frame is cropped, encoded
 * and recognised here, in a worker, and only the text it holds comes back.
 *
 * **Lazy loaded, and the largest thing the scan page can pull in.** Nothing
 * imports this at the top of a module the shell reaches: the scan page's
 * `usePrintedIsbnReader` resolves it with `await import` when the member opens
 * the printed number reader, and `tests/pages/ScanPage/hooks.test.tsx` holds
 * that. The engine, its WebAssembly and the model are files this build emits
 * and the app serves itself, named by `?url` imports in the worker: the third
 * party CDN the engine's own wrapper defaults to is refused by the content security
 * policy, and is not loosened for it.
 *
 * **Each of the three is fetched on the first open only, and none is
 * precached.** `vite.config.ts` keeps them out of the service worker's
 * manifest by name, beside the worker chunk. The sizes and the reasoning are
 * in `docs/decisions.md`.
 *
 * **The SIMD build alone.** A browser without WebAssembly SIMD has no
 * `DecompressionStream` either, which the model needs, so the plain build
 * would buy nothing: such a browser is told the reader cannot run in it.
 *
 * The suite replaces this module with `tests/doubles/textRecognition.ts`, since
 * there is no worker, no canvas and no WebAssembly engine in a test DOM.
 */

/** A part of the frame, each side a fraction of the frame's own size. */
export interface FrameRegion {
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
}

/** An open engine. Close it when the reader closes: it holds a worker. */
export interface TextRecogniser {
  /** The text printed inside `region` of the frame `video` shows now. */
  read(video: HTMLVideoElement, region: FrameRegion): Promise<string>;
  close(): void;
}

type Reply =
  | { kind: "opened" }
  | { kind: "read"; text: string }
  | { kind: "failed"; message: string };

interface Waiting {
  resolve(reply: Reply): void;
  reject(error: Error): void;
}

/**
 * Post one request and wait for its reply. The reader asks one at a time, so
 * there is one slot for the request in flight rather than a queue.
 */
function asker(worker: Worker) {
  let waiting: Waiting | null = null;
  function settle(): Waiting | null {
    const was = waiting;
    waiting = null;
    return was;
  }
  worker.addEventListener("message", (event: MessageEvent<Reply>) => {
    const was = settle();
    if (event.data.kind === "failed")
      was?.reject(new Error(event.data.message));
    else was?.resolve(event.data);
  });
  // A worker that fails to start, or dies, says so here and nowhere else.
  worker.addEventListener("error", (event) => {
    event.preventDefault();
    settle()?.reject(new Error(event.message || "the reader stopped"));
  });
  return (request: object, transfer: Transferable[] = []) =>
    new Promise<Reply>((resolve, reject) => {
      waiting = { resolve, reject };
      worker.postMessage(request, transfer);
    });
}

/** The region of the frame as a PNG, which the engine decodes losslessly. */
async function framePicture(
  video: HTMLVideoElement,
  region: FrameRegion,
): Promise<ArrayBuffer> {
  const sx = Math.round(video.videoWidth * region.left);
  const sy = Math.round(video.videoHeight * region.top);
  const width = Math.round(video.videoWidth * region.width);
  const height = Math.round(video.videoHeight * region.height);
  const canvas = new OffscreenCanvas(width, height);
  const context = canvas.getContext("2d");
  if (context === null || width === 0 || height === 0) {
    throw new Error("the camera has no frame to read");
  }
  context.drawImage(video, sx, sy, width, height, 0, 0, width, height);
  const picture = await canvas.convertToBlob({ type: "image/png" });
  return picture.arrayBuffer();
}

/**
 * A promise that settles only by rejecting, with the reason `signal` is aborted
 * for, and the call that stops listening.
 *
 * **`detach` is what a successful open calls.** Without it the listener stayed
 * on the signal for as long as the signal lived, one per open.
 */
function whenAborted(signal: AbortSignal): {
  aborted: Promise<never>;
  detach: () => void;
} {
  let reject!: (reason: Error) => void;
  // The executor runs before the constructor returns, so `reject` is set
  // before anything below can call it.
  const aborted = new Promise<never>((_, settle) => {
    reject = settle;
  });
  const onAbort = () => reject(signal.reason as Error);
  signal.addEventListener("abort", onAbort, { once: true });
  return {
    aborted,
    detach: () => signal.removeEventListener("abort", onAbort),
  };
}

/**
 * Start the worker and load the engine and its model into it.
 *
 * **Aborting `closing` ends the load where it is.** The first open downloads
 * and compiles about 5.9 MB; without this a reader closed meanwhile left the
 * worker loading to the end, and closing and reopening ran two loads at once.
 */
export async function openTextRecogniser(
  closing: AbortSignal,
): Promise<TextRecogniser> {
  closing.throwIfAborted();
  const worker = new Worker(
    new URL("./textRecognition.worker.ts", import.meta.url),
  );
  const ask = asker(worker);
  const { aborted, detach } = whenAborted(closing);
  try {
    await Promise.race([ask({ kind: "open" }), aborted]);
  } catch (error) {
    worker.terminate();
    throw error;
  } finally {
    detach();
  }
  return {
    async read(video, region) {
      const image = await framePicture(video, region);
      const reply = await ask({ kind: "read", image }, [image]);
      return reply.kind === "read" ? reply.text : "";
    },
    close: () => worker.terminate(),
  };
}
