/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom. Building one costs more than this file
 * spends running: measured across the suite, `environment` was 168s of a 245s
 * run, paid once per file.
 */
/**
 * Rules that hold across the whole tree, asserted rather than trusted.
 *
 * None of them has any other enforcement, and every one is the kind of thing
 * that looks fine in a diff and is only wrong when read against the rest of the
 * tree, which is exactly what a reviewer does not do. (This said "neither" and
 * "both" while the file held eleven rules, which is what a count written in
 * prose does: it does not recount itself when a rule is added beside it. There
 * is deliberately no number here now.)
 *
 * The sources are read with `import.meta.glob` rather than `node:fs` so this
 * needs no `@types/node`, which the project does not otherwise want: a guard
 * test is a poor reason to add a dependency and widen the global types.
 */

import { describe, expect, it, vi } from "vitest";
import { parseAst } from "vite";

// Imported through the specifier the application uses, so this is the double
// only if the alias is in force.
import * as zxingDouble from "@zxing/library";

// The subject of the column count rule at the foot of this file. Imported so
// the figure it refuses is computed rather than written here.
import { COLUMN_SPECS } from "../src/lib/libraryColumns";

// The refusal this file and the ScanPage guard both apply, in one home: the
// module says why it is not a copy per guard.
import { CARRIES_A_BOOK } from "./carriesABook";

// **This file's own source, which no glob here can supply.** The reason and
// the measurement are at `SELF` in the address rule below, which is the one
// place this tree states it: a rule reading a glob written here is exempt from
// itself. Restating it instead of pointing at it is how the column count rule
// came to assert the opposite in its own docstring while passing.
//
// A `?raw` specifier is a different module id, so this is a string and not a
// cycle.
import ownSource from "./houseRules.test.ts?raw";

const SOURCES = import.meta.glob("../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function entries(): [string, string][] {
  return Object.entries(SOURCES).map(([path, source]) => [
    path.replace("../src/", ""),
    source,
  ]);
}

describe("the generated client stays behind hooks.ts", () => {
  it("is imported by nothing else", () => {
    // The single indirection is what stops a regeneration rippling through
    // every component. Types are a different matter and are imported freely:
    // `api/generated/model` is a description of the API, not a call to it.
    const offenders = entries()
      .filter(([path]) => !path.startsWith("api/"))
      .filter(([, source]) => source.includes("api/generated/endpoints"))
      .map(([path]) => path)
      .filter((path) => !path.endsWith("hooks.ts"));

    expect(offenders).toEqual([]);
  });

  it("reads the source tree at all", () => {
    // A glob that matched nothing would make both tests above pass forever.
    expect(entries().length).toBeGreaterThan(50);
  });
});

describe("nothing hand-written lives under the assets directory", () => {
  // The invariant behind the backend's cache policy, which gives everything in
  // `assets/` a year with `immutable` and everything else `no-cache`. That is
  // safe only because Vite emits `assets/` and every name in it carries a
  // content hash. Vite also copies `public/` into the build verbatim, so a file
  // at `public/assets/anything` would land there unhashed and be pinned in
  // every reader's browser for a year, with no way to bust it short of a
  // rename: the exact failure the header exists to prevent, inverted.
  //
  // Asserted rather than commented, because the rule is about a directory
  // nobody has a reason to create and would therefore be created by somebody
  // who never read the comment. Backend side: `main.cache_control_for`.
  // Lazy and untyped on purpose: only the keys are wanted, and an eager raw
  // glob would inline every icon in `public/` into this test file as a string.
  const PUBLIC = import.meta.glob("../public/**/*");

  it("has no public/assets", () => {
    const offenders = Object.keys(PUBLIC).filter((path) =>
      path.startsWith("../public/assets/"),
    );
    expect(offenders).toEqual([]);
  });

  it("reads public/ at all", () => {
    // A glob that matched nothing would make the test above pass for ever.
    expect(Object.keys(PUBLIC).length).toBeGreaterThan(0);
  });
});

describe("paper-400 and paper-500 are not text in light mode", () => {
  it("appears nowhere in the source", () => {
    // Measured against the card they sit on: 2.35:1 and 3.83:1, where AA wants
    // 4.5. Both pass in dark, on a dark card, which is why nobody noticed: a
    // light surface admits fewer legible grey tiers than a dark one, and the
    // app was treating the ramp as symmetric. Muted text is `paper-600` in
    // light and `paper-400` in dark.
    //
    // Retiring the two as text is also what lets three upstream palettes ship
    // verbatim later: as decoration the step has to clear 3.0, not 4.5.
    //
    // `disabled:` is the exemption, and the only one. WCAG 1.4.3 does not apply
    // to an inactive control, and a disabled field that reads as strongly as a
    // live one is worse than a faint one.
    //
    // `index.css` is not covered, and no longer because it cannot be: the glob
    // above is TypeScript, while `tests/theme/palettes.test.ts` reads the
    // stylesheets as text and could do the same here. It holds exactly one of
    // these tokens, on `.field:disabled`, which is the exemption, so a second
    // glob would buy an assertion about a line that is already allowed.
    const offenders = entries().flatMap(([path, source]) =>
      [...source.matchAll(/[\w:./[\]-]*text-paper-[45]00/g)]
        .map((match) => match[0])
        .filter(
          (token) => !token.includes("dark:") && !token.includes("disabled:"),
        )
        .map((token) => `${path}: ${token}`),
    );

    expect(offenders).toEqual([]);
  });
});

