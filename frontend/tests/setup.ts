import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";

import { forgetPreferences } from "../src/lib/preference";
import { resetZxingDouble } from "./doubles/zxing";
import { openLedger, uncontrolled } from "./lib/doorLedger";
import {
  hadDecompressionStream,
  realDecompressionStream,
} from "./lib/withoutDecompression";

/**
 * The zone every run of this suite is in, pinned rather than inherited.
 *
 * **Nothing pinned one before, so the suite's answers depended on the machine.**
 * The container resolved one zone and a development machine another, and both
 * looked correct, so a date assertion could be green here and red there with no
 * file having changed. That alone is reason enough to pin something.
 *
 * **Which zone is not arbitrary, and it is not the one the container happened to
 * run.** Measured by driving the two naive parse mutants against the arms in
 * `tests/lib/date.test.ts`, one zone at a time:
 *
 * | zone | `endOfDayInstant` parsed as UTC | `monthLabel` key parsed as UTC |
 * |---|---|---|
 * | `UTC` | not caught | not caught |
 * | east of Greenwich (Berlin, Kolkata, Kiritimati) | caught | **not caught** |
 * | west of Greenwich (this one, Phoenix, Honolulu) | caught | caught |
 *
 * Under `UTC`, parsing a wall clock as local and parsing it as UTC are the same
 * function, so no expression over their output can tell them apart: both arms
 * are dead and the deadline work's whole guard with them. East of Greenwich
 * revives the first and leaves the second dead, because UTC midnight of a
 * `YYYY-MM` bucket is still the same month locally. **Only west of Greenwich
 * catches both**, which is what `lib/date.ts` already says in words when it
 * warns that a UTC parse puts a January bucket in December "for anybody west of
 * Greenwich". So the zone is west, and that is a measurement rather than taste.
 *
 * **No DST, which is the second constraint.** A zone that changes offset makes a
 * fixture's expected value depend on which month its literal names, so the next
 * person to write one inherits a trap. This zone is -09:30 year round, measured
 * at 570 minutes in both January and August.
 *
 * -09:30 rather than a whole hour is the tiebreak and is argued as one rather
 * than measured: no mutant here needs it, and it costs nothing to have an offset
 * that a whole hour assumption cannot reproduce.
 *
 * **How much further west the pin could move is 30 minutes, and that is the
 * minimum over the fixtures rather than a comfortable one picked from them.**
 * An earlier version of this said 2.5 hours, which is the headroom of the one
 * fixture with the most slack, and is the measurement this repository keeps
 * paying for: a figure taken over the easiest member and written as a property
 * of the set. The binding family is 21 occurrences of a 10:00 UTC stamp across
 * five files, which render at 00:30 local, and three of those files assert a
 * calendar date outright.
 *
 * **And this figure is armed rather than merely measured, which is the rung
 * worth knowing.** Driven: moving the pin 90 minutes further west, to a zone
 * that passes every check in this file once `SUITE_TIMEZONE_OFFSET` moves with
 * it, reds **four named arms in four files**. So the pin cannot move by
 * accident at all, the checks below refuse that, and a deliberate two line move
 * reds by name rather than quietly costing the suite its fixtures. Still
 * re-derive the population rather than trusting this line:
 *
 *     /bin/grep -rhoE '"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z"' tests/ | sort | uniq -c
 *
 * Each stamp's headroom is its UTC clock time minus this pin's 9:30, as minutes
 * past local midnight, and the smallest positive one binds.
 *
 * **Ten occurrences already render the previous day, and that is intended.**
 * Nine are either asserted with a line saying so or assert no date at all. The
 * tenth is a client built `toISOString()` compared as a string, which no zone
 * can move, so it is not a member of this class.
 *
 * **There is no fidelity argument for any zone, which is why catching power
 * decides.** This app stores no zone against an account: `lib/date.ts` records
 * that the browser's is the only statement of where a member is. So there is no
 * production zone for a suite to match, and `UTC` was never the realistic choice,
 * only the container's accident.
 *
 * **Set here rather than in an arm, because it is a global.** The suite runs
 * `isolate: false`, so one process serves many files per worker and a pin that
 * failed to restore would redden unrelated files non deterministically.
 *
 * **And it has to stay above everything.** `lib/date.ts` builds its formatters
 * lazily on first call, and nothing this file imports constructs a `Date` or an
 * `Intl` formatter while it is being evaluated, so this runs before any of them
 * reads a zone. An eager formatter at module scope anywhere in that import graph
 * would capture the old zone and this pin would miss it.
 */
