/**
 * The worker that reads printed text, with the Tesseract engine compiled to
 * WebAssembly. `textRecognition.ts` starts it and is the only thing that talks
 * to it; what it says is `Request` and `Reply` there.
 *
 * **It talks to `tesseract.js-core` directly, not through `tesseract.js`.** The
 * wrapper's defaults fetch its worker, the engine and the model from a
 * third party CDN, start the worker from a `blob:` URL, and ship two
 * `Function` fallbacks, and the content security policy refuses all three.
 * What it would add over these lines is a job queue and a cache this app
 * does not need, since every asset here is a hashed file the browser caches.
 *
 * A classic worker, which is Vite's default for `new Worker(new URL(...))`,
 * because the engine's loader is a classic script read with `importScripts`.
 * The loader is an emitted file rather than part of this bundle so that the
 * bundler never rewrites Emscripten's output.
 *
 * **The three assets are named here, by the URL Vite emitted for each, and
 * they are the three requests this worker makes**: `importScripts` of the
 * loader, the engine's own fetch of its WebAssembly through `locateFile`, and
 * the fetch of the model. None carries anything out. `tests/houseRules.test.ts`
 * holds that each is made once and by its pinned binding, since the frame this
 * worker reads is the member's picture and a module in `lib/` holding one may
 * not reach the network otherwise.
 */

import coreUrl from "tesseract.js-core/tesseract-core-simd-lstm.js?url";
import wasmUrl from "tesseract.js-core/tesseract-core-simd-lstm.wasm?url";
import modelUrl from "@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz?url";

import type { WorkerScope } from "./workerScope";

/** The parts of Tesseract's `TessBaseAPI` this worker calls. */
interface TessBaseApi {
  Init(dataPath: null, language: string, engineMode: number): number;
  SetVariable(name: string, value: string): boolean;
  SetImageFile(exifOrientation: number, angle: number): number;
  Recognize(monitor: null): number;
  GetUTF8Text(): string;
}

interface TesseractModule {
  FS: { writeFile(path: string, data: Uint8Array): void };
  TessBaseAPI: new () => TessBaseApi;
}

type CoreFactory = (module: {
  locateFile(name: string): string;
}) => Promise<TesseractModule>;

interface EngineScope extends WorkerScope {
  /** What the engine's loader defines, once `importScripts` has run it. */
  TesseractCore?: CoreFactory;
}

const scope = self as unknown as EngineScope;

/** Tesseract's LSTM engine, the only one the `-lstm` build carries. */
const LSTM_ONLY = 1;

/**
 * Treat the picture as one block of text: the guide box holds the ISBN line
 * and perhaps a line either side of it, never columns.
 */
const SINGLE_BLOCK = "6";

/**
 * The characters a printed ISBN line holds. Anything else in the picture is
 * read as one of these, which only ever adds a character the parser drops.
 */
const ISBN_CHARACTERS = "0123456789X-ISBN: ";

let api: TessBaseApi | null = null;
let engine: TesseractModule | null = null;

/** The model, which ships gzipped and is unpacked here rather than by a library. */
async function modelBytes(): Promise<Uint8Array> {
  const response = await fetch(modelUrl);
  if (!response.ok || response.body === null) {
    throw new Error(`the model answered ${response.status}`);
  }
  const unpacked = response.body.pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(unpacked).arrayBuffer());
}

async function open(): Promise<void> {
  scope.importScripts(coreUrl);
  const factory = scope.TesseractCore;
  if (factory === undefined) throw new Error("the engine did not load");
  // The loader would look for its WebAssembly beside itself under the name it
  // was built with, which the hashed asset no longer has.
  const [loaded, data] = await Promise.all([
    factory({ locateFile: () => wasmUrl }),
    modelBytes(),
  ]);
  loaded.FS.writeFile("eng.traineddata", data);
  const opened = new loaded.TessBaseAPI();
  if (opened.Init(null, "eng", LSTM_ONLY) !== 0) {
    throw new Error("the engine refused its model");
  }
  opened.SetVariable("tessedit_pageseg_mode", SINGLE_BLOCK);
  opened.SetVariable("tessedit_char_whitelist", ISBN_CHARACTERS);
  engine = loaded;
  api = opened;
}

function read(image: ArrayBuffer): string {
  if (api === null || engine === null)
    throw new Error("the engine is not open");
  // Tesseract reads its picture from a file, decoded by Leptonica.
  engine.FS.writeFile("/input", new Uint8Array(image));
  if (api.SetImageFile(1, 0) !== 0)
    throw new Error("the picture did not decode");
  api.Recognize(null);
  return api.GetUTF8Text();
}

async function answer(request: Record<string, unknown>): Promise<unknown> {
  if (request.kind === "open") {
    await open();
    return { kind: "opened" };
  }
  return { kind: "read", text: read(request.image as ArrayBuffer) };
}

scope.addEventListener("message", (event) => {
  answer(event.data as Record<string, unknown>).then(
    (reply) => scope.postMessage(reply, []),
    (error: unknown) =>
      scope.postMessage({ kind: "failed", message: String(error) }, []),
  );
});