describe("no control draws its own focus ring", () => {
  it("appears nowhere in the source", () => {
    // There is one ring, in `index.css`, and a control that brings its own is a
    // control that gets missed the next time that one moves. Twenty-one of them
    // did: `focus:ring-accent-400` measures 2.24:1 against the page where WCAG
    // 1.4.11 wants 3:1, and sixteen killed the browser default with
    // `focus:outline-none` first, so the text fields had the weakest focus
    // indicator in the app and nothing underneath it.
    //
    // `focus-visible:` as well as `focus:`, and arbitrary values, because the
    // shared rule *is* `:focus-visible`: the next person repairing a control
    // reaches for that spelling first, and for `ring-[3px]` second. Two shapes
    // are deliberately out of scope, both of which stop looking like a focus
    // ring at all: `focus:[box-shadow:...]`, which is a raw property rather than
    // a ring utility, and a bare `outline-none`, which removes the outline in
    // every state rather than on focus and belongs to a rule about outlines.
    //
    // `peer-focus-visible:` is exempt and is the settings toggle: its input is
    // `sr-only`, so the shared ring lands on something with no size and the
    // visible track has to draw its own.
    const offenders = entries().flatMap(([path, source]) =>
      [
        ...source.matchAll(
          /[\w:./[\]-]*focus(-visible)?:(outline-none|ring-[\w./#%[\]-]+)/g,
        ),
      ]
        .map((match) => match[0])
        .filter((token) => !token.includes("peer-focus-visible:"))
        .map((token) => `${path}: ${token}`),
    );

    expect(offenders).toEqual([]);
  });
});

/**
 * The modules that read a picked ebook file, which is the whole reading path.
 *
 * Named rather than globbed: this is a rule about a specific seam, and a glob
 * would either miss a reader added elsewhere or sweep in the page that
 * legitimately does both. A new reader is added to this list by the ticket that
 * writes it, which is the moment somebody is thinking about the rule.
 */
/**
 * What makes a module a reader, so the list below is checked and not trusted.
 *
 * **Derived, because an inclusion list is what goes stale when the repository
 * grows a file.** A reader is a module under `src/lib/` that handles bytes or
 * parses a document. Every way this app's readers get hold of either is named:
 * `File` and `Blob` are what a picker hands over, `ArrayBuffer`, `Uint8Array`
 * and `ReadableStream` are what those become, and `DOMParser` is the document.
 * Everything else in that directory works on values somebody already read.
 *
 * **Two exclusions, and the one that matters is the directory.** Measured over
 * this tree: 20 modules outside `src/lib/` meet the same criterion, 7 of them
 * generated multipart body types under `src/api/generated/`, and the other 13 a
 * page or a page's hook, every one of which legitimately both reads a file and
 * makes a request. A network rule cannot tell those two apart,
 * which is the whole reason this one sits where only the first exists. The seam
 * is that a reader lives in `lib/`, so a new one belongs there rather than
 * here, and a reader written outside it is outside this rule until it moves.
 *
 * The second exclusion is a `.d.ts`, which declares and executes nothing and so
 * is not a reader however many of these names it mentions.
 *
 * `Blob` and `ReadableStream` derive the same five modules as the shorter list
 * did, measured, so they cost nothing today and close the case of a reader that
 * takes a `Blob` and never names a typed array. **It is still an enumeration of
 * an open set**: `DataView` and `FileReader` are not in it, and a further arm is
 * not the fix. What bounds it is the directory: a module in `lib/` reaching the
 * network is refused whichever of these it names, and one that names none of
 * them is not in the derived set at all, which is the hole the equality below
 * makes visible rather than closes.
 */
const READS_BYTES =
  /\b(Uint8Array|ArrayBuffer|ReadableStream|DOMParser|File|Blob)\b/;

function fileReaders(): string[] {
  return entries()
    .filter(([path]) => path.startsWith("lib/") && !path.endsWith(".d.ts"))
    .filter(([, source]) => READS_BYTES.test(withoutProse(source)))
    .map(([path]) => path)
    .sort();
}

/**
 * The readers there are today, which the derivation above has to reproduce.
 *
 * Both directions are the point. A reader added to `src/lib/` and not named
 * here fails, which is the prompt to ask whether it is one; a name deleted from
 * here fails too, which is the evasion that a plain inclusion list allows. That
 * evasion was measured on this file: removing two names left every test green.
 */
const FILE_READERS = [
  "lib/audiobook.ts",
  "lib/calibre.ts",
  "lib/cbz.ts",
  "lib/epub.ts",
  "lib/fb2.ts",
  "lib/fileReaders.ts",
  "lib/mobi.ts",
  "lib/opf.ts",
  "lib/pdf.ts",
  "lib/sqlite.ts",
  "lib/takeout.ts",
  "lib/zip.ts",
];

/**
 * The one network call a reader may make, written as the expression rather than
 * as a file on an exemption list.
 *
 * `sqlite.ts` fetches the WebAssembly asset Vite emitted, by the URL Vite
 * emitted, with no body: it carries nothing out and there is nowhere for a
 * member's database to go. Exempting the file would have exempted a second
 * `fetch` in it as well, which is the one this rule would need to catch.
 */
const ENGINE_FETCH = /fetch\(wasmUrl\)/g;
const ENGINE_READER = "lib/sqlite.ts";

/**
 * Where `wasmUrl` has to come from, asserted beside the exemption.
 *
 * The exemption strips an expression, and an expression names a binding rather
 * than a value: a local `const wasmUrl = "https://…" + btoa(theDatabase)` would
 * make an exfiltrating GET exempt by name. This pins the binding to the build
 * asset Vite emitted, which is the fact that makes the call carry nothing.
 */
const ENGINE_URL_IMPORT =
  'import wasmUrl from "sql.js/dist/sql-wasm-browser.wasm?url"';

/**
 * The ways out this can see, which are fewer than the ways out there are.
 *
 * Six names and one import shape: a reader that calls `fetch`, builds an
 * `XMLHttpRequest`, opens a `WebSocket`, beacons, packs a `FormData`, or imports
 * the generated client. That is every way anything under `lib/` sends **data
 * out** today, so the rule holds. It is not why the published claim holds.
 *
 * Both halves of that sentence are load bearing. Requests that carry nothing out
 * are made here and match no arm: `lib/fileReaders.ts` loads five modules with
 * `import()`, at eight sites, and `lib/sqlite.ts` fetches the wasm engine, which
 * is exempted below by its expression. And the scope is `lib/` rather than the
 * tree, because `api/mutator.ts` navigates on a lost session.
 *
 * **The exclusion is a request that spells none of them, and that set is open.**
 * `EventSource`, `import(url)`, an image `src`, a navigation, `postMessage` to a
 * worker and the service worker each reach the network without matching a
 * character of this. They are instances rather than the family, and the last is
 * not hypothetical: this app ships one, generated by workbox from
 * `vite.config.ts`, sitting between every module here and the network and
 * outside the glob above entirely. **An arm per spelling is not the fix**: it is
 * the shape this repository keeps paying for, and here it would make the
 * overclaim worse by looking thorough. Measured over the 430 modules under
 * `src/`, files rather than occurrences: four of the six names,
 * `XMLHttpRequest`, `WebSocket`, `sendBeacon` and `navigator.send`, match no
 * file at all, and one of those four is not a web API. `navigator.send` cannot
 * even match `navigator.sendBeacon`, because the trailing word boundary falls
 * between `d` and `B`. A real closure is a different instrument, one that denies
 * these modules the network, rather than a longer regex.
 *
 * **What the published claim rests on is the server, not this scan.** `README.md`
 * and `docs/featurelist.md` both tell a reader that a book file is read in their
 * browser and never uploaded, and what makes that true is that there is nowhere
 * to send one: no route accepts a book file, asserted as an equality over the
 * routes the app registers in `backend/tests/test_no_custody.py`. This rule is
 * the second line, and what it is good for is the accident: a reader that grows
 * a request, in the one directory where a member's own bytes are the only bytes
 * there are.
 */
const REACHES_THE_NETWORK =
  /\b(fetch|XMLHttpRequest|WebSocket|sendBeacon|FormData|navigator\.send)\b|from "[^"]*\/api\//;

describe("a member's book file cannot leave the browser", () => {
  it("keeps every reader out of reach of the network", () => {
    // The decision on the digital copies ticket is that no bytes reach the
    // server, and it is worth more as a structural property than as a
    // discipline: the reader modules hold the only `ArrayBuffer` of somebody's
    // book, so if none of them can reach the network, no arrangement of the
    // page above them can send one.
    //
    // A guard on the page instead would have to tell a book file from a cover
    // image, and the page legitimately sends the second. This one does not need
    // to, because it sits where only the first exists.
    const offenders = entries()
      .filter(([path]) => fileReaders().includes(path))
      .filter(([path, source]) => {
        const code = withoutProse(source);
        return REACHES_THE_NETWORK.test(
          path.endsWith(ENGINE_READER) ? code.replace(ENGINE_FETCH, "") : code,
        );
      })
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it("is watching every reader there is, and only those", () => {
    // The failure this test is for: a reader added, renamed, or quietly taken
    // off the list, and silently stopping being covered. Asserted as an
    // equality in both directions rather than as "every name resolves", which
    // a shortened list satisfies.
    expect(fileReaders()).toEqual(FILE_READERS);
  });

  it("makes the one exempt call, so the exemption is not silently unused", () => {
    // An exemption for an expression that no longer exists is an exemption
    // waiting to cover something else. This is the half that notices.
    const engine = entries().find(([path]) => path.endsWith(ENGINE_READER));
    expect(engine).toBeDefined();
    const code = withoutProse(engine![1]);
    expect(code.match(ENGINE_FETCH)).toHaveLength(1);
    expect(code).toContain(ENGINE_URL_IMPORT);
    // **The count, not a list of the ways a name can be rebound.** The import
    // existing is not the same as the name at the fetch site being it, and the
    // first attempt at this refused `const`, `let` and `var`, which is three
    // arms of an open set: a destructured `const { wasmUrl } = …` and a
    // parameter named `wasmUrl` both slip past and both shadow the import.
    // There are two occurrences today, the import and the fetch, so a third of
    // any spelling is what this refuses.
    expect(code.match(/\bwasmUrl\b/g)).toHaveLength(2);
  });

  it("keeps the picked file out of the value a request is built from", () => {
    // The draft builders are the seam between the reading path and the request
    // path, and the property is the parameter: each takes what was parsed, so a
    // member's book has nowhere to travel. Taking one would compile, would pass
    // every other test, and would put the bytes one spread away from a body.
    const offenders = draftBuilders()
      .filter(takesABook)
      .map((one) => `${one.path}: ${one.name ?? "an anonymous export"}`);

    expect(offenders).toEqual([]);
  });

  it("reads every draft builder the tree spells, wherever it sits", () => {
    // **Two instruments and no number.** The text finds every `draftFrom`
    // identifier the source spells, a declaration or a call alike; the walk
    // finds what is declared. A name spelled and not declared is a file the
    // walk did not reach, a parse that returned an empty program, or a glob
    // that matched nothing, and each of those arrives here as a disagreement
    // rather than as the rule above passing over an empty set.
    const spelled = new Set(
      entries().flatMap(([, source]) =>
        [...withoutProse(source).matchAll(/\bdraftFrom\w*/g)].map(
          (match) => match[0],
        ),
      ),
    );
    const declared = new Set(draftBuilders().map((one) => one.name));

    expect([...spelled].filter((name) => !declared.has(name))).toEqual([]);
    expect(spelled.size).toBeGreaterThan(1);
  });

  it("visits every module that annotates a draft as a return", () => {
    // The other half of the file set, and the half the arm above cannot hold: a
    // builder called something else is never spelled `draftFrom`, so narrowing
    // the walk's file filter would hide it with that arm green. This asks the
    // text where a draft is returned and requires the walk to have been in that
    // file. It exists because it was evaded: the filter narrowed to one module,
    // with a renamed builder written into another, passed every other arm here.
    const annotates = entries()
      .filter(([, source]) => ANNOTATES_A_DRAFT.test(withoutProse(source)))
      .map(([path]) => path);
    const visited = new Set(draftBuilders().map((one) => one.path));

    expect(annotates.filter((path) => !visited.has(path))).toEqual([]);
    expect(annotates.length).toBeGreaterThan(0);
  });

  it("reads a draft return in the spellings a builder writes it", () => {
    // **The pattern is driven rather than described**, because nothing else
    // drives it: it is the second instrument, so it can narrow until it matches
    // nothing and the arm above passes over an empty set. Its first draft
    // required `BookDraft` to be the first token after the colon, which an
    // async builder's `Promise<BookDraft>` walks straight past. Both critic
    // seats measured that independently, each with a diagonal differing in the
    // return spelling alone, which is why these are rows rather than a sentence.
    expect(ANNOTATES_A_DRAFT.test("): BookDraft {")).toBe(true);
    expect(ANNOTATES_A_DRAFT.test("): Promise<BookDraft> {")).toBe(true);
    expect(ANNOTATES_A_DRAFT.test("): null | BookDraft {")).toBe(true);
    expect(ANNOTATES_A_DRAFT.test("): Readonly<BookDraft> {")).toBe(true);
    expect(
      ANNOTATES_A_DRAFT.test("const make: (cover: File) => BookDraft = f;"),
    ).toBe(true);
    expect(ANNOTATES_A_DRAFT.test("): Request {")).toBe(false);
    expect(
      ANNOTATES_A_DRAFT.test("const f = (x: number) => makeBookDraft();"),
    ).toBe(false);
  });

  it("finds a builder by what it returns and not only by its name", () => {
    // The half that goes quiet without failing. Where the return arm stops
    // matching, a parser property renamed under it or a `BookDraft` reached
    // through an alias, this rule degrades to the name check it already was and
    // nothing goes red. Asserted as "at least one", not as the member that
    // satisfies it today, so it does not become a list to keep.
    expect(draftBuilders().filter((one) => !one.byName)).not.toHaveLength(0);
  });

  /**
   * What the derivation says about each shape, as a table.
   *
   * A table rather than a run of assertions in one test, so a row that stops
   * holding names itself: the run aborts at the first failure, and a mutation
   * that weakened two arms would be reported as one.
   *
   * **It drives `takesABook`, which is the predicate the rule above applies**,
   * rather than a second spelling of it. A table asserting its own copy cannot
   * see that copy diverge, and that is not hypothetical: narrowing the rule to
   * `File` alone left every row here green and admitted a `Blob`.
   *
   * The refused rows are evasions somebody ran rather than shapes somebody
   * imagined. An arrow, and a second bracket in a parameter list, are what
   * `tests/pages/ScanPage/types.test.ts` records against the signature regex
   * this replaced. An overload set and an anonymous default export are what the
   * walk that replaced it admitted on its first draft.
   */
  const SHAPES: [string, string, boolean][] = [
    [
      "a declaration taking a File is refused",
      "export function draftFromX(file: File): BookDraft {}",
      true,
    ],
    [
      "an arrow assigned to a const is refused",
      "export const draftFromX = (file: File): BookDraft => 0;",
      true,
    ],
    [
      "an overload is refused for what it declares, not what it implements",
      "export function draftFromX(file: File): BookDraft;\n" +
        "export function draftFromX(input: unknown): BookDraft {}",
      true,
    ],
    [
      "an anonymous default export is refused",
      "export default function (file: File): BookDraft {}",
      true,
    ],
    [
      "a callable held as an object property is refused",
      "export const built = { draftFromX: (file: File) => 0 };",
      true,
    ],
    [
      "a File behind two other parameters is refused",
      "export function draftFromX(c: NameClues, done: () => void, f: File) {}",
      true,
    ],
    [
      "a builder renamed out of the family is refused for its return",
      "function make(cover: File): BookDraft {}",
      true,
    ],
    [
      "an array view is refused, and not only a File",
      "export function draftFromX(bytes: Uint8Array): BookDraft {}",
      true,
    ],
    [
      "a buffer view sharing no name with an array is refused",
      "export function draftFromX(bytes: DataView): BookDraft {}",
      true,
    ],
    [
      "a Blob is refused, which is the pair this rule was written for",
      "export function draftFromX(bytes: Blob): BookDraft {}",
      true,
    ],
    [
      "so is what a Blob is built out of, which a bare name admitted",
      "export function draftFromX(bytes: BlobPart): BookDraft {}",
      true,
    ],
    // `BufferSource` and not `ArrayBufferView`, which reads like the row for
    // this arm and is not: everything spelled `*Array*` is caught by the array
    // arm whether the buffer arm is there or not, so a row naming one leaves
    // the buffer arm undriven. Measured by the design seat, which removed that
    // arm and got a green suite.
    [
      "a buffer named without the word array is refused",
      "export function draftFromX(bytes: BufferSource): BookDraft {}",
      true,
    ],
    [
      "bytes that arrive a chunk at a time are refused",
      "export function draftFromX(bytes: ReadableStream): BookDraft {}",
      true,
    ],
    [
      "a handle onto a file the member picked is refused",
      "export function draftFromX(picked: FileList): BookDraft {}",
      true,
    ],
    [
      "a builder taking the parsed record is admitted",
      "export function draftFromX(record: FileMetadata): BookDraft {}",
      false,
    ],
    [
      "a parameter merely named for an array is admitted: a name is not a type",
      "export function draftFromX(bookArray: NameClues): BookDraft {}",
      false,
    ],
    [
      "a function that builds no draft is admitted",
      "export function elsewhere(file: File): Request {}",
      false,
    ],
  ];

  it.each(SHAPES)("%s", (_label, source, refused) => {
    expect(buildersIn(source, "ts").some(takesABook)).toBe(refused);
  });

  /**
   * The one exception list `CARRIES_A_BOOK` carries, held against the tree.
   *
   * **The `File` half of that pattern refuses by default and admits by name**,
   * because this repository's own types are spelled the way the DOM spells its
   * handles and nothing in the text tells the two apart. That direction is the
   * safe one and it has a cost: a new `File`-prefixed type of this tree's own
   * is refused until somebody adds it. This is what makes that arrive as a
   * failure naming the type rather than as a builder guard nobody can explain.
   *
   * **Both sides are asserted.** A pattern that stopped matching `File` at all
   * would empty the refused set while leaving an admitted set that still read
   * correctly, so the admitted half alone cannot see the rule switch off.
   *
   * Comments are stripped first: `Files` and `FileResponse` appear in this
   * tree in prose only, and a census over the raw text asks somebody to
   * classify a word in a sentence.
   */
  it("sorts every File name the source spells onto one side or the other", () => {
    const names = new Set<string>();
    for (const [, source] of entries())
      for (const name of withoutProse(source).match(/\bFile\w*\b/g) ?? [])
        names.add(name);

    const sorted = [...names].sort();
    expect(sorted.filter((name) => CARRIES_A_BOOK.test(name))).toEqual([
      // The type itself.
      "File",
      // This tree declares its own, in `lib/fileReaders.ts`, and it is
      // `(file: Blob) => Promise<FileReading>`. Refusing it is the point.
      "FileReader",
    ]);
    expect(sorted.filter((name) => !CARRIES_A_BOOK.test(name))).toEqual([
      // What a decoder reports about a file, and how it is named. No bytes.
      "FileFailure",
      "FileIdentifier",
      "FileMetadata",
      "FileNaming",
      // The picker component, and its props.
      "FilePickPanel",
      "FilePickPanelProps",
      // The other half of `FileReader`: what one resolves to.
      "FileReading",
    ]);
  });

  /**
   * No exemption covers a name the tree does not spell.
   *
   * **A dead exemption is one waiting to cover something**, and this one had
   * one: `FileResponse` was exempted and occurs in `src/` only inside a
   * docstring, which the census above strips, so the census could not see it
   * was dead. The backend returns a `FileResponse` from `routers/covers.py`,
   * so a generated model of that name would have arrived already admitted.
   * Both critic seats found it independently, which is what that costs.
   *
   * **Read out of the pattern rather than restated**, so this cannot pass by
   * describing a lookahead the predicate no longer has.
   *
   * A prefix, not an equality: `PickPanel` exempts `FilePickPanelProps` too,
   * and an exemption covering a name by prefix is doing its job.
   */
  it("exempts no File name the tree has stopped spelling", () => {
    const lookahead = /File\(\?!([^)]*)\)/.exec(CARRIES_A_BOOK.source);
    expect(lookahead).not.toBeNull();
    const exemptions = lookahead![1]!.split("|");
    expect(exemptions.length).toBeGreaterThan(0);

    const spelled = new Set<string>();
    for (const [, source] of entries())
      for (const name of withoutProse(source).match(/\bFile\w*\b/g) ?? [])
        spelled.add(name);

    const dead = exemptions.filter(
      (exemption) =>
        ![...spelled].some((name) => name.startsWith(`File${exemption}`)),
    );

    expect(dead).toEqual([]);
  });
});

/**
 * Where the text says a draft is returned.
 *
 * **The walk's own test for the return derivation, spelled for source text**: a
 * `BookDraft` anywhere in the annotation rather than the whole of it, because
 * two instruments disagreeing about what a member is leave the gap between them
 * unheld. That gap was measured twice, each time as a diagonal differing in the
 * return spelling alone: the first draft asked for the bare type and missed
 * `Promise<BookDraft>`, the second read only the colon and missed
 * `(cover: File) => BookDraft`, which is a callable type and a member.
 *
 * **Both introducers, and there are two**: TypeScript writes a return
 * annotation after `:` or after `=>`, so the alternation is closed and a third
 * arm is not waiting to be found. Measured over the 430 modules under `src/`
 * with comments stripped: this, the colon only form and a newline bounded
 * variant all select the same one module, so the widest of them requires no
 * extra visit today.
 *
 * **The class stops at `;`, `{` and `=` and not at a newline**, so a wrapped
 * annotation is still seen. The cost is that a match can reach from one line
 * into a mention below it, and the direction is deliberate: an extra file in
 * this set demands a visit that is not needed, which fails loudly, where a file
 * missing from it is a builder nothing holds and fails not at all.
 *
 * **What the `=>` arm newly over-matches is an arrow body, not a name.** After
 * an arrow the class runs to the next `;`, `{` or `=`, so a single expression
 * body naming the bare type reads here as a return annotation:
 * `const asDraft = (r: FileMetadata) => coerceRecord(r) as BookDraft;` puts
 * module in this set. Measured by appending that line to `lib/fb2.ts` with the
 * file filter left alone: `SUITE EXIT: 1`, this arm naming a module that
 * declares no builder. It fires on nothing in the tree today, and it is the
 * loud direction, so it is a cost rather than a defect. **It is written down
 * for whoever it fires on**: told the cost is a name prefix, they would read a
 * failing cast as the pattern being wrong and narrow it, and narrowing it is
 * the regression found twice already here. The negative row in the fixture
 * below is about the word boundaries and is not this case.
 *
 * **Stopping at `{` is also what it does not see**: an inline object return,
 * `): { draft: BookDraft; warnings: string[] }`, is outside this. The rule
 * still refuses such a builder, since the walk reads the whole annotation; what
 * is not held for it is the file set, and only where somebody has also narrowed
 * the filter. A bounded run of any character would reach it and buys a number
 * nobody can re-derive, and a third stop character is the enumeration this file
 * argues against everywhere else.
 */
const ANNOTATES_A_DRAFT = /\)\s*(?::|=>)[^;{=]*\bBookDraft\b/;

/** One function that builds a draft: where it is, and what it takes. */
type DraftBuilder = {
  path: string;
  /** As bound, or `null` where nothing binds it. */
  name: string | null;
  /** Found by its name rather than by its return type. */
  byName: boolean;
  /** Each parameter as it is written, annotation included. */
  params: string[];
};

/**
 * Does this builder take a member's book?
 *
 * **One predicate, used by the rule and by the table that measures the rule.**
 * Spelled twice they drift, and the drift is silent in the direction that
 * matters: narrowed to `File` in the rule and left whole in the table, a
 * builder taking a `Blob` is admitted with every arm green.
 */
function takesABook(one: DraftBuilder): boolean {
  return one.params.some((param) => CARRIES_A_BOOK.test(param));
}

/**
 * Every draft builder in one source, found by two derivations.
 *
 * **Two, because either alone is beaten by the rename the other sees.** A name
 * beginning `draftFrom` is the family as it is written today; an annotated
 * return of `BookDraft` is what a member of it *is*, and that arm is what makes
 * a builder called something else a member. It is also the only thing that
 * makes an anonymous one a member, which is what
 * `export default function (file: File): BookDraft` established.
 *
 * **A callable is anything carrying a `params` array**, which is the whole
 * family: a declaration, an expression, an arrow, a method, an accessor, an
 * overload signature and a function type. That is the structural test `defers`
 * makes further down this file, and it replaces two named node kinds that
 * between them saw neither an overload nor an anonymous export.
 *
 * **A name is the `id` or the `key` of the callable or of the node above it**,
 * which is every field this AST binds a name in, rather than a list of the node
 * kinds that do the binding. A callable bound by neither is anonymous, and is a
 * member only by what it returns.
 *
 * **Parsed rather than matched, and the parameter is taken as source text.**
 * The shape is what matters and not how the line is spelled, and a default
 * value with a bracket in it truncates a captured parameter list without
 * changing how many matches there are. Both are evasions this tree measured
 * against the regex that stood here.
 *
 * **The exclusions, which are what this does not close.** A builder both
 * renamed and left with no return annotation is in neither derivation. A
 * parameter typed through an alias reads as the alias, whether that is the type
 * itself (`type Picked = File`) or an object holding one (`{ file: File }`).
 * And the whole rule is about a parameter: a builder reaching a file through a
 * closure or a module global takes nothing and is invisible here, which is why
 * `tests/pages/ScanPage/types.test.ts` holds the stronger rule, every mention
 * in the module rather than every parameter, over the one file the family lives
 * in today.
 */
function buildersIn(source: string, lang: "ts" | "tsx"): DraftBuilder[] {
  const found: DraftBuilder[] = [];
  const slice = (node: Node): string =>
    source.slice(Number(node.start), Number(node.end));
  const bound = (node: Node | null): string | null => {
    for (const field of ["id", "key"] as const) {
      const named = node?.[field];
      if (isNode(named) && named.type === "Identifier") return text(named.name);
    }
    return null;
  };
  const consider = (node: Node, parent: Node | null): void => {
    if (!Array.isArray(node.params)) return;
    const name = bound(node) ?? bound(parent);
    const byName = name !== null && name.startsWith("draftFrom");
    const returns = isNode(node.returnType) ? slice(node.returnType) : "";
    if (!byName && !/\bBookDraft\b/.test(returns)) return;
    found.push({
      path: "",
      name,
      byName,
      params: (node.params as unknown[]).filter(isNode).map(slice),
    });
  };
  const walk = (value: unknown, parent: Node | null): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item, parent);
      return;
    }
    if (!isNode(value)) return;
    consider(value, parent);
    for (const key of Object.keys(value)) walk(value[key], value);
  };
  walk(parseAst(source, { lang }), null);
  return found;
}