const SUITE_TIMEZONE = "Pacific/Marquesas";

/** What `SUITE_TIMEZONE` is worth in minutes, which is what `Date` actually does. */
const SUITE_TIMEZONE_OFFSET = 570;

process.env.TZ = SUITE_TIMEZONE;

/**
 * The pin, proved rather than assumed, and proved again after every test.
 *
 * **An unavailable zone is silently ignored, in both spellings and with two
 * different wrong answers.** Measured on bun 1.4.2, the version the suite
 * container runs: a name the runtime cannot resolve leaves a `process.env.TZ`
 * assignment with the zone that was already in force, and leaves a `TZ=` set
 * before the process started at `UTC`. Neither throws and neither warns. So a
 * pin that is merely written is the shape of configuration this repository has
 * twice shipped inert: accepted, plausible and binding nothing. It would be
 * worse than no pin, because it reads as the discriminating zone while being
 * one that discriminates nothing.
 *
 * **Four things are checked, and none of them is redundant.**
 *
 * The **name** is what the runtime says about itself. The **offset** is what
 * `Date` actually does, and they can disagree if `Intl` carries zone data the
 * clock does not.
 *
 * The **hemisphere** is the table above read as a requirement rather than as an
 * observation, and until it was checked nothing enforced it. A bare
 * `YYYY-MM-DD` parsed as UTC midnight lands on the day it names in every zone
 * whose offset is zero or east, so at such a pin the date-only arms in
 * `tests/lib/date.test.ts` and the Bought on arm in
 * `tests/pages/Home/components/BookTable.test.tsx` pass on the broken parse.
 * Driven, pin moved to `Asia/Tokyo` with this check disarmed, which is how it
 * has to be re-derived now that the check exists: six arms in four files red
 * with the code correct, and **the identical six, same names and same counts,
 * with the date-only parse reverted**. None of the six is a date-only arm. So
 * east of here the defect is not harder to see, it is invisible, and every red
 * looks like a fixture date wanting a new expected value. Updating them is the
 * repair the failure invites and it would take this suite's whole regression
 * coverage of that defect with it, plus the `monthLabel` mutant the table above
 * says only a western pin catches.
 *
 * **The four compose, and that is worth more than any one of them.** No single
 * edit moves the pin east past all four: changing the zone forces the name
 * check, which forces the constant to change with it; the two seasonal readings
 * then force that constant to be what the clock actually does; and this one
 * refuses it once it is negative. Each check alone is evadable by editing its
 * neighbour's input, and together they are not.
 *
 * The **second offset, six months out, is what holds the no DST constraint**.
 * The zone is chosen partly because it does not change offset, so a fixture's
 * expected value never depends on which month its literal names. One reading
 * cannot see that: swapped to a DST zone, a single instant passes and the suite
 * quietly acquires two offsets. Two readings half a year apart refuse it.
 *
 * **Called from the teardown as well as here, because this is a mutable
 * global.** Setting it once at module scope is a claim about the moment the
 * module ran, and a test file's own module scope runs **after** this one: a line
 * reassigning `process.env.TZ` there is undone for the next file but stands for
 * every test in its own, where a one time assertion has already passed. Driven:
 * one such line left this green and reddened two arms elsewhere. The teardown
 * below already refuses a leaked global for three other objects, so this is that
 * same check with a fourth subject.
 */
function assertTheZoneIsPinned(): void {
  const resolved = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (resolved !== SUITE_TIMEZONE) {
    throw new Error(
      `the suite's timezone pin did not take: asked for ${SUITE_TIMEZONE}, got ${resolved}. ` +
        `Either this runtime cannot resolve that zone, which it fails silently rather ` +
        `than saying, or something reassigned the zone after setup ran.`,
    );
  }
  // Two instants, roughly six months apart, so a zone that keeps a summer and a
  // winter offset is refused rather than sampled at whichever one happens to
  // pass. Both are read as UTC instants so the reading does not depend on the
  // very thing it is checking.
  const winter = new Date("2026-01-19T12:00:00Z").getTimezoneOffset();
  const summer = new Date("2026-08-19T12:00:00Z").getTimezoneOffset();
  if (winter !== SUITE_TIMEZONE_OFFSET || summer !== SUITE_TIMEZONE_OFFSET) {
    throw new Error(
      `${SUITE_TIMEZONE} is not at a constant ${SUITE_TIMEZONE_OFFSET} minutes: ` +
        `January reads ${winter} and August reads ${summer}. A suite zone that ` +
        `changes offset makes a fixture's rendered day depend on its month.`,
    );
  }
  // `getTimezoneOffset` counts minutes BEHIND UTC, so west is positive. Read
  // off the constant rather than off the clock, because the constant is what a
  // person edits when they move the pin and it is already proved equal to the
  // clock two lines above.
  if (SUITE_TIMEZONE_OFFSET <= 0) {
    throw new Error(
      `the suite zone must be WEST of Greenwich and ${SUITE_TIMEZONE} is at ` +
        `${SUITE_TIMEZONE_OFFSET} minutes. This is not a preference: a bare ` +
        `YYYY-MM-DD parsed as UTC midnight lands on the day it names at every ` +
        `offset of zero or east, so the date-only arms would pass on the ` +
        `broken parse and the monthLabel mutant would go uncaught. Moving the ` +
        `pin east reds the same arms whether or not those defects are present, ` +
        `which is why this refuses by name here instead.`,
    );
  }
}

