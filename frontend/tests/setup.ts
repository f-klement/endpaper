import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, vi } from "vitest";

import { resetZxingDouble } from "./doubles/zxing";

// jsdom has no layout engine; some libraries measure on mount.
//
// Guarded on `window` existing at all, not just on the method. This file is the
// suite-wide setup, so it also runs for the files carrying
// `@vitest-environment node`: the pure helpers, the house rules, the palette
// maths. Reaching for a bare `window` there is a ReferenceError that collects
// zero tests and reports the file as failed with no assertion named, which is a
// confusing way to learn that a docblock took effect.
// happy-dom implements no modal dialogue functions at all, where jsdom shipped
// stubs that throw "not implemented". The app calls `confirm()` before the
// destructive actions (emptying the trash, deleting a curated tag, a bulk
// delete), and tests spy on it to assert that a given action does or does not
// ask. `vi.spyOn` on a missing property fails outright, so these have to exist
// before a spy can replace them. Defaults are deliberately the safe answers: a
// confirm nobody stubbed says no, so a test that forgets to stub cannot
// silently perform a deletion.
if (typeof window !== "undefined") {
  window.confirm ??= () => false;
  window.alert ??= () => undefined;
  window.prompt ??= () => null;
}

if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

/**
 * The stylesheet, read as text.
 *
 * No stylesheet is loaded here in the ordinary way: `vite.config.ts` processes
 * CSS only so that it can be read like this, and nothing under test imports
 * one. Every custom property on the document is therefore empty unless a test
 * writes it, and `patterns.ts` resolves the wallpaper's colours off the
 * document at runtime rather than owning any hex, so without them the app under
 * test is one with no palette, which is not the app.
 */