/**
 * The draft builders in the tree, which is every module and not one file.
 *
 * **The file set is the exclusion this fix was for.** This read
 * `pages/ScanPage/types.ts` alone, found by `endsWith`, while its comment
 * claimed the family: a builder written in any other module was outside it with
 * nothing red. Every builder sits in that module today, so the wider read
 * refuses nothing extra now and needs no revisiting when the family moves or
 * grows a second home.
 *
 * Files are skipped rather than declarations, and by the identifiers a builder
 * cannot be declared without spelling.
 *
 * **What holds the file set, measured rather than claimed.** Narrowing this
 * filter back passes on today's tree, since every builder is in that module.
 * With one written elsewhere it fails "reads every draft builder the tree
 * spells" where that builder is named for the family, and "visits every module
 * that annotates a draft as a return" where it is not. **One arm per
 * derivation**, each the text instrument for one of the two things that make a
 * callable a member, `ANNOTATES_A_DRAFT` being the second. What holds is only
 * what those instruments read, which is why the second says which spellings of
 * a return it sees and which it does not: a member written in a spelling it
 * misses still fails the rule itself, and does not hold the file set. The first
 * was the whole answer until a renamed builder in another module passed every
 * arm, and the second missed an async return, then a callable type.
 */
function draftBuilders(): DraftBuilder[] {
  return entries()
    .filter(
      ([, source]) =>
        source.includes("draftFrom") || source.includes("BookDraft"),
    )
    .flatMap(([path, source]) =>
      buildersIn(source, path.endsWith(".tsx") ? "tsx" : "ts").map((one) => ({
        ...one,
        path,
      })),
    );
}

/** The source with comments removed, so a rule cannot be satisfied by prose. */
function withoutProse(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");
}