assertTheZoneIsPinned();

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
    addListener: vi.fn<MediaQueryList["addListener"]>(),
    removeListener: vi.fn<MediaQueryList["removeListener"]>(),
    addEventListener: vi.fn<MediaQueryList["addEventListener"]>(),
    removeEventListener: vi.fn<MediaQueryList["removeEventListener"]>(),
    dispatchEvent: vi.fn<MediaQueryList["dispatchEvent"]>(),
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
 * This file is the suite-wide setup, so everything at module scope runs again
 * for every file in the suite, and each file gets a fresh module registry: a
 * plain module-level `let` is therefore not a cache, it is the same work with an
 * extra branch. `globalThis` outlives that registry because the pool reuses the
 * process, so a run parses the stylesheet far fewer times than it has files.
 *
 * **Both halves are measured rather than reasoned.** Driven through the suite
 * runner over 58 files, two probes, because either alone is ambiguous:
 *
 * | probe | reading |
 * |---|---|
 * | a counter on `globalThis`, bumped by this file's module scope | reads **2** on the second file a process serves, so the global survives between files |
 * | a parse counter in `process.env`, which survives the same way | **never reaches 2**, so `shippedPalette()` runs at most once per process |
 *
 * The second probe alone would be the weaker evidence, because `process.env`
 * resetting per file would fake it; the first is what rules that out, and it
 * shows both stores surviving together.
 *
 * **The file count is deliberately not written here**, because it moves
 * whenever a test file is added and is then read as current. Count them with
 * the suite's own report.
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
 * **Why neither spy works, measured against happy-dom and vitest's spy.** A spy
 * on the instance lands there because the proxy's `defineProperty` trap puts it
 * on the target. vitest found the method on the prototype, so its restore
 * deletes the instance's property, and the proxy's `deleteProperty` trap
 * refuses anything that is not a stored item. `mockRestore()` on the handle
 * does put storage right, by resetting the spy to call through, though the spy
 * stays. A spy on `Storage.prototype` is restored, but happy-dom binds an own
 * copy of each storage method onto the instance the first time it is read,
 * and this probe reads all three after every test. Installed after that read,
 * the spy is never called and its test runs on storage that answered;
 * installed before it, the bound copy calls the spy, which restoring the
 * prototype does not reach. Replace the method on the instance and put it back
 * in a `finally`, as `whileStorageRefuses` in `tests/storageRefusal.ts` does.
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
  // **Centrally for the same reason.** `lib/preference.ts` holds its decoded
  // snapshots and its listeners at module scope, because a snapshot has to be
  // the same value until its stored string changes and a listener set has to
  // outlive one component. The suite runs with `isolate: false`, so those live
  // as long as the worker: a file that cleared storage and not this would be
  // handed the previous file's snapshot for a key it believes is empty, and a
  // listener left by an unmounted hook would be called by the next file's write.
  // Clearing the storage alone is what makes that invisible rather than loud.
  forgetPreferences();
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

//: The parser this file's environment shipped, read before any test can wrap
//: it. **Per file and not memoised per worker**, unlike the inflater below:
//: the inflater is the runtime's and survives an environment, while happy-dom
//: and jsdom each bring their own `DOMParser`, and this module is evaluated
//: once per test file, after that file's environment is built.
const REAL_DOM_PARSER = (globalThis as { DOMParser?: unknown }).DOMParser;

