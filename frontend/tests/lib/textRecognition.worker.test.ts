/**
 * @vitest-environment node
 *
 * A worker has no DOM, and in node `self` is free for the stand in scope below.
 */
/**
 * Tests for src/lib/textRecognition.worker.ts, driven through its messages,
 * the seam `textRecognition.ts` talks to it through.
 *
 * The worker's scope is a stand in installed as `self` before the module is
 * imported, since the module takes its scope once, when it loads. The engine
 * is a stand in its loader defines, and the model is served by a stubbed
 * `fetch`. The module keeps the open engine between messages, as a worker
 * does, so each test loads a fresh copy of the module: no test depends on
 * the order it runs in, or on a registry an earlier test left an engine in.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

type Listener = (event: { data: unknown }) => void;

/** The worker's scope: what the module listens with and replies through. */
const scope = {
  listener: null as Listener | null,
  replies: [] as unknown[],
  TesseractCore: undefined as unknown,
  importScripts: vi.fn<(url: string) => void>(),
  addEventListener(_type: "message", listener: Listener) {
    scope.listener = listener;
  },
  postMessage(reply: unknown) {
    scope.replies.push(reply);
  },
};

/** Post `request` to the worker and wait for its reply. */
async function ask(request: object): Promise<unknown> {
  const before = scope.replies.length;
  scope.listener!({ data: request });
  await vi.waitFor(() => expect(scope.replies.length).toBe(before + 1));
  return scope.replies[before];
}

const MODEL = new TextEncoder().encode("a trained model");

/** The model as the server sends it: gzipped. */
async function served(): Promise<Response> {
  const packed = new Blob([MODEL])
    .stream()
    .pipeThrough(new CompressionStream("gzip"));
  return new Response(packed);
}

/** What the engine was told to set, in order. */
const variables: [string, string][] = [];

/** An engine its loader defines, and what was written into its files. */
function engine({ init = 0, decode = 0, text = "" } = {}) {
  const files = new Map<string, Uint8Array>();
  class TessBaseAPI {
    Init = () => init;
    SetVariable = (name: string, value: string) => {
      variables.push([name, value]);
      return true;
    };
    SetImageFile = () => decode;
    Recognize = () => 0;
    GetUTF8Text = () => text;
  }
  const core = () =>
    Promise.resolve({
      FS: {
        writeFile: (path: string, data: Uint8Array) => files.set(path, data),
      },
      TessBaseAPI,
    });
  scope.importScripts.mockImplementation(() => {
    scope.TesseractCore = core;
  });
  return files;
}

beforeEach(async () => {
  variables.length = 0;
  scope.replies.length = 0;
  scope.listener = null;
  vi.stubGlobal("self", scope);
  // A fresh module registers its listener again and holds no engine.
  vi.resetModules();
  await import("../../src/lib/textRecognition.worker");
  scope.TesseractCore = undefined;
  scope.importScripts.mockReset();
  vi.stubGlobal("fetch", vi.fn(served));
});

describe("the text recognition worker", () => {
  it("refuses a read before the engine is open", async () => {
    expect(await ask({ kind: "read", image: new ArrayBuffer(1) })).toEqual({
      kind: "failed",
      message: "Error: the engine is not open",
    });
  });

  it("fails the open when the loader defines no engine", async () => {
    expect(await ask({ kind: "open" })).toEqual({
      kind: "failed",
      message: "Error: the engine did not load",
    });
  });

  it("fails the open when the model is not served", async () => {
    engine();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 404 }))),
    );
    expect(await ask({ kind: "open" })).toEqual({
      kind: "failed",
      message: "Error: the model answered 404",
    });
  });

  it("fails the open when the engine refuses its model", async () => {
    engine({ init: -1 });
    expect(await ask({ kind: "open" })).toEqual({
      kind: "failed",
      message: "Error: the engine refused its model",
    });
  });

  it("opens the engine on the unpacked model and reads a picture's text", async () => {
    const files = engine({ text: "ISBN 978-3-16-148410-0\n" });
    expect(await ask({ kind: "open" })).toEqual({ kind: "opened" });
    expect(files.get("eng.traineddata")).toEqual(MODEL);
    expect(variables).toEqual([
      ["tessedit_pageseg_mode", "6"],
      ["tessedit_char_whitelist", "0123456789X-ISBN: "],
    ]);

    const picture = new Uint8Array([1, 2, 3]);
    expect(await ask({ kind: "read", image: picture.buffer })).toEqual({
      kind: "read",
      text: "ISBN 978-3-16-148410-0\n",
    });
    expect(files.get("/input")).toEqual(picture);
  });

  it("fails a read whose picture does not decode", async () => {
    engine({ decode: 1 });
    expect(await ask({ kind: "open" })).toEqual({ kind: "opened" });
    expect(await ask({ kind: "read", image: new ArrayBuffer(1) })).toEqual({
      kind: "failed",
      message: "Error: the picture did not decode",
    });
  });
});