function sessionWrites(code: string): number {
  return [...code.matchAll(/\b(set|clear)Session\s*\(/g)].length;
}

function cacheClears(code: string): number {
  return [...code.matchAll(/queryClient\.clear\(\)/g)].length;
}

/** The one module that owns the session, and the one that defines it. */
const SESSION_OWNER = "pages/hooks.ts";
const SESSION_DEFINITION = "api/mutator.ts";

describe("an identity change drops the cache with it", () => {
  it("is decided in one module, not at each call site", () => {
    // The instance of this that mattered was the whole shelf. React Query's
    // client is built once per page load and outlives a sign-out, "Switch
    // account" is a router link rather than a navigation, switching into a
    // test account is a button in Settings, and under proxy auth the identity
    // can change with nothing happening in this app at all. `visible_to()` is
    // "public or mine", so the next member in was handed the previous one's
    // private books back under identical keys, with nothing refetching for
    // another thirty seconds.
    //
    // `useSession` now clears on a change of account id, so every path gets
    // it, including the proxy one, which has no call site here to add a clear
    // to. What this rule protects is that arrangement: a component that writes
    // the session itself would change the identity without going past the
    // hook watching it, and no effect can cover that.
    //
    // This replaced a count of `queryClient.clear()` against a count of
    // session writes per file. That was the right question while three call
    // sites each had to remember; against one effect keyed on the identity it
    // asks for a redundant call per writer, which is a rule that teaches the
    // wrong lesson to whoever adds the fourth path.
    //
    // Said out loud so nobody trusts it as total: this counts spellings, not
    // calls. A module that writes `localStorage` itself, or through an alias,
    // is outside it. No regex closes that gap: it is the distance between a
    // concept and the characters it is usually written with.
    const offenders = entries()
      .filter(([path]) => path !== SESSION_DEFINITION && path !== SESSION_OWNER)
      .map(([path, source]) => [path, withoutProse(source)] as const)
      .filter(([, code]) => sessionWrites(code) > 0)
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it("still clears the cache somewhere in that module", () => {
    // A tripwire, not the proof: what the clearing actually does is asserted
    // in tests/pages/hooks.test.ts, per mode and per path. This is here so
    // that deleting the mechanism outright cannot be a silent diff.
    const owner = entries().find(([path]) => path === SESSION_OWNER);
    expect(owner).toBeDefined();
    expect(cacheClears(withoutProse(owner![1]))).toBeGreaterThan(0);
  });

  it("is watching something", () => {
    // A rule whose subject has been renamed passes by matching nothing.
    const writers = entries().filter(
      ([, source]) => sessionWrites(withoutProse(source)) > 0,
    );
    expect(writers.length).toBeGreaterThan(1);
  });
});

/** The one module allowed to drop the whole cache. */
const INVALIDATION_OWNER = "api/invalidate.ts";

describe("a write names what it made stale", () => {
  it("does not drop the whole cache at the call site", () => {
    // `queryClient.invalidateQueries()` with no key refetches every mounted
    // query on the page, whatever it is about and whatever staleTime it was
    // given. Eleven call sites did it. Measured on 2026-08-26: ten requests on
    // a book's page for deleting a curated tag, where five are about the tag,
    // and on the scan page a refetch of `/api/books/search`, which is a billed
    // Google Books call the query's own staleTime exists to avoid re-spending.
    //
    // Two writes still earn the whole cache and both go through
    // `invalidate.everything()`, where the reason is written down: restoring a
    // backup, and merging duplicates. The rule is that the decision is made in
    // the module that knows what each group covers, not at a call site that
    // has to remember.
    //
    // Said out loud so nobody trusts it as total: this counts a spelling. A
    // call site holding a `QueryClient` under another name, or building an
    // empty filter object, is outside it.
    const offenders = entries()
      .filter(([path]) => path !== INVALIDATION_OWNER)
      .map(([path, source]) => [path, withoutProse(source)] as const)
      .filter(([, code]) => /invalidateQueries\(\s*\)/.test(code))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it("drops the whole cache from exactly two call sites", () => {
    // `everything()` is the same keyless invalidate with a better name, and the
    // rule above permits it anywhere. Its docstring says "two callers, and both
    // earn it", which is a count, and a count with no enforcement is how the
    // group whose whole point is being rare stops being rare.
    //
    // Both are named here rather than counted, because what makes them correct
    // is what they do and not how many they are: a backup restore replaces
    // every row in the database including the signed-in member's, and merging
    // duplicates moves notes, quotes, progress and reading statuses between
    // books with no account in the response of what moved. A third caller is a
    // decision somebody has to make, in this file, rather than a line in a
    // diff.
    const callers = entries()
      .map(([path, source]) => [path, withoutProse(source)] as const)
      .filter(([, code]) => /\.everything\s*\(/.test(code))
      .map(([path]) => path)
      .sort();

    expect(callers).toEqual([
      "pages/DuplicatesPage/hooks.ts",
      "pages/SettingsPage/DataSettingsPage/hooks.ts",
    ]);
  });

  it("still has an owner that does it", () => {
    // A rule whose subject has been renamed passes by matching nothing.
    const owner = entries().find(([path]) => path === INVALIDATION_OWNER);
    expect(owner).toBeDefined();
    expect(withoutProse(owner![1])).toMatch(/invalidateQueries\(\s*\)/);
  });
});

describe("a dark hover state is stated, never inherited", () => {
  it("appears nowhere in the source", () => {
    // Every ramp runs the other way in the dark, so a hover written once is
    // legible at rest and illegible while pointed at. Twelve sites were written
    // that way: `text-accent-700 hover:text-accent-800` clears the 4.5 text
    // floor on a light card and fails it on every dark one, because
    // `accent-800` in a dark ramp is nearly the card itself.
    //
    // **No band is quoted here, deliberately.** The figure is recomputed by
    // `tests/theme/palettes.test.ts::the hover a dark ramp makes illegible`,
    // which is also where the reason it is not written down lives.
    //
    // This rule ships with no exemption list, which is a claim rather than an
    // omission: all twelve were repaired in the same change, so there is
    // nothing to exempt. The alternative shape was considered and rejected for
    // that reason. A frozen allowlist is what this repository does when a rule
    // arrives before its repair (`api/mutator.ts` in the session rule,
    // `.field:disabled` in the paper rule), and a list of twelve would have
    // been a list of twelve things nobody was going to come back to.
    //
    // Only `hover:text-`, and not `hover:bg-` or `hover:border-`. A background
    // or a border that is a shade off in the dark is a flat surface that looks
    // slightly wrong; text that is a shade off is text nobody can read, and
    // WCAG 1.4.3 has a number for the second and not the first.
    //
    // Concatenated class strings are joined before matching. Four of these are
    // written as `"…light…" + "…dark…"` across a line break, and a rule that
    // read the halves separately would report all four as offenders and teach
    // the next person to work around it. Counted 2026-08-24, by joining each
    // concatenation chain and asking which put the plain hover and the dark one
    // in different segments: `components/Button.tsx`,
    // `app/components/NavBar.tsx`, `pages/Home/components/BookFilters.tsx`,
    // `pages/SettingsPage/AboutSettingsPage/components/AboutBadges.tsx`. This comment said "two"
    // while there were three, which is why the count is now dated and the files
    // named: a claim that there are exactly N is worth nothing without them.
    //
    // Said out loud so nobody trusts it as total: the unit is the string
    // literal, not the utility. A literal carrying two unqualified hover
    // states and one `dark:hover:text-` satisfies this rule while leaving one
    // of them unrepaired. No such site exists, and every site in the tree pairs
    // one hover with one dark hover, so pinning that shape would assert today's
    // spelling rather than the rule.
    const offenders = entries().flatMap(([path, source]) =>
      [
        ...source
          .replace(/["`]\s*\+\s*["`]/g, " ")
          .matchAll(/["`]([^"`]*hover:text-[^"`]*)["`]/g),
      ]
        .filter(([, classes]) => !/dark:hover:text-/.test(classes!))
        .flatMap(([, classes]) => [
          ...classes!.matchAll(
            /(?<![-\w:])hover:text-(?:paper|accent|bloom|danger)-\d+/g,
          ),
        ])
        .map((match) => `${path}: ${match[0]}`),
    );

    expect(offenders).toEqual([]);
  });

  it("is watching something", () => {
    // A rule whose subject has been renamed passes by matching nothing. There
    // are dark hover states in this tree; the rule is that they are all stated.
    const stated = entries().filter(([, source]) =>
      /dark:hover:text-/.test(source),
    );
    expect(stated.length).toBeGreaterThan(10);
  });
});

/** A background painted with the light-only top surface, at any variant. */
const LIGHT_FILL = /(?<![-\w])(?:[a-z-]+:)*bg-paper-0(?:\/\d+)?(?![-\w])/;
const DARK_FILL = /(?<![-\w])dark:(?:[a-z-]+:)*bg-/;
const DARK_INK = /(?<![-\w])dark:(?:[a-z-]+:)*text-/;

/** The class strings in one module, with concatenation chains joined first. */
function classStrings(source: string): string[] {
  return [
    ...source.replace(/["`]\s*\+\s*["`]/g, " ").matchAll(/["`]([^"`]*)["`]/g),
  ].map((match) => match[1]!);
}

describe("a dark ink never lands on the light-only surface", () => {
  it("appears nowhere in the source", () => {
    // `paper-0` is the top surface, and it is the one paper token no palette
    // and no mode redefines: `index.css` sets it once and `:root.dark` leaves
    // it alone, which is why every dark call site in this tree spells
    // `dark:bg-paper-900` rather than relying on the token to flip. So a
    // literal that paints `bg-paper-0`, states a `dark:text-` and states no
    // dark background has moved the ink into the dark ramp and left the pill
    // in the light one.
    //
    // That is not a shade being slightly off. It is a light label on a white
    // pill: the two on the book detail cover measured 1.26:1 for
    // `text-paper-200` on `paper-0`, against the 4.5:1 WCAG 1.4.3 asks, and
    // they had read that way since they were written because nothing looks
    // wrong in the diff. Both now use the shared Button, whose `secondary`
    // variant states the fill and the foreground together: 14.25:1 light and
    // 15.79:1 dark.
    //
    // Both halves of the trigger matter. A literal with no `dark:text-` at all
    // inherits its ink from a parent that has one, and 42 of the 44 literals
    // painting this token do exactly that, correctly. The offence is stating
    // one half of the pair and not the other, which is the same defect the
    // dark hover rule above exists for, one property along.
    //
    // Variant prefixes are matched rather than assumed away: `PublicShell`'s
    // skip link is `focus:bg-paper-0` with `dark:focus:bg-paper-900`, and a
    // rule anchored on the bare spellings would report it.
    //
    // Concatenation chains are joined for the same reason the hover rule joins
    // them: the light half and the dark half are routinely written in
    // different segments across a line break.
    const offenders = entries().flatMap(([path, source]) =>
      classStrings(source)
        .filter(
          (classes) =>
            LIGHT_FILL.test(classes) &&
            DARK_INK.test(classes) &&
            !DARK_FILL.test(classes),
        )
        .map((classes) => `${path}: ${classes}`),
    );

    expect(offenders).toEqual([]);
  });

  it("is watching something", () => {
    // A rule whose subject was renamed passes by matching nothing. Counted
    // 2026-08-29: 44 literals in the tree paint this token.
    const painted = entries().flatMap(([, source]) =>
      classStrings(source).filter((classes) => LIGHT_FILL.test(classes)),
    );

    expect(painted.length).toBeGreaterThan(30);
  });

  it("reports the shapes it exists for", () => {
    const offends = (classes: string) =>
      LIGHT_FILL.test(classes) &&
      DARK_INK.test(classes) &&
      !DARK_FILL.test(classes);

    // The two it was written for, verbatim.
    expect(
      offends("bg-paper-0/90 shadow-sm text-paper-700 dark:text-paper-200"),
    ).toBe(true);
    expect(offends("bg-paper-0 text-paper-700 dark:text-paper-200")).toBe(true);
    // Stating the pair is the fix, at any variant depth.
    expect(
      offends(
        "bg-paper-0 dark:bg-paper-900 text-paper-800 dark:text-paper-100",
      ),
    ).toBe(false);
    expect(
      offends(
        "focus:bg-paper-0 dark:focus:bg-paper-900 dark:focus:text-paper-100",
      ),
    ).toBe(false);
    // Inheriting the ink is correct and is what most of the tree does.
    expect(offends("bg-paper-0 border border-paper-200")).toBe(false);
    // Neither a longer token nor a longer ramp step is this surface.
    expect(offends("bg-paper-0-something dark:text-paper-200")).toBe(false);
    expect(offends("bg-paper-900 dark:text-paper-200")).toBe(false);
  });
});

describe("no dash is used as punctuation", () => {
  it("appears nowhere in the source", () => {
    // House style. The message catalogues have their own test; this covers
    // comments, docstrings and anything else with words in it. A dash is easy
    // to paste in and invisible when skimming.
    const offenders = entries()
      .filter(([, source]) => /[–—]/.test(source))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});

describe("a tag reaches a reader through tagName", () => {
  /** The one module allowed to read a tag's stored name. */
  const TAG_NAME_OWNER = "i18n/tagNames.ts";

  it("is not printed from the stored name at a call site", () => {
    // `tags.name` is the **English** name, and only the English name: the
    // German one is looked up by `tags.key` in `i18n/tagNames.ts`. A component
    // that prints `tag.name` therefore prints English into a German page, with
    // nothing failing and nothing to see in a diff. Counted 2026-08-27 against
    // the tree this rule arrived in: **9** reads in 6 files, every one of them
    // a tag on screen, which is why this is a rule rather than a habit.
    //
    // Said out loud so nobody trusts it as total: this counts a spelling. It
    // matches an identifier whose name ends in `tag` or `tags`, which is what
    // every site in this tree calls one, and a site that named its variable
    // `chip` or destructured `{ name }` off a `TagOut` would walk past it. No
    // regex closes that gap: it is the distance between a concept and the
    // characters it is usually written with.
    const offenders = entries()
      .filter(([path]) => path !== TAG_NAME_OWNER)
      .map(([path, source]) => [path, withoutProse(source)] as const)
      .flatMap(([path, code]) =>
        [...code.matchAll(/\b\w*[Tt]ags?\.name\b/g)].map(
          (match) => `${path}: ${match[0]}`,
        ),
      );

    expect(offenders).toEqual([]);
  });

  it("is watching something", () => {
    // A rule whose subject has been renamed passes by matching nothing. There
    // are tag names on screen in this tree; the rule is that every one of them
    // goes through the function.
    const callers = entries().filter(
      ([path, source]) =>
        path !== TAG_NAME_OWNER && /\btagName\(/.test(withoutProse(source)),
    );

    expect(callers.length).toBeGreaterThan(4);
  });
});

describe("no fixture or string carries an address outside reserved space", () => {
  // The frontend half of
  // `backend/tests/test_house_rules.py::TestNoFixtureLooksLikeACredential`.
  // That arm walks the backend test tree only, and its own reason for existing
  // is that **both** trees are published: this repository mirrors `src/`,
  // `tests/` and `docs/` to public GitHub. `src/i18n/en.ts` ships a placeholder
  // address in published source, which the backend rule cannot see at all.
  //
  // RFC 2606 reserves `example.com`, `example.net` and `example.org`, and RFC
  // 6761 the `.test`, `.example`, `.invalid` and `.localhost` names. Anything
  // outside them is registrable, and a stranger reading the mirror cannot tell
  // a placeholder from somebody's real mailbox.
  const RESERVED = [
    "example.com",
    "example.net",
    "example.org",
    "test",
    "example",
    "invalid",
    "localhost",
  ];

  // A label boundary, not a suffix. The backend arm shipped for one round
  // comparing with `endsWith` against bare names, which accepted
  // `notexample.com`, `myexample.org` and `fakeexample.net`.
  const isReserved = (domain: string) =>
    RESERVED.some((base) => domain === base || domain.endsWith(`.${base}`));

  // Deliberately looser than any address validator: this looks for what a
  // reader would take for an address, and nobody triaging the mirror runs our
  // rules over it first.
  const ADDRESS = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;

  const TESTS = import.meta.glob("./**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  // This file writes the shapes down in order to forbid them, so it is filtered
  // out. **Measured: today that filter removes nothing**, because Vite excludes
  // the importing module from its own `import.meta.glob`. A probe run from a
  // sibling file saw `./houseRules.test.ts` among 131 keys; run from here it is
  // absent. The filter stays because it is one line and it is what keeps the
  // rule working if that ever changes, and the assertion below pins the fact so
  // that nobody reads the filter as evidence of something it is not doing.
  const SELF = "./houseRules.test.ts";

  function everything(): [string, string][] {
    return [
      ...entries(),
      ...Object.entries(TESTS)
        .filter(([path]) => path !== SELF)
        .map(([path, source]): [string, string] => [
          path.replace("./", "tests/"),
          source,
        ]),
    ];
  }

  it("finds none", () => {
    const offenders = everything().flatMap(([path, source]) =>
      source.split("\n").flatMap((line, index) =>
        [...line.matchAll(ADDRESS)]
          .map((match) => match[0])
          .filter(
            (address) => !isReserved(address.split("@")[1]!.toLowerCase()),
          )
          .map((address) => `${path}:${index + 1} (${address})`),
      ),
    );

    expect(offenders).toEqual([]);
  });

  it("reads both trees, not just one", () => {
    // The backend arm walks one tree while its docstring named two, which is
    // why this one exists. A glob that matched nothing would make the rule
    // above pass forever.
    const paths = everything().map(([path]) => path);

    expect(paths.some((path) => path.startsWith("tests/"))).toBe(true);
    expect(paths.some((path) => path.startsWith("i18n/"))).toBe(true);
  });

  it("is not scanning itself, and the exclusion above is not what stops it", () => {
    // Pointing `SELF` at a name that does not exist changes nothing, which is
    // how this was found: Vite already keeps the importing module out of its
    // own glob. Pinned rather than left implicit, because if that behaviour
    // changes the honest failure is this line saying so, not the rule above
    // failing on this file's own deliberately unreserved fixture.
    expect(Object.keys(TESTS)).not.toContain(SELF);
  });

  it("reports the shapes it exists for", () => {
    expect(isReserved("mail.example.org")).toBe(true);
    expect(isReserved("example.org")).toBe(true);
    expect(isReserved("anything.invalid")).toBe(true);
    // The three a bare suffix comparison lets through.
    expect(isReserved("notexample.com")).toBe(false);
    expect(isReserved("myexample.org")).toBe(false);
    expect(isReserved("fakeexample.net")).toBe(false);
    expect(isReserved("gmail.com")).toBe(false);

    const found = [
      ..."write to kim.jones@gmail.com or sam@example.org".matchAll(ADDRESS),
    ].map((match) => match[0]);
    expect(found).toEqual(["kim.jones@gmail.com", "sam@example.org"]);
  });
});

// The three names, and only the names: where the receiver is and how the call
// is spelled across lines are the parser's problem now. Nothing here is an
// inclusion list left to go stale, because `covers every vitest api that
// replaces a module` builds the set it must contain from `vi` at run time.
const REPLACES_A_MODULE = /^(?:mock|doMock|importMock)$/;

/**
 * Does this source call a vitest api that replaces a module?
 *
 * **Parsed, not matched, because a comment is not a line shape.** This was a
 * filter dropping lines beginning `//`, `*` or `/*` and a regex over what was
 * left, which is a second parser for a language whose comments do not begin
 * lines: a call after code on a line ending in a trailing comment, and a call
 * inside a block comment whose own line carries no leading marker, were both
 * reported. `parseAst` is what the decoder rule at the end of this file already
 * reads its sources with.
 *
 * **`withoutProse` further down this file is still a regex stripper**, and this
 * did not remove it: fourteen rules read it, including the census above. So the
 * claim is narrower than "one instrument in the file" and is worth stating
 * exactly, because the broader one is what a reader would assume: what went is
 * `codeOnly`, which had one consumer, this rule.
 *
 * **What the swap gave up, which is the question to ask of a replacement.** The
 * matcher saw a call spelled inside a string literal and this does not, because
 * a literal is not a call expression. Nothing executes one, so what is lost is
 * a false positive: it is why this file had to assemble the spelling out of two
 * pieces to escape its own rule, and why it no longer does. The fixtures below
 * are ordinary literals now, and the file stays inside the rule by
 * construction rather than by hiding from it.
 *
 * **What it newly refuses is a source that does not parse.** The matcher
 * returned something for any text at all. Measured across the 618 modules under
 * `tests/` and `src/`: every one parses, and both instruments report the same
 * empty offender set. `parses every file it reads` below is the arm that keeps
 * that true, because a file this throws on takes the rule down with it rather
 * than being skipped.
 *
 * **The receiver is still `vi`, and that is a choice rather than a limit of the
 * instrument.** `v.mock(` after `import { vi as v }`, a destructured `mock` and
 * a call through a saved reference all pass, as they did before; the rule is a
 * tripwire on the idiomatic form, not a type checker. `vi["mock"]` is the one
 * of the four the parser closes for free, since a computed member carries the
 * name as a literal and reading it is not another arm.
 *
 * `typescript` is not the parser to reach for, and that was checked rather than
 * assumed: at 7.x it is the native compiler and exposes no `createSourceFile`
 * at all (it is `undefined` at runtime).
 */
function replacesAModule(source: string, lang: "ts" | "tsx"): boolean {
  let found = false;
  const named = (node: Node): string | null => {
    // An identifier after a dot, or the literal inside brackets. Both are the
    // name being called, and neither is a spelling this has to anticipate.
    const property = node.property;
    if (!isNode(property)) return null;
    return (
      text(property.name) ??
      (typeof property.value === "string" ? property.value : null)
    );
  };
  /**
   * The receiver, by its rightmost name.
   *
   * **`globalThis.vi.mock()` is the same call**, and `vite.config.ts` sets
   * `globals: true`, so `globalThis.vi === vi` in this suite. Reading only an
   * identifier missed it, and the regex this replaced did not: that was a
   * spelling the swap gave up, found by the security seat, and it is not the
   * false positive the paragraph above talks about. Rightmost name rather than
   * an arm for `globalThis` and another for `window`, which is the same rule
   * already applied to the property.
   */
  const receiver = (node: Node): string | null =>
    text(node.name) ?? named(node);
  const walk = (value: unknown): void => {
    if (found) return;
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (!isNode(value)) return;
    const callee = value.callee;
    if (
      value.type === "CallExpression" &&
      isNode(callee) &&
      callee.type === "MemberExpression" &&
      isNode(callee.object) &&
      receiver(callee.object as Node) === "vi" &&
      REPLACES_A_MODULE.test(named(callee) ?? "")
    ) {
      found = true;
      return;
    }
    for (const key of Object.keys(value)) walk(value[key]);
  };
  walk(parseAst(source, { lang }));
  return found;
}

/** What a path says about how to parse it. */
function langOf(path: string): "ts" | "tsx" {
  return path.endsWith(".tsx") ? "tsx" : "ts";
}

/**
 * Its own separate glob, because the one in the address rule above is scoped
 * inside that describe block.
 */
const TEST_SOURCES = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("a module is replaced by an alias, never by a module mock", () => {
  /**
   * **This is what makes `isolate: false` sound rather than merely lucky.**
   * The files in a worker share one module registry, so a module mock is a
   * claim one file makes about a module another file may already have
   * evaluated, and the loser is silent: the mock is dropped and the real
   * module is what the test gets.
   *
   * Measured before this rule existed, in both directions, with the whole
   * suite otherwise green. `App.test.tsx` ahead of `BarcodeScanner.test.tsx`
   * gave the scanner the real ZXing and failed fifteen of its tests at once.
   * `App.test.tsx` ahead of `BookDetail.test.tsx` gave it the real
   * `useNavigate` and failed the one test asserting on that spy. Both files
   * pass alone and pass in the other order, which is what makes this worth a
   * guard rather than a note.
   *
   * The replacement is `test.alias` in `vite.config.ts` pointing into
   * `tests/doubles/`: one implementation for the whole suite, so there is no
   * real module left to lose to and no ordering to get wrong.
   * `tests/doubles/README.md` is the argument in full.
   */
  it("is not called anywhere in the suite", () => {
    const offenders = Object.entries(TEST_SOURCES)
      .filter(([path, source]) => replacesAModule(source, langOf(path)))
      .map(([path]) => path.replace("./", "tests/"));

    expect(offenders).toEqual([]);
  });

  it("reads the test tree at all", () => {
    // A glob that matched nothing would make the rule above pass for ever.
    expect(Object.keys(TEST_SOURCES).length).toBeGreaterThan(100);
  });

  it("parses every file it reads", () => {
    // **The one failure mode the parser has and the line filter did not.** A
    // file it throws on takes the rule above down with it, which is loud, and
    // this is where that arrives naming the file rather than as a stack in the
    // middle of a rule about mocks. Measured across the whole suite tree when
    // the swap landed: nothing here fails to parse.
    const refused = Object.entries(TEST_SOURCES)
      .filter(([path, source]) => {
        try {
          replacesAModule(source, langOf(path));
          return false;
        } catch {
          return true;
        }
      })
      .map(([path]) => path.replace("./", "tests/"));

    expect(refused).toEqual([]);
  });

  it("tells a call apart from prose about one", () => {
    // Every live mention in this suite is prose: in `tests/utils.tsx`, in both
    // ScanPage test files, and in `tests/doubles/zxing.ts`. A rule matching the
    // spelling would report all of them and would have to be switched off, so
    // the two cases are pinned apart rather than left to a reader's judgement.
    //
    // **Written as a module rather than as loose lines**, because the parser
    // refuses text that does not parse: a bare ` * continuation` line is a
    // syntax error where the line filter returned something for it. Modelling
    // the comment it came from is the honest fixture either way.
    const prose = [
      `// vi.mock("react-router-dom") is refused: see the rule above.`,
      `/**`,
      ` * with a vi.mock("@zxing/library") the scanner gets the real decoder.`,
      ` */`,
      `/* vi.mock("./thing"); */`,
      `const nothing = 1;`,
    ].join("\n");
    expect(replacesAModule(prose, "ts")).toBe(false);

    // A call spelled inside a string is prose too, as far as a module is
    // concerned, and this is the fixture that says so: it is why the file no
    // longer assembles the name out of two pieces to escape its own rule.
    expect(replacesAModule(`const said = "vi.mock(x)";`, "ts")).toBe(false);

    for (const code of [
      `vi.mock("@zxing/library", () => ({}));`,
      `  vi.doMock("./thing");`,
      // Not anchored to the start of a line: that was the cheaper rule and it
      // is blind to anything sharing the line with the call.
      `const a = 1; vi.mock("./thing");`,
      // The receiver split onto its own line, which is what prettier does to a
      // call that heads an assignment chain, and which three real call sites in
      // this tree are already written as. A regex needed a whitespace class on
      // both sides of the dot to see this; the parser needs nothing.
      `const m = vi\n  .mock("./thing");`,
      // Bracketed rather than dotted, which the regex it replaced walked past.
      `vi["mock"]("./thing");`,
      // Reached through the global, which `vite.config.ts` puts it on and which
      // the regex DID see: reading only an identifier for the receiver gave
      // this up, and reading the rightmost name gives it back.
      `globalThis.vi.mock("./thing");`,
    ]) {
      expect(replacesAModule(code, "ts")).toBe(true);
    }
  });

  /**
   * **The one mistake here with a production consequence, so it is the one
   * checked against the running config rather than against its text.**
   *
   * `test.alias` is scoped to the suite. `resolve.alias` is not: the same entry
   * one level up would put a decoder that never decodes into the shipped
   * bundle, and no test could tell, because from inside the suite the two are
   * indistinguishable by construction. That is exactly the shape a guard has to
   * cover from outside.
   *
   * Asking vite what the **build** resolves is the only assertion that cannot
   * be satisfied by a config that merely looks right. A text check would pass
   * on a `resolve.alias` added in a shape it did not anticipate.
   *
   * This test exists because a docstring in `tests/doubles/zxing.ts` said it
   * did, for a round, while nothing read the config at all.
   */
  it("keeps the doubles out of the application build", async () => {
    const { resolveConfig } = await import("vite");
    // No root passed: vite falls back to the working directory and finds the
    // config the way a build does, which is the thing under test.
    for (const command of ["build", "serve"] as const) {
      const resolved = await resolveConfig({}, command);

      // **Assert a config was found, or this passes by reading nothing.**
      // Measured from a different working directory: `configFile` comes back
      // `undefined` and `resolve.alias` is byte identical, because the project
      // contributes nothing to it, which is the correct state and is also
      // exactly what never opening the file looks like. Same shape as a script
      // that takes a ref and reads whichever repository the shell is in.
      expect(resolved.configFile).toMatch(/vite\.config\.ts$/);

      // **The directory, not the two names in use.** A `find` that is a RegExp
      // serialises to `{}`, so the discriminating half of an entry is erased
      // before this sees it, and vite's own defaults already contain two such
      // entries. Naming the words `zxing` and `doubles` would therefore pass on
      // a double keyed by a pattern, and it would be an inclusion list one test
      // after this file removed one for being an inclusion list. Measured
      // absent from the resolved default.
      expect(JSON.stringify(resolved.resolve.alias)).not.toContain("/tests/");
    }
  });

  it("still aliases them for the suite", () => {
    // The other half, and it is what stops the test above passing because
    // somebody deleted the alias rather than because it is correctly scoped.
    // Read off the running suite rather than off the config text: this
    // specifier is the one the application uses, so whatever it resolves to
    // here is what the code under test got.
    //
    // The real `BarcodeFormat` is a numeric enum and the double's is strings,
    // so the value alone says which one answered.
    //
    // **`tsc` disagrees with the runtime here, and that is the point.** It
    // resolves this import to the real library's types, because the alias is
    // vitest's and not tsconfig's. So the application keeps the real types
    // while the suite gets the double, which is the arrangement the test above
    // checks from the other side. It also means only the shape the real
    // library declares can be read through this import: reaching for one of
    // the double's spies here is a type error, and they are imported from
    // `tests/doubles/zxing` by the files that assert on them.
    expect(zxingDouble.BarcodeFormat.EAN_13).toBe("EAN_13");
  });

  it("covers every vitest api that replaces a module", () => {
    // **Derived from vitest, and stated as an exclusion.** The first version of
    // the rule named two of the three and missed `importMock`, which takes a
    // specifier and replaces the module exactly as the other two do. The second
    // version derived the set with `/^(do|import)?[Mm]ock$/`, which is an
    // inclusion list wearing a pattern's clothes: it would have gone on passing
    // against a `mockModule` or a `mockRequire`, because a name of a shape it
    // did not anticipate simply is not selected.
    //
    // So: everything vitest spells with "mock", minus the ones classified below
    // as not replacing a module. A new API containing that word then fails here
    // until somebody decides which side it is on, which is the whole point.
    const NOT_A_REPLACEMENT = new Set([
      // Reads or asserts on a mock that already exists.
      "mocked",
      "isMockFunction",
      // Replaces an object's methods, never a module specifier.
      "mockObject",
      // Undoes a replacement rather than making one. These two do take a module
      // specifier, which is why this test is named for replacing rather than
      // for the argument: the argument is not what makes one dangerous.
      "unmock",
      "doUnmock",
      // Act on every spy at once, and take no specifier.
      "clearAllMocks",
      "resetAllMocks",
      "restoreAllMocks",
      // Fake timers.
      "getMockedSystemTime",
    ]);
    const replacers = Object.keys(vi).filter(
      (name) => /mock/i.test(name) && !NOT_A_REPLACEMENT.has(name),
    );

    // Not a stated count. A floor, so an API that has been enumerated away, or
    // one this filter can no longer see, fails here rather than passing quietly
    // on an empty set.
    expect(replacers.length).toBeGreaterThanOrEqual(3);

    // Driven through the rule rather than compared against its source text: a
    // substring check would pass on a pattern that happens to mention the name
    // without matching a call.
    for (const name of replacers) {
      expect(replacesAModule(`vi.${name}("./x");`, "ts")).toBe(true);
    }
  });
});

type Node = { type: string } & Record<string, unknown>;

function isNode(value: unknown): value is Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/**
 * Does the node at `at` defer what is written inside it to a later call?
 *
 * **Anything carrying a `params` array is a callable**, which is the whole
 * family (a declaration, an expression, an arrow, a method, an accessor) and
 * not a list of node names for a new syntax to grow past.
 *
 * **A callable a call expression holds directly is refused**, whether it is the
 * callee, as `(() => …)()` is, or an argument the call hands on, as the arrow
 * in `["utf-16be"].map(…)` is. The second is the one that matters: it is a one
 * line rewrite of the two constructions this rule was written for, and reading
 * "is it the callee" accepted it. Refused rather than called there, and the
 * difference is the point: a `setTimeout(() => …, 0)` at module scope is held
 * by a call and runs later, and it is refused too. The walk climbs a member
 * expression on the way out, which is the shape `.call` and `.apply` have, so
 * neither is named here.
 *
 * A callable the walk cannot show to be called is treated as deferring, which
 * is the lenient direction and is where the remaining holes are: a callable
 * reached by a call through something else, `wrap({ make: () => … })`, defers
 * as far as this can tell. A callable it can show is refused whether or not it
 * runs, so `.bind` on an arrow is refused, which is the strict one.
 */
function defers(ancestors: Node[], at: number): boolean {
  const node = ancestors[at];
  if (node === undefined || !Array.isArray(node.params)) return false;
  let child = node;
  for (let above = at - 1; above >= 0; above -= 1) {
    const outer = ancestors[above];
    if (outer === undefined) return true;
    if (outer.type === "CallExpression" || outer.type === "NewExpression") {
      return false;
    }
    if (outer.type !== "MemberExpression" || outer.object !== child)
      return true;
    child = outer;
  }
  return true;
}

/**
 * Is this node a construction of the platform's `TextDecoder`?
 *
 * The name is read off the identifier, or off the property at the end of a
 * member expression, so `new globalThis.TextDecoder(...)` is this constructor
 * spelled differently rather than a way past the rule.
 *
 * **Two references are out of reach and stay out of it**: an alias
 * (`const D = TextDecoder`) and a computed property
 * (`globalThis["TextDecoder"]`). Neither is a spelling of the label written at
 * the call, which is what the rule is about, and following a binding to its
 * declaration is a different instrument from reading a call.
 */
function isDecoderConstruction(node: Node): boolean {
  if (node.type !== "NewExpression") return false;
  const callee = node.callee;
  if (!isNode(callee)) return false;
  const named =
    callee.type === "MemberExpression" && isNode(callee.property)
      ? callee.property
      : callee;
  return text(named.name) === "TextDecoder";
}

/** The label a construction passes, or `null` where it is not a string literal. */
function labelOf(node: Node): string | null {
  const args = node.arguments;
  if (!Array.isArray(args)) return null;
  // No argument at all is UTF-8 by the specification, and cannot throw.
  if (args.length === 0) return "utf-8";
  const first: unknown = args[0];
  if (!isNode(first) || first.type !== "Literal") return null;
  const label = text(first.value);
  return label === null ? null : label.toLowerCase();
}

/**
 * One construction: the label it passes, and whether a callable defers it.
 *
 * `deferred` and not `atModuleEvaluation`, because that is what is computed. A
 * class field initialiser defers to instantiation and no callable holds it, so
 * it reads `false` here and the rule refuses it; naming the field for module
 * evaluation would have made the offender list say something untrue about it.
 */
type Construction = { label: string | null; deferred: boolean };

/**
 * Every `new TextDecoder(...)` in one source file, and what defers each.
 *
 * Parsed rather than matched, because the rule is about where a construction
 * sits and not about how its line is spelled: an export, a `let`, an explicit
 * type annotation and a value inside an object literal are four anchors to a
 * regular expression and one shape to a parser. **The parser is imported from
 * `vite`, which re-exports it**, and not from the package underneath: that one
 * is reachable only because a dependency of a dependency is hoisted, and this
 * file publishes. Where it is ever gone, this file fails to import, which is
 * louder than a rule that has quietly stopped matching anything.
 */
function decoderConstructions(
  source: string,
  lang: "ts" | "tsx",
): Construction[] {
  const found: Construction[] = [];
  const ancestors: Node[] = [];
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (!isNode(value)) return;
    if (isDecoderConstruction(value)) {
      found.push({
        label: labelOf(value),
        deferred: ancestors.some((_node, at) => defers(ancestors, at)),
      });
    }
    ancestors.push(value);
    for (const key of Object.keys(value)) walk(value[key]);
    ancestors.pop();
  };
  walk(parseAst(source, { lang }));
  return found;
}

function decoders(): [string, Construction][] {
  return (
    entries()
      // A construction cannot hide from the identifier it names, so this skips
      // files rather than constructions.
      .filter(([, source]) => source.includes("TextDecoder"))
      .flatMap(([path, source]) =>
        decoderConstructions(source, path.endsWith(".tsx") ? "tsx" : "ts").map(
          (one): [string, Construction] => [path, one],
        ),
      )
  );
}

/** The one label every runtime is required to carry. */
const UNIVERSAL_LABEL = "utf-8";

/**
 * The rule itself, in one place.
 *
 * Written once because the tests below would otherwise hold two copies of it,
 * the live one and the fixtures', and a fixture that exercises its own copy
 * reports on a rule the tree is not being read against.
 */
function refused(one: Construction): boolean {
  return !one.deferred && one.label !== UNIVERSAL_LABEL;
}

/**
 * What has to be in the text for a construction to exist, as a second
 * instrument on the same question.
 *
 * Deliberately not the string `decoders()` prefilters on: two instruments
 * keyed on one spelling agree with each other while missing the same file, and
 * the only thing this comparison is for is the case where they disagree.
 */
const CONSTRUCTION = /new\s+(?:[A-Za-z_$][\w$]*\.)*TextDecoder\s*\(/g;

describe("a decoder a runtime may not carry is never built at module scope", () => {
  it("passes no other label where no callable defers the construction", () => {
    // `new TextDecoder` throws a `RangeError` for a label the runtime has no
    // table for. Inside a function that costs the one call, which every caller
    // here already has a fallback for; at module scope it escapes module
    // evaluation, the dynamic import in `readerFor` rejects, and a whole format
    // reads as unreadable rather than one string. Two constructions in `pdf.ts`
    // were that, and three other readers had already guarded theirs.
    //
    // **Stated as an exclusion.** Not "no utf-16be", which is the one that was
    // wrong, and not a list of the labels a runtime is required to have, which
    // is a thing to be right about later and fails silently when it is not. A
    // label that is not a string literal is refused for the same reason: what
    // cannot be shown to be the universal one is not it.
    //
    // The whole of `src` and not the readers alone: what makes a construction
    // dangerous is module evaluation, which every module has. Measured on the
    // tree this arrived in, all 13 constructions are under `src/lib`, so the
    // wider rule refuses nothing extra today and needs no revisiting when a
    // reader moves.
    const offenders = decoders()
      .filter(([, one]) => refused(one))
      .map(([path, one]) => `${path}: ${one.label ?? "not a literal"}`);

    expect(offenders).toEqual([]);
  });

  it("is reading the constructions there are, and all of them", () => {
    // Two instruments, and no number written down: the walk counts
    // `NewExpression` nodes, the text count counts what has to be present for
    // one to exist. A glob that matched nothing, a parser that returned an
    // empty program and a walk that stopped descending all arrive here as a
    // disagreement rather than as a rule passing over an empty set.
    //
    // Prose in `src` writing a construction out in full would fail this too.
    // That is the trade for a check with no constant in it, and the fix is to
    // write the constructor without the `new`, as `audiobook.ts` does.
    const written = entries()
      .map(([, source]) => (source.match(CONSTRUCTION) ?? []).length)
      .reduce((total, count) => total + count, 0);

    expect(decoders().length).toBe(written);
    expect(written).toBeGreaterThan(0);
  });

  /**
   * Every shape the rule has an opinion about, and what it says about each.
   *
   * A table rather than a run of assertions in one test, so a row that stops
   * holding names itself: the run aborts at the first failure, and a mutation
   * that weakened two arms would be reported as one.
   */
  const SHAPES: [string, "ts" | "tsx", boolean][] = [
    // Module scope, whatever statement is written around it.
    [`const d = new TextDecoder("utf-16be");`, "ts", true],
    [`export const d = new TextDecoder("utf-16be");`, "ts", true],
    [`let d: TextDecoder = new TextDecoder("utf-16be");`, "ts", true],
    [`const all = { be: new TextDecoder("utf-16be") };`, "ts", true],
    // The same constructor, named through the object that carries it.
    [`const d = new globalThis.TextDecoder("utf-16be");`, "ts", true],
    // A callable a call holds directly is called there and shelters nothing,
    // as the callee or as an argument. The `map` row is the two constructions
    // this rule was written for, rewritten in one line.
    [`const d = (() => new TextDecoder("utf-16be"))();`, "ts", true],
    [`const d = (function () { return new TextDecoder("x"); })();`, "ts", true],
    [`const d = (() => new TextDecoder("utf-16be")).call(null);`, "ts", true],
    [`const ds = ["utf-16be"].map((l) => new TextDecoder(l));`, "ts", true],
    [`Array.from([1], () => new TextDecoder("utf-16be"));`, "ts", true],
    // Not a literal, so not shown to be the universal label.
    [`const d = new TextDecoder(LABEL);`, "ts", true],
    // A field initialiser defers to instantiation, and no callable holds it.
    // Refused, which is the strict direction.
    [`class C { d = new TextDecoder("utf-16be"); }`, "ts", true],
    // The other language the glob matches. No `.tsx` file in the tree names a
    // decoder today, so nothing else exercises that arm, and a `.tsx` source
    // handed to the `.ts` grammar throws at its first tag rather than passing.
    [`const view = <p x={new TextDecoder("utf-16be")} />;`, "tsx", true],

    // Deferred, in each shape that defers.
    [`function f() { return new TextDecoder("utf-16be"); }`, "ts", false],
    [`const f = () => new TextDecoder("utf-16be");`, "ts", false],
    [`const o = { f() { return new TextDecoder("utf-16be"); } };`, "ts", false],
    [
      `const o = { get f() { return new TextDecoder("utf-16be"); } };`,
      "ts",
      false,
    ],
    [`class C { f() { return new TextDecoder("utf-16be"); } }`, "ts", false],
    [
      `function f() { return [1].map(() => new TextDecoder("x")); }`,
      "ts",
      false,
    ],
    // The universal label at module scope, in any spelling of it. Labels are
    // matched case insensitively by the specification.
    [`const d = new TextDecoder("utf-8");`, "ts", false],
    [`const d = new TextDecoder("UTF-8");`, "ts", false],
    [`const d = new TextDecoder();`, "ts", false],
  ];

  it.each(SHAPES)("reads %s", (source, lang, refuses) => {
    expect(decoderConstructions(source, lang).some(refused)).toBe(refuses);
  });
});

/**
 * Every Markdown document this repository versions.
 *
 * **The exclusion is stated and it is build output, not a corner of the
 * tree.** An earlier draft globbed the repository root and one level of
 * `docs/`, which is an inclusion list: it read 11 of the 18 published
 * documents and left the rest unjudged, `DOCKERHUB.md` among them, which is
 * derived from the README's feature bullets and so is the likeliest place a
 * deleted sentence is copied back to. `backend/tests/test_roster_counts.py`
 * measured that same shape, replaced it and pinned against it.
 *
 * **What decides publication is the declaration in a document's header**,
 * applied by `scope` below. It is the property the publish gate reads, so the
 * two cannot drift, and a document added anywhere needs no entry anywhere.
 */
const DOCUMENTS = import.meta.glob(
  [
    "../../**/*.md",
    "!../../**/node_modules/**",
    "!../../**/.venv/**",
    "!../../**/.git/**",
    // The stripped tree the publish script materialises at the repository root,
    // gitignored. Every file in it is a copy of one already in scope, so
    // including it scans the corpus twice, and a **stale** copy reports a
    // violation the source no longer has: measured 2026-09-10, a four day old
    // copy of `docs/featurelist.md` failed the column count rule on a sentence
    // deleted in the same merge. Whether it exists at all depends on whether
    // somebody ran the publish script locally, which is not something a test
    // result may turn on.
    "!../../public/**",
  ],
  {
    query: "?raw",
    import: "default",
    eager: true,
  },
) as Record<string, string>;

/**
 * No register is excluded, and the two that invite one are read.
 *
 * **`docs/decisions.md` was excluded in a draft of this rule on the reasoning
 * that its counts are dated, and that reasoning does not hold.**
 * `backend/tests/test_roster_counts.py` reached the same exclusion first,
 * published the refutation, and pins against re-taking it: that register
 * carries no version headings and records decisions that still bind, so its
 * counts read as present tense, and it held four stale roster counts when that
 * file landed. `CHANGELOG.md` is dated by its own structure and is excluded
 * there for a reason that does hold; it is read here because a changelog entry
 * describing a count is a sentence somebody may copy forward.
 *
 * **The cost is a false positive this rule cannot resolve, and it is not
 * hypothetical.** Both registers carry historical column counts. The day
 * `COLUMN_SPECS` passes through one of those values, a correct historical
 * sentence is reported and must not be corrected. Resolving one needs a
 * verdict saying what the number counts, which is the census architecture in
 * the file named above; the answer then is to write the verdict, not to
 * exclude the register.
 */

/**
 * The publish gate's own anchor for an internal document, and its window.
 *
 * **A copy, and the third the repository holds.** A published file cannot read
 * the gate's script, which is stripped, so the number is written out rather
 * than derived, here and in
 * `backend/tests/test_roster_counts.py::test_the_window_is_the_number_the_publish_gate_uses`.
 * **That test pins that file's copy and not this one**, which an earlier
 * draft of this comment claimed the other way round: change the constant here
 * alone and it stays green. This copy is pinned by a literal in
 * `reads the declaration the way the publish gate reads it` below, and it has
 * to be, because the boundary fixture there is built from `HEADER_LINES` and
 * so moves with it: measured, the arm is green at every value from 3 to 200
 * while the set of documents it drops moves by six.
 *
 * **Getting the window wrong here is quiet rather than loud.** A narrower one
 * keeps a document whose declaration sits below it, which widens the rule's
 * scope and can only add a report; a wider one drops a document that merely
 * discusses the convention, which is the direction the gate's own comment says
 * the bound exists to protect.
 */
const INTERNAL = /^[^A-Za-z0-9]{0,6}[ \t]*\*\*This file is internal\.\*\*/m;
const HEADER_LINES = 30;

/**
 * Whether a document declares itself internal in its opening lines.
 *
 * **Lines, and the same count the gate uses.** Anything measured another way
 * is a second rule wearing the gate's name.
 */
function declaresItselfInternal(source: string): boolean {
  return INTERNAL.test(source.split("\n").slice(0, HEADER_LINES).join("\n"));
}

const ONES = [
  "zero",
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "nine",
  "ten",
  "eleven",
  "twelve",
  "thirteen",
  "fourteen",
  "fifteen",
  "sixteen",
  "seventeen",
  "eighteen",
  "nineteen",
];
const TENS = [
  "",
  "",
  "twenty",
  "thirty",
  "forty",
  "fifty",
  "sixty",
  "seventy",
  "eighty",
  "ninety",
];

/**
 * How English spells one number below a hundred, in both spellings it uses.
 *
 * **A table bounded by the language, not by this repository**, which is what
 * separates it from the enumeration the working notes refuse: it is asked for
 * the spelling of one value that is computed, and it does not grow when the
 * tree does.
 */
function inWords(n: number): string[] {
  const small = ONES[n];
  if (small !== undefined) return [small];
  const tens = TENS[Math.floor(n / 10)];
  const unit = ONES[n % 10];
  // **Throws rather than returning nothing.** An empty list would leave the
  // pattern below built from the digit alone, still passing, and guarding half
  // of what its name says. A count this cannot spell breaks the run instead.
  if (tens === undefined || unit === undefined || tens === "") {
    throw new Error(`no spelling for ${n}`);
  }
  return n % 10 === 0 ? [tens] : [`${tens} ${unit}`, `${tens}-${unit}`];
}

/**
 * One line of text out of wrapped prose, with the emphasis markers dropped.
 *
 * **The markers are removed because they hide a count from the pattern
 * below.** A gap that has to begin with whitespace does not see a bolded
 * number ahead of its noun, and a leading underscore is a word character, so
 * no boundary holds before an italicised one either.
 * `backend/tests/test_roster_counts.py` measured that hole in its own grammar
 * and describes it at length; the house writes bolded numbers throughout, so
 * it is a spelling this prose produces rather than one an evader has to reach
 * for.
 *
 * **Neither of those examples is spelled out here, and that is the rule this
 * comment broke.** Quoting one costs the markers that made it a quote, which
 * is exactly what this function removes, so the example becomes the claim and
 * the rule below reports its own docstring. Found by a critic; the fixtures
 * three arms down were already built from the count for this reason.
 *
 * **They are dropped unconditionally, and the two kinds differ.** An asterisk
 * and a backtick are not word characters, so removing one can only join and
 * never split. An underscore is, so removing it can also split: that is what
 * makes an italicised count visible at all, and it is the arm below relying on
 * it. Both directions only add reports, because the pattern needs a boundary
 * before the number and an invented one can only produce a match to look at.
 */
function flattened(source: string): string {
  return source
    .replace(/\n[ \t]*(?:\*|\/\/|#)?[ \t]*/g, " ")
    .replace(/[*_`]/g, "");
}

/** A number, at most two words, then the noun. */
function stated(n: number): RegExp {
  const forms = [String(n), ...inWords(n)];
  return new RegExp(
    String.raw`\b(?:${forms.join("|")})\b[ \t]+(?:[A-Za-z]+[ \t]+){0,2}columns?\b`,
    "i",
  );
}

/**
 * The size of `COLUMN_SPECS` is not restated in prose anywhere.
 *
 * **The figure was written down in six published places and recomputed in
 * none**, and it had already drifted: the README stated a count the table had
 * outgrown while `docs/featurelist.md` stated the right one. Deleting the
 * figure is the fix, because a count that is never written cannot go stale,
 * and this is what stops it being written again.
 *
 * **It looks for the count the tree has, not for a number.** The pattern is
 * built from `COLUMN_SPECS` when the test runs, so adding a column moves what
 * this refuses without anybody editing it, and no spelling of any other value
 * is named here.
 *
 * **What it catches is the figure arriving while it is still correct**, which
 * is the only moment drift can be stopped: a number has to be written before
 * it can go stale, and every one of the six was right on the day somebody
 * wrote it. A count that is wrong the moment it is typed is invisible here,
 * and stating that is cheaper than a verdict table for one noun.
 *
 * **Two bounds, and the grammar is the one a reader does not expect.** The
 * first is the glob: the frontend source, every test file, this file's own
 * source added back for the reason `SELF` above records, and every Markdown
 * document less those declaring themselves internal. The second is
 * the shape of the sentence: a number, at most two words, then the noun. A
 * count reaching its noun any other way is invisible, and the ones known to be
 * are an elided noun ("all of them are drawn"), an ordinal, and a number and
 * noun in different table cells. `flattened` closes the markup case, which was
 * the fourth and is the one the house prose produces.
 *
 * The backend's equivalent machinery is `backend/tests/test_roster_counts.py`,
 * which is a census with a verdict for every candidate rather than one noun
 * and one computed value.
 */
describe("the number of table columns is not written down", () => {
  const count = Object.keys(COLUMN_SPECS).length;

  function scope(): [string, string][] {
    return [
      ...Object.entries(SOURCES),
      ...Object.entries(TEST_SOURCES),
      ["./houseRules.test.ts", ownSource] as [string, string],
      ...Object.entries(DOCUMENTS).filter(
        ([, source]) => !declaresItselfInternal(source),
      ),
    ];
  }

  it("reads the source documents and not a materialised copy of them", () => {
    // The exclusion above, asserted rather than trusted: a glob that silently
    // stops excluding is the failure this arm exists for, and it costs nothing.
    expect(
      Object.keys(DOCUMENTS).filter((path) => path.startsWith("../../public/")),
    ).toEqual([]);
  });

  it("is a count this spelling table can spell", () => {
    expect(count).toBeGreaterThan(0);
    // The edges of the table, so a count growing past it is known to stop the
    // run rather than to leave the digit arm guarding on its own.
    expect(() => inWords(100)).toThrow();
    expect(() => inWords(-1)).toThrow();
  });

  it("appears in no source file and no published document", () => {
    const pattern = stated(count);
    const found = scope()
      .filter(([, source]) => pattern.test(flattened(source)))
      .map(([path]) => path);

    expect(found).toEqual([]);
  });

  it("reads the declaration the way the publish gate reads it", () => {
    // **Pinned on synthetic input, never on a count over the corpus.** The
    // number of documents this drops is positive here and **zero** in the
    // mirror, by construction: the gate refuses to publish a file that
    // declares itself internal, so the published tree holds none. This file
    // publishes and the mirror carries a runnable suite, so an arm resting on
    // that count would pass here and fail there.
    expect(declaresItselfInternal("**This file is internal.**\n")).toBe(true);
    // Any short run of non-alphanumerics may precede it, which is the gate's
    // anchor rather than a list of the comment prefixes somebody thought of.
    expect(declaresItselfInternal("> **This file is internal.**\n")).toBe(true);
    // **The false direction is the one that matters, and it was unpinned.** A
    // filter stuck at true drops every document, leaving the rule above
    // judging the source trees alone, and a count of what it dropped rises
    // rather than falls. Nothing else here would notice.
    const past = `${"x\n".repeat(HEADER_LINES)}**This file is internal.**\n`;
    expect(declaresItselfInternal(past)).toBe(false);
    expect(declaresItselfInternal("nothing to declare\n")).toBe(false);
    // **The window itself, as a literal.** Every assertion above is built from
    // `HEADER_LINES`, so all of them follow it wherever it goes and none of
    // them bounds it. Without this line the constant is at the "stated" rung
    // while the comment above it claims "tested".
    expect(HEADER_LINES).toBe(30);
  });

  it("is reading the documents at all", () => {
    // **Asserted against `scope()` and not against the glob**, which is the
    // same distinction one level up: a filter that dropped everything would
    // leave an unfiltered glob still holding every one of these.
    const paths = scope().map(([path]) => path);
    expect(paths).toContain("../../README.md");
    // Deliberately not the two an inclusion list would have reached anyway.
    // These four sit in four different places and each was unjudged while the
    // scope was the repository root and one level of `docs/`.
    expect(paths).toContain("../../DOCKERHUB.md");
    expect(paths).toContain("../../CHANGELOG.md");
    expect(paths).toContain("../../conformance/README.md");
    // The two coverage registers sit beside this file, and a specifier that
    // resolves back into this directory is keyed relative to it rather than by
    // the way it was written. Matched by suffix so the assertion is about the
    // document rather than about that normalisation.
    expect(paths.some((path) => path.endsWith("COVERAGE.md"))).toBe(true);
    expect(Object.keys(TEST_SOURCES).length).toBeGreaterThan(0);
    // **This file has to be in the set it is scanning.** The rule's docstring
    // says its own prose is inside its subject rather than exempted, and that
    // was a sentence rather than a test: the run stayed green while this file
    // carried a live count in a docstring, which is either a glob that skips
    // its importer or a scope that forgets it, and neither is visible by
    // reading.
    expect(scope().map(([path]) => path)).toContain("./houseRules.test.ts");
  });

  it("sees a count that markup has wrapped", () => {
    // The shape the house prose actually produces. Each of these was invisible
    // while the gap after the number had to begin with whitespace.
    const words = inWords(count)[0];
    const pattern = stated(count);
    expect(pattern.test(flattened(`**${words}** columns`))).toBe(true);
    expect(pattern.test(flattened(`**${count}** columns`))).toBe(true);
    expect(pattern.test(flattened(`_${words}_ columns`))).toBe(true);
    expect(pattern.test(flattened(`\`${count}\` columns`))).toBe(true);
    expect(pattern.test(flattened(`**${words} columns**`))).toBe(true);
  });

  it("refuses the sentence this rule was written for", () => {
    // Built from the count rather than typed, so this file does not become an
    // instance of what it refuses.
    const words = inWords(count)[0];
    expect(stated(count).test(`a table of ${words} metadata columns`)).toBe(
      true,
    );
    expect(stated(count).test(`the table carries ${count} columns`)).toBe(true);
    // Across a wrapped comment, which is where four of the six sites sat.
    expect(stated(count).test(flattened(` * ${words}\n * columns exist`))).toBe(
      true,
    );
  });

  it("says nothing about a count that is not this one", () => {
    // "two columns" is ordinary English and the tree is full of it. Only the
    // live size is refused, which is what keeps this off every other sentence.
    expect(stated(count).test("two columns")).toBe(false);
    expect(stated(count).test(`${count + 1} columns`)).toBe(false);
    expect(stated(count).test(`${count} rows`)).toBe(false);
  });
});