//: Whether this environment can inflate, seeded before any test can take it
//: away.
//:
//: `tests/lib/withoutDecompression.ts` deletes this global to reach the one
//: refusal in the reader family whose cause is the runtime rather than the
//: file, and puts it back in a `finally`. The `afterEach` below is the backstop
//: for a route that does not, and it is the storage probe's argument one object
//: over: under `isolate: false` a global left missing reaches every later file
//: in the worker, where five readers open a zip and the sixth inflates PDF
//: streams, so what it produces is a file reporting a member's book as one this
//: browser cannot read, in a file that did nothing wrong.
//:
//: **Called here and not only from the check, which is the whole of what makes
//: it a backstop.** The memo answers what this worker started with, and it
//: takes that answer from the first call: leave the first call to `afterEach`
//: and a test that leaks the global before any test has finished seeds it
//: `false`, silencing the check for every remaining file. Measured by the
//: design seat, a leak in the first `it` of a file: `SUITE EXIT: 0` with
//: nothing reported, against a named failure with this line present. Module
//: scope here runs before any test body in the file, and the memo is per
//: worker, so the seed happens once and before anything can move it.
//:
//: An environment that never had one is not a leak, which is why this is a
//: question about what this worker started with rather than an assertion.
hadDecompressionStream();
realDecompressionStream();

//: **A fresh door ledger per file**, opened at module scope, which runs once
//: per test file before any of its tests, and read after its last one.
//: `tests/lib/doorLedger.ts` says why it is per file and not per worker.
openLedger();
afterAll(() => {
  const missing = uncontrolled();
  if (missing.length > 0) {
    throw new Error(
      "A door this file drives declares a bound no positive control in this " +
        "file overran, so deleting or loosening it reds nothing: " +
        `${missing.join("; ")}. Add an overrunBreach arm per bound, from ` +
        "tests/lib/readerContract.ts.",
    );
  }
});

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

  // **The inflater, asked of the memo seeded at module scope.** Neither
  // `vi.unstubAllGlobals()` nor `vi.restoreAllMocks()` puts back a deleted
  // property, for the reason the location descriptor above carries: they know
  // about stubs vitest installed, and a `delete` is not one.
  if (hadDecompressionStream() && typeof DecompressionStream === "undefined") {
    throw new Error(
      "This test left DecompressionStream missing. Under isolate: false that " +
        "reaches every later file, where every reader that opens a zip then " +
        "reports a member's file as one this browser cannot inflate. Remove " +
        "it with withoutDecompressionStream() from tests/lib/" +
        "withoutDecompression.ts, which puts it back in a finally.",
    );
  }
  // **And the same object, which presence cannot say.** The meter replaces the
  // inflater with a counting one for one call; one left installed is present,
  // so the check above passes it, and every later file in the worker inflates
  // through a meter nobody reads.
  if (
    hadDecompressionStream() &&
    (globalThis as { DecompressionStream?: unknown }).DecompressionStream !==
      realDecompressionStream()
  ) {
    throw new Error(
      "This test left a replacement DecompressionStream installed. Under " +
        "isolate: false every later file in the worker inflates through it. " +
        "Install one with the meter in tests/lib/meter.ts, which puts the " +
        "original back in a finally.",
    );
  }

  // **The parser, by the same identity.** The meter wraps it for one call to
  // count what a reader hands it; one left installed reaches every later test
  // in this file, which then parses through a meter nobody reads.
  if ((globalThis as { DOMParser?: unknown }).DOMParser !== REAL_DOM_PARSER) {
    throw new Error(
      "This test left a replacement DOMParser installed. Install one with the " +
        "meter in tests/lib/meter.ts, which puts the original back in a finally.",
    );
  }

  // **Last, after every restore above has had its chance.** Storage still
  // broken here is broken for every later file under `isolate: false`.
  const broken = storageLeftBroken();
  if (broken) {
    throw new Error(
      `This test left ${broken} broken. vi.restoreAllMocks() does not put ` +
        "back a spy installed on a storage instance, so it reaches every " +
        "later file. Replace the method on the instance and put it back in a " +
        "finally, as whileStorageRefuses in tests/storageRefusal.ts " +
        "does, or keep the handle vi.spyOn() returns and call mockRestore() " +
        "on it. A spy on Storage.prototype is no way out: once the method " +
        "has been read, it is never called.",
    );
  }

  // **The zone, for the same reason as the three above it.** It is a mutable
  // global, so the module scope assertion only speaks for the moment setup ran:
  // anything that reassigns it afterwards, including a test file's own module
  // scope, stands for the rest of that file unchallenged.
  assertTheZoneIsPinned();
});
