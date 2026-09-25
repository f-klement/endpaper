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
import { declarePreference } from "../src/lib/preference";

// The refusal this file and the ScanPage guard both apply, in one home: the
// module says why it is not a copy per guard.
import { CARRIES_A_BOOK } from "./carriesABook";

// The comment stripper every rule below reads its sources through, and what
// decides how a path is parsed. One home for the same reason: the tree had two
// instruments for this, and the second was blind to the class this one had just
// been fixed for. `withoutProse.test.ts` holds what it keeps and what it cuts.
import { langOf, withoutProse } from "./withoutProse";

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

/**
 * One endpoint, one set of options.
 *
 * The rule above is not this rule, and the difference is what let this one
 * break. That one asks whether the generated client is reached from a
 * `hooks.ts`; the flags query was called from five of them, all passing, while
 * three inherited `MAX_RETRIES` for a request the shell had decided not to
 * retry. All five share a query key, so which observer mounted first decided
 * the options for every one of them.
 *
 * Per endpoint rather than a rule about every endpoint, because most have one
 * caller and need no owner. This one is read by the shell, the login page, the
 * scanner and the book page, which is what makes an owner worth a test.
 */
describe("the feature flags query has one owner", () => {
  const OWNER = "app/hooks.ts";
  const GENERATED = "api/generated/endpoints/settings/settings";

  /**
   * Every way the generated client exposes this endpoint, less the one that is
   * not a configuration.
   *
   * **Matching one name is what a first draft of this did, and two evasions
   * walked past it.** Orval emits six identifiers per operation, and
   * `useQuery({...getGetFeatureFlagsQueryOptions(), retry: 5})` reintroduces
   * the exact defect this rule exists for, in a `hooks.ts`, while naming
   * nothing the rule was watching. So the match is the operation rather than
   * the hook: every one of the six carries `etFeatureFlags`.
   *
   * **The query key is struck out first, because invalidating is not
   * configuring.** `pages/SettingsPage/hooks.ts` invalidates by it after a
   * settings write, which is a caller that has to know the key and must not
   * own the options. Struck out by text rather than allowed by path, so the
   * exemption belongs to the identifier and not to a file.
   *
   * **Three residuals, stated rather than coded around**, all one root: this
   * matches text over a whole file rather than code. `setQueryDefaults` keyed
   * off the query key alone would configure the query and name nothing this
   * matches. A hand rolled `useQuery` on `/api/settings/features` is a second
   * reader of the same endpoint and is invisible here. And a comment naming
   * the owner by identifier is an offender, which is the opposite of what this
   * repository asks of a cross reference: measured, so point at
   * `app/hooks.ts` by file rather than by hook name.
   *
   * Matching the path as well was measured and refused: it turns the clean
   * tree red at `pages/ScanPage/hooks.ts`, which names the path in a comment.
   * Closing any of the three properly means matching code rather than text.
   */
  function configures(source: string): boolean {
    return /[Gg]etFeatureFlags/.test(
      source.split("getGetFeatureFlagsQueryKey").join(""),
    );
  }

  it("is configured nowhere but there", () => {
    const offenders = entries()
      // The generated module, which declares the operation rather than calling
      // it. `api/generated/` and not `api/`: `api/mutator.ts` and
      // `api/query-client.ts` are hand written, and excluding them by accident
      // is a second evasion that passed.
      .filter(([path]) => !path.startsWith("api/generated/"))
      .filter(([path]) => path !== OWNER)
      .filter(([, source]) => configures(source))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it("is configured there, so the rule above is not vacuous", () => {
    // **Through the same predicate the rule is spelled with**, which is the
    // only thing that catches the way this rule dies: a regenerated client
    // names the operation something else, `configures` then matches nothing in
    // the tree, and "no offenders" reads exactly like a rule being kept.
    //
    // Asserting the import path instead does not catch it, and that was
    // measured rather than reasoned: the owner can keep importing this module
    // while nothing in it matches any more.
    const owner = entries().find(([path]) => path === OWNER);
    expect(owner && configures(owner[1])).toBe(true);
    expect(owner?.[1]).toContain(`from "../${GENERATED}"`);
  });

  it("leaves the caller that invalidates by key alone", () => {
    // The boundary the strike-out draws, asserted from both sides so it cannot
    // be satisfied by refusing everything or by allowing it.
    expect(configures('import { getGetFeatureFlagsQueryKey } from "x";')).toBe(
      false,
    );
    expect(configures("useGetFeatureFlags({ query: { retry: 5 } })")).toBe(
      true,
    );
    expect(
      configures("useQuery({ ...getGetFeatureFlagsQueryOptions(), retry: 5 })"),
    ).toBe(true);
    expect(configures("getFeatureFlags()")).toBe(true);
  });
});

/** The generated model this tree is given for the public flags endpoint. */
const FLAGS_MODEL = "api/generated/model/featureFlagsOut.ts";

/** The hook that owns the query, and the type its answer is carried in. */
const REACHES_THE_FLAGS = ["useFeatureFlagsState", "FeatureFlagsOut"];

/**
 * Every name a module writes, as identifiers and as string literals.
 *
 * **Read off the parse rather than the text**, so a field named only in a
 * comment is not a reader. That is the whole difference between this and the
 * rule above it, which says so in its own docstring and pays for it in three
 * residuals.
 *
 * **Deliberately one flat set rather than member accesses alone.** A reader
 * writes `flags?.library_mode`, `const { library_mode } = flags`,
 * `const { library_mode: mode } = flags`, `flags["library_mode"]` and
 * `flags[KEY]` with `KEY` a literal somewhere above, and every one of those
 * puts the name in the parse as an identifier or a literal. Matching only the
 * member expression would report four of the five as unread, and a guard that
 * calls a real reader missing is the one somebody deletes.
 *
 * **A template literal needs its own arm, because its text is not a `value` this
 * walk can read.** A `TemplateElement` holds `{ raw, cooked }`, an object with no
 * `type`, so `isNode` refuses it and `text(value.value)` is handed an object and
 * answers null. Measured against the parse: of nine ways to name a member,
 * `d[\`x\`]()`, the same through a `const`, through an `as const` record, through
 * `Date.prototype[K].call`, and `new Intl[\`x\`]()` were all invisible, five of
 * nine, while the plain access and the string literal index were seen.
 * `withoutProse.ts` in this directory already counted `TemplateElement` among the
 * node kinds that carry text, so the tree held the fact this was missing.
 * **Removing this arm silently unsees a whole spelling** in every rule that reads
 * through here, which is why it is not folded into the line below it.
 *
 * **What is still open is concatenation**, `d["toLocale" + "DateString"]`, which
 * needs constant folding. It is stated rather than chased: TypeScript refuses it
 * on `Date` and on `Intl`, neither having an index signature, so the type checker
 * is what holds it and no arm here does.
 */
function namesIn(path: string, source: string): Set<string> {
  const names = new Set<string>();
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (!isNode(value)) return;
    if (value.type === "Identifier") {
      const name = text(value.name);
      if (name !== null) names.add(name);
    }
    if (value.type === "TemplateElement") {
      const cooked = text((value.value as { cooked?: unknown })?.cooked);
      if (cooked !== null) names.add(cooked);
    }
    const literal = text(value.value);
    if (literal !== null) names.add(literal);
    for (const key of Object.keys(value)) walk(value[key]);
  };
  walk(parseAst(source, { lang: langOf(path) }));
  return names;
}

/**
 * The flags a reader of this endpoint never names, given what it declares.
 *
 * **The scope is derived and so is the reading.** A module is asked only if it
 * names the owning hook or the model's type, which is what keeps the rule from
 * being satisfied by a coincidence: `google_books_enabled` is read off
 * `SettingsOut` at `pages/SettingsPage/CatalogueSettingsPage/components/`, and
 * counting that would have made this rule green on the exact field it was
 * written for.
 */
function unreadAmong(
  declared: string[],
  modules: [string, string][],
): string[] {
  const read = new Set<string>();
  for (const [path, source] of modules) {
    const names = namesIn(path, source);
    if (!REACHES_THE_FLAGS.some((one) => names.has(one))) continue;
    for (const name of names) read.add(name);
  }
  return declared.filter((name) => !read.has(name));
}

/**
 * Every field the public flags endpoint sends is read by this client.
 *
 * `GET /api/settings/features` is the one endpoint a caller with no token can
 * read, so a field on it that nothing reads is disclosure bought for nothing.
 * `FeatureFlagsOut` said exactly this in its comment on `library_mode`, and
 * prose enforces nothing: `google_books_enabled` sat on the same model with no
 * reader, and with `google_books_ready` beside it the pair told a stranger the
 * toggle was on and no key was stored.
 *
 * **What this cannot see**, stated because a derivation that looks thorough is
 * read as one:
 *
 * * **A read that never names the field.** `Object.keys(flags)`, a key built by
 *   concatenation, a `Pick` passed through a generic. The field then reports as
 *   unread, so the failure is loud and the fix is to name it: this is the safe
 *   direction and the only one worth being wrong in.
 * * **A collision inside a module that does reach the flags.** Any name that
 *   module writes counts, so a same-named property of a different object there
 *   would satisfy the rule. The scope filter is what keeps that rare; nothing
 *   here makes it impossible.
 * * **A field the backend added and nobody regenerated.** The subject is the
 *   committed client, not the server. CI diffs the schema and the client it
 *   generates from it against a fresh generation, and the backend pins the
 *   sent field set by equality at `TestFeatureFlags`; this rule leans on both
 *   and replaces neither. Retained as a residue rather than closed here,
 *   because a rule about what the client reads cannot see the server at all.
 * * **A client this repository does not contain.** The API is public, so
 *   dropping a field is a contract change whatever this tree reads.
 */
describe("every feature flag has a reader", () => {
  /** The fields the generated model declares, read off its own declaration. */
  function declared(): string[] {
    const source = SOURCES[`../src/${FLAGS_MODEL}`];
    if (source === undefined) throw new Error(`${FLAGS_MODEL} is not here`);
    const model = declaredIn(FLAGS_MODEL, source, "FeatureFlagsOut");
    if (model === null)
      throw new Error(`${FLAGS_MODEL} declares no FeatureFlagsOut`);
    return propertiesOf(model).map((one) => one.name);
  }

  /** Every module that could hold a reader, the generated client aside. */
  function candidates(): [string, string][] {
    return entries().filter(([path]) => !path.startsWith("api/generated/"));
  }

  it("names every flag it is sent", () => {
    expect(unreadAmong(declared(), candidates())).toEqual([]);
  });

  it("has a subject and a scope, so the rule above is not vacuous", () => {
    // **The two ways this rule dies quietly.** A renamed or moved model leaves
    // it judging an empty list of fields, and a renamed hook leaves every
    // module out of scope, which reports every field unread and is loud. Only
    // the first is silent, so it is the one asserted.
    expect(declared().length).toBeGreaterThan(3);
    expect(
      candidates()
        .filter(([path, source]) => {
          const names = namesIn(path, source);
          return REACHES_THE_FLAGS.some((one) => names.has(one));
        })
        .map(([path]) => path),
    ).toContain("app/hooks.ts");
  });

  it("refuses a flag nothing in scope names", () => {
    const reader: [string, string][] = [
      ["app/hooks.ts", "useFeatureFlagsState().flags?.library_mode;"],
    ];

    expect(unreadAmong(["library_mode", "telemetry_enabled"], reader)).toEqual([
      "telemetry_enabled",
    ]);
  });

  it("does not take a flag named in a comment for a reader", () => {
    // The claim `namesIn` is written on, asserted rather than trusted: this is
    // the whole difference between this rule and the one above it, and it
    // holds only for as long as the names come off the parse.
    const mentions: [string, string][] = [
      ["app/hooks.ts", "useFeatureFlagsState(); // library_mode"],
      ["app/hooks.ts", "useFeatureFlagsState(); /* library_mode */"],
    ];

    for (const module of mentions)
      expect(unreadAmong(["library_mode"], [module])).toEqual(["library_mode"]);
  });

  it("sees a reader that reaches the flag indirectly", () => {
    // The false positive direction, which is the one that gets a guard turned
    // off. Five spellings of one read, none of them a plain member access.
    const spellings = [
      "const { library_mode } = useFeatureFlagsState().flags ?? {};",
      "const { library_mode: mode } = useFeatureFlagsState().flags ?? {};",
      'useFeatureFlagsState().flags?.["library_mode"];',
      'const KEY = "library_mode"; useFeatureFlagsState().flags?.[KEY];',
      'function F(flags: FeatureFlagsOut) { return at(flags, "library_mode"); }',
    ];

    for (const source of spellings)
      expect(unreadAmong(["library_mode"], [["x.ts", source]])).toEqual([]);
  });

  it("does not count a module that never reaches the flags", () => {
    // The defect this was written for, driven through the rule: the admin
    // screen reads the same name off a different model behind a token.
    const settings: [string, string][] = [
      ["pages/SettingsPage/x.tsx", "const on = settings.google_books_enabled;"],
    ];

    expect(unreadAmong(["google_books_enabled"], settings)).toEqual([
      "google_books_enabled",
    ]);
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
    .filter(([path, source]) =>
      READS_BYTES.test(withoutProse(source, langOf(path))),
    )
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
  "lib/adobeDigitalEditions.ts",
  "lib/audiobook.ts",
  "lib/calibre.ts",
  "lib/cbz.ts",
  "lib/epub.ts",
  "lib/fb2.ts",
  "lib/fileReaders.ts",
  "lib/kindle.ts",
  "lib/mobi.ts",
  "lib/opf.ts",
  "lib/pdf.ts",
  "lib/sqlite.ts",
  "lib/stores.ts",
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
// **The import arm excludes the generated model, and that is a widening this
// rule pays for on purpose.** It used to refuse any import from `api/`, which
// was safe while the population was the fifteen readers, none of which imports
// anything from there. Once the population became the whole directory it false
// refused **nine** modules whose only match is `from "../api/generated/model"`,
// a type import that house rule 3 permits outright and that is erased before
// anything runs: a type cannot carry a member's bytes anywhere.
//
// **What this now accepts that it refused before**: a module in `lib/` naming a
// generated type. What it still refuses is every runtime path to the network,
// and the generated client specifically, which is `api/generated/endpoints/`
// and is separately held behind the hooks by the first rule in this file. So
// the client is guarded twice and the types are guarded by neither, which is
// the right way round.
const REACHES_THE_NETWORK =
  /\b(fetch|XMLHttpRequest|WebSocket|sendBeacon|FormData|navigator\.send)\b|from "[^"]*\/api\/(?!generated\/model")/;

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
    //
    // **The population is the directory, not the derived reader set**, and that
    // is a real difference rather than a tidier spelling. `fileReaders()` keeps
    // the modules naming one of six byte tokens, and a module can hold a
    // member's parsed document without naming any of them: the sibling walk
    // every reader calls was moved into `lib/elementChildren.ts` on 2026-09-25
    // and that module names none of the six, so a `fetch` written into the one
    // module every reader passes its nodes to would have published with this
    // arm green, where the identical line in any of the three readers it came
    // out of fails it. The derivation's own docstring names that hole and says
    // the equality below makes it visible rather than closing it.
    //
    // **Widening it is free, measured rather than assumed**: the only two
    // `lib/` modules naming a network token are already in the derived set, so
    // this catches nothing that was not already watched and closes the class
    // for every future module that names no byte token. The equality arm below
    // keeps its own population, because that one is a claim about the readers
    // and not about the directory.
    const offenders = entries()
      .filter(([path]) => path.startsWith("lib/") && !path.endsWith(".d.ts"))
      .filter(([path, source]) => {
        const code = withoutProse(source, langOf(path));
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
    const code = withoutProse(engine![1], langOf(engine![0]));
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
      entries().flatMap(([path, source]) =>
        [...withoutProse(source, langOf(path)).matchAll(/\bdraftFrom\w*/g)].map(
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
      .filter(([path, source]) =>
        ANNOTATES_A_DRAFT.test(withoutProse(source, langOf(path))),
      )
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
    for (const [path, source] of entries())
      for (const name of withoutProse(source, langOf(path)).match(
        /\bFile\w*\b/g,
      ) ?? [])
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
    for (const [path, source] of entries())
      for (const name of withoutProse(source, langOf(path)).match(
        /\bFile\w*\b/g,
      ) ?? [])
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
      buildersIn(source, langOf(path)).map((one) => ({
        ...one,
        path,
      })),
    );
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
      .map(
        ([path, source]) => [path, withoutProse(source, langOf(path))] as const,
      )
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
    expect(
      cacheClears(withoutProse(owner![1], langOf(SESSION_OWNER))),
    ).toBeGreaterThan(0);
  });

  it("is watching something", () => {
    // A rule whose subject has been renamed passes by matching nothing.
    const writers = entries().filter(
      ([path, source]) => sessionWrites(withoutProse(source, langOf(path))) > 0,
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
      .map(
        ([path, source]) => [path, withoutProse(source, langOf(path))] as const,
      )
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
      .map(
        ([path, source]) => [path, withoutProse(source, langOf(path))] as const,
      )
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
    expect(withoutProse(owner![1], langOf(INVALIDATION_OWNER))).toMatch(
      /invalidateQueries\(\s*\)/,
    );
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
      .map(
        ([path, source]) => [path, withoutProse(source, langOf(path))] as const,
      )
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
        path !== TAG_NAME_OWNER &&
        /\btagName\(/.test(withoutProse(source, langOf(path))),
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
        decoderConstructions(source, langOf(path)).map(
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

/**
 * The module the rule below reads, keyed as the source glob keys it.
 *
 * One file rather than the directory, because the rule it carries is that
 * module's own: `theme/patterns.ts` publishes a generator per primitive so that
 * a geometry guard can reach it, and `docs/decisions.md` records why. A rule
 * over every module in the tree would be a different rule, and a stricter one
 * than this tree wants.
 */
const WALLPAPER = "../src/theme/patterns.ts";

/**
 * A path with its `.` and `..` segments collapsed and its extension dropped.
 *
 * **Both sides of the comparison go through it**, which is the half a match on
 * the written specifier gets wrong: the glob keys the subject with an
 * extension and an importer writes it with or without one, and
 * `allowImportingTsExtensions` means both spellings occur.
 */
function flatten(parts: string[]): string {
  const out: string[] = [];
  for (const part of parts) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (out.length > 0 && out[out.length - 1] !== "..") out.pop();
      else out.push("..");
      continue;
    }
    out.push(part);
  }
  return out.join("/").replace(/\.(?:ts|tsx)$/, "");
}

/**
 * A relative specifier, resolved against the module that wrote it.
 *
 * Both globs are keyed relative to this directory, so resolving into the same
 * space makes an importer's `../../src/theme/patterns` and the glob's
 * `../src/theme/patterns.ts` one string.
 *
 * **A bare specifier answers `null` and that is the known hole.** A package
 * name cannot name a file under `src` today: `tsconfig.json` declares no
 * `paths` and `vite.config.ts` aliases only under `test.alias`, which replaces
 * a package with a double and never points into this tree. An alias added into
 * `src` would make this rule quieter rather than louder, which is the direction
 * to watch.
 *
 * **A query is left on, so a `?raw` import resolves to nothing.** That is the
 * right answer twice over: it is a different module id carrying a string rather
 * than a binding, so it references no export, and it is this tree's standard
 * source text instrument, this file among its callers. Stripping the query made
 * it resolve to the subject and then throw as a default import, which stops the
 * run and names the wrong cause. Found by the design seat.
 */
function resolvedFrom(from: string, specifier: string): string | null {
  if (!specifier.startsWith(".")) return null;
  return flatten([...from.split("/").slice(0, -1), ...specifier.split("/")]);
}

/**
 * The names one module imports from another, read off the import specifiers.
 *
 * **This is the whole point of the rule, and a grep cannot do it.** A word
 * matched search over the tree counts a name written in a comment, a docstring
 * or a string literal as a reference, so the evasion is not a new dead export,
 * which either instrument catches: it is deleting the last import of a name and
 * leaving the word behind in prose. `src/index.css` mentions this module twice
 * and imports from it never, which is what that reads like.
 *
 * **Four ways of naming a module carry no name, and each throws rather than
 * answering nothing.** A namespace import, a default import, an `export *` and
 * a dynamic `import()` each reference the module while referencing no export,
 * so treating any of them as "imported nothing" would let one of them turn this
 * rule off with every arm still green. None exists today; the throw is what
 * makes adding one a decision rather than an accident.
 *
 * **A specifier that is not a string literal is invisible here**, which is the
 * one way past that does not throw: `import(`../src/theme/${name}`)` carries no
 * value to compare. Nothing in this tree builds a specifier, and a module
 * loaded that way is outside what any static reader can follow.
 */
function importedFrom(path: string, source: string, subject: string): string[] {
  const names: string[] = [];
  const refuse = (what: string): never => {
    throw new Error(`${path} reaches ${subject} by ${what}`);
  };
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (!isNode(value)) return;
    const from = isNode(value.source) ? text(value.source.value) : null;
    const specifiers = value.specifiers;
    // **Both sides go through `flatten`**, which is the half a comparison on
    // the written specifier gets wrong: the glob keys the subject with its
    // extension and an importer writes it with or without one.
    if (
      from !== null &&
      resolvedFrom(path, from) === flatten(subject.split("/"))
    ) {
      if (value.type === "ImportExpression") refuse("a dynamic import");
      if (value.type === "ExportAllDeclaration") refuse("an export star");
      for (const one of Array.isArray(specifiers) ? specifiers : []) {
        if (!isNode(one)) continue;
        if (one.type === "ImportNamespaceSpecifier")
          refuse("a namespace import");
        if (one.type === "ImportDefaultSpecifier") refuse("a default import");
        const named = one.type === "ExportSpecifier" ? one.local : one.imported;
        const name = isNode(named)
          ? (text(named.name) ?? text(named.value))
          : null;
        if (name === null) refuse(`a specifier this cannot read: ${one.type}`);
        else names.push(name);
      }
    }
    for (const key of Object.keys(value)) walk(value[key]);
  };
  walk(parseAst(source, { lang: langOf(path) }));
  return names;
}

/**
 * Every name a module exports, read off the declarations.
 *
 * A default export and an `export *` throw for `importedFrom`'s reason turned
 * round: neither publishes a name this rule could ask about, so counting either
 * as nothing exported would shrink the subject silently.
 */
function exportedBy(path: string, source: string): string[] {
  const names: string[] = [];
  const ast = parseAst(source, { lang: langOf(path) }) as unknown as {
    body: unknown[];
  };
  for (const node of ast.body) {
    if (!isNode(node)) continue;
    if (node.type === "ExportDefaultDeclaration")
      throw new Error(`${path} has a default export`);
    if (node.type === "ExportAllDeclaration")
      throw new Error(`${path} re-exports a whole module`);
    if (node.type !== "ExportNamedDeclaration") continue;
    const declaration = node.declaration;
    if (!isNode(declaration)) {
      for (const one of Array.isArray(node.specifiers) ? node.specifiers : []) {
        if (!isNode(one) || !isNode(one.exported)) continue;
        const name = text(one.exported.name) ?? text(one.exported.value);
        if (name !== null) names.push(name);
      }
      continue;
    }
    if (declaration.type === "VariableDeclaration") {
      for (const one of Array.isArray(declaration.declarations)
        ? declaration.declarations
        : []) {
        if (!isNode(one) || !isNode(one.id) || one.id.type !== "Identifier")
          throw new Error(`${path} exports a binding pattern`);
        const name = text(one.id.name);
        if (name !== null) names.push(name);
      }
      continue;
    }
    const id = declaration.id;
    const name = isNode(id) ? text(id.name) : null;
    if (name === null)
      throw new Error(`${path} exports an unnamed ${declaration.type}`);
    names.push(name);
  }
  return names;
}

/** The exports of `subject` that nothing among `importers` imports by name. */
function unreferenced(
  subject: string,
  subjectSource: string,
  importers: [string, string][],
): string[] {
  const reached = new Set(
    importers
      .filter(([path]) => path !== subject)
      .flatMap(([path, source]) => importedFrom(path, source, subject)),
  );
  return exportedBy(subject, subjectSource).filter(
    (name) => !reached.has(name),
  );
}

/**
 * Every wallpaper export is reached by an import, somewhere.
 *
 * **The module publishes more than the app calls, on purpose**, and that is
 * settled rather than tolerated: a generator per primitive is exported so
 * `tests/theme/patterns.test.ts` can assert curve continuity, coverage and the
 * widest empty run, none of which `patternDataUri` can state. Un-exporting them
 * was refused once and the refusal shipped a defect, which
 * `docs/decisions.md` records with the measurement.
 *
 * So the rule is not "export only what the app calls". It is that **every**
 * name on the door is reached by somebody, which is what tells a deliberate
 * test only export from one whose last caller went away. The eight this arrived
 * with were the second kind.
 */
describe("every wallpaper export is imported by name somewhere", () => {
  function scope(): [string, string][] {
    return [
      ...Object.entries(SOURCES),
      ...Object.entries(TEST_SOURCES),
      ["./houseRules.test.ts", ownSource] as [string, string],
    ];
  }

  it("leaves none of them unreached", () => {
    const source = SOURCES[WALLPAPER];
    expect(source).toBeDefined();

    expect(unreferenced(WALLPAPER, source ?? "", scope())).toEqual([]);
  });

  it("is reading a door and a tree, not two empty sets", () => {
    // Both halves of the comparison, asserted: a subject with no exports and a
    // scope with no importers agree, and the arm above cannot tell that from a
    // rule that holds.
    expect(exportedBy(WALLPAPER, SOURCES[WALLPAPER] ?? "")).toContain(
      "patternDataUri",
    );
    expect(
      exportedBy(WALLPAPER, SOURCES[WALLPAPER] ?? "").length,
    ).toBeGreaterThan(10);
    const reached = scope()
      .filter(([path]) => path !== WALLPAPER)
      .flatMap(([path, source]) => importedFrom(path, source, WALLPAPER));
    expect(reached).toContain("PATTERNS");
    expect(new Set(reached).size).toBeGreaterThan(10);
  });

  it("reports a name that nothing imports", () => {
    // The rule's own mutation, run on synthetic input so the tree is not
    // written to: an export no importer names is what this exists to find.
    const subject = "../src/theme/patterns.ts";
    expect(
      unreferenced(subject, "export const alive = 1;\nexport const dead = 2;", [
        ["./x.ts", 'import { alive } from "../src/theme/patterns";'],
      ]),
    ).toEqual(["dead"]);
  });

  it("does not count a name that only prose mentions", () => {
    // The evasion, and the reason this reads specifiers rather than text:
    // leaving the word behind in a comment, a docstring or a string is what a
    // word matched grep takes for a reference.
    const subject = "../src/theme/patterns.ts";
    const prose = [
      "// dead is the old name for alive",
      "/** See dead in ../src/theme/patterns. */",
      'const note = "dead";',
      'import { alive } from "../src/theme/patterns";',
    ].join("\n");

    expect(
      unreferenced(subject, "export const alive = 1;\nexport const dead = 2;", [
        ["./x.ts", prose],
      ]),
    ).toEqual(["dead"]);
  });

  it("reads a name through every specifier that carries one", () => {
    // A rename, a type only import and a re-export each name the export rather
    // than the local binding, which is the half a reader can get backwards
    // without any arm noticing.
    const subject = "../src/theme/patterns.ts";
    const source = [
      'import { alive as here } from "../src/theme/patterns";',
      'import type { Shape } from "../src/theme/patterns";',
      'export { hidden } from "../src/theme/patterns";',
      // **Renamed in both directions, which is what separates the two halves.**
      // An import names `imported` and a re-export names `local`, and in
      // `export { hidden } from` above the two identifiers are the same, so a
      // reader taking `exported` there passed. Found by the security seat.
      'export { buried as surfaced } from "../src/theme/patterns";',
    ].join("\n");

    expect(importedFrom("./x.ts", source, subject).sort()).toEqual([
      "Shape",
      "alive",
      "buried",
      "hidden",
    ]);
  });

  it("resolves the specifier rather than matching its text", () => {
    // Four spellings of one module, from three depths. A comparison on the
    // written specifier reads the first as a different module from the second.
    const subject = "../src/theme/patterns.ts";
    for (const [from, written] of [
      ["../src/theme/index.tsx", "./patterns"],
      [
        "../src/pages/AppearancePage/components/X.tsx",
        "../../../theme/patterns",
      ],
      ["./theme/patterns.test.ts", "../../src/theme/patterns"],
      ["./utils.tsx", "../src/theme/patterns.ts"],
    ] as [string, string][]) {
      expect(
        importedFrom(from, `import { alive } from "${written}";`, subject),
      ).toEqual(["alive"]);
    }
    // And a neighbour in the same directory is not this module.
    expect(
      importedFrom(
        "../src/theme/index.tsx",
        'import { alive } from "./palettes";',
        subject,
      ),
    ).toEqual([]);
    // **Nor is a module whose last two segments are the same two.** The whole
    // resolved path is compared, so a second `theme/patterns` anywhere else in
    // the tree is a different module. A resolver truncated to a basename pair
    // satisfies every other case here. Found by the security seat.
    expect(
      importedFrom(
        "./x.ts",
        'import { alive } from "../src/other/theme/patterns";',
        subject,
      ),
    ).toEqual([]);
  });

  it("does not let a module vouch for its own exports", () => {
    // A module importing from itself is legal and cyclic, and a name reached
    // only that way is reached by nobody. The subject is dropped from the
    // scope for that, and nothing else in any arm here would notice.
    const subject = "../src/theme/patterns.ts";
    expect(
      unreferenced(subject, "export const dead = 1;", [
        [subject, 'import { dead } from "./patterns";'],
      ]),
    ).toEqual(["dead"]);
  });

  it("keeps the value rule's table off every door but its own", () => {
    // **`lib/stores.PRODUCED_VALUE` is on the door for the guard alone**, which
    // its own docstring said and nothing enforced: a walk indexing the table
    // directly re-creates the direct access consolidating the three copies
    // removed, with every arm green. `producedValue` and `storeIdentifier` are
    // the door. Found by the design seat.
    const OWNER = "../src/lib/stores.ts";
    const reached = Object.entries(SOURCES)
      .filter(([path]) => path !== OWNER)
      .flatMap(([path, source]) => importedFrom(path, source, OWNER));

    expect(reached).not.toContain("PRODUCED_VALUE");
    // The readers that do go through the door, so a reader finding nothing is
    // distinguishable from a rule that holds.
    expect(reached).toContain("storeIdentifier");
  });

  it("refuses every way of naming the module that names no export", () => {
    // Each of these references the module and reaches no name, so answering
    // "imported nothing" would leave this rule green while it stopped guarding.
    //
    // **The message is asserted, not merely that something threw.** A namespace
    // and a default specifier carry no `imported`, so the unreadable specifier
    // fallback throws for them anyway: against one loose pattern both dedicated
    // refusals could be deleted with every arm green. Found by the design seat.
    const subject = "../src/theme/patterns.ts";
    const ways: [string, RegExp][] = [
      ['import * as every from "../src/theme/patterns";', /a namespace import/],
      ['import whole from "../src/theme/patterns";', /a default import/],
      ['export * from "../src/theme/patterns";', /an export star/],
      ['const m = await import("../src/theme/patterns");', /a dynamic import/],
    ];
    for (const [source, because] of ways) {
      expect(() => importedFrom("./x.ts", source, subject)).toThrow(because);
    }
  });

  it("ignores a source text import of the module", () => {
    // `?raw` is a different module id carrying a string, so it reaches no
    // export and is not a reference; it must not stop the run either, being
    // what half the guards in this tree read a module with.
    expect(
      importedFrom(
        "./x.ts",
        'import text from "../src/theme/patterns.ts?raw";',
        "../src/theme/patterns.ts",
      ),
    ).toEqual([]);
  });

  it("reads a name off every kind of declaration a module can export", () => {
    // **Wider than the subject writes today, on purpose.** `patterns.ts`
    // carries a function, an interface, a type alias and a const, so a reader
    // that dropped the specifier branch was invisible: nothing in this tree
    // exports through a bare `export { ... }` and the rule would silently stop
    // covering one the day somebody did. Found by the security seat.
    expect(
      exportedBy(
        "../src/theme/patterns.ts",
        [
          "export function a() {}",
          "export interface B { x: number }",
          "export type C = string;",
          "export const d = 1, e = 2;",
          "const f = 3;",
          "export { f };",
          'export { g as h } from "./y";',
        ].join("\n"),
      ).sort(),
    ).toEqual(["B", "C", "a", "d", "e", "f", "h"]);
  });

  it("refuses a door it cannot name", () => {
    // A default export publishes no name, so counting it as nothing exported
    // would hide it from the rule rather than report it.
    expect(() => exportedBy("../src/theme/x.ts", "export default 1;")).toThrow(
      /default export/,
    );
    expect(() =>
      exportedBy("../src/theme/x.ts", 'export * from "./y";'),
    ).toThrow(/re-exports/);
  });
});

/**
 * The module whose reason union this rule is about.
 *
 * One file rather than every union in the tree, and that is the honest scope:
 * this is the only union in `src` whose members are stored in state and
 * rendered later, which is what makes a payload on one of them reachable by
 * nothing.
 */
const SCAN_REASONS = "pages/ScanPage/hooks.ts";

/**
 * What `name` is declared as in `source`, or null.
 *
 * An interface answers a `TSTypeLiteral` over its own body, so a caller reading
 * properties does not have to know which of the two spellings it met. That is
 * not a convenience: an arm spelled as an interface is one of the three ways
 * measured past the first draft of this rule.
 *
 * **The last declaration of the name in the file wins, function bodies
 * included**, which is a property of walking by name rather than by scope: a
 * type declared inside a function and sharing an arm's name is the one
 * resolved. Unreached by anything in this tree and cheap to say.
 */
function declaredIn(path: string, source: string, name: string): Node | null {
  let found: Node | null = null;
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (!isNode(value)) return;
    const named = isNode(value.id) && text(value.id.name) === name;
    if (
      named &&
      value.type === "TSTypeAliasDeclaration" &&
      isNode(value.typeAnnotation)
    )
      found = value.typeAnnotation;
    if (named && value.type === "TSInterfaceDeclaration" && isNode(value.body))
      found = { type: "TSTypeLiteral", members: value.body.body };
    for (const key of Object.keys(value)) walk(value[key]);
  };
  walk(parseAst(source, { lang: langOf(path) }));
  return found;
}

/**
 * A type as its own declaration in this file spells it.
 *
 * A reference to a type declared elsewhere in the same module is followed;
 * anything else, an import included, comes back as it was. The hop count is
 * bounded rather than trusted, because `type A = B; type B = A` is a legal
 * thing to write and a rule that hangs is a suite that has no verdict.
 *
 * **Eight is a ceiling and not a guarantee, and it fails safely.** A chain
 * longer than this leaves the arm looking unresolved, which the pre-flight
 * refuses rather than the payload rule: measured once at nine, red in 55ms.
 * Nothing in either sweep covers the depth itself, so that is stated rather
 * than tested, and no chain anybody writes comes near it.
 */
function resolvedIn(path: string, source: string, node: Node): Node {
  let here = node;
  for (let hops = 0; hops < 8; hops += 1) {
    if (here.type !== "TSTypeReference" || !isNode(here.typeName)) return here;
    const name = text(here.typeName.name);
    const next = name === null ? null : declaredIn(path, source, name);
    if (next === null) return here;
    here = next;
  }
  return here;
}

/** The members of a union type, or the type itself where it is not one. */
function armsOf(alias: Node): Node[] {
  if (alias.type !== "TSUnionType") return [alias];
  const types = alias.types;
  return (Array.isArray(types) ? types : []).filter(isNode);
}

/** The string literals a union of literal types is made of. */
function literalsOf(alias: Node): string[] {
  return armsOf(alias).flatMap((arm) =>
    arm.type === "TSLiteralType" &&
    isNode(arm.literal) &&
    typeof arm.literal.value === "string"
      ? [arm.literal.value]
      : [],
  );
}

/** One `{ name: type }` pair per property of an object type. */
function propertiesOf(arm: Node): { name: string; type: Node }[] {
  const members = arm.members;
  return (Array.isArray(members) ? members : []).flatMap((member) => {
    if (!isNode(member) || member.type !== "TSPropertySignature") return [];
    if (!isNode(member.key) || !isNode(member.typeAnnotation)) return [];
    const name = text(member.key.name) ?? text(member.key.value);
    const type = member.typeAnnotation.typeAnnotation;
    return name !== null && isNode(type) ? [{ name, type }] : [];
  });
}

/** The type of an arm's `kind`, which is what discriminates it. */
function discriminantOf(arm: Node): Node | null {
  return propertiesOf(arm).find((one) => one.name === "kind")?.type ?? null;
}

/** What an arm's `kind` says it is, for a failure message. */
function kindOf(arm: Node): string {
  const kind = discriminantOf(arm);
  if (kind === null) return "an arm with no kind";
  if (kind.type === "TSLiteralType" && isNode(kind.literal))
    return text(kind.literal.value) ?? kind.type;
  if (kind.type === "TSTypeReference" && isNode(kind.typeName))
    return text(kind.typeName.name) ?? kind.type;
  return kind.type;
}

/**
 * A scan reason is a name, and three arms carry anything else.
 *
 * **What the type system was measured not to say.** A reason with no sentence
 * is a compile error, which is the whole of why `ScanPage/hooks.ts` stores
 * names instead of prose. Two things it does not refuse:
 *
 * - **A payload on an arm that is already a name reaches nothing.**
 *   `{ kind: "unreadable"; at: number; of: number }` compiles clean, because
 *   `reasonText`'s last line narrows to `NamedScanReason` and
 *   `REASONS["unreadable"]` resolves whatever else the arm carries. The numbers
 *   never reach a screen. Hanging a value on a name that is already there is
 *   the shortest path for an author who needs one, which is why `ScanReason`'s
 *   own docstring sends them to a kind of their own instead.
 * - **A second free text arm**, added with its own branch in `reasonText`,
 *   compiles clean too. One free text arm is a rule, and the first one is what
 *   makes free text look ordinary.
 *
 * **The rule counts and names, and never reads a type, which is what closes
 * the family.** It asserts the arms carrying anything besides `kind`, and what
 * each of them carries, by name. A rule that asked whether a property is
 * `string` held for the keyword and for nothing else: `type ServerWords =
 * string` and `detail: { message: string }` both went past it with the suite
 * green, and `string | null`, `string[]` and a template literal are the same
 * move again. Reading no type at all is blind to every one of them at once.
 *
 * **The names and not only the arms**, because the first draft of this had
 * exactly the weakness it was written to remove: it saw which arms carry a
 * payload and never how many properties one carries, so `detail?: string`
 * added beside `failure` on the `file` arm was a second free text store in
 * queue state, compiling clean with the suite green. Being an equality it is
 * red in both directions, so the interpolating arm the union anticipates is
 * red too, whatever it carries.
 *
 * **An arm spelled as a local interface or alias is resolved first**, so the
 * payload rule judges it rather than the pre-flight. Leaning on the pre-flight
 * would be the fragile arrangement: it is the assertion somebody relaxes the
 * day a legitimately named arm arrives.
 *
 * **The residues, stated rather than discovered.** A type swapped on a
 * property this already names is outside the rule: `failure` may become
 * anything at all and this stays green, which is the price of reading no type.
 * **The gate still refuses it**, because all three named payloads are consumed
 * at a typed site in `reasonText`: measured, `failure: string` is `TS7053` at
 * the `FILE_FAILURES` lookup and `message: number` is `TS2322` there and at
 * four writer sites. So this is a residue of the rule and not an open door, and
 * the reason to say so is that a residue read as a door is the next person's
 * excuse to widen something.
 * And an arm the resolution cannot reach, which is one spelled as a type
 * imported from another module, fails the pre-flight rather than this rule and
 * so names the wrong defect; no read of this file alone can do better.
 *
 * **Its blind spot, which is the whole of the other half**: it reads the
 * declaration. It says nothing about what `reasonText` does with a payload once
 * one exists, and nothing about a reason rendered anywhere but there.
 *
 * A type could not do this half: refusing a payload needs an exact object
 * constraint, which in TypeScript is written by naming the keys the other arms
 * carry, and an enumeration of an open set is what this file's guards keep
 * paying for.
 */
describe("a scan reason is a name, and three arms carry anything else", () => {
  function union(): { names: string[]; named: Node; arms: Node[] } {
    const source = SOURCES[`../src/${SCAN_REASONS}`];
    if (source === undefined) throw new Error(`${SCAN_REASONS} is not here`);
    const named = declaredIn(SCAN_REASONS, source, "NamedScanReason");
    const reason = declaredIn(SCAN_REASONS, source, "ScanReason");
    if (named === null || reason === null)
      throw new Error(`${SCAN_REASONS} declares no ScanReason union`);
    const resolve = (node: Node) => resolvedIn(SCAN_REASONS, source, node);
    return {
      names: literalsOf(named),
      named,
      arms: armsOf(resolve(reason)).map(resolve),
    };
  }

  it("finds the union it is about", () => {
    // **The rule reads two declarations by name**, so a rename or a move takes
    // its subject away, and a guard with no subject passes over nothing. This
    // is what fails instead.
    const { names, named, arms } = union();
    expect(names.length).toBeGreaterThan(0);
    expect(arms.length).toBeGreaterThan(1);
    // **Every name is a literal**, which is what makes the reference below
    // worth checking: `type NamedScanReason = string` would leave the arm that
    // points at it discriminated by nothing.
    expect(names).toHaveLength(armsOf(named).length);
    for (const arm of arms) {
      expect(arm.type).toBe("TSTypeLiteral");
      expect(propertiesOf(arm).map((one) => one.name)).toContain("kind");
      // **The discriminant is closed**, here rather than inside the payload
      // rule: a `kind` widened to `string` is a defect of its own, and the rule
      // that goes red should be the one that names it. The compiler refuses it
      // too, at the `REASONS` lookup.
      const kind = discriminantOf(arm);
      const closed =
        (kind?.type === "TSLiteralType" &&
          isNode(kind.literal) &&
          typeof kind.literal.value === "string") ||
        (kind?.type === "TSTypeReference" &&
          isNode(kind.typeName) &&
          text(kind.typeName.name) === "NamedScanReason");
      expect(closed ? "closed" : `${kindOf(arm)} is not a closed kind`).toBe(
        "closed",
      );
    }
  });

  it("lets three arms carry one named payload each and no others", () => {
    const { arms } = union();
    const carrying = arms.filter((arm) =>
      propertiesOf(arm).some((one) => one.name !== "kind"),
    );

    // **What each arm carries, not only which arms carry something**, which is
    // the dimension the shape before this was blind in: it read the set of arms
    // and never how many properties one of them holds, so `detail?: string`
    // beside `failure` on the `file` arm was a second free text store in queue
    // state with the whole suite green. Optional is the spelling that got
    // through; required is refused by the compiler at five sites.
    //
    // Sorted because the rule is which and not in what order, and an equality
    // so it is red in both directions: a fourth arm, a second property on one
    // of these three, and one of these three losing what it carries.
    expect(
      carrying
        .map(
          (arm) =>
            `${kindOf(arm)}: ${propertiesOf(arm)
              .map((one) => one.name)
              .filter((name) => name !== "kind")
              .sort()
              .join(",")}`,
        )
        .sort(),
    ).toEqual(["audio: failure", "file: failure", "server-said: message"]);
  });
});

/**
 * What a catalogue answered about a queued row is read in one file.
 *
 * **The rule the queue's own figures rest on.** Every count the scan page puts
 * on a control is derived in `pages/ScanPage/hooks.ts` by a predicate that file
 * owns, and the component that draws them renders them and may not recompute
 * them: a predicate written twice is a button offering to look up twelve beside
 * a run that looks up nine. The queue component held the last exception, one
 * `entries.some` deciding by hand whether to tell a member that catalogues list
 * few ebooks, and it could have said so beside a queue where no catalogue had
 * answered nothing.
 *
 * **Read off the stripped source**, so a docstring naming the field is not a
 * reader. That is what lets every paragraph in this tree discuss it freely.
 *
 * **What it matches, exactly, because a claim of exactness here has been wrong
 * twice.** A comparison whose one side is the field, with or without a receiver
 * in front, and whose other side is one of the answers the union declares or
 * `undefined`. **In either order**, **loose or strict**, and **in any of the
 * three quotes this language spells a string with**. Every one of those three
 * widenings was an evasion somebody ran: the field on the left only,
 * `===` only, and double quotes only, which the formatter writes and a hand
 * does not have to. **The lint rules that would refuse the reversed and the
 * loose spellings both live in a category this config does not enforce**, so
 * there is nothing else watching either of them. **And the other side is bound
 * to the union's own literals**, because a rule matching any right hand side
 * reddens on an unrelated field of the same ordinary English word, which it
 * did.
 *
 * **What goes past it, described rather than listed.** A comparison against a
 * value held in a variable, a `switch`, and a read handed to another function.
 * A destructure is not among them: the field keeps its name, so the comparison
 * after it is matched. What holds the rest is that there is nothing to read
 * them from, since the figures arrive counted, and that is a property of the
 * interface rather than of this rule.
 */
describe("what a catalogue answered is read in one file", () => {
  /** The file that owns the queue's rows, and every rule over them. */
  const QUEUE = "pages/ScanPage/hooks.ts";

  /**
   * A comparison between a row's stored answer and one of the answers there
   * are, in either order, over stripped source.
   *
   * Built from the union's own arms rather than written out, so an answer added
   * to it is covered here by arriving rather than by somebody remembering.
   */
  function comparesAnAnswer(): RegExp {
    const source = SOURCES[`../src/${QUEUE}`];
    const declared =
      source === undefined
        ? null
        : declaredIn(QUEUE, source, "CatalogueAnswer");
    // **Every quote this language has, not the one the formatter writes.** A
    // backticked answer is the same comparison and passed the version that
    // listed double quotes alone.
    const answers = declared === null ? [] : literalsOf(declared);
    const values = [
      ...answers.flatMap((answer) => [
        `"${answer}"`,
        `'${answer}'`,
        `\`${answer}\``,
      ]),
      "undefined",
    ]
      .map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|");
    const field = "(?:[\\w$]+\\.)*\\banswered\\b";
    // **Loose equality as well as strict**, because the rule that would
    // otherwise refuse `==` lives in a lint category this tree does not
    // enforce, which is the same reason the reversed spelling needed covering.
    // Spelled so that a single `=` cannot match: an assignment is not a
    // comparison, and a class of `!` or `=` followed by an optional one reads
    // one.
    const compares = "(?:!==?|===?)";
    return new RegExp(
      `(?:${field}\\s*${compares}\\s*(?:${values})|(?:${values})\\s*${compares}\\s*${field})`,
    );
  }

  function readers(): string[] {
    const compares = comparesAnAnswer();
    return entries()
      .filter(([path, source]) =>
        compares.test(withoutProse(source, langOf(path))),
      )
      .map(([path]) => path)
      .sort();
  }

  it("finds the file it is about", () => {
    // **A rule with no subject passes over nothing**, which is what a rename or
    // a move would leave behind: the rule is that one file reads the field, and
    // a tree where no file reads it satisfies that vacuously. This is what goes
    // red instead, and it is checked against the declaration as well as the
    // reading, so a queue that kept the readings and lost the union is caught.
    const source = SOURCES[`../src/${QUEUE}`];
    expect(source).toBeDefined();
    const answers = declaredIn(QUEUE, source!, "CatalogueAnswer");
    expect(answers).not.toBeNull();
    expect(literalsOf(answers!).length).toBeGreaterThan(1);
    expect(readers()).toContain(QUEUE);
  });

  it("is read in no other module", () => {
    expect(readers()).toEqual([QUEUE]);
  });
});

/**
 * Browser storage is reached through one door, and every other reader is named
 * along with the keys it may touch.
 *
 * **Stated as an exclusion, because an inclusion list is what goes stale.** A
 * guard that pinned the declared keys would say nothing about a sixth
 * preference added beside the door instead of through it, which is the shape
 * this rule exists for: five modules each spelled their own key, their own
 * `try`, their own "absence means the default", and the page that read two of
 * them carried a counter to make a write visible to its own next render.
 *
 * **Named by key and not by file**, and that is the difference between this
 * rule and the one it replaced. A file level exemption is one a sixth
 * preference walks straight through: four lines of
 * `localStorage.setItem("librarySort", ...)` inside an already exempt module
 * satisfies it, and `theme/appearance.ts` is exactly where somebody would put a
 * per device wallpaper key. The exemption is file shaped where the rule is key
 * shaped, so the keys are declared and the arguments are read back out.
 *
 * **What each exemption buys is written beside it**, so the list cannot outlive
 * its reason: two arms below fail when a file named here stops reaching storage
 * at all, or stops touching a key it declares, which is how a suppression list
 * stops being one.
 *
 * Read off the stripped source, so a module that only mentions storage in a
 * docstring is not a reader. That is what lets the prose above name
 * `localStorage` freely, and it is why the match can be the bare identifier.
 *
 * **Its blind spots, stated rather than left to be discovered, and the list is
 * shorter than it was because the first version of this sentence was
 * reassuring about the case that was actually open.** It said what was left was
 * an argument no literal resolves, and that such an argument is reported rather
 * than dropped, which is true and was not the hole: a property access named no
 * argument at all, so the key was absent rather than reported, and three
 * spellings of it passed every arm. A comment defending the case that is covered
 * is how a reviewer agrees with a guard and the hole survives.
 *
 * **This paragraph was wrong twice, in the same way both times**, which is why
 * the rule no longer works by naming spellings. It said the alias needed a
 * parser, then said bracket access did; each was one pattern, and each time the
 * sentence defended the case that was covered while the open one went
 * unmentioned. Three rounds produced four spellings, every one found by whichever
 * seat had not written the previous fix, which is the tell for a guard
 * enumerating something open.
 *
 * **So the last arm counts rather than enumerates.** Every mention of a storage
 * object in the stripped source is either explained, by a member access or by a
 * bracket holding a literal, or reported. A computed bracket, a reference passed
 * on under another name, and a storage object handed to something else are all
 * unexplained mentions, so all three fail without being named. Following a
 * reference needs a parser; noticing one was taken does not.
 *
 * What is left, and is not bought here:
 *
 * * **A string literal in code naming the identifier**, such as an error
 *   message. It reads as an unexplained mention and costs one row here. There is
 *   none today, and the sentence near `pages/hooks.ts`'s own docstring is the
 *   near miss: prose is stripped, so it does not count, and this rule's
 *   correctness now rests on the stripper in a way the member pattern did not.
 * * **Which key an unexplained reach names**, as opposed to that there is one.
 *   This reports the reach and fails the declared set, so nothing passes; it
 *   cannot tell you what was stored, and it is not trying to.
 */
describe("browser storage is reached through one door", () => {
  const THE_DOOR = "lib/preference.ts";

  const NOT_A_PREFERENCE: Record<string, { keys: string[]; because: string }> =
    {
      "api/mutator.ts": {
        keys: ["endpaper.edge-reload", "token", "user"],
        because:
          "the token and the identity, which are not a choice anybody made, plus a per tab reload marker whose lifetime is the document",
      },
      "pages/hooks.ts": {
        keys: ["user"],
        because: "reads the identity the mutator owns, and writes none of it",
      },
      "i18n/index.tsx": {
        keys: ["locale"],
        because:
          "the locale, whose one reader and one writer are the same provider, so a subscription would buy it nothing",
      },
      "theme/appearance.ts": {
        keys: ["appearance", "theme"],
        because:
          "a cache of a value the account owns: one key holds a record over accounts and a pointer to the last one, and the server is the authority",
      },
    };

  const REACHES_STORAGE = /\b(?:localStorage|sessionStorage)\b/;
  const REACHES_STORAGE_ANYWHERE = /\b(?:localStorage|sessionStorage)\b/g;
  // **The lookahead is what stops a built key resolving to its first token.**
  // Without it `setItem(STORAGE_KEY + "." + id, value)` reads as the declared
  // prefix and passes, and a key per account is the obvious next refactor of the
  // appearance cache. An argument that continues into an expression is not
  // bounded here, and `REACHES_AN_ITEM_CALL` below is what stops the tightening
  // from quietly matching fewer calls instead of more.
  const TOUCHES_A_KEY =
    /\b(?:localStorage|sessionStorage)\s*\??\.\s*(?:get|set|remove)Item\s*\(\s*(?:(["'`])([^"'`]*)\1|([A-Za-z_$][\w$]*))(?=\s*[,)])/g;
  const REACHES_AN_ITEM_CALL =
    /\b(?:localStorage|sessionStorage)\s*\??\.\s*(?:get|set|remove)Item\s*\(/g;
  const NAMES_A_LITERAL =
    /\bconst\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*(["'`])([^"'`]*)\2/g;
  const REACHES_A_MEMBER =
    /\b(?:localStorage|sessionStorage)\s*\??\.\s*([A-Za-z_$][\w$]*)/g;
  const REACHES_A_BRACKET =
    /\b(?:localStorage|sessionStorage)\s*\??\[\s*(["'`])([^"'`]*)\1\s*\]/g;

  function readers(): [string, string][] {
    return entries()
      .map(([path, source]) => [path, withoutProse(source, langOf(path))])
      .filter(([, code]) => REACHES_STORAGE.test(code!)) as [string, string][];
  }

  function codeOf(path: string): string {
    const found = readers().find(([one]) => one === path);
    return found?.[1] ?? "";
  }

  /**
   * The keys one file names, with `const X = "literal"` in the same file
   * resolved, and anything else reported as itself rather than dropped.
   *
   * **Two passes, and the second one is the reason this rule works at all.**
   * `Storage` is a proxy, so `localStorage.librarySort = value` and
   * `delete localStorage.librarySort` store and remove a key without naming
   * `setItem` at all. Reading only the method calls left the whole of that class
   * open **inside an already exempt module**, which is precisely what a key
   * shaped exemption exists to close: measured, three spellings of a sixth
   * preference passed every arm against all four exempt files.
   *
   * So any member that is not one of the six `Storage` offers is a property
   * access, which means a key, and it is reported rather than ignored. An
   * exclusion over a closed interface rather than a list of the spellings
   * somebody thought of.
   */
  /**
   * The members that address a key, or address none and read nothing out.
   *
   * **`clear` is deliberately not here**, though it is part of the interface.
   * The partition this rule wants is not "is it `Storage`", it is "can it change
   * what is stored without naming a key", and `clear` is the only member that
   * can: `getItem`, `setItem` and `removeItem` name one and the first pass reads
   * it, `key` and `length` name none and change nothing, and `clear` removes
   * every key in the origin, this application's eight preferences and the four
   * the exempt modules own alike. Leaving it in the list made it invisible to
   * both passes.
   *
   * There is a real path to somebody writing it: `docs/decisions.md` records
   * that a sign out leaves the saved searches and the last location behind and
   * prescribes clearing both stores in `clearSession()`, and the shortest
   * reading of that is `localStorage.clear()` inside an exempt module. Reported
   * rather than refused, so it needs a row and a reason here.
   */
  const THE_STORAGE_API = ["getItem", "setItem", "removeItem", "key", "length"];

  function keysTouchedIn(code: string): string[] {
    const literals = new Map<string, string>();
    for (const match of code.matchAll(NAMES_A_LITERAL))
      literals.set(match[1]!, match[3]!);

    const keys = new Set<string>();
    for (const match of code.matchAll(TOUCHES_A_KEY)) {
      if (match[2] !== undefined) keys.add(match[2]);
      else if (match[3] !== undefined)
        keys.add(literals.get(match[3]) ?? `${match[3]} (unresolved)`);
    }
    for (const match of code.matchAll(REACHES_A_MEMBER)) {
      const member = match[1]!;
      if (!THE_STORAGE_API.includes(member))
        keys.add(`${member} (property access)`);
    }
    // **Every bracket reach is reported, whichever half of the interface it
    // names.** `localStorage["librarySort"] = v` is a key, and
    // `localStorage["setItem"](…)` is a method whose key argument the patterns
    // above cannot see, so neither may pass quietly: both fail the declared set
    // rather than being absent from it.
    for (const match of code.matchAll(REACHES_A_BRACKET))
      keys.add(`${match[2]!} (bracket access)`);

    // **A call the key pattern could not bound is reported rather than missing.**
    // Tightening a pattern makes it match less, and a rule that reads fewer
    // calls than a file makes looks cleaner while seeing less. Counting the
    // calls and the reads against each other is what makes the tightening safe.
    const calls = [...code.matchAll(REACHES_AN_ITEM_CALL)].length;
    const read = [...code.matchAll(TOUCHES_A_KEY)].length;
    if (read < calls) keys.add("a key this rule could not read");

    // **Every mention of a storage object is accounted for, or reported.** This
    // is the arm that stops the rule being a list of spellings. It went through
    // four of them in three rounds, dotted member, property write, bracket
    // literal and computed bracket, each found by whichever seat had not written
    // the previous fix, which is the tell for a guard enumerating something open:
    // the answer is structural, never a fifth alternative.
    //
    // So rather than naming the ways a key can be reached, this counts the ways
    // this rule **explained** what it saw. A member access and a bracket with a
    // literal each account for one mention; anything left over is a reach nobody
    // here can read, which covers a computed bracket, a reference passed on under
    // another name, and a storage object handed to something else, in one arm
    // rather than three. Following a reference needs a parser; noticing that one
    // was taken does not.
    const mentions = [...code.matchAll(REACHES_STORAGE_ANYWHERE)].length;
    const explained =
      [...code.matchAll(REACHES_A_MEMBER)].length +
      [...code.matchAll(REACHES_A_BRACKET)].length;
    if (explained < mentions)
      keys.add("a storage reach this rule could not read");
    return [...keys].sort();
  }

  it("reads the source tree at all", () => {
    // A glob that matched nothing would make every assertion below pass for
    // ever, and this rule's whole subject is a module nobody noticed arriving.
    expect(readers().length).toBeGreaterThan(0);
  });

  it("is reached by the door and by nothing that is not named here", () => {
    const named = [THE_DOOR, ...Object.keys(NOT_A_PREFERENCE)];
    expect(
      readers()
        .map(([path]) => path)
        .filter((path) => !named.includes(path)),
    ).toEqual([]);
  });

  it("names nothing that has stopped reaching storage", () => {
    const reaching = readers().map(([path]) => path);
    const named = [THE_DOOR, ...Object.keys(NOT_A_PREFERENCE)].sort();
    expect(named.filter((path) => !reaching.includes(path))).toEqual([]);
  });

  it("lets an exempt file touch only the keys it declares", () => {
    // The arm the file shaped version did not have. A sixth preference added
    // inside an exempt module fails here by name.
    for (const [path, { keys }] of Object.entries(NOT_A_PREFERENCE)) {
      expect(keysTouchedIn(codeOf(path)), path).toEqual([...keys].sort());
    }
  });

  it("keeps the door from spelling a key of its own", () => {
    // Every key it touches arrives from a declaration. A literal here would be
    // a preference the door had swallowed rather than published.
    expect(
      keysTouchedIn(codeOf(THE_DOOR)).filter(
        (key) => !key.endsWith("(unresolved)"),
      ),
    ).toEqual([]);
  });

  it("reaches storage by a member this rule can read", () => {
    // The second pass, asserted on the shipped tree rather than only on the
    // evasions it was written for: every member any reader names is one of the
    // six, so no exempt file is already touching a key by property access and
    // the arm above is comparing like with like.
    const members = new Set<string>();
    for (const [, code] of readers())
      for (const match of code.matchAll(REACHES_A_MEMBER))
        members.add(match[1]!);
    expect(
      [...members].filter((one) => !THE_STORAGE_API.includes(one)),
    ).toEqual([]);
  });

  it("claims none of the keys an exempt module owns", () => {
    // **The two lists tied together, because they were kept apart.** The door
    // reserves the names a preference may not claim; this rule names the keys the
    // exempt modules touch. A key on one list and not the other is a name a
    // preference can claim with the collision refused nowhere, so every exempt
    // key is offered to the door here and has to be refused.
    for (const { keys } of Object.values(NOT_A_PREFERENCE)) {
      for (const key of keys) {
        expect(
          () =>
            declarePreference(key, {
              decode: (raw) => raw,
              encode: (value) => value,
              fallback: () => "",
            }),
          key,
        ).toThrow(/not a preference/);
      }
    }
  });

  it("gives every exemption a reason rather than a bare path", () => {
    // A path with an empty reason is the entry somebody adds in a hurry, and it
    // is indistinguishable from a considered one once it is in the list.
    //
    // **Non empty, and deliberately not a length.** A word count is a proxy for
    // "was this thought about", which nothing can measure, and it was wrong on
    // its first run: the door's own entry read "the door itself", which is the
    // whole reason and three words long. A threshold that refused it would have
    // been satisfied by padding.
    for (const [path, { because }] of Object.entries(NOT_A_PREFERENCE)) {
      expect(because.trim(), path).not.toBe("");
    }
  });
});

/**
 * Every module specifier a file names, whichever construct named it.
 *
 * **Not `importedFrom`, and the difference is the question rather than the
 * module.** That helper answers which *names* one module takes from another and
 * refuses a nameless reach by throwing, a default import among them, because
 * the rule it serves is about reaching a named export. Every component here is
 * a default export, so asking it which names a page took from a component would
 * refuse on the ordinary case. This asks which module was named at all, and to
 * that question a default import is an answer.
 *
 * **Both are used in this block, on different subjects**, which is the thing to
 * read before assuming one is redundant: this one is asked about a component,
 * where a default import is the norm, and `importedFrom` is asked about the
 * translation door, which exports only names. A refusal from it there is an
 * answer rather than an error, and the arm that asks says so.
 *
 * **It reads a `source` node, so it sees every construct that carries one**:
 * a plain, type only or side effect import, a re-export, an `export *`, and a
 * dynamic `import()` in value or type position. **What carries no `source` node
 * is outside it**, and the one such form reachable here is `import.meta.glob`,
 * which is first class in this bundler and is how this very file reads the
 * tree. A registry globbing its own assets would name no module this can see.
 */
function specifiersOf(path: string, source: string): string[] {
  const out: string[] = [];
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (!isNode(value)) return;
    if (isNode(value.source)) {
      const from = text(value.source.value);
      if (from !== null) out.push(from);
    }
    for (const key of Object.keys(value)) walk(value[key]);
  };
  walk(parseAst(source, { lang: langOf(path) }));
  return out;
}

/**
 * `src/components/` holds only components that belong to no one page.
 *
 * House rule 4, which until this rule existed was enforced by a reviewer
 * noticing. The component it let through served a single page and said so in
 * its own strings.
 *
 * **It names no domain word, and that is the whole design.** The obvious rule
 * greps the folder for a book, a loan and a tag. `Icon.tsx` names `book`,
 * `bookmark` and `tag` as glyph names, so the obvious rule is red on a drawing
 * vocabulary the day it is written, and the fix that adds a fourth and fifth
 * spelling is the shape this tree has watched fail repeatedly: the storage door
 * rule went through four spellings in three rounds before it stopped naming
 * them. A list of forbidden words is a list somebody has to think of.
 *
 * So neither arm below knows what a book is.
 *
 * **The vocabulary arm** asks a module which message namespaces it states, and
 * then asks the tree how many page folders state the same ones. A namespace
 * exactly one page speaks is that page's property, and a component speaking it
 * is that page's component wherever the file happens to sit. This reaches a
 * book, a loan and a tag for free, and reaches every other namespace nobody
 * would have thought to list.
 *
 * **The reach arm** states what a general component is allowed to name, and
 * reports everything else with the specifier it named. Stated as an allowance
 * because the refusals are open ended: the next domain module to arrive is not
 * on any list of forbidden ones. It is what catches a component that carries a
 * page's knowledge in its *types* while saying nothing at all.
 *
 * **Their blind spots intersect rather than covering each other, and that is
 * the first thing to know about this rule.** Both detect something a module
 * *names*. A component that states no namespace and imports nothing but the
 * framework and a sibling satisfies both unconditionally, whatever it is about,
 * and most of this folder is green for that reason rather than by being
 * general. Both still run, because each reaches a class the other does not: one
 * speaking a page's language, one carrying a page's knowledge in its types.
 *
 * ## What it cannot see, as properties rather than as a list
 *
 * **A module that names nothing is outside both arms, and that is the largest
 * hole rather than a residue.** Its knowledge then lives in prop names and in
 * markup, where reaching it needs the word list this rule exists to avoid. A
 * component one tier down, reached by one page and stating no namespace, passes
 * on arrival if somebody moves it up; so does this rule's own motivating
 * violation if its labels are lifted to props, which is an ordinary
 * accessibility refactor rather than an evasion.
 *
 * **It reads what a module states, never what it renders.** A whole domain
 * object arriving through a generic or untyped prop is outside both arms, and
 * so is a component whose only domain knowledge is a convention its caller
 * holds. Following a value needs a dataflow pass; noticing a name does not.
 *
 * **The vocabulary arm's verdict is a property of the whole tree rather than of
 * this folder.** It goes red when a page folder changes and green when a page
 * is copied, so a failure naming a component can have been caused where nobody
 * touched it. That is why the message names the namespace and its speakers
 * rather than the component alone.
 *
 * **Two consequences of counting page folders, both verdicts rather than
 * definitions.** The shell is not a page, so a namespace it shares with exactly
 * one page counts one and is reported. And the margin is thin where a namespace
 * has exactly two speakers: retiring either one reports a component nobody
 * edited. Both are the rule working, and both are why the message has to carry
 * the cause.
 *
 * **A renamed translation binding is reached only indirectly.** Both patterns
 * key on the local name, so a destructured rename empties the count and the
 * shortfall check that is supposed to keep it honest, together. What closes it
 * is the door, which cannot be renamed away: a module that opens the door and
 * states nothing is reported.
 *
 * **Generality is deliberately not enforced here, and that is a refusal rather
 * than a gap.** The bar at `src/components/index.ts` has a second half, that a
 * component be useful to more than one page. Measured over this folder, the
 * predicate "reached by fewer than two page folders", measured by which
 * component a page folder names in its import from the barrel rather than by
 * module reachability, reports four components,
 * `CollapsibleSection` among them, which is correctly general and whose every
 * other mention in the tree is a comment.
 *
 * **What refuses it is the exemption it would need, and the ground is churn
 * rather than falsifiability.** A row could state the page folders that reach a
 * component today, which is observable and could be pinned the way the storage
 * rule pins a key set, so the first version of this paragraph was wrong to say
 * no arm could falsify one. The cost is that a reach set moves on ordinary
 * work: every new page that imports the button edits the table, so the table is
 * rubber stamped within a month and a suppression nobody reads is worse than no
 * arm at all. Refused on that, and not on any confidence in review: review is
 * what let this rule's own violation through.
 *
 * **The naive form of that arm is worse than absent, which is worth keeping
 * here because it is where somebody would start.** Computed module to module,
 * rather than by the binding a page names, every component in the folder is
 * imported by the barrel and the barrel is imported by every page folder
 * without exception, so all of them reach all of them and the arm is vacuous
 * rather than merely weak. Measured while this rule was being designed: the
 * violation it exists for scored the full set while sitting in the wrong folder.
 */
describe("a general component carries no one page's knowledge", () => {
  const FOLDER = "components/";

  // **One module, and each arm derives the form it can ask in.** The allowance
  // list matches a specifier as written; the door arm asks which names a module
  // took, which needs the resolved module id instead. A regex only one of those
  // two questions can be put with is the version that drifts, so the module is
  // the constant and the spelling is derived from it.
  //
  // **One home for the module's identity, and no further than that.** The
  // derived spelling also encodes this folder's depth, which the module id does
  // not, so the two arms part company on the same module written from one tier
  // down: the door arm resolves `../../i18n` correctly and the allowance list
  // reports it. That is the already stated loud direction rather than a second
  // defect, and the derivation is not to be trusted past the identity.
  const THE_I18N_MODULE = "i18n";
  const THE_TRANSLATION_DOOR = new RegExp(`^\\.\\./${THE_I18N_MODULE}$`);
  /**
   * Which names a general component may take from the translation door.
   *
   * **Module granularity is not enough here, and one export is the reason.**
   * The door exports a function that renders a library tag, so a component
   * importing it renders a tag wherever the file happens to sit, which is the
   * thing this whole block exists to stop. Allowing the module allowed that
   * name with it, and every arm here was silent on it.
   *
   * **It is the names the folder takes and nothing held in reserve.** The
   * allowance list above has an arm refusing a permission no module uses, on the
   * ground that it is a hole opened on a guess. A second standard for the same
   * kind of list, thirty lines apart, would be the inconsistency rather than the
   * exception, so `allows no name the folder does not already take` holds this
   * one to it too.
   *
   * **A pre-authorised name is not free, and that is the measurement that
   * settled the list rather than an argument about taste.** A message key type
   * sat here for one round, admitted so that a component taking a key and
   * letting its caller translate would not be refused on arrival. It made the
   * **typed** spelling of the key literal shape green: a block of key literals
   * typed against it, with no translation call anywhere in the file, passes
   * every arm in this block while carrying the exact literal that makes the
   * violation this rule exists for fail. Refusing on arrival costs one line in
   * the diff of whoever writes that component, at the moment the trade is
   * visible to a reviewer.
   *
   * **Refusing it does not close that family, and saying it did would be the
   * claim this block keeps removing.** Write the same literals as a plain
   * constant naming nothing, and the module passes every arm with this list or
   * without it, under the blind spot stated first in the docstring above: a
   * module that names nothing is outside all of this. What the refusal buys is
   * narrower and still worth having, that the typed spelling no longer rides in
   * free on a permission granted for something else.
   *
   * **Why an inclusion is safe here, and it is not the reason it resembles.**
   * The storage rule partitions an interface this repository cannot change, so
   * closedness is a property of the specification and is what makes the
   * enumeration safe there. This partitions a module the repository edits
   * whenever anybody touches translation, so closedness does none of that work.
   * What makes it safe is the direction of failure on growth, a new export of
   * the door arriving reported and named rather than admitted, together with the
   * arm that recomputes this list against the door's own exports.
   *
   * **Everything else the door publishes is refused, the tag renderer among
   * them.** The refused half is deliberately not accounted for name by name: an
   * accounting of it goes stale against the door's export clause and is then
   * read as current, and a reader who agrees with a list that is one member
   * short leaves that member unexamined. The arm below recomputes the allowed
   * half against the door instead.
   */
  const THE_TRANSLATION_API = ["Translate", "useTranslation"];

  /**
   * Is this the helper's own refusal of a nameless reach, about this file?
   *
   * **Anchored and bound to the path**, because the alternative is a substring
   * test against a stringified unknown: anything whose text happened to carry
   * the phrase would then read as an opened door, a wrapper or a nested frame
   * included. The helper writes `${path} reaches ${subject} by ${what}`, so both
   * halves of the prefix are already known here and there is no reason to match
   * on less than the whole of it.
   */
  function takesTheDoorWhole(path: string, refusal: unknown): boolean {
    return (
      refusal instanceof Error &&
      refusal.message.startsWith(`${path} reaches ${THE_I18N_MODULE} by `)
    );
  }

  // **Stated as what is allowed.** A general component needs the framework, a
  // sibling in its own folder, the translation door, and the transport error
  // that names no entity. Anything else is reported by name, so a generated
  // model, a page module or a domain helper fails the day it is imported
  // without this rule having to know that any of them exist.
  //
  // **These are spellings, and that is the one enumeration in this block.** The
  // comparison is against the specifier as written rather than the module it
  // resolves to, so a second spelling of an allowed module is refused: `../i18n`
  // passes and `../i18n/index` does not. That direction is a report rather than
  // an admission, which is the safe half, but the failure arrives reading
  // `reaches ../i18n/index` and will look like a bug in the rule unless this
  // says otherwise.
  //
  // **The known collision, written here so the first refusal does not become a
  // widening.** A component that remembered its own open state would have to
  // name the preference door that the storage rule requires of every stored
  // choice, and this arm reports it. The resolution is to move that component
  // into a page folder, not to widen this list: the widening that reaches one
  // general helper admits every domain helper beside it in the same stroke.
  const MAY_REACH = [
    /^react$/,
    /^\.\/[A-Za-z]+$/,
    THE_TRANSLATION_DOOR,
    /^\.\.\/api\/mutator$/,
  ];

  const STATES_A_NAMESPACE = /\bt\(\s*"([a-z][A-Za-z0-9]*)\./g;
  // The denominator for the shortfall arm below. `\b` is what keeps this off
  // the `t(` inside `errorText(`, which is a call to something else entirely.
  const CALLS_TRANSLATE = /\bt\(/g;

  function code(): [string, string][] {
    return entries().map(([path, source]) => [
      path,
      withoutProse(source, langOf(path)),
    ]);
  }

  /**
   * The page a module belongs to, or nothing.
   *
   * `pages/components/` is the middle tier, shared by several pages and a page
   * itself. It owns no vocabulary, so it neither fails this rule nor counts
   * toward the sharing that clears it.
   */
  function pageOf(path: string): string | null {
    const parts = path.split("/");
    if (parts[0] !== "pages" || parts.length < 3) return null;
    return parts[1] === "components" ? null : parts[1]!;
  }

  function namespacesIn(source: string): string[] {
    return [...source.matchAll(STATES_A_NAMESPACE)].map((match) => match[1]!);
  }

  /**
   * Who states each namespace: the page folders, and the modules outside this
   * folder that are not a page.
   *
   * **The second half exists so the failure can name a cause.** The count that
   * decides the verdict is the page folders alone, and when that count is zero
   * the speaker is the middle tier or the shell, which is exactly the case this
   * rule was widened to catch. Reporting "no page" and stopping there names the
   * component and nothing about why, and the component is the one part of the
   * message the reader already knows.
   */
  function speakers(): Map<
    string,
    { pages: Set<string>; elsewhere: Set<string> }
  > {
    const out = new Map<
      string,
      { pages: Set<string>; elsewhere: Set<string> }
    >();
    for (const [path, source] of code()) {
      if (path.startsWith(FOLDER)) continue;
      const page = pageOf(path);
      for (const namespace of namespacesIn(source)) {
        const found = out.get(namespace) ?? {
          pages: new Set<string>(),
          elsewhere: new Set<string>(),
        };
        if (page === null) found.elsewhere.add(path);
        else found.pages.add(page);
        out.set(namespace, found);
      }
    }
    return out;
  }

  function theFolder(): [string, string][] {
    return code().filter(([path]) => path.startsWith(FOLDER));
  }

  it("reads the folder and the tree it compares against", () => {
    // A glob that matched nothing, or a tree that stated no namespace, would
    // make every arm below pass for ever. This rule's whole subject is a
    // component nobody noticed was in the wrong folder.
    expect(theFolder().length).toBeGreaterThan(0);
    expect(speakers().size).toBeGreaterThan(0);
  });

  it("states no vocabulary that belongs to one page", () => {
    const spoken = speakers();
    const reported: string[] = [];
    for (const [path, source] of theFolder()) {
      for (const namespace of new Set(namespacesIn(source))) {
        const found = spoken.get(namespace);
        const pages = [...(found?.pages ?? [])].sort();
        const elsewhere = [...(found?.elsewhere ?? [])].sort();
        // **Fewer than two, and zero is the case that matters.** A namespace no
        // page folder speaks is not unowned: it belongs to the middle tier or
        // to the component itself, and both are the domain case. Every
        // namespace minted for a new component lands at zero by construction,
        // so "exactly one" would clear the shape somebody reaches for first.
        if (pages.length < 2)
          reported.push(
            // **Naming a cause on both branches, not just the informative one.**
            // The verdict is a property of the whole tree, so the component this
            // message opens with is rarely where the cause is. One page folder
            // names that page; no page folder names whatever does speak it,
            // which is the middle tier or the shell, and saying only "no page"
            // there would leave the reader the one fact they already had.
            `${path} states ${namespace}., spoken by ${
              pages.length > 0
                ? pages.join(", ")
                : elsewhere.length > 0
                  ? `no page folder, only ${elsewhere.join(", ")}`
                  : "nothing else in the tree"
            }`,
          );
      }
    }
    expect(reported).toEqual([]);
  });

  it("reaches nothing a general component has no business naming", () => {
    const reported: string[] = [];
    for (const [path, source] of theFolder())
      for (const specifier of specifiersOf(path, source))
        if (!MAY_REACH.some((allowed) => allowed.test(specifier)))
          reported.push(`${path} reaches ${specifier}`);
    expect(reported).toEqual([]);
  });

  it("allows nothing the folder does not already name", () => {
    // An allowance covering nothing is one waiting to cover something. Each of
    // these is a permission, and a permission no module in the folder uses is
    // a hole that was opened on a guess.
    //
    // **It is also what stops the reach arm passing on an empty read.** If the
    // specifier walk ever returned nothing, the arm above would report nothing
    // and look clean; this one goes red on every pattern at once. A rule that
    // reads less than it did is the failure a green arm cannot show you.
    const named = theFolder().flatMap(([path, source]) =>
      specifiersOf(path, source),
    );
    expect(
      MAY_REACH.filter(
        (allowed) => !named.some((specifier) => allowed.test(specifier)),
      ).map(String),
    ).toEqual([]);
  });

  it("states a namespace wherever it opens the translation door", () => {
    // **The denominator the vocabulary arm cannot have.** Both of its patterns
    // key on the local name `t`, so `const { t: label } = useTranslation()`
    // empties the namespaces it reads and the shortfall check that is meant to
    // notice, in one edit: a renamed binding is invisible to a rule and to its
    // own honesty check at the same time. The storage rule above does not have
    // this weakness only because `localStorage` is a global that cannot be
    // renamed without the module failing to resolve, and a destructured `t` can.
    //
    // **It asks which name the module took, not which module it named**, and
    // that is what keeps it off the most general design this folder can hold: a
    // component whose prop is a `MessageKey` and whose caller does the
    // translating imports a type from the door and calls nothing. That shape is
    // live one tier down, so an arm keyed on the specifier would refuse the
    // thing `src/components/` is for, on arrival. Asking for the name is also
    // the stronger reading of the rename: a specifier carries what was
    // imported rather than what it was bound to, so an alias at the import site
    // still answers `useTranslation`, and the door cannot rename its own export
    // without breaking every caller loudly.
    //
    // **One class uniquely, not three, and the earlier wording of this claimed
    // three.** It fires only where no readable namespace is left, so: a renamed
    // binding is caught here and nowhere else, which is the whole reason it
    // exists; a key built from a template and a key held in a prop are the
    // shortfall arm's, which counts calls against reads and sees both. And a
    // module that states one namespace honestly can still hold a second under a
    // renamed binding or a translator threaded into a helper, which this arm
    // does not reach, because the count it tests is not zero. Following a
    // binding there needs the AST rather than a count.
    const reported: string[] = [];
    for (const [path, source] of theFolder()) {
      // **A reach with no name is the strongest yes this arm can get, and the
      // helper refuses it.** `importedFrom` throws on a namespace, default,
      // dynamic or star reach, because the rule it serves asks which name was
      // taken and a nameless reach would turn such a rule off with every arm
      // green. This arm asks only whether the door was opened, and taking the
      // module whole is taking the door, so the refusal is an answer of yes.
      // Left to propagate it would fail this arm on
      // `import * as i18n from "../i18n"` beside an honest key, which nothing
      // in this block forbids, and it would report one file per run where every
      // other arm here reports all of them.
      //
      // **It over matches a type only namespace reach, and that is the loud
      // direction rather than a second defect.** `import type * as i18n` is an
      // ordinary spelling for reaching a message key type, carries no
      // translator and opens nothing, and it refuses here all the same, so a
      // component whose prop is one is reported for a door it never opened.
      // That is the type only case arriving by the namespace spelling, narrow
      // enough to state rather than to build machinery for, and unstated it is
      // a failure with nothing attached to explain it.
      //
      // **The re-throw is the half not to drop.** A bare catch would read a
      // parse failure inside the helper as an opened door, and that then passes
      // silently on every file that states a namespace. A matched refusal
      // leaves the loop running, so every offender is reported; an unmatched one
      // still leaves the loop and names the first file only, which is the right
      // way round for something nobody predicted.
      let opened: boolean;
      try {
        opened = importedFrom(path, source, THE_I18N_MODULE).includes(
          "useTranslation",
        );
      } catch (refusal) {
        if (!takesTheDoorWhole(path, refusal)) throw refusal;
        opened = true;
      }
      if (opened && namespacesIn(source).length === 0)
        reported.push(`${path} opens the translation door and states nothing`);
    }
    expect(reported).toEqual([]);
  });

  it("takes only translation machinery from the door", () => {
    // The arm the allowance list cannot be, because that one is keyed on a
    // module and the domain sits on a name inside it.
    const reported: string[] = [];
    for (const [path, source] of theFolder()) {
      let names: string[];
      try {
        names = importedFrom(path, source, THE_I18N_MODULE);
      } catch (refusal) {
        if (!takesTheDoorWhole(path, refusal)) throw refusal;
        // **The same refusal, read the opposite way from the door arm, and the
        // question is what makes the difference.** That arm asks whether the
        // door was opened, which taking the module whole answers yes. This one
        // asks which names came through, and taking it whole takes every name
        // in it, the domain one included. So a nameless reach is reported here
        // rather than treated as an answer.
        //
        // **The type only namespace spelling is reported here too, and here
        // with no escape.** It cannot take the tag renderer as a value at all,
        // so this reasoning does not cover it, and where the door arm lets such
        // a module pass once it states a namespace, this arm reports
        // unconditionally. One class with two messages: it is the same defect
        // the door arm's own comment states, and it wants one fix rather than
        // two.
        reported.push(`${path} takes the whole door, domain names included`);
        continue;
      }
      for (const name of names)
        if (!THE_TRANSLATION_API.includes(name))
          reported.push(`${path} takes ${name} from the door`);
    }
    expect(reported).toEqual([]);
  });

  it("allows no name the folder does not already take", () => {
    // The standard the allowance list above already holds, applied to this list
    // rather than left to it: a permission no module uses is a hole opened on a
    // guess, and a name admitted against a design nobody has written yet is
    // exactly that. A component that turns out to need one fails by name, and
    // the list edit that admits it is reviewed beside the component.
    const taken = new Set<string>();
    for (const [path, source] of theFolder()) {
      try {
        for (const name of importedFrom(path, source, THE_I18N_MODULE))
          taken.add(name);
      } catch (refusal) {
        if (!takesTheDoorWhole(path, refusal)) throw refusal;
      }
    }
    expect(THE_TRANSLATION_API.filter((name) => !taken.has(name))).toEqual([]);
  });

  it("names only what the door actually exports", () => {
    // **An allowance for a name the door does not publish is one waiting to
    // cover something**, and a typo here would silently widen the arm above by
    // permitting a name nothing can refuse. Recomputed from the door's own
    // export clause so the list cannot outlive it.
    //
    // **What this arm and the one above it buy together is equality**, which is
    // more than either states alone. The partition arm gives every name the
    // folder takes an allowance; the arm above gives every allowance a taker;
    // this one gives every allowance an export. So the list cannot drift from
    // what the folder imports in either direction, and a name held in reserve
    // is impossible rather than merely discouraged.
    //
    // **What none of the three reaches** is a name added to silence a component
    // that already takes it: import the tag renderer, watch the partition arm
    // name it, then add it here. That is a deliberate act in a reviewable diff
    // rather than the typo or the reserved guess these arms are for. And
    // nothing ties this machinery to the export that motivated it, so retiring
    // that export would leave all of it standing with its reason gone.
    const door = code().find(([path]) =>
      path.startsWith(`${THE_I18N_MODULE}/index`),
    );
    expect(
      door,
      "the translation door is not where this rule expects",
    ).toBeDefined();
    const exported = exportedBy(door![0], door![1]);
    expect(
      THE_TRANSLATION_API.filter((name) => !exported.includes(name)),
    ).toEqual([]);
  });

  it("still recognises the refusal it reads as an opened door", () => {
    // **The branch above is an allowance covering nothing on this tree.** No
    // module in the folder takes the door whole, so nothing exercises the catch
    // and its only other evidence was a mutant that was inverted away. That
    // leaves it resting on prose another function writes: reword the refusal and
    // nothing goes red, because with no nameless reach the branch is never
    // entered. It stays invisible until somebody writes the construct, and then
    // the arm turns red on an honest file with a message about a construct.
    //
    // So the coupling is pinned here instead, in the shape the allowance arm
    // above already uses for the same reason. This exercises it on every run
    // rather than once, and it fails the day either side moves: the helper
    // giving up its refusal, or its wording drifting past the prefix.
    const path = "components/Probe.ts";
    let refusal: unknown;
    try {
      importedFrom(
        path,
        `import * as door from "../${THE_I18N_MODULE}";`,
        THE_I18N_MODULE,
      );
    } catch (thrown) {
      refusal = thrown;
    }
    expect(refusal, "a nameless reach is no longer refused").toBeDefined();
    expect(takesTheDoorWhole(path, refusal)).toBe(true);
    // **The negative half, because the path binding is the whole reason the
    // anchor beats a substring test.** Without these two the `startsWith` could
    // be reduced to ignore the path, or to match any error at all, and this arm
    // would stay green on both.
    expect(takesTheDoorWhole("components/Other.ts", refusal)).toBe(false);
    expect(takesTheDoorWhole(path, new Error("something else"))).toBe(false);
  });

  it("reads every namespace the folder states", () => {
    // **The arm that keeps the vocabulary arm honest.** A key built rather than
    // written, `t(`help.${topic}`)` among them, is a namespace this rule cannot
    // read, and a rule that silently reads fewer keys than a file states looks
    // cleaner while seeing less. Counting the calls against the reads is what
    // makes the pattern above safe to tighten.
    const reported: string[] = [];
    for (const [path, source] of theFolder()) {
      const calls = [...source.matchAll(CALLS_TRANSLATE)].length;
      const read = [...source.matchAll(STATES_A_NAMESPACE)].length;
      if (read < calls)
        reported.push(`${path} states a namespace this rule could not read`);
    }
    expect(reported).toEqual([]);
  });
});

/**
 * The module every rendered date goes through, as a path this rule holds once.
 *
 * Spelled as a `SOURCES` key because `unreferenced` resolves importers'
 * specifiers against it, and stripped separately for the arms that walk
 * `entries()`.
 */
const THE_DATE_DOOR = "../src/lib/date.ts";
const THE_DATE_DOOR_MODULE = "lib/date.ts";

/**
 * Every name the platform publishes for formatting something in a locale.
 *
 * **Derived rather than written, and that is the whole design of this rule.**
 * The obvious version greps for `toLocaleDateString`, which is the shape
 * `docs/decisions.md` records failing here twice: a guard that enumerates
 * spellings this repository writes is walked around by the next equivalent
 * spelling, and the fix that adds a fourth spelling is the tell. This asks the
 * runtime what it publishes instead, so a member arriving in a node bump is
 * reported by name rather than silently admitted.
 *
 * **`toLocale` is a prefix the specification owns, across every prototype that
 * publishes one.** Five names, and `toLocaleString` is published by five of these
 * six, every one but `String`, which is the fact that sinks the tempting version
 * of this rule: a partition of "the date formatting API" that names
 * `toLocaleString` has named a method `Number`, `Array`, `BigInt` and `Object`
 * publish too. **This sentence said "all six" until a seat counted it**, which is
 * the failure this repository charges for most often and which the arm below now
 * makes impossible to repeat: it compares against the list's own length rather
 * than against a threshold, so the prose and the assertion move together.
 * `String` earns its place in the list by publishing the two case folding names,
 * not this one.
 *
 * **The runtime this is measured under is bun 1.4.2, not the node on the
 * machine somebody reads this on.** The suite runs in `oven/bun:1.4.2-alpine`,
 * pinned by digest where the pipeline declares its image, and that image carries
 * no node at all. Both runtimes answer 5 and 12 here, so the conclusion does not
 * turn on it; the instrument is named because the first version of this comment
 * named the wrong one, which is the error this repository charges for most often.
 *
 * **And the derivation asks the test runtime while the code runs in a browser,
 * which is a hole no arm here can close.** A locale aware member a browser ships
 * before bun does is absent from the surface, is classified nowhere, and fails
 * nothing, because a short surface empties both of the totality arm's filters.
 * That is not hypothetical and the lag has always run browser first:
 * `Intl.Segmenter` reached Chrome months before node, and `Intl.DurationFormat`
 * likewise. So "growth is a report" holds for a runtime bump and not for a
 * browser gaining a member, which is the direction that matters for a rule about
 * what a member sees. Closing it needs a list the browser agrees with, which this
 * arm cannot have, so the extent is refused rather than overstated.
 */
const PUBLISHES_A_LOCALE_MEMBER: { prototype: object }[] = [
  Date,
  String,
  Number,
  Array,
  BigInt,
  Object,
];

function localeMembers(): string[] {
  const names = new Set<string>();
  for (const publisher of PUBLISHES_A_LOCALE_MEMBER)
    for (const name of Object.getOwnPropertyNames(publisher.prototype))
      if (name.startsWith("toLocale")) names.add(name);
  return [...names];
}

function intlMembers(): string[] {
  return Object.getOwnPropertyNames(Intl);
}

function theLocaleSurface(): string[] {
  return [...localeMembers(), ...intlMembers()];
}

/**
 * The half of that surface which puts a date or a time in front of a person.
 *
 * **One partition over the whole derived surface, refused when a name is
 * classified nowhere or twice**, which is `backend/book_columns.py`'s discipline
 * rather than a new one. The point of a partition over an inclusion list is that
 * growth is a report: a name this tree has never heard of fails the totality arm
 * naming itself, and the cost is one classified line in the diff of whoever
 * bumped the runtime.
 *
 * **`toLocaleString` is here because it is ambiguous by name and refusing it is
 * cheaper than attributing it.** `Date` publishes it, so it renders a date;
 * `Number` publishes it too, so `count.toLocaleString(locale)` would be refused
 * by this rule although it formats no date. Telling those apart needs the
 * receiver's type, which no walk over a parse has. There are zero of either in
 * the tree, so the refusal costs nothing on arrival and lands in the diff of
 * whoever writes the first one, which is where the trade is visible to a
 * reviewer. **Do not exempt it for numbers**: it is also the only name here that
 * would catch a `Temporal` value's own `toLocaleString`, and `Temporal` is a
 * sibling global rather than an `Intl` member, so nothing else in this rule can
 * see it at all.
 *
 * **`RelativeTimeFormat` and `DurationFormat` are here although the tree uses
 * neither.** They format a point and a span of time for a locale, so they are
 * the door's subject by any reading, and `LoanRow` already computes "days
 * overdue" by hand, which is the component that reaches for the first of them.
 * A rule forbidding only what somebody has already written is the enumeration
 * failure one level up.
 *
 * **`DurationFormat` puts a floor under the runtime, which is worth knowing
 * before somebody hits it.** It is classified here, so the totality arm needs a
 * runtime that publishes it; on an older one the arm goes red saying
 * `DurationFormat` is classified but not published, which reads as a mistake in
 * this list and is really a runtime downgrade. bun 1.4.2 publishes it. Note also
 * that `tsconfig.json` sets `lib: ["ES2022", "DOM", "DOM.Iterable"]`, under which
 * `Intl.DurationFormat` has no types at all, so the name is watched before it can
 * be written. That is the right direction to be wrong in and it is not what the
 * paragraph above claims to buy.
 */
const RENDERS_A_DATE = [
  // `Date.prototype`, and nothing else publishes these two.
  "toLocaleDateString",
  "toLocaleTimeString",
  // Ambiguous by name, refused rather than attributed. See above.
  "toLocaleString",
  // The constructors that format an instant, a relative instant and a span.
  "DateTimeFormat",
  "RelativeTimeFormat",
  "DurationFormat",
];

/**
 * The rest of it, each with the reason it is not this rule's business.
 *
 * `toLocaleLowerCase` is the row that matters: it is why this rule is a
 * partition and not a pattern. A guard matching `/toLocale\w+/` is red on
 * `pages/AuthorsPage/AuthorsPage.tsx` the day it is written, and it goes green
 * by classification here rather than by an exemption naming that file, which is
 * the distinction `docs/decisions.md` draws in "A guard for the general
 * components folder names no domain word".
 */
const RENDERS_SOMETHING_ELSE = [
  // `String.prototype`. Case folding, not dates.
  "toLocaleLowerCase",
  "toLocaleUpperCase",
  // `Intl` members that format or inspect something other than a time.
  "Collator",
  "NumberFormat",
  "ListFormat",
  "PluralRules",
  "DisplayNames",
  "Segmenter",
  "Locale",
  "getCanonicalLocales",
  "supportedValuesOf",
];

/**
 * Names that render a date to a person without consulting a locale at all.
 *
 * **Outside the partition above, deliberately, because they are not on the
 * surface it derives.** None is `toLocale` prefixed and none is an `Intl` member,
 * so putting them in `RENDERS_A_DATE` would fail the totality arm as classified
 * but unpublished. They are watched by the keep out arm and excluded from the
 * comparison, which is the honest shape: two lists with different grounds rather
 * than one list with an exception.
 *
 * **Measured at 0 sites each under `src`, so they cost nothing on arrival.**
 * `new Date(iso).toDateString()` renders `Wed Aug 19 2026` to a member, which is
 * the same defect the door exists for wearing different clothes, and the earlier
 * version of this rule dismissed the whole locale insensitive class on a
 * measurement taken over `toISOString` alone. That was the one member of the
 * class with legitimate uses, so the measurement that justified leaving the class
 * alone was taken on exactly the case that could not be watched.
 *
 * **`toISOString` is the one that stays out, and the reason is not squeamishness.**
 * It has 2 code sites, `lib/digitalReference.ts` building an API payload and
 * `pages/SettingsPage/DataSettingsPage/hooks.ts` building a backup filename, and
 * both are serialisations rather than renderings. A third mention is prose in a
 * docstring, which a parse does not see. Watching it would redden two correct
 * sites, one of them in a file this change does not own.
 *
 * **`getFullYear`, `getMonth` and `getDate` are out too**, at 0 sites each: a
 * concatenated date needs several of them plus the joining, and an arm on any one
 * name would report arithmetic on a date that renders nothing.
 */
const RENDERS_A_DATE_WITHOUT_A_LOCALE = [
  "toDateString",
  "toTimeString",
  "toUTCString",
];

/**
 * `Intl` members that cannot do the explaining, because this app spells them too.
 *
 * `Intl.Locale` is a member, and `Locale` is also the generated enum imported
 * across this tree, with `LocaleProvider`, `LocaleGate`, `LocaleContext`,
 * `LocaleContextValue` and `LocaleProviderProps` beside it. Left in, any module
 * that named `Intl` while importing the app's enum would be explained whatever it
 * did with `Intl`. Measured over the modules under `src`: 5 identifiers are `Intl`
 * member prefixed without being the member, every one of the five is one of those
 * `Locale` names, and 0 literals and 0 template chunks are among them.
 *
 * **Measured once, and nothing re derives it**, so the next collision of this kind
 * arrives silently. Stated rather than closed: an arm re deriving the collision set
 * would make it self enforcing, and it is not written because the set it guards has
 * one member and the cost of being wrong about it is a report.
 *
 * That cost is a genuine `Intl.Locale` being reported. 0 sites today, and a report
 * is the safe direction.
 */
const EXPLAINS_NOTHING = ["Locale"];

/**
 * Does this module name `Intl` while naming nothing `Intl` publishes?
 *
 * **Extracted so a fixture can drive it.** Written inline, it left the `Intl` arm
 * the only one in this block with no synthetic case, and both of its mechanisms,
 * the `Locale` exclusion and the prefix match, survived being removed.
 */
function passesIntlOnUnexplained(path: string, source: string): boolean {
  const named = namesIn(path, source);
  const members = intlMembers().filter(
    (member) => !EXPLAINS_NOTHING.includes(member),
  );
  const explained = [...named].some((name) =>
    members.some((member) => name.startsWith(member)),
  );
  return named.has("Intl") && !explained;
}

/** Every watched name a module mentions in its code. */
function rendersADateIn(path: string, source: string): string[] {
  const named = namesIn(path, source);
  return [...RENDERS_A_DATE, ...RENDERS_A_DATE_WITHOUT_A_LOCALE].filter(
    (name) => named.has(name),
  );
}

describe("a date reaches a reader through one module", () => {
  /**
   * **Read off the parse, which is what closes computed access.** `namesIn`
   * collects identifiers and literals both, so `d.toLocaleDateString()`,
   * `d["toLocaleDateString"]()`, `const { DateTimeFormat } = Intl` and
   * `Intl["DateTimeFormat"]` all put a watched name in the parse. A regex over
   * `\.toLocaleDateString` sees the first of those four. Comments are outside a
   * parse, so this needs no `withoutProse` pass and a name left behind in a
   * docstring is not a reach.
   *
   * **This rule reads `src` and deliberately not the test tree.** Two tests
   * name the surface on purpose, to build an expected string by a path
   * independent of the one the component takes, which is what lets an arm
   * observe that a component used the app's locale rather than the host's.
   * Extending this rule over `tests/` would buy nothing and cost two exemption
   * rows for assertions that are correct.
   *
   * ## What this rule does not reach, measured rather than waved at
   *
   * Listed one per line with its own count, because the first version of this
   * put four of them in one sentence and offered a measurement for one, and a
   * reader then takes the whole list as uniformly out of scope. One of the four
   * was live in the tree.
   *
   * **`<input type="date">` renders a date in the browser's locale, and there
   * are 2 of them**, at `pages/BookDetail/components/CopyPanel.tsx` and
   * `LoanPanel.tsx`. The rendering belongs to the control, so no module level
   * rule can reach it and this one does not claim to; it is the same defect the
   * door exists for, and it is in the tracker rather than here.
   *
   * **The glob is `.ts` and `.tsx` under `src`, and the browser runs more than
   * that.** `public/sw-cleanup.js` is 1 file of shipped browser code outside it
   * by both extension and directory, and `index.html` is 1 more. Neither renders
   * a date today. This is an inclusion list inside a rule whose whole argument is
   * that inclusion lists go stale, which is worth saying plainly rather than
   * leaving for somebody to find.
   *
   * **A date the backend already formatted is outside any tree scan**, and is
   * currently empty: the only `strftime` reaching a client is `%Y-%m` from the
   * statistics route, which is what `monthLabel` takes.
   *
   * **A date reaching `t()` as a value**, `t("x", { when: someDate })`, is held
   * by `TranslateParams` being `Record<string, string | number>` rather than by
   * anything here. Widening that type reopens it silently.
   *
   * ## The false refusals this arm accepts, so neither is read as a bug
   *
   * **`Intl.DateTimeFormat` used to read rather than to render** is reported:
   * `resolvedOptions().timeZone` is the only way to learn the reader's zone and
   * renders no date. 0 sites today, and one feature away. It is accepted rather
   * than exempted, because the alternative is `lib/date.ts` growing a function
   * that renders nothing, and refusing on arrival puts the trade in front of a
   * reviewer at the moment it is made.
   *
   * **`toLocaleString` on a number** is reported for the reason its own
   * classification gives.
   */
  it("keeps every date bearing name out of every module but the door", () => {
    const watched = entries().filter(([path]) => path !== THE_DATE_DOOR_MODULE);
    // **The scope is asserted, not assumed.** Narrowing this arm to
    // `startsWith("pages/")` leaves every other arm green, which makes the
    // filter the cheapest place to defeat the whole rule. Stated as the
    // relationship rather than as a number, so it cannot go stale: everything
    // the glob reaches, less the door itself.
    expect(watched.length).toBe(entries().length - 1);

    const reported = watched.flatMap(([path, source]) =>
      rendersADateIn(path, source).map((name) => `${path} names ${name}`),
    );

    expect(reported).toEqual([]);
  });

  it("classifies every name the platform publishes, exactly once", () => {
    // **Totality, and the stale half with it.** A name the runtime publishes
    // and nobody classified fails here rather than falling through one of the
    // two lists silently; a name in a list that the runtime no longer publishes
    // fails too, so an entry cannot outlive its reason, which is the rule
    // `oxlintRatchet.test.ts` applies to its own suppressions.
    const surface = theLocaleSurface();
    const classified = [...RENDERS_A_DATE, ...RENDERS_SOMETHING_ELSE];

    expect(surface.filter((name) => !classified.includes(name))).toEqual([]);
    expect(classified.filter((name) => !surface.includes(name))).toEqual([]);
    expect(
      classified.filter(
        (name) =>
          RENDERS_A_DATE.includes(name) &&
          RENDERS_SOMETHING_ELSE.includes(name),
      ),
    ).toEqual([]);

    // The second watched list sits outside this partition by construction, and
    // that is asserted so it cannot drift into the surface unnoticed: a name that
    // became `toLocale` prefixed, or an `Intl` member, would belong in the
    // partition and would then be classified in neither of its halves.
    expect(
      RENDERS_A_DATE_WITHOUT_A_LOCALE.filter((name) => surface.includes(name)),
    ).toEqual([]);
  });

  it("keeps every publisher that earns its place, and counts them", () => {
    // **Two things nothing checked, and the first version of this arm checked
    // neither.** `[Date, String]` alone yields all five names, so four of the six
    // could be deleted with every other arm in this block green. And the
    // docstring said `toLocaleString` was published by all six when it is
    // published by five, `String` being the exception, so an arm asserting "more
    // than one" passed at five and would have passed at two: it did not check the
    // sentence it was written for.
    //
    // **Compared by identity, and a count is what the first two attempts both
    // got wrong.** `toBeGreaterThan(1)` could not fail a claim about six.
    // Comparing against `PUBLISHES_A_LOCALE_MEMBER.length - 1` is defined in
    // terms of the list, so deleting an entry moves both sides together:
    // measured by deleting each of the six in turn, that version left `Number`,
    // `Array`, `BigInt` and `Object` deletable with this whole block green, which
    // is four of six and the original report unfixed. **A threshold and a
    // self relative count are the same failure**, and only naming the members
    // closes it.
    //
    // **Which arm catches which, because a count of catches is not evidence.**
    // This arm reddens on the deletion of `Date`, `Number`, `Array`, `BigInt` or
    // `Object`. It does **not** redden on deleting `String`, whose removal leaves
    // this list unchanged; that one is caught by `classifies every name the
    // platform publishes, exactly once`, because `String` is the sole publisher
    // of the two case folding names and losing it empties them from the surface.
    // Six deletions, two arms, no gap.
    const publishers = PUBLISHES_A_LOCALE_MEMBER.filter((publisher) =>
      Object.getOwnPropertyNames(publisher.prototype).includes(
        "toLocaleString",
      ),
    );

    expect(publishers).toEqual([Date, Number, Array, BigInt, Object]);
    expect(localeMembers()).toContain("toLocaleLowerCase");
  });

  // **There is no separate vacuity arm here, and that is a removal rather than an
  // omission.** One existed and was the sole catcher of nothing across eighteen
  // single change mutants, because all three of its assertions live elsewhere in
  // this block: a tree with no modules fails the keep out arm's own scope equality,
  // since `0` is not `entries().length - 1` for an empty glob; its synthetic case
  // was character for character the first assertion of `reports the shapes it
  // exists for`; and `SOURCES[THE_DATE_DOOR]` is asserted by the door arm below.
  // An arm whose every claim is made by a neighbour reads as coverage and is not.

  it("leaves no export of the door unreached", () => {
    // **Derived rather than a threshold**, which is the wallpaper rule's shape
    // and is stronger than a written bound in the direction
    // `guards-and-mutation` records: a stated `6` against a constant that had
    // moved to seven passes, because a smaller count is a weaker claim. This
    // writes no number. It fails if the door is renamed and if a format is added
    // with no caller.
    //
    // **The application tree only, which is where this parts company with the
    // wallpaper rule it copies.** That rule keeps the test tree in scope on
    // purpose, because a test only export is legitimate there. Here it is not,
    // and inheriting the scope without the reason cost the claim this comment
    // used to make: `tests/lib/date.test.ts` imports all five exports by name, so
    // with tests in scope every `src` caller could go away and this arm would
    // stay green on the test file alone, which is exactly the dead door it said
    // it caught. Measured per export under `src`: 5, 3, 2, 1, 1 importers, 11
    // modules in all, so scoping this down costs nothing today and makes the
    // sentence true.
    const source = SOURCES[THE_DATE_DOOR];
    expect(source).toBeDefined();

    expect(
      unreferenced(THE_DATE_DOOR, source ?? "", Object.entries(SOURCES)),
    ).toEqual([]);
  });

  it("explains every bare Intl mention by a member the module names", () => {
    // **The counting arm, and it reaches only half the surface.** The storage
    // rule can count every mention of `localStorage` because that is one named
    // global, so an unexplained one is reportable. Half of this surface has no
    // named receiver at all: `d.toLocaleDateString()` names `d`, and `d` is any
    // expression, so there is nothing to count. `Intl` is a named global and
    // this is that idiom applied to the half where it works. The asymmetry is
    // stated rather than papered over, because a reader who assumes the storage
    // rule transferred whole will believe this rule closes more than it does.
    //
    // **A member name or a name built on one**, which is the difference between
    // this arm and a false refusal waiting to happen. `Intl.DateTimeFormatOptions`
    // and `Intl.NumberFormatOptions` are types whose names are not `Intl` members,
    // so an exact comparison reports a module that named a member's own options
    // type and rendered nothing. There are none in the tree today and the second
    // is the likelier arrival, since a price formatter taking options needs it.
    //
    // **It is also defeated by a sibling**, which is the limit worth knowing:
    // `new Intl[`DateTimeFormat`](l)` in a module that also names
    // `Intl.NumberFormat` satisfies this arm. The keep out arm is what catches
    // that shape now, since `namesIn` reads a template's text.
    // **`Locale` cannot do the explaining, because this app has one of its own.**
    // `Intl.Locale` is a member, and `Locale` is also the generated enum imported
    // across this tree, with `LocaleProvider` and `LocaleContextValue` beside it,
    // every one of which starts with the member's name. Left in, any module that
    // named `Intl` while importing the app's enum would be explained whatever it
    // did with `Intl`, which is this arm passing for a reason it does not state.
    // It happens to be green either way today, since the three modules naming
    // `Intl` in code each name a real member, so this is one import away rather
    // than broken. The cost of taking it out is that a genuine `Intl.Locale` is
    // reported: 0 sites, and a report is the safe direction.
    const reported = entries()
      .filter(([path, source]) => passesIntlOnUnexplained(path, source))
      .map(([path]) => `${path} passes Intl on without naming a member`);

    expect(reported).toEqual([]);
  });

  it("reports an Intl the app's own Locale names cannot account for", () => {
    // **Both of this arm's mechanisms were on the rung "stated" until these two
    // cases existed**: emptying `EXPLAINS_NOTHING` and reverting the prefix match
    // to an exact comparison each survived every other arm, because the tree has
    // no `Intl.*Options` type and the three modules naming `Intl` in code each
    // name a real member. The arm was green for the reason it claims by luck.
    //
    // The first case is why `Locale` is excluded: a module naming `Intl` and the
    // app's own enum has explained nothing.
    expect(
      passesIntlOnUnexplained("x.ts", 'const l: Locale = "en"; hand(Intl);'),
    ).toBe(true);

    // The second is why the comparison is a prefix: a member's own options type
    // is not a member name, and reporting it would be a false refusal.
    expect(
      passesIntlOnUnexplained(
        "x.ts",
        "function f(o: Intl.NumberFormatOptions) { return o; }",
      ),
    ).toBe(false);

    // And the ordinary case, so the two above are not the only thing it can say.
    expect(
      passesIntlOnUnexplained("x.ts", "new Intl.NumberFormat(l).format(n);"),
    ).toBe(false);
  });

  it("classifies a toLocale name by its publisher wherever one prototype owns it", () => {
    // **Four of the five `toLocale` names belong to a half by derivation rather
    // than by judgement, and nothing said so.** The diagonal below pins a name
    // only while that name has a row in its own case list, so reclassifying
    // `toLocaleTimeString` **and deleting its row** survived everything: the set
    // equality fails first and its message tells the next reader which line to
    // delete. That catches the slip and not the decision.
    //
    // This is the decision. `toLocaleDateString` and `toLocaleTimeString` are
    // published by `Date.prototype` alone, so they render a date by construction;
    // `toLocaleLowerCase` and `toLocaleUpperCase` by `String.prototype` alone, so
    // they do not. A sole publisher is the whole argument, and it holds the two
    // names whose own defect motivated this door.
    //
    // **The `Intl` six cannot be pinned this way and that is said rather than
    // implied.** Nothing mechanical separates `DateTimeFormat` from
    // `NumberFormat`: both are `Intl` members and the split between them is a
    // judgement about what a reader sees. `toLocaleString` is the fifth name and
    // is excluded here for the same reason, having several publishers.
    const publishersOf = (name: string) =>
      PUBLISHES_A_LOCALE_MEMBER.filter((publisher) =>
        Object.getOwnPropertyNames(publisher.prototype).includes(name),
      );

    const derived = localeMembers().filter(
      (name) => publishersOf(name).length === 1,
    );

    for (const name of derived) {
      if (publishersOf(name)[0] === Date) {
        expect(RENDERS_A_DATE).toContain(name);
      } else {
        expect(RENDERS_SOMETHING_ELSE).toContain(name);
      }
    }

    // Four of the five, and the fifth is the ambiguous one. Stated as the
    // relationship so a name arriving with a sole publisher joins this by itself.
    expect(derived.length).toBe(localeMembers().length - 1);
    expect(derived).not.toContain("toLocaleString");
  });

  it("reports the shapes it exists for, and not the ones it does not", () => {
    // The rule's own mutation, on synthetic input so nothing is written to the
    // tree. The three refusals are the spellings a regex would miss; the three
    // clean cases are the false refusals this rule is a partition to avoid.
    //
    // **It caught none of eighteen mutants and is kept anyway**, which is worth
    // stating because the arm beside it was deleted for exactly that. Swap
    // `rendersADateIn` from the parse to `source.includes(name)` and this is the
    // **only** arm that reddens, on the comment fixture. The keep out arm cannot
    // see that mutation: there are zero text mentions of any watched name anywhere
    // under `src` outside the door, so abandoning the design's central claim is
    // invisible everywhere else in this block. The three clean cases are its value,
    // not the three refusals.
    expect(rendersADateIn("x.ts", "d.toLocaleDateString(locale);")).toEqual([
      "toLocaleDateString",
    ]);
    expect(rendersADateIn("x.ts", 'const f = Intl["DateTimeFormat"];')).toEqual(
      ["DateTimeFormat"],
    );
    expect(
      rendersADateIn(
        "x.ts",
        'new Intl.RelativeTimeFormat(l).format(-3, "day");',
      ),
    ).toEqual(["RelativeTimeFormat"]);

    expect(rendersADateIn("x.ts", "s.toLocaleLowerCase();")).toEqual([]);
    expect(
      rendersADateIn("x.ts", "new Intl.NumberFormat(l).format(n);"),
    ).toEqual([]);
    expect(
      rendersADateIn("x.ts", "// toLocaleDateString is how this used to work"),
    ).toEqual([]);
  });

  it("sees a name carried by a template rather than by a literal", () => {
    // **The spelling this rule was blind to, and the reason `namesIn` grew an
    // arm.** A `TemplateElement` keeps its text in `value.cooked`, behind an
    // object with no `type`, so five of nine access shapes were invisible while
    // the plain access and the string literal index were seen. Every one below
    // is ordinary typechecked TypeScript: `as const` gives the template a literal
    // type, so the index needs no `any` and no suppression.
    for (const source of [
      "d[`toLocaleDateString`](l);",
      "const K = `toLocaleDateString`; d[K](l);",
      "const M = { a: `toLocaleDateString` } as const; d[M.a](l);",
      "const K = `toLocaleDateString`; Date.prototype[K].call(d, l);",
    ]) {
      expect(rendersADateIn("x.ts", source)).toEqual(["toLocaleDateString"]);
    }
    expect(rendersADateIn("x.ts", "new Intl[`DateTimeFormat`](l);")).toEqual([
      "DateTimeFormat",
    ]);
  });

  it("reports a date rendered with no locale at all", () => {
    // The second watched list, which the partition cannot hold. Each renders a
    // date to a person in a fixed English form, and each is at 0 sites, so this
    // arm is the only thing standing between them and the next component.
    expect(rendersADateIn("x.ts", "new Date(iso).toDateString();")).toEqual([
      "toDateString",
    ]);
    expect(rendersADateIn("x.ts", "new Date(iso).toTimeString();")).toEqual([
      "toTimeString",
    ]);
    expect(rendersADateIn("x.ts", "new Date(iso).toUTCString();")).toEqual([
      "toUTCString",
    ]);

    // And the serialisations that stay out, because watching them would report
    // two correct sites, one of them in a file this change does not own.
    expect(
      rendersADateIn("x.ts", "new Date().toISOString().slice(0, 10);"),
    ).toEqual([]);
    expect(
      rendersADateIn("x.ts", "d.getFullYear() + '-' + d.getMonth();"),
    ).toEqual([]);
  });

  it("is watching each name for itself", () => {
    // **The diagonal**, which is what separates a rule watching nine names from
    // one watching a single name that several fixtures happen to trip. Drop each
    // name in turn: its own fixture goes clean and every other stays reported. A
    // mutation dropping two at once would show nothing.
    //
    // **Every watched name has a row, and the three that did not were the
    // dangerous ones.** `toLocaleTimeString`, `toLocaleString` and
    // `DurationFormat` could each be moved to the other half of the partition
    // with every arm in this block green. `toLocaleTimeString` is the worst of
    // the three, because it was live in this tree unlocalised, twice in one file,
    // so the name whose own defect motivated the door could be unwatched without
    // a single arm noticing. `toLocaleString` is the next most likely, because it
    // is the one classification the prose argues hardest for, so the next reader
    // to hit its refusal has the note in front of them and moving the name one
    // list down is the cheapest green.
    const CASES: [string, string][] = [
      ["toLocaleDateString", "d.toLocaleDateString(locale);"],
      ["toLocaleTimeString", "d.toLocaleTimeString(locale);"],
      ["toLocaleString", "d.toLocaleString(locale);"],
      ["DateTimeFormat", 'const f = Intl["DateTimeFormat"];'],
      [
        "RelativeTimeFormat",
        'new Intl.RelativeTimeFormat(l).format(-3, "day");',
      ],
      ["DurationFormat", "new Intl.DurationFormat(l).format(d);"],
      ["toDateString", "new Date(iso).toDateString();"],
      ["toTimeString", "new Date(iso).toTimeString();"],
      ["toUTCString", "new Date(iso).toUTCString();"],
    ];

    const watched = [...RENDERS_A_DATE, ...RENDERS_A_DATE_WITHOUT_A_LOCALE];
    // Every watched name has a row above, so the diagonal covers the whole set
    // rather than whichever part somebody thought of. Stated as the relationship,
    // not as a count, so adding a name to either list fails here until it has one.
    expect(CASES.map(([name]) => name).sort()).toEqual([...watched].sort());

    for (const [dropped] of CASES) {
      const narrowed = watched.filter((name) => name !== dropped);
      for (const [name, source] of CASES) {
        const named = namesIn("x.ts", source);
        const found = narrowed.filter((one) => named.has(one));
        if (name === dropped) expect(found).toEqual([]);
        else expect(found).toContain(name);
      }
    }
  });
});

/** Every node under `value`, in no particular order. */
function visitNodes(value: unknown, visit: (node: Node) => void): void {
  if (Array.isArray(value)) {
    for (const item of value as unknown[]) visitNodes(item, visit);
    return;
  }
  if (!isNode(value)) return;
  visit(value);
  for (const key of Object.keys(value)) visitNodes(value[key], visit);
}

/** One exported hook, its interface width and the writes behind it. */
interface HookRow {
  readonly path: string;
  readonly hook: string;
  /** What the module binds it as, which is the row's identity. See `hooks`. */
  readonly local: string;
  readonly members: number;
  readonly mutations: number;
}

/** Distinct generated mutation hooks reached, per member of the interface. */
function ratioOf(row: HookRow): number {
  return row.mutations / row.members;
}

/**
 * The generated client's mutation hooks, read rather than matched on a name.
 *
 * **What makes one a write is its own signature**, an options bag typed
 * `UseMutationOptions`, and not the shape of its name: the generated client
 * spells a read and a write alike, so a name pattern would count both and the
 * ratio would stop being about writes at all.
 */
function mutationHookNames(): Set<string> {
  const names = new Set<string>();
  for (const [path, source] of entries()) {
    if (!path.startsWith("api/generated/endpoints/")) continue;
    visitNodes(parseAst(source, { lang: langOf(path) }), (node) => {
      if (node.type !== "VariableDeclarator") return;
      const id = isNode(node.id) ? text(node.id.name) : null;
      if (id === null || !/^use[A-Z]/.test(id)) return;
      let mutates = false;
      visitNodes(node, (inner) => {
        if (
          inner.type === "TSTypeReference" &&
          isNode(inner.typeName) &&
          text(inner.typeName.name) === "UseMutationOptions"
        )
          mutates = true;
      });
      if (mutates) names.add(id);
    });
  }
  return names;
}

/** A binding under the name a module exports it as, which may be another. */
interface ExportedHook extends Binding {
  /** The name the module binds. Two exports of one binding share it. */
  readonly local: string;
}

/** One name a declaration binds, what it binds to it, and how it is typed. */
interface Binding {
  readonly name: string;
  readonly value: Node;
  /** The type annotation on the binding itself, where the form allows one. */
  readonly declaredAs: Node | null;
}

/**
 * Every name a top level declaration binds, and what it binds it to.
 *
 * **A declaration binds through its own `id`, or through the `id` of each
 * declarator it carries**, and that is the whole rule: it is a property of the
 * node rather than a list of the node types that have one, so a declaration
 * form this tree does not use today still yields its names. The first version
 * of the census named the forms instead and was blind to the ones it had not
 * thought of, which is what this file has paid for four times over.
 *
 * The value is the declarator's initialiser where there is one, because that is
 * what a caller gets, and the declaration itself otherwise.
 */
function bindingsOf(node: Node): Binding[] {
  const named = isNode(node.id) ? text(node.id.name) : null;
  if (named !== null) return [{ name: named, value: node, declaredAs: null }];
  const declarations = Array.isArray(node.declarations)
    ? (node.declarations as unknown[])
    : [];
  return declarations.flatMap((one) => {
    if (!isNode(one) || !isNode(one.id)) return [];
    const value = isNode(one.init) ? one.init : one;
    const direct = text(one.id.name);
    // **The annotation on the binding, kept beside the value it binds.** A
    // callable carries its return type on itself, and a binding can carry the
    // whole signature instead: both write the return type down, and a rule
    // about whether one is written has to read either. Only the identifier
    // form has one to read, because a pattern's annotation describes the
    // object being destructured rather than any one name it binds.
    const declaredAs = isNode(one.id.typeAnnotation)
      ? one.id.typeAnnotation
      : null;
    if (direct !== null) return [{ name: direct, value, declaredAs }];
    // **The name is inside a pattern**, and a pattern binds names as much as an
    // identifier does. Asking whether the `id` happens to be an identifier is
    // the same mistake one binding form over as asking whether a declaration
    // happens to sit under an `export` keyword: a hook destructured out of a
    // factory reached neither list. Every identifier the pattern carries is
    // taken, so no spelling of a pattern is enumerated here.
    return identifiersIn(one.id).map((name) => ({
      name,
      value,
      declaredAs: null,
    }));
  });
}

/**
 * Every name a binding pattern binds.
 *
 * **In a destructuring pattern a key is never a binding, under any spelling.**
 * In `{ a: b }` the name bound is `b` and `a` is the property being read from;
 * in `{ [expr]: b }` the same holds, and `expr` is an expression that names a
 * value already bound somewhere else. So a key contributes no name here, and
 * that is a property of what a key is rather than a list of the ways one can be
 * written.
 *
 * **Do not re-add a condition that descends into a computed key.** It was tried
 * on the argument that a computed key is an expression where a written one is a
 * label, which is true and is the reason to skip both: descending collects a
 * **read** as though it were a binding. Measured, `{ [useTheHook]: renamed }`
 * took that hook out of the measured set.
 *
 * **What it costs when this is wrong is a row deleted, not a row added.** The
 * census keys its bindings by name, so a name collected here that nothing
 * declares overwrites whatever did declare it with a value that is not
 * callable, and the hook leaves the measured set. Three lines whose only effect
 * was one key turned two red arms green. Same class as the specifier export and
 * the pattern binding, and the third time it has been paid for.
 */
function identifiersIn(pattern: Node): string[] {
  const names: string[] = [];
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (!isNode(value)) return;
    if (value.type === "Identifier") {
      const name = text(value.name);
      if (name !== null) names.push(name);
      return;
    }
    const carriesAKey = value.type.endsWith("Property");
    for (const key of Object.keys(value)) {
      if (carriesAKey && key === "key") continue;
      walk(value[key]);
    }
  };
  walk(pattern);
  return names;
}

/** One exported hook and whether its return type is written down. */
interface ContractRow {
  readonly path: string;
  readonly hook: string;
  /**
   * A return type is declared, on the callable itself or on its binding.
   *
   * **Present, never informative.** `(): unknown` satisfies this, and so does
   * an alias for something inferred elsewhere. What a return type is worth
   * saying is not judged here and no assertion below claims it is.
   */
  readonly annotated: boolean;
  /**
   * Something callable is bound to the name, so there is a signature to read.
   *
   * False when the name is bound to anything else, `memo(f)` or a factory's
   * answer, where the only thing left to read is the binding's own annotation.
   */
  readonly callable: boolean;
}

/** Does this binding put a return type in the source, in either place? */
function declaresItsReturn(one: Binding): boolean {
  return isNode(one.value.returnType) || isNode(one.declaredAs);
}

/** A value whose signature can be read: anything carrying a parameter list. */
function isCallable(value: Node): boolean {
  return /Function|Arrow/.test(value.type);
}

/**
 * What one module exports under a hook's name, and the two maps read beside it.
 *
 * **One walk, because there is one population.** The width census below and the
 * contract census both ask which names a module exports as hooks, and two walks
 * asking it would be the same fact stored twice, drifting the first time one of
 * them learned a form the other had not. Every fix this walk has taken is a fix
 * both censuses get.
 *
 * `widths` and `fromTheClient` are the width census's alone and are collected
 * here because they are properties of the same traversal.
 *
 * **The two censuses take this population differently, and widening it is not
 * symmetric.** The contract census takes every row; the width census keeps the
 * rows it can measure and names the rest in `unmeasured`. So a form learned
 * here, as the renamed specifier export was, adds rows to both and may add
 * them to `unmeasured` rather than to `measured`, which **no width arm can
 * see**: those arms are ordinal over the measured rows and a row that never
 * enters them changes nothing. Benign so far, and stated because it is the
 * shape in which this walk growing would quietly narrow the other rule.
 */
function hooksExportedBy(
  path: string,
  source: string,
): {
  hooks: ExportedHook[];
  widths: Map<string, number>;
  fromTheClient: Set<string>;
} {
  const ast: unknown = parseAst(source, { lang: langOf(path) });
  const top = isNode(ast) && Array.isArray(ast.body) ? ast.body : [];
  const widths = new Map<string, number>();
  const fromTheClient = new Set<string>();
  const bound = new Map<string, Binding>();
  // **Keyed on the name the module exports, valued by the name it binds**, and
  // the two differ under exactly one form, `export { inner as useX }`. Reading
  // the local name there tested `inner` against the hook pattern and produced
  // no row at all, so a hook renamed on its way out was outside both this
  // census and the floor arm that guards it: the one export form where this
  // walk read the declaration rather than the export, which is the mistake its
  // own docstring says it does not make. The tree has renamed specifier
  // exports, all of them re-exports carrying a `from`, which is why nothing
  // here demonstrated the hole.
  //
  // **Changing a population's key moves membership in both directions at
  // once**, which is not how changing its extent behaves and is the thing to
  // check when this line is next edited. This key gained the rename and the
  // aliased second row, and lost the default written as a specifier and the
  // string literal name, before any of the four was noticed; `renamesOf`
  // carries what each of them is now.
  const exported = new Map<string, string>();

  for (const statement of top as unknown[]) {
    if (!isNode(statement)) continue;
    if (statement.type === "ImportDeclaration") {
      const from = isNode(statement.source)
        ? text(statement.source.value)
        : null;
      if (from === null || !from.includes("api/generated/endpoints")) continue;
      for (const one of localNamesOf(statement)) fromTheClient.add(one);
      continue;
    }

    const wraps = statement.type.startsWith("Export");
    const declared =
      wraps && isNode(statement.declaration)
        ? statement.declaration
        : statement;
    if (declared.type === "TSInterfaceDeclaration" && isNode(declared.id)) {
      const name = text(declared.id.name);
      const body = isNode(declared.body) ? declared.body.body : null;
      if (name !== null && Array.isArray(body)) widths.set(name, body.length);
    }
    for (const binding of bindingsOf(declared))
      bound.set(binding.name, binding);

    if (!wraps) continue;
    if (isNode(statement.declaration)) {
      for (const { name } of bindingsOf(statement.declaration))
        exported.set(name, name);
      // `export default theHook`, where the export names an existing binding
      // rather than carrying a declaration of its own.
      const direct = text(statement.declaration.name);
      if (direct !== null) exported.set(direct, direct);
    }
    // A specifier export with a `source` re-exports another module's name and
    // binds nothing here, so it is not this module's row.
    if (statement.source === null || statement.source === undefined)
      for (const one of renamesOf(statement)) exported.set(one.out, one.here);
  }

  const hooks: ExportedHook[] = [];
  for (const [hook, local] of exported) {
    if (!/^use[A-Z]/.test(hook)) continue;
    const binding = bound.get(local);
    // **Named twice on purpose.** `name` is what callers see and is what the
    // rule is about; `local` is what the module binds and is what identifies
    // the row, because one binding exported twice is two names and still one
    // hook. Dropping the second is how a hook came to sit in an ordering under
    // both its names while the arm that refuses a duplicate stayed green.
    if (binding !== undefined) hooks.push({ ...binding, name: hook, local });
  }
  return { hooks, widths, fromTheClient };
}

/**
 * The one exclusion either census makes, named rather than globbed.
 *
 * Orval writes this directory and a regeneration rewrites it, so a rule about
 * how the hooks in this tree are written cannot bind it: the answer to a
 * failure there is a generator setting, not an edit. **Every other module under
 * `src` is in the population, whatever it is called and wherever it sits**,
 * which is the half an inclusion glob of `pages` would have lost: hook
 * exporting modules sit outside it, and a glob that missed them would have run
 * green over them for ever rather than failing once.
 */
const NOT_OURS_TO_WRITE = "api/generated/";

/**
 * Every exported hook in the tree, split by whether it can be measured.
 *
 * **The population is stated as an exclusion and the exclusion is reported.** A
 * row is every `use*` a module both binds and exports, outside the generated
 * client, whether it is bound through an identifier or through a pattern. It
 * is measurable when the value bound is callable and its declared
 * return type resolves to an interface declared in the same module, which is a
 * property of the hook; every exported `use*` that is not goes into
 * `unmeasured` by name. Dropping those would be an inclusion list arrived at by
 * another route, and a blank cell reads as zero. **That name is the one the
 * module binds**, because the list is also the identity key the duplicate arm
 * reads: for a hook exported only under a rename it is therefore an internal
 * name no caller sees, and the exported name is carried on the row rather than
 * here. Keying the population on the
 * `Use<X>Result` name instead would be the same mistake with better manners: a
 * name is not a property of a hook.
 *
 * **`contracts` is the same population read for a different property**, whether
 * the hook writes its return type down, which every exported hook has whether
 * or not its width can be measured. It is not the complement of `unmeasured`
 * and must not be read as one: a hook returning an annotated type declared in
 * another module is unmeasurable here and perfectly well annotated.
 *
 * **What is exported is read from the export, not from the declaration.** The
 * first version asked whether a declaration was written under an `export`
 * keyword, so a hook exported by specifier or as a default reached neither set
 * and was not even in the exclusion list: a planted hook wider than anything in
 * the tree and deeper than anything in it passed all three arms, one character
 * of difference from the form that failed two of them. The fix is not a fourth
 * form in a list; it is that a name is exported when an export names it, in
 * whatever way, and a candidate is any name a top level declaration binds.
 *
 * **A name exported here but declared elsewhere is measured where it is
 * declared**, which is every `index.ts` in this tree re-exporting its page's
 * hook. Such an export binds nothing locally, so it yields no candidate here
 * and is not lost: it is counted once, in the module that writes it.
 */
let census: {
  measured: HookRow[];
  unmeasured: string[];
  contracts: ContractRow[];
} | null = null;

function hookRows(): {
  measured: HookRow[];
  unmeasured: string[];
  contracts: ContractRow[];
} {
  if (census !== null) return census;
  const writes = mutationHookNames();
  const measured: HookRow[] = [];
  const unmeasured: string[] = [];
  const contracts: ContractRow[] = [];

  for (const [path, source] of entries()) {
    if (path.startsWith(NOT_OURS_TO_WRITE)) continue;
    const { hooks, widths, fromTheClient } = hooksExportedBy(path, source);

    for (const binding of hooks) {
      const hook = binding.name;
      const local = binding.local;
      const fn = binding.value;
      contracts.push({
        path,
        hook,
        annotated: declaresItsReturn(binding),
        callable: isCallable(fn),
      });
      if (!isCallable(fn)) {
        unmeasured.push(`${path}:${local}`);
        continue;
      }
      const returned = isNode(fn.returnType)
        ? fn.returnType.typeAnnotation
        : null;
      const named =
        isNode(returned) &&
        returned.type === "TSTypeReference" &&
        isNode(returned.typeName)
          ? text(returned.typeName.name)
          : null;
      const members = named === null ? undefined : widths.get(named);
      if (members === undefined) {
        unmeasured.push(`${path}:${local}`);
        continue;
      }
      const called = new Set<string>();
      visitNodes(fn.body, (node) => {
        if (node.type !== "CallExpression" || !isNode(node.callee)) return;
        const callee = text(node.callee.name);
        if (callee !== null) called.add(callee);
      });
      const mutations = [...called].filter(
        (name) => fromTheClient.has(name) && writes.has(name),
      ).length;
      measured.push({ path, hook, local, members, mutations });
    }
  }

  census = { measured, unmeasured, contracts };
  return census;
}

/**
 * What an export statement's specifiers call each name, inside and outside.
 *
 * The two are the same under every spelling but one, and `localNamesOf` beside
 * this reads only the inside half, which is all an import needs and is why it
 * is left alone.
 *
 * **`default` is not a name**, it is the slot, so a specifier exporting into it
 * falls back to the local name. `export default useX` a few lines above already
 * does that, and without this the same hook written
 * `export { useX as default }` keyed on a word no hook can be called and left
 * the population, which is the sibling branch and this one disagreeing about
 * one hook.
 *
 * **A type only export carries no value**, so `export type { Foo as useX }`
 * and a `type` marked specifier inside an ordinary export are skipped rather
 * than admitted as a hook bound to something uncallable. `exportKind` is read
 * on the statement and on the specifier because either may carry it.
 *
 * A specifier naming its outside half with a string literal yields nothing
 * here, which is a form this walk used to cover under its local name and now
 * does not: no identifier can be spelled that way, so nothing it named could
 * have been reached as a hook.
 */
function renamesOf(statement: Node): { out: string; here: string }[] {
  if (text(statement.exportKind) === "type") return [];
  const specifiers = Array.isArray(statement.specifiers)
    ? (statement.specifiers as unknown[])
    : [];
  return specifiers.flatMap((one) => {
    if (!isNode(one) || !isNode(one.local)) return [];
    if (text(one.exportKind) === "type") return [];
    const here = text(one.local.name);
    const named = isNode(one.exported) ? text(one.exported.name) : here;
    const out = named === "default" ? here : named;
    return here === null || out === null ? [] : [{ out, here }];
  });
}

/** The local names an import or export statement's specifiers stand for. */
function localNamesOf(statement: Node): string[] {
  const specifiers = Array.isArray(statement.specifiers)
    ? (statement.specifiers as unknown[])
    : [];
  return specifiers.flatMap((one) => {
    if (!isNode(one) || !isNode(one.local)) return [];
    const local = text(one.local.name);
    return local === null ? [] : [local];
  });
}

/**
 * Width is a symptom, and this is where that claim is held.
 *
 * **The claim the decision record on deep modules behind narrow doors makes
 * about this tree's hooks**, asserted here rather than left in its prose. That
 * document is stripped before publication and this file is not, so the pointer
 * runs one way only: it names this block, and nothing here names it. Its
 * frontend section carried three live figures and every one of them was wrong
 * by the time anybody re read them, which is what a number in prose does: it
 * stops being re derived and starts being copied.
 *
 * **Two quantities, and the third was measured and refused.** The width of a
 * hook's result interface, and per member the distinct generated mutation hooks
 * its body **calls by the name it imported them under**. That is what is
 * counted, and it is narrower than reaching them: a call through an alias,
 * `const call = useAddBook`, and a call through a member expression are both
 * invisible to it, so a hook whose writes all go that way measures zero and
 * enters the comparison as a shallow one. **The extent of what else is not
 * bounded here**, and no alias is chased: following one needs a resolver, which
 * is a larger instrument than this arm and is the enumeration the population
 * walk has already been fixed three times for. An arm's job is to fail on a
 * mutation rather than to quantify its own blind spot.
 *
 * A count of the private declarations a hook reads was the obvious third and is
 * not here: two instruments disagreed on it for two of the
 * three rows anybody had published while agreeing on these two for every row of
 * the tree, and a private declaration that a sibling hook also reads belongs to
 * neither of them, so the column needs a policy and a policy is the hand
 * judgement a derived figure exists to remove.
 *
 * **No figure is written down and no cut is asserted.** Both arms below are
 * ordinal. A bound stops guarding without ever failing, which this tree has
 * measured twice, and the backend guard for the same document records a rank
 * cut passing with a margin of three hundredths before it was replaced by a
 * claim about a family.
 *
 * **What it does not hold, stated rather than bounded: the refusal.** The
 * section refuses collapsing a wide hook of distinct operations into one
 * `update(patch)`, and no assertion over these two quantities can refuse it,
 * because the collapse takes members away and leaves the writes where they
 * are, which moves that hook **up** the second ordering and leaves every arm
 * below green. What stops that is the paragraph. How much else these two
 * quantities miss is not bounded here, because every seat that tries will
 * succeed at measuring something and fail at bounding it.
 */
describe("a hook's width does not rank it by what is behind its door", () => {
  /**
   * The two hooks the section argues about, by name.
   *
   * **Named because the document names them**, which is the difference between
   * this and the pair it refuses to name elsewhere: that one is an illustration
   * chosen to show a general claim and swaps as the tree moves, and these two
   * are the subject the section was written about. A rename or a deletion has
   * to fail here rather than pass over a population that no longer holds them.
   */
  const NARROWED = "useLibrary";
  const REFUSED = "useBookActions";

  it("finds the hooks the section argues about", () => {
    const { measured, unmeasured } = hookRows();

    // **No hook is counted twice and the exclusion is a list rather than a
    // silence.** A row the instrument cannot measure is named in `unmeasured`
    // and a duplicate would let one hook sit at the top of both orderings
    // under two entries, which is the arithmetic the arms below rest on.
    //
    // **Keyed on what the module binds, not on what it exports**, because one
    // binding exported twice, `export { useX as useAlias }` beside `useX`, is
    // two names and one hook: keyed on the exported name this arm stayed green
    // over exactly the duplicate its comment says it refuses, while the
    // orderings below took the hook twice.
    //
    // **The arms below depend on this one for identity, not only for
    // arithmetic**, which is a dependency rather than an order of execution.
    // They tell hooks apart by the exported name and, at the intersection of
    // widest and deepest, by object reference. Both are unique per hook only
    // while no binding has two rows: with an alias, a hook is compared against
    // itself, and one hook can stand at the top of both orderings under two
    // names with the intersection still empty. So a red here is not a count
    // going wrong, it is the population those arms are written over ceasing to
    // be one row per hook.
    expect(measured.length + unmeasured.length).toBe(
      new Set([
        ...measured.map((row) => `${row.path}:${row.local}`),
        ...unmeasured,
      ]).size,
    );
    expect(measured.length).toBeGreaterThan(1);

    const found = measured.map((row) => row.hook);
    expect(found).toContain(NARROWED);
    expect(found).toContain(REFUSED);
  });

  it("ranks no hook first by width and first by depth at once", () => {
    // **The claim itself.** Falsified exactly when the two orderings agree at
    // the top, which is the tree in which ranking hooks by the width of their
    // interface would be ranking them by what is behind it, and the section
    // would be wrong. Written over the whole population rather than over a
    // pair, and tie safe in both orderings: a hook is at the top when nothing
    // stands strictly above it.
    const { measured } = hookRows();
    const widest = measured.filter(
      (row) => !measured.some((other) => other.members > row.members),
    );
    const deepest = measured.filter(
      (row) => !measured.some((other) => ratioOf(other) > ratioOf(row)),
    );

    expect(
      widest.filter((row) => deepest.includes(row)).map((row) => row.hook),
    ).toEqual([]);
  });

  it("keeps the refused hook the deeper of every hook as wide as it", () => {
    // **The sentence the section actually writes**, in both halves. The pair:
    // these two look alike by width and only one of them is a defect. The
    // family: at that width, this hook is the one with an operation per name.
    //
    // **The pair alone is not enough and that was measured.** The narrowed hook
    // calls no mutation at all, so "deeper than it" is "deeper than nothing",
    // and the only tree that falsifies it is one where the refused hook's
    // writes reach exactly zero. Planted, its writes collapsed to one and six
    // hooks standing above it, and the pair arm stayed green. The family arm is
    // red on that same mutant, because the widest hook in the tree sits above
    // it the moment its operations stop being distinct.
    //
    // **Quantified over the hooks at least as wide, not over all of them.** A
    // thin door over two writes ranks high per member and says nothing about
    // this claim, which is about what is behind a wide door; asking the whole
    // population is the rank cut this replaced, and it reddens on such a door
    // arriving. Today the subpopulation is this hook and the widest one, at
    // 10x.
    //
    // **And the subpopulation has to have somebody in it**, which is this
    // file's own rule that a claim with no subject passes over nothing, applied
    // to a claim whose subject is a set rather than a name. Two ordinary
    // changes empty it: widening the refused hook past everything, which also
    // takes its ratio down and is invisible to every other arm, and narrowing
    // the widest hook below it, which is the subject of the work this block was
    // written during. Either one means the section's own "two came out at the
    // top" has stopped describing the tree, so a red here is a paragraph
    // wanting re-reading rather than a spurious failure.
    const { measured } = hookRows();
    const refused = measured.find((row) => row.hook === REFUSED);
    const narrowed = measured.find((row) => row.hook === NARROWED);
    expect(refused).toBeDefined();
    expect(narrowed).toBeDefined();

    expect(
      ratioOf(refused!) > ratioOf(narrowed!)
        ? "the refused hook is the deeper of the two"
        : `${REFUSED} is no longer deeper per member than ${NARROWED}`,
    ).toBe("the refused hook is the deeper of the two");

    const asWide = measured.filter(
      (row) => row.hook !== REFUSED && row.members >= refused!.members,
    );

    expect(
      asWide.length > 0
        ? "some other hook is as wide as the refused one"
        : `nothing is as wide as ${REFUSED} any more, so this claim holds over nothing`,
    ).toBe("some other hook is as wide as the refused one");

    expect(
      asWide
        .filter((row) => ratioOf(row) >= ratioOf(refused!))
        .map((row) => row.hook),
    ).toEqual([]);
  });
});

/**
 * Every exported hook writes its return type down.
 *
 * **An inferred hook return is invisible to review**, which is the whole
 * reason: one had reached twelve members before anybody noticed, because a
 * diff adding a field to an inferred object shows a field and never a
 * signature. A declared return type puts the shape in the source, so widening
 * it is an edit somebody has to make on purpose.
 *
 * **The population is the census above**, every `use*` a module under `src`
 * both binds and exports, and it is stated as an exclusion: the generated
 * client, at `NOT_OURS_TO_WRITE`, and nothing else. A glob of the pages tree
 * would have been an inclusion list arrived at by another route, silent about
 * every hook exporting module outside it.
 *
 * **Two spellings, and only one of them has a counter example in this tree.**
 * A rule matching `export function use` misses `export const useX = () => …`
 * entirely, and nothing in the tree would make a reader think of it. So the
 * check reads the property, a return type on the callable or on the binding it
 * is assigned to, and the fixture arm below pins both spellings whether or not
 * either is written here today. **The name is read from the export in every
 * form, including the rename**, `export { inner as useX }`: reading the local
 * name there produced no row at all, and the tree's renamed exports all carry
 * a `from` and are somebody else's rows, which is why nothing here showed it.
 *
 * **What it does not hold, stated rather than bounded.** It asks whether a
 * return type is written, never whether it says anything: `(): unknown` passes,
 * and so does an alias for something inferred elsewhere. It takes a name
 * beginning `use` as the definition of a hook, because nothing short of a type
 * checker distinguishes one, so a hook under another name is outside it and a
 * constant under this one is inside it. A hook declared in one module and
 * re-exported by another is judged where it is declared, which is the census's
 * own rule and is why every page's `index.ts` contributes nothing here. How
 * much else a name based population misses is not bounded: every seat that
 * tries will succeed at measuring something and fail at bounding it.
 */
describe("every exported hook declares its return type", () => {
  /**
   * A module that exports a hook, by the coarsest reading available.
   *
   * **A floor for the census, not a second population.** It sees the two
   * spellings written at the top of a line and is blind to the specifier and
   * default exports the census walk does see, so it under reports by
   * construction and the census is the only thing holding those forms. It can
   * also over report, which is why a red below is a module to go and look at
   * rather than proof of a missed export: comments are read past, but
   * `withoutProse` keeps template chunks and JSX text, so a line beginning
   * `export const useFake` written inside either is characters to this probe
   * and nothing at all to the census.
   */
  function looksLikeItExportsAHook(path: string, source: string): boolean {
    return /^export (?:function|const) use[A-Z]/m.test(
      withoutProse(source, langOf(path)),
    );
  }

  it("finds the exported hooks of every module that has one", () => {
    const { contracts } = hookRows();

    // **A subject, before any claim about it.** A census that silently returned
    // nothing would satisfy every assertion below by holding over nobody, which
    // is this file's own rule applied to itself. Renaming the census, moving
    // the source glob or breaking the parse all land here.
    expect(contracts.length).toBeGreaterThan(0);

    const covered = new Set(contracts.map((row) => row.path));
    const missed = entries()
      .filter(([path]) => !path.startsWith(NOT_OURS_TO_WRITE))
      .filter(([path, source]) => looksLikeItExportsAHook(path, source))
      .map(([path]) => path)
      .filter((path) => !covered.has(path));

    // Named rather than counted: a module dropped from the population is the
    // failure that reads as a pass, and a number says nothing about which.
    //
    // **This is also what catches a second exclusion**, and it is the only
    // thing that does: a prefix skipped anywhere in the census leaves its
    // modules out of `covered` and they arrive here by name. It catches one
    // only over the modules the floor can see, which is every hook exporting
    // module in the tree today and no claim about tomorrow's.
    expect(missed).toEqual([]);

    // The named exclusion is honoured. **This assertion cannot see a second
    // one**: an early `continue` for another prefix leaves it green, because
    // what it reads is which paths are present rather than which are skipped.
    expect(
      contracts.filter((row) => row.path.startsWith(NOT_OURS_TO_WRITE)),
    ).toEqual([]);
  });

  it("tells an inferred return from a declared one in either spelling", () => {
    // **The detector's own diagonal.** Every arm here reports what the tree
    // holds, and a check that answered "annotated" to everything would report a
    // clean tree for ever. So the same function is run over a module written to
    // contain both answers, and it has to split them.
    //
    // The forms are the ones this census has already been wrong about or is
    // warned about: the declaration, the arrow that no counter example in the
    // tree would suggest, the binding carrying the signature instead of the
    // callable, the export by specifier that once took a hook out of the
    // population entirely, the rename on the way out, which is the one form
    // where this walk read the declaration instead of the export and so had no
    // row to be wrong about, the default slot written as a specifier, which is
    // a hook and not a hook called `default`, and the two type only spellings,
    // which are neither. The floor arm above cannot see any specifier form, so
    // this is where all of them are held.
    const source = [
      "interface Shape { a: number }",
      "export function useAnnotatedDeclaration(): Shape { return here(); }",
      "export function useInferredDeclaration() { return here(); }",
      "export const useAnnotatedArrow = (): Shape => here();",
      "export const useInferredArrow = () => ({ a: 1 });",
      "export const useAnnotatedBinding: () => Shape = () => here();",
      "const useInferredSpecifier = () => ({ a: 1 });",
      "export { useInferredSpecifier };",
      "const innerName = () => ({ a: 1 });",
      "const annotatedInner = (): Shape => here();",
      "export { innerName as useInferredRename };",
      "export { annotatedInner as useAnnotatedRename };",
      // `default` is the slot rather than a name, so this is the same row
      // `export default useDefaultSlot` would give, under the local name.
      "const useDefaultSlot = () => ({ a: 1 });",
      "export { useDefaultSlot as default };",
      // A type carries no value and is not a hook however it is named.
      "interface Foo { b: number }",
      "export type { Foo as useNotAHookAtAll };",
      "export { type Foo as useNorThisOne };",
    ].join("\n");

    const hooks = hooksExportedBy("fixture.ts", source).hooks;
    const split = (annotated: boolean): string[] =>
      hooks
        .filter((one) => declaresItsReturn(one) === annotated)
        .map((one) => one.name)
        .sort();

    // Asserted by the exported name, which is the name a caller sees and the
    // one the rule is about. `innerName` appearing here instead would mean the
    // walk had gone back to reading the declaration.
    // **Two names for one binding are two rows and one hook**, which is what
    // the width census's duplicate arm keys on `local` to see. Asserted apart
    // from the two lists so that neither has to carry an alias of a name it
    // already holds.
    const aliased = hooksExportedBy(
      "fixture.ts",
      [
        "const useOne = () => ({ a: 1 });",
        "export { useOne, useOne as useTwo };",
      ].join("\n"),
    ).hooks;
    expect(aliased.map((one) => `${one.name}:${one.local}`).sort()).toEqual([
      "useOne:useOne",
      "useTwo:useOne",
    ]);

    expect(split(true)).toEqual([
      "useAnnotatedArrow",
      "useAnnotatedBinding",
      "useAnnotatedDeclaration",
      "useAnnotatedRename",
    ]);
    expect(split(false)).toEqual([
      "useDefaultSlot",
      "useInferredArrow",
      "useInferredDeclaration",
      "useInferredRename",
      "useInferredSpecifier",
    ]);
  });

  it("leaves no exported hook's return type to inference", () => {
    // **The rule.** Listed by name, because the point of a red here is to say
    // which hook to go and annotate.
    const { contracts } = hookRows();

    expect(
      contracts
        .filter((row) => !row.annotated)
        .map((row) => `${row.path}:${row.hook}`)
        .sort(),
    ).toEqual([]);
  });

  it("reads a callable for every exported hook", () => {
    // **A form the check can only half read, raised rather than passed over.**
    // A name bound to something that is not callable, `memo(f)` or a factory's
    // answer, carries no signature of its own, so the arm above is left reading
    // the binding's annotation and nothing else. There are none today. A red
    // here is a spelling arriving that somebody has to look at, not a defect in
    // the hook it names.
    const { contracts } = hookRows();

    expect(
      contracts
        .filter((row) => !row.callable)
        .map((row) => `${row.path}:${row.hook}`)
        .sort(),
    ).toEqual([]);
  });
});