const INDEX_CSS = (
  import.meta.glob("../src/index.css", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>
)["../src/index.css"];

/**
 * The six palette steps the wallpaper reads, taken from the stylesheet itself.
 *
 * They were six literals with a comment claiming they were the shipped values,
 * and one of them was not: `--color-paper-950` read `#1a1816` where the
 * stylesheet says `#100e0c`, so every dark mode alpha in the suite was solved
 * against a page 27% lighter than the one that ships. Nothing failed, because
 * the assertions were self-consistent with the wrong ground. A comment is not
 * a mechanism, so the values are extracted instead.
 *
 * Four of the six are inks and two are the page each mode is drawn on. The page
 * is read for the same reason the inks are: every layer's opacity is solved
 * from how far its ink moves the page it sits on, so a tile with no page has no
 * opacity to be drawn at and is not painted.
 */
const WALLPAPER_TOKENS = [
  "--color-accent-700",
  "--color-accent-300",
  "--color-bloom-700",
  "--color-bloom-300",
  "--color-paper-50",
  "--color-paper-950",
];

function shippedPalette(): Record<string, string> {
  if (!INDEX_CSS || INDEX_CSS.length < 1000) {
    // Under `css: false` a raw CSS import is an empty string, and every test
    // that draws a tile would then quietly run with no palette at all.
    throw new Error("tests/setup.ts could not read src/index.css");
  }
  const code = INDEX_CSS.replace(/\/\*[\s\S]*?\*\//g, "");
  const tokens: Record<string, string> = {};
  for (const token of WALLPAPER_TOKENS) {
    const declared = [
      ...code.matchAll(new RegExp(`${token}\\s*:\\s*([^;]+);`, "g")),
    ].map((match) => match[1]!.trim());
    // Exactly one, deliberately. Endpaper declares all six in `@theme static`
    // and overrides none of them under `:root.dark`, so first-match and
    // only-match are the same answer today. If that stops being true, taking
    // the first would silently hand the dark solve a light page, which is the
    // bug this replaced. Failing here makes somebody choose instead.
    if (declared.length !== 1 || !/^#[0-9a-f]{6}$/i.test(declared[0]!)) {
      throw new Error(
        `${token}: expected one literal hex in index.css, found ${JSON.stringify(declared)}`,
      );
    }
    tokens[token] = declared[0]!;
  }
  return tokens;
}

/**
 * Parsed once per worker **process**, not once per test file.
 *
 * This file is the suite-wide setup, so anything at module scope runs again for
 * every one of the seventy-eight files, and vitest gives each file a fresh
 * module registry: a plain module-level `let` is therefore not a cache, it is
 * the same work with an extra branch. `globalThis` outlives the registry
 * because the fork pool reuses the process, so with two workers this parses
 * twice for the whole run instead of seventy-eight times.
 *
 * The work and its errors are unchanged; only how often it happens is.
 */
const PALETTE_CACHE_KEY = "__endpaper_palette_tokens__";

function paletteTokensOnce(): Record<string, string> {
  const store = globalThis as Record<string, unknown>;
  store[PALETTE_CACHE_KEY] ??= shippedPalette();
  return store[PALETTE_CACHE_KEY] as Record<string, string>;
}

/**
 * Storage that a finished test left broken.
 *
 * **A behaviour check, after three attempts to detect this by introspection.**
 * The failure it exists for is real and cost a review round to attribute:
 * `vi.spyOn(window.sessionStorage, "setItem")` mocked to throw is **not** put
 * back by `vi.restoreAllMocks()`, and under `isolate: false` the throwing stub
 * then reaches every later file. It surfaced as four failures in
 * `tests/app/App.test.tsx`, a file that did not cause it, on one shuffled seed
 * in nine, and the first diagnosis blamed an unrelated module level flag.
 *
 * Why not look for the spy itself. Three versions tried and each was wrong in
 * its own way, which is the argument for asking the object what it does rather
 * than what it is made of:
 *
 * * the prototype's own descriptors do not hold it, because a spy on an
 *   inherited method is installed against the instance;
 * * the instance's own properties do not either, because happy-dom implements
 *   `Storage` as a **Proxy** whose `hasOwnProperty` answers false for a key
 *   whose `get` hands back the spy;
 * * and `.mock` is present on a spy that has already been **restored**, so
 *   looking for it reports a file that did the right thing.
 *
 * Reading every key to get past the first two throws, because prototype
 * accessors are invoked by reading them and happy-dom's event handler getters
 * fail on a bare receiver.
 *
 * A round trip has none of those problems and tests the property that actually
 * matters: a `setItem` that throws, a `getItem` that lies and a `removeItem`
 * that does nothing are all caught, whatever installed them.
 *
 * **What it does not catch, stated because the message must not over claim.** A
 * pass through spy left installed on an instance is invisible here: storage
 * still works, so the round trip is clean, and the probe's own writes are
 * recorded as calls on it. That is a real leak with a harmless payload. The
 * rule enforced is "storage still works", not "no spy remains", which is why
 * the message says broken rather than mocked.
 *
 * On the `removeItem` arm the probe key is left in the store, because the thing
 * that would clear it is the thing that is broken. Contained: the test is
 * failing anyway and `beforeEach` clears both stores before the next one.
 *
 * Why `vi.spyOn(Storage.prototype, ...)` is fine while the instance is not:
 * the prototype is a plain object, so the suite wide restore does reach it.
 * **Eight files spy that way and none of them leaks; exactly one spied on an
 * instance, and that is the one that did.** Counted excluding this file, which
 * matches only because this comment names the call.
 */
function storageLeftBroken(): string | null {
  if (typeof window === "undefined") return null;
  const key = "__endpaper_storage_probe__";
  for (const [name, store] of [
    ["sessionStorage", window.sessionStorage],
    ["localStorage", window.localStorage],
  ] as const) {
    try {
      store.setItem(key, "1");
      if (store.getItem(key) !== "1") return `${name}.getItem`;
      store.removeItem(key);
      if (store.getItem(key) !== null) return `${name}.removeItem`;
    } catch {
      return `${name}.setItem`;
    }
  }
  return null;
}

beforeEach(() => {
  // **Centrally, so that no file can forget it.** The ZXing double is aliased in
  // for the whole suite, so its spies are reachable from any file that renders a
  // scanner, whether or not that file knows the double exists. Left to each file
  // there was an asymmetry that had already cost something: `ScanPage.test.tsx`
  // waits for `decodeFromStream` to have been called before delivering a
  // barcode, and with calls left over from an earlier test that barrier was true
  // on arrival and could never fail.
  //
  // The camera is deliberately not reset here. It is a global rather than a
  // module, it is absent unless a file asks for it, and `installCamera()` resets
  // its spies as part of installing it: a file that never opens a camera should
  // not have one.
  resetZxingDouble();
  // Same guard as the matchMedia shim above, and for the same reason: this hook
  // runs for the `@vitest-environment node` files too, which have neither a
  // localStorage nor a document. The network stub below is installed either way,
  // because a node-environment test reaching the real network is exactly as
  // wrong as a jsdom one doing it.
  if (typeof document !== "undefined") {
    localStorage.clear();
    // `sessionStorage` too, because `api/mutator.ts` records its edge-sign-out
    // reload marker there. A marker left behind by one test makes the next one
    // take the "we have already reloaded once" branch, which is the difference
    // between reloading and rendering a dead end.
    sessionStorage.clear();
    for (const [token, value] of Object.entries(paletteTokensOnce())) {
      document.documentElement.style.setProperty(token, value);
    }
  }
  // Anything the test forgot to stub should fail loudly rather than reach the
  // real network. Tests install their own handlers via mockApi().
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) =>
      Promise.reject(
        new Error(
          `Unhandled request: ${String(input)}. Stub it with mockApi()`,
        ),
      ),
    ),
  );
});

// jsdom implements <dialog> but not showModal/close, so a dialog opened the way
// the app opens one stays shut and its contents never reach the accessibility
// tree. The gap is jsdom's, not the app's: real browsers have had these for
// years. Toggling `open` is enough to make the element behave for a test.
beforeAll(() => {
  // Third and last of the DOM guards in this file. See the matchMedia shim.
  if (typeof window === "undefined") return;
  const dialog = window.HTMLDialogElement?.prototype;
  if (dialog && !dialog.showModal) {
    dialog.showModal = function showModal(this: HTMLDialogElement) {
      this.open = true;
    };
    dialog.close = function close(this: HTMLDialogElement) {
      this.open = false;
      this.dispatchEvent(new Event("close"));
    };
  }
});

//: The real `window.location`, captured before any test can replace it.
//
// **Three test files replace it wholesale** with `Object.defineProperty`,
// because a real navigation is not a thing a test environment can do. Neither
// `vi.unstubAllGlobals()` nor `vi.restoreAllMocks()` undoes that: they know
// about stubs vitest installed, and a direct `defineProperty` is not one.
//
// That costs nothing while every file gets its own window and is a leak the
// moment they share one. Measured under `isolate: false`, one worker, file
// order seeded: `tests/api/mutator.test.ts` leaves a location of
// `{href: "/", pathname: "/"}` behind, with no origin, and the next file that
// renders an `<img src="/covers/1.jpg">` gets an error event instead of a
// load, because a relative URL cannot resolve against it. Three of
// `CoverImage.test.tsx`'s eight tests then found the placeholder where they
// expected the cover, with nothing in either file wrong on its own.
//
// Restored here rather than in the three files, because the next file to
// replace it should not have to know this.
const REAL_LOCATION =
  typeof window === "undefined"
    ? undefined
    : Object.getOwnPropertyDescriptor(window, "location");

//: The URL the environment starts at, so a test that navigates cannot decide
//: where the next one begins. Replacing the location object does not restore
//: this: a navigation changes the real one, and `document.baseURI` follows it.
const REAL_HREF =
  typeof window === "undefined" ? undefined : window.location.href;

//: Whether this environment came with a camera, so `tests/doubles/camera.ts`
//: can be uninstalled rather than left on `navigator` for the next file.
//:
//: happy-dom defines no `mediaDevices`, so the honest restore is to delete the
//: property again rather than to write `undefined` over it: a test asking
//: `"mediaDevices" in navigator` would otherwise get the wrong answer from a
//: camera nobody installed.
const REAL_MEDIA_DEVICES =
  typeof navigator === "undefined"
    ? undefined
    : Object.getOwnPropertyDescriptor(navigator, "mediaDevices");

afterEach(() => {
  // `cleanup()` unmounts React trees, of which a node-environment file has none.
  if (typeof document !== "undefined") cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  // Unconditionally, and the conditional this replaced is worth a sentence
  // because it read as a cheap guard and was not one:
  // `Object.getOwnPropertyDescriptor` builds a fresh object every call, so
  // comparing one against the captured descriptor with `!==` is always true and
  // the branch always fired. Writing the same descriptor back is idempotent, so
  // the behaviour is unchanged and only the claim is.
  if (REAL_LOCATION) Object.defineProperty(window, "location", REAL_LOCATION);
  // **And the URL itself.** Measured under a shared environment: the download
  // tests leave it at `blob:mock-url`, after which a relative `src` on an image
  // cannot resolve at all, happy-dom fires `error` instead of loading, and the
  // next file's cover tests find the placeholder they were checking against.
  // Several files navigate less dramatically and leave a path behind.
  //
  // **Assigned rather than pushed.** `history.pushState` refuses to cross an
  // origin, and the download tests leave the document on `blob:mock-url`, whose
  // origin is null: measured, the reset itself then threw a SecurityError and
  // failed the very file that had navigated. Setting `href` has no such rule.
  if (REAL_HREF && window.location.href !== REAL_HREF) {
    window.location.href = REAL_HREF;
  }
  // **And the camera.** Installed with `defineProperty` by every file that
  // renders the scanner, so nothing vitest owns takes it off again.
  // Put it back, or take it off if this environment never had one. happy-dom
  // defines no `mediaDevices` at all, so the delete is the live branch here and
  // it is a no-op when nothing installed a camera.
  //
  // **Not the same case as the location above, though it was described as one
  // for a round.** There the comparison was between two freshly built
  // descriptor objects and so always fired; here, with no camera installed,
  // both sides are `undefined` and the old conditional correctly did nothing.
  // Only the location branch was ever dead. Unconditional here is a
  // simplification rather than a fix.
  if (typeof navigator !== "undefined") {
    if (REAL_MEDIA_DEVICES) {
      Object.defineProperty(navigator, "mediaDevices", REAL_MEDIA_DEVICES);
    } else {
      delete (navigator as { mediaDevices?: unknown }).mediaDevices;
    }
  }

  // **Last, after every restore above has had its chance.** Storage still
  // broken here is broken for every later file under `isolate: false`.
  const broken = storageLeftBroken();
  if (broken) {
    throw new Error(
      `This test left ${broken} broken. vi.restoreAllMocks() does not put ` +
        "back a spy installed on a storage instance, so it reaches every " +
        "later file. Spy on Storage.prototype instead, or keep the handle " +
        "vi.spyOn() returns and call mockRestore() on it.",
    );
  }
});
