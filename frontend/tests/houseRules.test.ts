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
 * The sources come from `tests/sourceModules.ts`, which reads them and says
 * why it reads them the way it does. They used to be globbed here, and the
 * pattern is what a narrowing edits.
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

// The config that decides which files are tests at all. Read so the one
// spelling of that suffix below is checked against it rather than repeated.
import viteConfig from "../vite.config.ts?raw";

// The repository's own statement of what it refuses to version. Read so that
// the directory a publish run's output cannot be **kept** in is pinned by a
// fact this repository already maintains rather than by a name written here,
// which is what the exclusion below used to be. Where the output lands is an
// argument to the script and is the premise of this whole reading, so nothing
// here may call any directory the one it is guaranteed to land in.
import ignoreRules from "../../.gitignore?raw";

// The one enumeration of `src/`, and the one thing that refuses a corpus that
// is no longer the tree. The pattern used to be written here, where narrowing
// it was one edit in the file holding the rules it disarmed.
import { sourceEntries as entries, sourceText } from "./sourceModules";

// The one enumeration of `tests/`, and the one thing that refuses a corpus
// that is no longer the tree. Three patterns used to be written here and in
// `withoutProse.test.ts`, one per rule. **It holds this file's own source
// too**, which the glob here could not: a module is excluded from its own
// `import.meta.glob`, so every rule written here used to read one file short
// and the file was this one. That exemption is now stated by each rule that
// wants it, and refused when it names a file the tree does not hold.
import { testEntries, testEntriesBesides } from "./testModules";

/**
 * The application tree in the space the test tree's specifiers resolve into.
 *
 * **A spelling, not a second population.** `resolvedFrom` resolves both
 * corpora into paths relative to this directory, so a scope mixing the
 * application tree with the test tree has to spell the first from here or
 * every cross tree specifier resolves to a key nothing holds.
 */
function sourcesAsImported(): [string, string][] {
  return entries().map(([path, source]) => [`../src/${path}`, source]);
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
    // **A floor used to stand here, and a floor is not an arming check.**
    // Fifty, against a corpus of several hundred, left a narrowing room to
    // drop every page and clear it anyway. The corpus now comes
    // from `tests/sourceModules.ts`, which refuses one that is not the tree
    // and throws rather than answering a short one, so what this arm has
    // left to say is that the refusal is reached from here.
    expect(() => entries()).not.toThrow();
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
    const source = sourceText(FLAGS_MODEL);
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

/** What a cell of such a table may be. See `asRow`, which is why it is named. */
type Cell = string | number | boolean | readonly string[];

/** What separates one cell from the next on a rendered line. */
const CELL = " | ";

/** What separates one item from the next inside a cell holding a list. */
const ITEM = ", ";

/**
 * `text` with every character `marks` names prefixed by the escape character.
 *
 * **Both classes hold the escape character and only one of them needs it.**
 * In a list item it is load bearing: the item separator's escape is a
 * backslash and a comma, so an item ending in a backslash, followed by the
 * raw separator, is the same bytes as an item spelling that separator, and
 * `renders two rows of one shape as two lines that differ` carries the pair
 * that drives it.
 *
 * **In a string cell it is inert today, measured, and it stays because what
 * makes it inert is not this function.** The cell separator carries spaces
 * and the escape of a pipe does not, so the two cannot be confused. **Spell
 * that separator without its spaces and a collision becomes reachable across
 * shapes, and only across shapes**: the property asserted here is per shape,
 * by its own grouping and by the argument that rows of one table share a
 * column's kind and a width, so the per shape result stays empty under
 * exactly that condition and no arm here would red. That is the extent of
 * what is known about it, and it is the reason this stays rather than being
 * measured inert and taken out.
 */
function escaped(text: string, marks: RegExp): string {
  return text.replace(marks, (one) => `\\${one}`);
}

/**
 * One row of a table driven rule group, rendered as a line.
 *
 * **A rule group here is a local table feeding one `it.each`, and each caller
 * holds its own table against a written list of these.** Without that list a
 * row can be deleted in silence: the generator makes one arm fewer, nothing
 * else reads the table, and the only thing that moves is the frontend
 * coverage register, which a merge re-renders as a matter of course, so the
 * one trace of a case leaving is erased by the ordinary process that follows
 * it.
 *
 * **What holds the lists themselves is `a table driven rule group is held by
 * a pin on one declaration`, and two things it does not hold are written
 * here rather than there.** Of the six edits that were silent beside this
 * renderer, five are now refused: a table added with no list beside it, a
 * list deleted, a list marked skipped, which is worse than a deletion
 * because the list is still there for the next reader to believe, a
 * generator handed a narrowed table, and a list pinning fewer rows than the
 * generator drives. Each is driven as a row of that rule's own refusals.
 *
 * **The sixth stands: the whole group of arms over this renderer deleted.**
 * That is the regress every guard in this tree sits on and nothing closes
 * it. **And one word still disarms the file**, because `only` on any arm
 * anywhere leaves the rule below among the arms that do not run, which no
 * rule written in this file can observe: it wants a focused test check in
 * the linter, which this project's configuration does not enable today.
 *
 * **Membership rather than a size.** A count cannot tell a row swapped for
 * another from the row it replaced, nor a row whose input is rewritten in
 * place onto a case the table already drives: both leave it where it was and
 * the case is gone either way.
 *
 * **Every cell, rather than the row's name.** A name alone is green on a row
 * whose input was rewritten under it, measured, and the case is as gone as if
 * the row had been deleted. The cost is that a cosmetic edit to a fixture
 * reds as loudly as a deletion, and loud is the direction to be wrong in.
 * **When one of these arms reds, rewrite the line only after confirming the
 * row still drives a case no other row drives**: rewriting it on sight is how
 * a case losing edit is waved through, and it is the same keystroke as the
 * legitimate answer.
 *
 * **The separators are escaped inside the values, because joining a list is
 * otherwise not injective.** A list of three documents and a single document
 * spelling all three render the same line: measured live on the copy table,
 * where the collision takes a named decision witness with it and leaves only
 * a collateral catch behind. Escaping was taken over refusing such a value at
 * the door because it refuses nothing: a door refusal on the cell separator
 * would have turned away a source fixture spelling a union type, which is
 * ordinary in exactly this subject matter. Measured on the tree as it stands,
 * no value holds either separator, so no line here is escaped today.
 *
 * **Both separators are escaped inside a list item, and the cell separator
 * is the one that was missing.** Two list columns are the copy table's own
 * shape, and with an item free to carry the cell separator two rows of one
 * kind per column and the same width render the same line. **Two kinds in
 * one column collide for a different reason**, and `asRows` refuses a mixed
 * column rather than this saying one does not arise.
 *
 * **One renderer rather than a key per table**, because the tables differ in
 * what their cells mean and not in what a cell is. Nothing here reads a
 * column's meaning, so no table is made to look like another.
 *
 * **`Cell` names what this can print**, so a cell of any other kind is a type
 * error at the call site. That is the whole of what it excludes: it says
 * nothing about two rows rendering alike.
 */
function asRow(cells: readonly Cell[]): string {
  return cells
    .map((one) => {
      if (typeof one === "object")
        return `[${one.map((item) => escaped(item, /[\\,|]/g)).join(ITEM)}]`;
      return typeof one === "string" ? escaped(one, /[\\|]/g) : String(one);
    })
    .join(CELL);
}

/**
 * Every row of a table, rendered, with what the rendering rests on refused.
 *
 * **One kind per column, asserted here rather than stated anywhere.** `asRow`
 * reads a cell as a list or as a value by its own kind, so a column holding
 * two kinds breaks the escaping argument outright, and three pairs collide
 * today: a string spelling a bracketed list against that list, a number
 * against its own spelling, and a boolean against its own. Nothing in the
 * tree has a mixed column and the tuple types are what keep it so, so this
 * refuses nothing as it stands and reds at the first one, which is the
 * moment the argument stops holding. **A refusal that refuses nothing today
 * is deleted by the next reader who measures it**, so both refusals here
 * carry an arm of their own in `a row of a rule table is rendered as one
 * line`: without them this whole file is green with both lines gone.
 *
 * **One width too**, because the column walk takes its width from the first
 * row: a row carrying cells past that width is never read, and a shorter one
 * is caught only as a column of two kinds, which is a message about the
 * wrong thing.
 */
function asRows(table: readonly (readonly Cell[])[]): string[] {
  expect(table, "a table with no rows, which drives nothing").not.toHaveLength(
    0,
  );

  const widths = [...new Set(table.map((row) => row.length))];
  expect(
    widths,
    "rows of one table that are not all the same width: a row with no value for a column is a different table rather than a short row",
  ).toHaveLength(1);

  const kindOf = (cell: Cell) =>
    typeof cell === "object" ? "list" : typeof cell;
  const mixed = [...Array.from({ length: widths[0] ?? 0 }).keys()].filter(
    (column) => new Set(table.map((row) => kindOf(row[column]!))).size > 1,
  );
  expect(
    mixed,
    "columns holding more than one kind of cell: the rendering reads a cell by its kind, so give the column one kind rather than widening this helper",
  ).toEqual([]);

  return table.map((row) => asRow(row));
}

describe("a row of a rule table is rendered as one line", () => {
  it("renders a cell of every kind the tables carry", () => {
    // **Arms on the renderer rather than through whichever table carries a
    // kind.** The list branch was held by the copy table's arm alone, so
    // dropping it reddened one arm of three and the claim that a change here
    // reds all three was an extent claim about the narrowings chosen.
    expect(asRow(["a text", 7, true, ["x", "y"]])).toBe(
      "a text | 7 | true | [x, y]",
    );
  });

  it("refuses a column holding more than one kind of cell", () => {
    // **The refusals inside `asRows` have no other arm.** Deleting both
    // leaves this file green, measured, because nothing on the tree has
    // either shape: a line that refuses nothing today and is held by nothing
    // is a line the next reader removes, and the escaping every membership
    // arm rests on goes with it.
    expect(() =>
      asRows([
        ["a", "b"],
        ["a", ["b"]],
      ]),
    ).toThrow(/more than one kind/);
  });

  it("refuses a table whose rows are not all one width, and an empty one", () => {
    expect(() => asRows([["a"], ["a", "b"]])).toThrow(/not all the same width/);
    expect(() => asRows([])).toThrow(/no rows/);
  });

  it("tells a list of items from one item spelling the whole list", () => {
    // The live collision, and the shape it was found in: a corpus of three
    // documents rewritten as one document naming all three rendered the same
    // line, kept the same generated name and the same verdict, and took the
    // row's decision witness with it.
    expect(asRow([["a", "b"]])).not.toBe(asRow([["a, b"]]));
  });

  it("renders two rows of one shape as two lines that differ", () => {
    // **The measurement, rather than the argument**, and it is grouped by the
    // kinds a row's columns hold, because that is the claim: rows of one
    // table share a column's kind, and two kinds in one column collide for a
    // different reason and are refused by `asRows`. Comparing across shapes
    // would red this arm over a collision nothing can reach.
    //
    // **The pair that matters is a value spelling a separator against the
    // values it would be read as**, so both are built rather than only the
    // concatenation. An alphabet that never constructs the colliding
    // spelling is green under the escapes dropped, measured.
    const alphabet = ["a", ",", "|", "\\", "a, b", "a | b"];
    const rows: Cell[][] = [];
    for (const first of alphabet)
      for (const second of alphabet) {
        rows.push([first, second]);
        rows.push([first + CELL + second]);
        rows.push([[first, second]]);
        rows.push([[first + ITEM + second]]);
        rows.push([[first], [second]]);
      }

    // **An item ending in the escape character, against an item spelling the
    // item separator.** This pair is what the escape character's own escape
    // inside a list item is for: the separator's escape is a backslash and a
    // comma, so without it these two render the same bytes. The alphabet
    // holds the character and never pairs it into that position, so the rows
    // are written out.
    rows.push([["a\\", "b"]]);
    rows.push([["a, b"]]);

    // **Two string columns, and this pair is what the cell separator escape
    // inside a string cell is for.** Grouping by shape is what made it
    // necessary: the pair that used to catch that escape was a two cell row
    // against a one cell row, which are different shapes and are no longer
    // compared, and dropping the escape went green until these two rows
    // existed. Measured both ways.
    rows.push(["a | b", "c"]);
    rows.push(["a", "b | c"]);

    // **Two list columns is the copy table's shape, and this pair is what
    // the cell separator escape inside an item is for.** One kind per column
    // and the same width in both, and with that escape dropped they render
    // the same line, which an alphabet of single values cannot construct.
    rows.push([["a] | [b"], ["c"]]);
    rows.push([["a"], ["b] | [c"]]);

    const shapeOf = (row: Cell[]) =>
      row
        .map((cell) => (typeof cell === "object" ? "list" : typeof cell))
        .join("/");
    const byShape = new Map<string, Cell[][]>();
    for (const row of rows)
      byShape.set(shapeOf(row), [...(byShape.get(shapeOf(row)) ?? []), row]);

    const collided = [...byShape]
      .filter(
        ([, group]) =>
          new Set(group.map((row) => asRow(row))).size !==
          new Set(group.map((row) => JSON.stringify(row))).size,
      )
      .map(([shape]) => shape);

    expect(collided).toEqual([]);
  });
});

/**
 * The renderer a pin reads a table through, named once. See `asRows`.
 *
 * **The rule matches ten names out of the code it reads**: this one,
 * `expect`, the two exact matchers, the two generator properties, the
 * three runner names and the module they come from. Each is loud when it
 * stops matching. Renaming the renderer without changing this line reds
 * every group at once; an aliased `expect` or matcher stops a pin being
 * read as a pin, which reports the group it was holding; a runner
 * spelling or a runner module outside those refuses a pin that runs.
 * Accepting any one argument call in the renderer's place would instead
 * take a pin that drops cells, with nothing said, which is the direction
 * this refuses.
 */
const PIN_RENDERER = "asRows";

/**
 * The matchers that hold a whole value, so that a row leaving is seen.
 *
 * A length, a containment or a predicate is green on a table that has lost a
 * row, which is the defect `asRow` exists for. Anything not here is not read
 * as a pin, so the group it was meant to hold is reported.
 */
const WHOLE_VALUE_MATCHERS = new Set(["toEqual", "toStrictEqual"]);

/**
 * Every node that opens a scope a name can be bound in.
 *
 * **The grammar's list rather than anybody's memory, and a kind missing
 * from it is a silent miss.** Its bindings land in the map of the scope
 * outside it, where the outer declaration was added first and wins, so the
 * pin and the generator reach one node and the group reads as held. That
 * is a false acceptance, which is the defect this whole rule is about, and
 * it is the opposite of what the first version of this sentence claimed.
 *
 * **So nothing here is self correcting and a row per construct is what
 * makes it loud.** Most members turn a refusal into an acceptance when
 * they go, the block statement and the arrow the most of any; the enum
 * body refuses something legitimate instead and the program does both,
 * because without it a foreign import binds nowhere and the nothing it
 * resolves to reads as the runner; and a handful move no row. **The breakdown is deliberately not written down**, because
 * it is a property of the rows and it went stale in the commit that added
 * one: remove a member at a time and read it off, which is how every
 * figure here was taken.
 *
 * **The members that move no row are measured rather than assumed.** A
 * shadow written in a function declaration, a static block, a class
 * declaration or a class expression is caught by the scope inside or
 * around it, driven each way; the two bodiless function kinds cannot hold
 * a generator at all.
 */
const SCOPES = new Set([
  "Program",
  "FunctionDeclaration",
  "FunctionExpression",
  "ArrowFunctionExpression",
  "TSDeclareFunction",
  "TSEmptyBodyFunctionExpression",
  "BlockStatement",
  "StaticBlock",
  "TSModuleBlock",
  "ForStatement",
  "ForInStatement",
  "ForOfStatement",
  "CatchClause",
  "SwitchStatement",
  "ClassDeclaration",
  "ClassExpression",
  // An enum body is a namespace of its own, so its members bind inside it
  // and nowhere else. It is here rather than exempted at the reader below
  // because that is what it is: without it, every member of every enum is a
  // declaration the reader does not know, and one enum anywhere in the file
  // would refuse every name in it.
  "TSEnumBody",
]);

/** The three specifiers an import binds a local name through. */
const IMPORT_BINDINGS = new Set([
  "ImportSpecifier",
  "ImportDefaultSpecifier",
  "ImportNamespaceSpecifier",
]);

/**
 * The declaration kinds carrying a name that binds in the type space alone.
 *
 * **They are named because they are the exception to the refusal below**,
 * which records any other kind declaring a name the reader does not read,
 * rather than walking past it. Keyed on carrying an `id` that is an
 * identifier, which is what declaring a name looks like whatever the kind is
 * called. Censused that way over every module of `src` and `tests`, 689
 * files: these two are the only kinds that reach it, at 618 and 464
 * occurrences, so the exemption is what keeps the refusal off ordinary
 * TypeScript and nothing else is being waved through.
 */
const BINDS_IN_THE_TYPE_SPACE = new Set([
  "TSTypeAliasDeclaration",
  "TSInterfaceDeclaration",
]);

/**
 * The properties that make a call a table driven generator.
 *
 * **Two members, and an enumeration of two is still an enumeration.** A
 * third table driving property added by the runner is **reported** rather
 * than missed, because a curried call on a runner member is read by its
 * shape wherever the property list is short: see the refusal beside the
 * walk. What the two members decide is whether such a call is read as a
 * group or named as one this rule cannot read. The second member is
 * written against the next group rather than against anything live:
 * measured over this file, no row spells `for` today.
 */
const GENERATOR_PROPERTIES = new Set(["each", "for"]);

/**
 * The names a call must carry for what it is handed to be read as running.
 *
 * **Three members, and the shape of the call was not enough.** Asking only
 * that the callee be a plain name accepted `const quietly = it.skip` and
 * every helper besides. A runner spelling outside this set, `suite` or
 * whatever is added next, refuses a pin that does run, loudly at the line,
 * which is the direction to be wrong in here.
 */
const RUNNER_NAMES = new Set(["it", "test", "describe"]);

/** The module a runner name has to come from to be the runner. */
const RUNNER_MODULE = "vitest";

/** The nodes `value` holds, whether it is one node or a list of them. */
function nodesIn(value: unknown): Node[] {
  if (Array.isArray(value))
    return (value as unknown[]).filter((one): one is Node => isNode(one));
  return isNode(value) ? [value] : [];
}

/** Every node `node` holds directly, by its own keys rather than by a list. */
function heldBy(node: Node): Node[] {
  return Object.keys(node).flatMap((key) => nodesIn(node[key]));
}

/** Every node under `root`, each with the node holding it. */
function parentsOf(root: Node): Map<Node, Node | null> {
  const parents = new Map<Node, Node | null>([[root, null]]);
  const pending: Node[] = [root];
  while (pending.length > 0) {
    const node = pending.pop() as Node;
    for (const child of heldBy(node)) {
      parents.set(child, node);
      pending.push(child);
    }
  }
  return parents;
}

/**
 * Every name a binding position binds, by the pattern grammar.
 *
 * **Closed, and a shape outside it is recorded rather than skipped.**
 * Skipping one is how a shadowing binding goes unseen, and an unseen shadow
 * is what lets a pin and a generator spelling one name read as holding one
 * table while they name two.
 */
function boundBy(pattern: unknown, out: Node[], unreadable: string[]): void {
  if (!isNode(pattern)) return;
  if (pattern.type === "Identifier") out.push(pattern);
  else if (pattern.type === "ObjectPattern")
    for (const one of nodesIn(pattern.properties))
      boundBy(one, out, unreadable);
  else if (pattern.type === "ArrayPattern")
    for (const one of nodesIn(pattern.elements)) boundBy(one, out, unreadable);
  else if (pattern.type === "Property") boundBy(pattern.value, out, unreadable);
  else if (pattern.type === "AssignmentPattern")
    boundBy(pattern.left, out, unreadable);
  else if (pattern.type === "RestElement")
    boundBy(pattern.argument, out, unreadable);
  else if (pattern.type === "TSParameterProperty")
    boundBy(pattern.parameter, out, unreadable);
  else unreadable.push(pattern.type);
}

/** What one scope binds, and the binding shapes it could not read. */
interface ScopeBindings {
  readonly names: Map<string, Node>;
  readonly unreadable: string[];
}

/**
 * What `scope` binds, read off the constructs that bind rather than off the
 * statements a scope is allowed to hold.
 *
 * **Three sources, and the third is the one a block walk misses.** What the
 * scope node itself binds, which is its parameters, a catch's parameter and
 * an expression's own name; what is declared in its own region, found by
 * walking until the next scope so that a nested block keeps its own; and,
 * for a function body and the module body, what a `var` hoists out of a
 * nested block into.
 */
function scopeBindings(scope: Node): ScopeBindings {
  const names = new Map<string, Node>();
  const unreadable: string[] = [];
  const add = (value: unknown): void => {
    if (!isNode(value) || value.type !== "Identifier") return;
    const name = text(value.name);
    if (name !== null && !names.has(name)) names.set(name, value);
  };
  const take = (pattern: unknown): void => {
    const out: Node[] = [];
    boundBy(pattern, out, unreadable);
    for (const one of out) add(one);
  };

  for (const one of nodesIn(scope.params)) take(one);
  if (scope.type === "CatchClause") take(scope.param);
  if (scope.type === "FunctionExpression" || scope.type === "ClassExpression")
    add(scope.id);

  const lexical = (node: Node): void => {
    for (const child of heldBy(node)) {
      if (SCOPES.has(child.type)) {
        // A nested declaration binds its own name out here even though its
        // body is somebody else's scope. **Written as the two exceptions
        // rather than as a list of declarations**, which is what it was: a
        // function expression and a class expression bind their own name
        // inward only, and every other scope node either carries a
        // declaration's name or carries no `id` at all, where this is a no
        // op. Naming the declarations instead left `declare function` out,
        // measured, and that is a shadow nobody sees.
        if (
          child.type !== "FunctionExpression" &&
          child.type !== "ClassExpression"
        )
          add(child.id);
        continue;
      }
      if (child.type === "VariableDeclarator") take(child.id);
      else if (IMPORT_BINDINGS.has(child.type)) add(child.local);
      else if (
        child.type === "TSEnumDeclaration" ||
        child.type === "TSModuleDeclaration" ||
        child.type === "TSImportEqualsDeclaration"
      )
        add(child.id);
      // **A declaration kind this reader does not know is recorded, not
      // walked past.** `boundBy` already does that for a pattern shape, and
      // for one round this one did not do it for a declaration kind, so
      // `import T = A.rows` was a shadow that went unseen and the group read
      // as held while driving another table. The key is carrying an `id`
      // that is an identifier, which is what declaring a name looks like
      // whatever the kind is called.
      else if (
        !BINDS_IN_THE_TYPE_SPACE.has(child.type) &&
        isNode(child.id) &&
        child.id.type === "Identifier"
      )
        unreadable.push(child.type);
      lexical(child);
    }
  };
  lexical(scope);

  if (scope.type === "Program" || Array.isArray(scope.params)) {
    const hoisted = (node: Node): void => {
      for (const child of heldBy(node)) {
        if (
          Array.isArray(child.params) ||
          child.type === "ClassDeclaration" ||
          child.type === "ClassExpression"
        ) {
          if (child.type === "FunctionDeclaration") add(child.id);
          continue;
        }
        if (child.type === "VariableDeclaration" && text(child.kind) === "var")
          for (const one of nodesIn(child.declarations)) take(one.id);
        hoisted(child);
      }
    };
    hoisted(scope);
  }
  return { names, unreadable };
}

/** The declaration a name reaches, or why it reaches none. */
interface Resolution {
  readonly declaration: Node | null;
  readonly why: string;
}

/**
 * A reader answering which declaration a name refers to.
 *
 * **This is the whole of the idea the rule below rests on.** A name resolves
 * to exactly one binding by the language's own scoping rules, so asking
 * whether a pin holds the table a generator drives is asking whether two
 * names reach one declaration. That question does not care which container
 * the shadowing happened in, which is why it terminates where four rounds of
 * naming containers did not.
 */
function resolverOver(
  parents: Map<Node, Node | null>,
): (use: Node) => Resolution {
  const cache = new Map<Node, ScopeBindings>();
  const bindings = (scope: Node): ScopeBindings => {
    const held = cache.get(scope);
    if (held !== undefined) return held;
    const fresh = scopeBindings(scope);
    cache.set(scope, fresh);
    return fresh;
  };
  return (use) => {
    const name = text(use.name) ?? "";
    let at = parents.get(use) ?? null;
    while (at !== null) {
      if (SCOPES.has(at.type)) {
        const { names, unreadable } = bindings(at);
        if (unreadable.length > 0)
          return {
            declaration: null,
            why: `a binding shape this rule cannot read, ${unreadable[0]}`,
          };
        const declaration = names.get(name);
        if (declaration !== undefined) return { declaration, why: "" };
      }
      at = parents.get(at) ?? null;
    }
    return { declaration: null, why: "no declaration in this file" };
  };
}

/** The name a member expression reads, or null where it reads none. */
function propertyName(member: Node): string | null {
  const property = member.property;
  if (!isNode(property)) return null;
  if (member.computed !== true && property.type === "Identifier")
    return text(property.name);
  if (property.type === "Literal" && typeof property.value === "string")
    return property.value;
  return null;
}

/** A call's callee read as a base name and the properties taken off it. */
interface Chain {
  readonly base: string;
  readonly props: string[];
}

function chainOf(callee: unknown): Chain | null {
  const props: string[] = [];
  let at: unknown = callee;
  while (isNode(at) && at.type === "MemberExpression") {
    const named = propertyName(at);
    if (named === null) return null;
    props.unshift(named);
    at = at.object;
  }
  if (!isNode(at) || at.type !== "Identifier") return null;
  const base = text(at.name);
  return base === null ? null : { base, props };
}

/**
 * Does everything between `node` and the module body run as written?
 *
 * **Every function on the way out has to be a call's own argument, and
 * that call has to name a runner.** A modifier is a property taken off the
 * runner, so `skip`, `only`, `todo` and whatever is added next fail the
 * test without being named; a pin lifted into a helper the arm merely
 * names is a function nobody passed to a call; and a pin handed to any
 * other call is one nothing here can say runs, whether that call defers
 * it, discards it or runs it at once.
 *
 * **Two versions of this test were beaten in opposite directions, and the
 * third asks the question the rest of the rule already asks.** Reading the
 * callee's **shape**, that it is a plain name, was beaten by aliasing the
 * runner into a local, `const quietly = it.skip`. Reading its **name** was
 * beaten by shadowing a local into the runner's, `const test = it.skip`.
 * Each fix closed the spelling just shown and left the other direction
 * open, which is the regress this whole rule exists to stop, reappearing
 * inside one function.
 *
 * **So `isTheRunner` reads the binding, as the generator side does.** A
 * name resolves to exactly one binding, and the only binding accepted is
 * an import of that name from the runner's module, or none at all.
 *
 * **That is closed against anything written in this file, and the argument
 * is the same one the group rule rests on.** It is two clauses rather than
 * three: a callee outside the three names is refused, **which covers a
 * callee that is not a name at all, because it carries no name to match**,
 * and a name resolving to anything but that import is refused. Nothing
 * else is left to spell. A third clause comparing the callee's node kind
 * stood here for a round and was discharged by the first: removing it
 * reddened nothing, which is the same masking the sweep found one layer
 * down.
 *
 * **Each half has a row, and the name test nearly did not.** The binding
 * test is held by the two locals carrying a runner's name and by the
 * foreign import. The name test looked held by the helper rows and was
 * not: a helper declared here is a local, so the binding test refuses it
 * whatever it is called, and dropping the name test left the suite green.
 * What the name test alone holds is a call **declared nowhere**, which
 * resolves to nothing and is accepted on the binding, and that is the row
 * `a pin under a call this file declares nowhere and no runner names`.
 * Found by this branch's own sweep, not by reading.
 *
 * **Two routes remain and neither is syntax**, which is why they are named
 * here rather than closed. The module could export something that is not
 * the runner under the right name, which no reading of this file can see.
 * And the runner could be replaced at run time, which `a module is
 * replaced by an alias, never by a module mock` is the rule for.
 *
 * **A name declared nowhere is read as the runner, and the reason is the
 * config rather than the fixtures.** This file imports four names and
 * `test` is not among them, so an arm written with `test` takes that
 * branch here today; saying it is what the fixtures are and the file is
 * not was wrong. What makes it right is that the suite runs with globals
 * on, so an undeclared runner name **is** the runner, and with globals off
 * it throws rather than passing quietly. The failure direction is loud
 * either way. `the runner a pin runs under is global when nothing declares
 * it` pins that setting, so the dependency reds rather than being stated.
 */
function isTheRunner(
  callee: unknown,
  parents: Map<Node, Node | null>,
  resolve: (use: Node) => Resolution,
): boolean {
  if (!isNode(callee)) return false;
  const named = text(callee.name);
  if (named === null || !RUNNER_NAMES.has(named)) return false;
  const declared = resolve(callee).declaration;
  // **Nothing declares it here, so it came from outside the file**, which
  // is what a fixture looks like and what an ambient runner looks like.
  // The resolver also answers nothing where a scope it met is unreadable,
  // and this reads that as the runner too: that costs nothing, because the
  // generator's own resolution hits the same scope and refuses the group.
  if (declared === null) return true;
  const holder = parents.get(declared) ?? null;
  if (holder === null) return false;
  // **A named import of that very name**, which is narrower than "some
  // import" by three live spellings: a namespace import, a default import
  // and a renamed import of another export all come from the runner's
  // module under a runner's name and are not the runner. One line does all
  // three: only a named import carries `imported` at all, so a namespace
  // or default specifier fails this test without being named.
  //
  // **A test for the specifier's kind stood beside this for a round and
  // was dominated by it**, reddening no row because this line already
  // refused everything it refused. That is the third time a clause in this
  // function has been masked by its neighbour, and the pattern is the part
  // worth keeping: drop each term of a predicate in turn and require one
  // row to move, or the term is dead. **Deleting it cost no arm**, because
  // the behaviour's witness is this line's own row, the renamed import.
  if (!isNode(holder.imported) || text(holder.imported.name) !== named)
    return false;
  const from = parents.get(holder) ?? null;
  return (
    from !== null && isNode(from.source) && from.source.value === RUNNER_MODULE
  );
}

function runsAsWritten(
  node: Node,
  parents: Map<Node, Node | null>,
  resolve: (use: Node) => Resolution,
): boolean {
  let at = parents.get(node) ?? null;
  while (at !== null) {
    if (Array.isArray(at.params)) {
      const holder = parents.get(at) ?? null;
      const passed =
        holder !== null &&
        holder.type === "CallExpression" &&
        nodesIn(holder.arguments).includes(at) &&
        isTheRunner(holder.callee, parents, resolve);
      if (!passed) return false;
    }
    at = parents.get(at) ?? null;
  }
  return true;
}

/**
 * Does the written list reach the declaration the pin is supposed to hold?
 *
 * A list built from the table is the table compared with itself, which is
 * green whatever the table says. Every node of the expected value is read,
 * so a spread and a call carrying the name are both refused rather than only
 * the spelling in hand.
 *
 * **And a name in between is not a laundry.** Stopping at the binding left
 * `const rendered = asRows(T)` and an expected value spelling `[...rendered]`
 * green, one variable away from the direct form this already refused, so a
 * name is followed. `seen` stops a cycle.
 *
 * **What it follows is narrow, and this is the mechanism rather than two
 * examples of it.** A name is followed only where the identifier it
 * resolves to is a declarator's own `id`, never one inside a pattern, and
 * only into that declarator's own initialiser. Every other route from the
 * rendering to the expected value is therefore accepted, measured: a
 * function declaration returning it, a static class field holding it,
 * either destructuring, and an assignment to a name declared without an
 * initialiser. The arm named for that blindness drives all five, so
 * closing the gap without moving this paragraph reds.
 */
function namesAgain(
  written: Node,
  declaration: Node,
  resolve: (use: Node) => Resolution,
  parents: Map<Node, Node | null>,
  seen: Set<Node>,
): boolean {
  if (written.type === "Identifier") {
    const reached = resolve(written).declaration;
    if (reached === null || seen.has(reached)) return false;
    if (reached === declaration) return true;
    seen.add(reached);
    const holder = parents.get(reached) ?? null;
    const init =
      holder !== null &&
      holder.type === "VariableDeclarator" &&
      holder.id === reached
        ? holder.init
        : null;
    return (
      isNode(init) && namesAgain(init, declaration, resolve, parents, seen)
    );
  }
  return heldBy(written).some((one) =>
    namesAgain(one, declaration, resolve, parents, seen),
  );
}

/** The nearest block or arm name above `node`, for the report. */
function labelAround(node: Node, parents: Map<Node, Node | null>): string {
  let at = parents.get(node) ?? null;
  while (at !== null) {
    if (
      at.type === "CallExpression" &&
      isNode(at.callee) &&
      at.callee.type === "Identifier"
    ) {
      const [first] = nodesIn(at.arguments);
      if (
        first !== undefined &&
        first.type === "Literal" &&
        typeof first.value === "string"
      )
        return first.value;
    }
    at = parents.get(at) ?? null;
  }
  return "no block";
}

/** One table driven rule group, and what holds the table it drives. */
interface Group {
  label: string;
  spelling: string;
  table: string;
  pin: string;
  fault: string;
}

/** One live equality over a whole value, and the declaration it holds. */
interface HeldPin {
  readonly through: string;
  readonly live: boolean;
  readonly declaration: Node | null;
}

/**
 * Every table driven rule group in `source`, and every generator it could
 * not read as one.
 *
 * **Keyed on the property rather than on the runner's name**, so a runner
 * this file has not seen is read rather than skipped. A generator the
 * chain reader cannot follow is reported instead of dropped, which is what
 * keeps the population from narrowing under the rule in silence, and it is
 * seeded from the same two properties, so widening one without the other
 * leaves the report blind to exactly the spelling it was widened for.
 *
 * **The seeding keys on the property alone and never on the chain**, so a
 * chain this reader cannot follow is reported whatever its base is: a
 * call, a conditional, `this`, a computed key on a call, a nested member.
 * Driven, all five.
 *
 * **`GENERATOR_PROPERTIES` is two members, and a third would be a miss
 * where a fourth runner name is a loud refusal.** That asymmetry is closed
 * by shape rather than by guessing the name: a curried call on a runner
 * member is reported whatever the property is called, because driving rows
 * is what currying on a runner is for.
 *
 * **What that still does not reach**, said rather than left to be found: a
 * table driving function that is not a runner member at all, and a runner
 * property that takes the callback directly instead of currying. Both are
 * misses, not refusals, and nothing here would say so.
 */
function tableGroupsIn(
  source: string,
  lang: "ts" | "tsx",
): {
  groups: Group[];
  unread: string[];
  nodes: { walked: number; serialised: number };
} {
  const root = parseAst(source, { lang }) as unknown as Node;
  const parents = parentsOf(root);
  const resolve = resolverOver(parents);
  const every = [...parents.keys()];

  const pins: HeldPin[] = [];
  for (const node of every) {
    if (node.type !== "CallExpression") continue;
    const matcher = node.callee;
    if (!isNode(matcher) || matcher.type !== "MemberExpression") continue;
    const held = propertyName(matcher);
    if (held === null || !WHOLE_VALUE_MATCHERS.has(held)) continue;
    const subject = matcher.object;
    if (!isNode(subject) || subject.type !== "CallExpression") continue;
    if (!isNode(subject.callee) || subject.callee.type !== "Identifier")
      continue;
    if (text(subject.callee.name) !== "expect") continue;
    const [written] = nodesIn(node.arguments);
    if (written === undefined || written.type !== "ArrayExpression") continue;
    const [value] = nodesIn(subject.arguments);
    if (value === undefined) continue;

    let name = value.type === "Identifier" ? value : null;
    let through = "the value itself";
    if (
      name === null &&
      value.type === "CallExpression" &&
      isNode(value.callee) &&
      value.callee.type === "Identifier" &&
      text(value.callee.name) === PIN_RENDERER
    ) {
      const wrapped = nodesIn(value.arguments);
      const [only] = wrapped;
      if (
        wrapped.length === 1 &&
        only !== undefined &&
        only.type === "Identifier"
      ) {
        name = only;
        through = PIN_RENDERER;
      }
    }
    if (name === null) continue;

    const to = resolve(name);
    const circular =
      to.declaration !== null &&
      namesAgain(written, to.declaration, resolve, parents, new Set());
    pins.push({
      through,
      live: runsAsWritten(node, parents, resolve),
      declaration: circular ? null : to.declaration,
    });
  }

  const unread = new Set(
    every.filter(
      (one) =>
        one.type === "MemberExpression" &&
        GENERATOR_PROPERTIES.has(propertyName(one) ?? ""),
    ),
  );
  const groups: Group[] = [];
  for (const node of every) {
    const applied =
      node.type === "CallExpression"
        ? node.callee
        : node.type === "TaggedTemplateExpression"
          ? node.tag
          : null;
    const chain = isNode(applied) ? chainOf(applied) : null;
    if (chain === null) {
      // **An applied member whose property cannot be read is recorded
      // here, not dropped.** `propertyName` answers null for a computed
      // key that is not a literal, and both this walk and the seeding
      // above read the property through it, so `it[k](table)` used to be
      // invisible to the rule, to the population arm and to this report at
      // once. Only an applied one is recorded: an ordinary subscript such
      // as `row[column]` is not a generator and would be noise.
      // **Keyed on the property being unreadable, not on the chain
      // failing.** `chainOf` also answers null where the base is not a
      // plain name, which every `expect(...).toEqual` is, so recording on
      // the chain turned every acceptance row red at once. Measured.
      if (
        isNode(applied) &&
        applied.type === "MemberExpression" &&
        propertyName(applied) === null
      )
        unread.add(applied);
      continue;
    }
    if (!chain.props.some((one) => GENERATOR_PROPERTIES.has(one))) {
      // **A curried call on a runner member drives rows, whatever the
      // property is called.** `GENERATOR_PROPERTIES` is two members and a
      // third would be a miss here where a fourth runner name is a loud
      // refusal, so the asymmetry is closed by reporting the shape rather
      // than by guessing the name. Currying is the shape: a runner member
      // called, and that call called again.
      const outer = parents.get(node) ?? null;
      if (
        RUNNER_NAMES.has(chain.base) &&
        node.type === "CallExpression" &&
        outer !== null &&
        outer.type === "CallExpression" &&
        outer.callee === node &&
        isNode(applied)
      )
        unread.add(applied);
      continue;
    }
    let spelled: unknown = applied;
    while (isNode(spelled) && spelled.type === "MemberExpression") {
      unread.delete(spelled);
      spelled = spelled.object;
    }

    const group: Group = {
      label: labelAround(node, parents),
      spelling: `${chain.base}.${chain.props.join(".")}`,
      table: "",
      pin: "",
      fault: "",
    };
    groups.push(group);

    if (chain.props.length !== 1) {
      group.fault = "is spelled with a modifier, so what it drives is not read";
      continue;
    }
    if (node.type !== "CallExpression") {
      group.fault = "is handed a template rather than a name";
      continue;
    }
    const handed = nodesIn(node.arguments);
    const [first] = handed;
    if (
      handed.length !== 1 ||
      first === undefined ||
      first.type !== "Identifier"
    ) {
      group.fault = "is handed an expression rather than a name";
      continue;
    }
    group.table = text(first.name) ?? "";
    const to = resolve(first);
    if (to.declaration === null) {
      group.fault = `names ${group.table}, which resolves to ${to.why}`;
      continue;
    }
    const theirs = pins.filter((one) => one.declaration === to.declaration);
    const living = theirs.filter((one) => one.live);
    if (living.length === 0) {
      group.fault =
        theirs.length > 0
          ? `names ${group.table}, whose only pin does not run as written`
          : `names ${group.table}, and no live pin holds that declaration`;
      continue;
    }
    group.pin = [...new Set(living.map((one) => one.through))]
      .sort()
      .join(", ");
  }

  return {
    groups,
    unread: [...unread].map((one) => labelAround(one, parents)),
    // **The walk's reach, against a second derivation of the same tree.**
    // The population arm reds on a truncation keyed where a group sits and
    // is blind to one keyed on a kind no group sits under: returning early
    // for a conditional statement hides thousands of nodes with every arm
    // green. A count taken off the serialised tree degrades differently
    // and cannot be forged from the source, because the serialiser escapes
    // a quote inside a string literal and this counts the unescaped form.
    nodes: {
      walked: every.length,
      serialised: JSON.stringify(root).split('"type":').length - 1,
    },
  };
}

/** Every group in `source` that nothing live holds, one line each. */
function groupsWithNoLivePin(
  source: string,
  lang: "ts" | "tsx" = "ts",
): string[] {
  const { groups, unread } = tableGroupsIn(source, lang);
  return [
    ...groups
      .filter((one) => one.fault !== "")
      .map((one) => `the group in "${one.label}" ${one.fault}`),
    ...unread.map(
      (label) =>
        `a generator named in "${label}" is applied where this rule cannot read what it drives`,
    ),
  ].sort();
}

/**
 * This file, as the shared corpus keys it.
 *
 * One spelling for two rules: the address rule below excludes itself with
 * it, and the rule here reads itself by it.
 */
const SELF = "./houseRules.test.ts";

/** This file's own text, taken from the shared corpus so a narrowing reds. */
function ownSource(): string {
  const mine = testEntries().find(([path]) => path === SELF);
  expect(
    mine,
    "this file is no longer in the shared test corpus, so the rule below would read nothing",
  ).toBeDefined();
  return mine?.[1] ?? "";
}

/**
 * The sources this rule must report, one row each.
 *
 * **Every row is a witness and none is discharged in prose.** The shadowing
 * rows are one per construct the grammar binds a name through, pattern
 * shapes and declaration kinds alike, because the argument that the regress
 * terminates is exactly that this list is the grammar's rather than a list
 * of containers somebody thought of, and an argument with a row nobody
 * drove is not an argument. One row holds the other half of that argument:
 * a declaration kind the reader does not know is reported rather than
 * walked past, so the list being short is a red line and not a miss.
 *
 * **A row here says a source is refused, not why**, and for the pattern
 * shapes those are two different things: deleting a branch of `boundBy`
 * makes the record refuse the same source, so the row stayed green while
 * the branch it is named for was gone. `is refused for an unreadable
 * binding shape on one row only` is what tells the two apart, and it is
 * what makes these rows witnesses rather than names.
 */
const REFUSED: [string, string][] = [
  [
    "a group with nothing pinning its table",
    `describe("g", () => { const T = [["a"]]; it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin marked skipped",
    `describe("g", () => { const T = [["a"]]; it.skip("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin marked todo",
    `describe("g", () => { const T = [["a"]]; it.todo("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin focused, which skips every arm beside it",
    `describe("g", () => { const T = [["a"]]; it.only("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin inside a skipped block",
    `describe("g", () => { const T = [["a"]]; describe.skip("inner", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin inside a helper the arm never calls",
    `describe("g", () => { const T = [["a"]]; const check = () => { expect(asRows(T)).toEqual([]); }; it("pin", check); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin inside a callback of its own",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { [1].forEach(() => { expect(asRows(T)).toEqual([]); }); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator handed a narrowed table",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T.filter(Boolean))("%s", () => {}); });`,
  ],
  [
    "a pin holding a narrowed table",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T.slice(1))).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin holding another table",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(U)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin holding a count rather than the rows",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toHaveLength(1); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin reading the table through anything but the renderer",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(labels(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin whose expected value is the table spread",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(T).toEqual([...T]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin whose expected value is rendered from the table",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([asRows(T)[0]]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator spelled with a skip in the chain",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.skip.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator spelled with a focus in the chain",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.only.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator reached under a computed name and narrowed",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it["each"](T.slice(0))("%s", () => {}); });`,
  ],
  [
    "a generator driven by a tagged template",
    `describe("g", () => { it.each\`ab\`("%s", () => {}); });`,
  ],
  [
    "a for named without being applied to anything",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); const g = it.for; g(T)("%s", () => {}); });`,
  ],
  [
    "an each named without being applied to anything",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); const g = it.each; g(T)("%s", () => {}); });`,
  ],
  [
    "a table this file declares nowhere",
    `describe("g", () => { it.each(T)("%s", () => {}); });`,
  ],
  [
    "a group outside every block",
    `const T = [["a"]]; it.each(T)("%s", () => {});`,
  ],
  [
    "a name shadowed by a block scoped const",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { const T = U; it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by a callback parameter",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); [U].forEach((T) => { it.each(T)("%s", () => {}); }); });`,
  ],
  [
    "a name shadowed by a function parameter",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); (function (T) { it.each(T)("%s", () => {}); })(U); });`,
  ],
  [
    "a name shadowed by a destructured parameter",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); (({ T }) => { it.each(T)("%s", () => {}); })({ T: U }); });`,
  ],
  [
    "a name shadowed by a rest parameter",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); ((...T) => { it.each(T)("%s", () => {}); })(); });`,
  ],
  [
    "a name shadowed by a parameter carrying a default",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); ((T = U) => { it.each(T)("%s", () => {}); })(); });`,
  ],
  [
    "a name shadowed by a for of binding",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); for (const T of [U]) { it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by a for in binding",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); for (const T in { a: 1 }) { it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by a catch parameter",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); try { x(); } catch (T) { it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by a function declaration",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { function T() {} it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by a class declaration",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { class T {} it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by a var hoisted out of a nested block",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); (() => { it.each(T)("%s", () => {}); if (x) { var T = U; } })(); });`,
  ],
  [
    "a name shadowed by a constructor parameter property",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); class C { constructor(private T: number) { it.each(T)("%s", () => {}); } } });`,
  ],
  [
    "a group outside the block whose pin shadows the import it names",
    `import { T } from "x"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); }); it.each(T)("%s", () => {});`,
  ],
  [
    "a name shadowed by an import equals declaration",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { import T = A.rows; it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by an ambient function declaration",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { declare function T(): void; it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by an enum declaration",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { enum T { A } it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed by a namespace declaration",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { namespace T { } it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a declaration kind the reader cannot read, in a scope the name reaches",
    `export as namespace W; const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator spelled for with nothing pinning its table",
    `describe("g", () => { const T = [["a"]]; it.for(T)("%s", () => {}); });`,
  ],
  [
    "a block generator spelled for with nothing pinning its table",
    `describe("g", () => { const T = [["a"]]; describe.for(T)("%s", () => {}); });`,
  ],
  [
    "a pin whose expected value is laundered through a name",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { const rendered = asRows(T); expect(asRows(T)).toEqual([...rendered]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin whose expected value is laundered through a call",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { const rendered = () => asRows(T); expect(asRows(T)).toEqual([...rendered()]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a name shadowed by a for statement binding",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); for (let T = U; false; ) { it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a name shadowed inside a namespace body",
    `const T = [["a"]]; const U = [["b"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); }); namespace N { const T = U; it.each(T)("%s", () => {}); }`,
  ],
  [
    "a name shadowed by a case clause binding",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); switch (x) { case 1: const T = U; it.each(T)("%s", () => {}); } });`,
  ],
  [
    "a pin under a runner reached through a local name",
    `describe("g", () => { const T = [["a"]]; const quietly = it.skip; quietly("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin handed to a helper that discards it",
    `describe("g", () => { const T = [["a"]]; const ignore = (fn) => {}; ignore(() => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin inside a callback on a plain name",
    `describe("g", () => { const T = [["a"]]; const run = (fn) => { fn(); }; it("pin", () => { run(() => { expect(asRows(T)).toEqual([]); }); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator under a computed key that is not a literal, table pinned",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); const k = "each"; it[k](T)("%s", () => {}); });`,
  ],
  [
    "a name shadowed by an array destructured parameter",
    `describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); (([T]) => { it.each(T)("%s", () => {}); })([U]); });`,
  ],
  [
    "a pin under a local bound to a runner's name",
    `describe("g", () => { const T = [["a"]]; const test = it.skip; test("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin under a local arrow carrying a runner's name",
    `describe("g", () => { const T = [["a"]]; const test = (n, fn) => {}; test("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin under a runner imported from somewhere other than the runner",
    `import { it } from "./not-the-runner"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator curried on a runner member that is no generator property",
    `describe("g", () => { const T = [["a"]]; it.over(T)("%s", () => {}); });`,
  ],
  [
    "a pin under a call this file declares nowhere and no runner names",
    `describe("g", () => { const T = [["a"]]; elsewhere("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin under a callee that carries no name to match",
    `describe("g", () => { const T = [["a"]]; (it as any)("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin under a namespace import of the runner's module",
    `import * as it from "vitest"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin under a default import from the runner's module",
    `import it from "vitest"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin under another export of the runner's module renamed to a runner",
    `import { describe as it } from "vitest"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
];

/**
 * The sources this rule must not report.
 *
 * **Two of these are paired with a refusal above, and the derivation is
 * named rather than implied**, so that neither row of a pair reads as
 * decoration. The callback of another name is `a name shadowed by a
 * callback parameter` with the parameter renamed. The generator spelled
 * `for` over a pinned table is `a generator spelled for with nothing
 * pinning its table` with the pin put back. The two sibling blocks are what
 * a rule keyed on the name rather than on the declaration would refuse, and
 * every shadowing row above is what such a rule would let through.
 *
 * The nested group is **not** the block scoped const refusal with the
 * binding removed, which yields a bare block rather than a block the runner
 * names; it is the shape the round before this one refused outright, kept
 * because that refusal was wrong.
 *
 * The rest carry their own reason rather than a pair: the rows beside a
 * table reached through the module body hold the exemptions the binding
 * reader needs, one per kind, and each reds when its own exemption is
 * taken away. The count is deliberately not written: it went stale in the
 * round that added two of them.
 */
const ACCEPTED: [string, string][] = [
  [
    "a pin written above the generator it holds",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin written below the generator it holds",
    `describe("g", () => { const T = [["a"]]; it.each(T)("%s", () => {}); it("pin", () => { expect(asRows(T)).toEqual([]); }); });`,
  ],
  [
    "a pin written in the block body rather than in an arm",
    `describe("g", () => { const T = [["a"]]; expect(asRows(T)).toEqual([]); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin written in a function expression arm",
    `describe("g", () => { const T = [["a"]]; it("pin", function () { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a nested group driving the table its parent pins",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); describe("inner", () => { it.each(T)("%s", () => {}); }); });`,
  ],
  [
    "a callback parameter of another name between the binding and the group",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); [1].forEach((row) => { it.each(T)("%s", () => {}); }); });`,
  ],
  [
    "a population pinned as itself rather than through the renderer",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(T).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator spelled as a block",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); describe.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator reached under a computed name",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it["each"](T)("%s", () => {}); });`,
  ],
  [
    "an arm holding a name of its own that no generator drives",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it("other", () => { const U = [1]; expect(U).toEqual([1]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a table declared outside the block that drives and pins it",
    `const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "two sibling blocks whose tables carry one name",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); }); describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a generator spelled for over a pinned table",
    `describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.for(T)("%s", () => {}); });`,
  ],
  [
    "a type alias beside a table the group reaches through the module body",
    `type Rows = string; const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "an interface beside a table the group reaches through the module body",
    `interface Rows { a: number } const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "an enum beside a table the group reaches through the module body",
    `enum Rows { T } const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "an import equals beside a table the group reaches through the module body",
    `import Rows = A.b; const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a namespace beside a table the group reaches through the module body",
    `namespace Rows { } const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
  [
    "a pin under the runner this file imports",
    `import { describe, expect, it } from "vitest"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
  ],
];

/**
 * **What this refuses that is legitimate, because a sweep only ever plants
 * defects and will never tell you.** Every one of these is loud, at the
 * line somebody is writing, which is the direction to be wrong in: a
 * generator handed a table written inline rather than declared, or handed
 * any expression at all; a table driven from a tagged template, which has
 * no name to resolve; a pin written with any matcher but an exact equality,
 * or reading the table through any call but the renderer, or lifted into a
 * helper two arms share; a pin reached through any property taken off the
 * runner, `concurrent` and `skipIf` with `skip` and `only`; **a pin
 * reached through any call that does not name one of the three runners**,
 * which takes in a helper that runs it at once, a wrapper that defers it,
 * an immediately invoked function, and a runner spelled `suite`; a pin
 * written inside the body of a block generator, which is the shape the
 * acceptances below invite by taking such a generator and is refused all
 * the same, because that body is handed to a call whose own callee is a
 * call, `describe.each(table)`, rather than a name at all; and a
 * generator called on anything whose receiver is not a plain name. None
 * of those is live in this file, derived rather than read, so the rule
 * refuses nothing as it stands and reds at the first one, which is where
 * somebody decides.
 *
 * **The pin inside a block generator's body is the one worth arguing
 * about**, and it stays refused: accepting it means accepting a pin under
 * every call made on a property, which is where a disarmed pin hides, and
 * nothing has measured what that would let through. Write the pin beside
 * the generator rather than inside it.
 *
 * **And one refusal reaches further than the group it names**: moving a
 * group into a nested block changes its row in the population arm below,
 * because that row carries the block it sits in. That is the membership
 * contract this file already keeps, not an extra rule.
 *
 * **What the argument rests on, said rather than assumed, so that the next
 * round attacks the right two things.** The node walk reaches every node,
 * and the lists it reads the grammar off are complete: the scopes a name
 * can be bound in, the shapes a binding position can hold, and the kinds
 * that declare a name.
 *
 * **The walk takes two arms, because one of them cannot see half the
 * narrowings.** The population arm reds on a truncation keyed where a
 * live group sits and is green on one keyed on a kind no group sits
 * under, measured. `reaches every node of its own source` holds the walk
 * against a count taken off the serialised tree, which degrades
 * differently, and reds on both.
 *
 * **How each of the three lists fails is different, and `SCOPES` is the
 * one to read for its own.** A pattern shape outside `boundBy` and a
 * declaration kind outside the reader in `scopeBindings` are each
 * recorded, so those two lists are backed by a refusal rather than by
 * being right. What a dropped `SCOPES` member costs is not one answer:
 * its own docstring measures it member by member, and the three it holds
 * that declare a name are backed by that same record while most of the
 * rest are not.
 *
 * **What the declaration record cannot see is a kind binding a name
 * through neither a pattern nor an identifier `id`**, and the live
 * grammar has several: the three import specifiers bind through `local`,
 * a type parameter through `name`, and a labeled statement through
 * `label`. The specifiers are read by name in the reader rather than
 * reached by the record; a type parameter binds in the type space and a
 * label in its own, where no table lives. So the record's key is an
 * identifier `id` and the sentence stops there. **No census settles
 * this**: a count says what a tree holds, never what the grammar permits.
 */
describe("a table driven rule group is held by a pin on one declaration", () => {
  it("holds every group this file drives", () => {
    expect(groupsWithNoLivePin(ownSource(), langOf(SELF))).toEqual([]);
  });

  /**
   * The groups this file drives, rendered.
   *
   * **The anti vacuity arm, and the one that refuses a narrowing.** A walk
   * that finds nothing reports nothing, so the arm above is green on a rule
   * that has stopped reading anything at all. This one holds the population
   * itself, so a filter written anywhere in the walk, by block, by runner
   * name or by position, moves a cell or loses a row.
   */
  it("holds exactly the groups this file drives, cell by cell", () => {
    const { groups, unread } = tableGroupsIn(ownSource(), langOf(SELF));
    expect(unread).toEqual([]);
    const rows = groups
      .map((one): Cell[] => [one.label, one.spelling, one.table, one.pin])
      .sort((first, second) => asRow(first).localeCompare(asRow(second)));
    expect(asRows(rows)).toEqual([
      `a decoder a runtime may not carry is never built at module scope | it.each | SHAPES | asRows`,
      `a directory reproducing the tree is read as a copy of it | it.each | SHAPES | asRows`,
      `a directory reproducing the tree is read as a copy of it | it.each | UNVERSIONED_AT_THE_ROOT | the value itself`,
      `a member's book file cannot leave the browser | it.each | SHAPES | asRows`,
      `a table driven rule group is held by a pin on one declaration | it.each | ACCEPTED | asRows`,
      `a table driven rule group is held by a pin on one declaration | it.each | REFUSED | asRows`,
    ]);
  });

  /**
   * The walk's reach, held against a second reading of the same tree.
   *
   * **The population arm cannot see every narrowing, which is why this
   * exists.** It reds on a truncation keyed where a live group sits and
   * stays green on one keyed on a kind no group sits under: returning
   * early for a conditional statement hides thousands of nodes with every
   * other arm green. The second reading counts the serialised tree, which
   * degrades differently and which the source cannot forge, because a
   * quote inside a string literal is escaped and this counts the
   * unescaped spelling.
   */
  it("reaches every node of its own source", () => {
    const { nodes } = tableGroupsIn(ownSource(), langOf(SELF));
    expect(nodes.walked).toBe(nodes.serialised);
    // Not a floor: the population arm below cannot hold six rows out of a
    // tree of nothing, so this says only that the two readings agree about
    // something rather than about an empty pair.
    expect(nodes.serialised).not.toBe(0);
  });

  /**
   * Which refusals are refused for a binding shape the reader cannot read.
   *
   * **Five pattern rows were passing for a reason other than the one they
   * name.** Deleting a branch of `boundBy` makes the record fire instead,
   * which still refuses, and a row asserting a non empty result cannot
   * tell a shadow found from a shape refused. Naming the rows that are
   * refused that way moves a name into this list when a branch goes, where
   * nothing moved before.
   */
  it("is refused for an unreadable binding shape on one row only", () => {
    const unreadable = REFUSED.filter(([, source]) =>
      groupsWithNoLivePin(source).some((one) =>
        one.includes("a binding shape this rule cannot read"),
      ),
    ).map(([name]) => name);
    expect(unreadable).toEqual([
      "a declaration kind the reader cannot read, in a scope the name reaches",
    ]);
  });

  /**
   * Why a runner name nothing declares is read as the runner.
   *
   * **The reason is the config, not the fixtures.** This file imports four
   * names and `test` is not among them, so an arm written with `test`
   * takes that branch here and not only in a fixture. What makes the
   * branch right is that the suite runs with globals on, so an undeclared
   * runner name is the runner at run time. With globals off it throws
   * rather than passing quietly, so the failure direction is loud either
   * way; this pins the setting so the dependency reds instead of being
   * stated, which is what the round before this one got wrong.
   */
  it("runs a pin under a runner that is global when nothing declares it", () => {
    expect(viteConfig).toMatch(/^\s*globals: true,$/m);
  });

  it.each(REFUSED)("refuses %s", (_name, source) => {
    expect(groupsWithNoLivePin(source)).not.toEqual([]);
  });

  /**
   * The rows above, rendered. `asRow` holds why they are written out, and
   * `asRows` refuses a column this rendering cannot tell apart.
   */
  it("holds exactly the refusals listed here, cell by cell", () => {
    expect(asRows(REFUSED)).toEqual([
      `a group with nothing pinning its table | describe("g", () => { const T = [["a"]]; it.each(T)("%s", () => {}); });`,
      `a pin marked skipped | describe("g", () => { const T = [["a"]]; it.skip("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin marked todo | describe("g", () => { const T = [["a"]]; it.todo("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin focused, which skips every arm beside it | describe("g", () => { const T = [["a"]]; it.only("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin inside a skipped block | describe("g", () => { const T = [["a"]]; describe.skip("inner", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); }); it.each(T)("%s", () => {}); });`,
      `a pin inside a helper the arm never calls | describe("g", () => { const T = [["a"]]; const check = () => { expect(asRows(T)).toEqual([]); }; it("pin", check); it.each(T)("%s", () => {}); });`,
      `a pin inside a callback of its own | describe("g", () => { const T = [["a"]]; it("pin", () => { [1].forEach(() => { expect(asRows(T)).toEqual([]); }); }); it.each(T)("%s", () => {}); });`,
      `a generator handed a narrowed table | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T.filter(Boolean))("%s", () => {}); });`,
      `a pin holding a narrowed table | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T.slice(1))).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin holding another table | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(U)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin holding a count rather than the rows | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toHaveLength(1); }); it.each(T)("%s", () => {}); });`,
      `a pin reading the table through anything but the renderer | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(labels(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin whose expected value is the table spread | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(T).toEqual([...T]); }); it.each(T)("%s", () => {}); });`,
      `a pin whose expected value is rendered from the table | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([asRows(T)[0]]); }); it.each(T)("%s", () => {}); });`,
      `a generator spelled with a skip in the chain | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.skip.each(T)("%s", () => {}); });`,
      `a generator spelled with a focus in the chain | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.only.each(T)("%s", () => {}); });`,
      `a generator reached under a computed name and narrowed | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it["each"](T.slice(0))("%s", () => {}); });`,
      `a generator driven by a tagged template | describe("g", () => { it.each\`ab\`("%s", () => {}); });`,
      `a for named without being applied to anything | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); const g = it.for; g(T)("%s", () => {}); });`,
      `an each named without being applied to anything | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); const g = it.each; g(T)("%s", () => {}); });`,
      `a table this file declares nowhere | describe("g", () => { it.each(T)("%s", () => {}); });`,
      `a group outside every block | const T = [["a"]]; it.each(T)("%s", () => {});`,
      `a name shadowed by a block scoped const | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { const T = U; it.each(T)("%s", () => {}); } });`,
      `a name shadowed by a callback parameter | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); [U].forEach((T) => { it.each(T)("%s", () => {}); }); });`,
      `a name shadowed by a function parameter | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); (function (T) { it.each(T)("%s", () => {}); })(U); });`,
      `a name shadowed by a destructured parameter | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); (({ T }) => { it.each(T)("%s", () => {}); })({ T: U }); });`,
      `a name shadowed by a rest parameter | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); ((...T) => { it.each(T)("%s", () => {}); })(); });`,
      `a name shadowed by a parameter carrying a default | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); ((T = U) => { it.each(T)("%s", () => {}); })(); });`,
      `a name shadowed by a for of binding | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); for (const T of [U]) { it.each(T)("%s", () => {}); } });`,
      `a name shadowed by a for in binding | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); for (const T in { a: 1 }) { it.each(T)("%s", () => {}); } });`,
      `a name shadowed by a catch parameter | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); try { x(); } catch (T) { it.each(T)("%s", () => {}); } });`,
      `a name shadowed by a function declaration | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { function T() {} it.each(T)("%s", () => {}); } });`,
      `a name shadowed by a class declaration | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { class T {} it.each(T)("%s", () => {}); } });`,
      `a name shadowed by a var hoisted out of a nested block | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); (() => { it.each(T)("%s", () => {}); if (x) { var T = U; } })(); });`,
      `a name shadowed by a constructor parameter property | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); class C { constructor(private T: number) { it.each(T)("%s", () => {}); } } });`,
      `a group outside the block whose pin shadows the import it names | import { T } from "x"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); }); it.each(T)("%s", () => {});`,
      `a name shadowed by an import equals declaration | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { import T = A.rows; it.each(T)("%s", () => {}); } });`,
      `a name shadowed by an ambient function declaration | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { declare function T(): void; it.each(T)("%s", () => {}); } });`,
      `a name shadowed by an enum declaration | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { enum T { A } it.each(T)("%s", () => {}); } });`,
      `a name shadowed by a namespace declaration | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); { namespace T { } it.each(T)("%s", () => {}); } });`,
      `a declaration kind the reader cannot read, in a scope the name reaches | export as namespace W; const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a generator spelled for with nothing pinning its table | describe("g", () => { const T = [["a"]]; it.for(T)("%s", () => {}); });`,
      `a block generator spelled for with nothing pinning its table | describe("g", () => { const T = [["a"]]; describe.for(T)("%s", () => {}); });`,
      `a pin whose expected value is laundered through a name | describe("g", () => { const T = [["a"]]; it("pin", () => { const rendered = asRows(T); expect(asRows(T)).toEqual([...rendered]); }); it.each(T)("%s", () => {}); });`,
      `a pin whose expected value is laundered through a call | describe("g", () => { const T = [["a"]]; it("pin", () => { const rendered = () => asRows(T); expect(asRows(T)).toEqual([...rendered()]); }); it.each(T)("%s", () => {}); });`,
      `a name shadowed by a for statement binding | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); for (let T = U; false; ) { it.each(T)("%s", () => {}); } });`,
      `a name shadowed inside a namespace body | const T = [["a"]]; const U = [["b"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); }); namespace N { const T = U; it.each(T)("%s", () => {}); }`,
      `a name shadowed by a case clause binding | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); switch (x) { case 1: const T = U; it.each(T)("%s", () => {}); } });`,
      `a pin under a runner reached through a local name | describe("g", () => { const T = [["a"]]; const quietly = it.skip; quietly("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin handed to a helper that discards it | describe("g", () => { const T = [["a"]]; const ignore = (fn) => {}; ignore(() => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin inside a callback on a plain name | describe("g", () => { const T = [["a"]]; const run = (fn) => { fn(); }; it("pin", () => { run(() => { expect(asRows(T)).toEqual([]); }); }); it.each(T)("%s", () => {}); });`,
      `a generator under a computed key that is not a literal, table pinned | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); const k = "each"; it[k](T)("%s", () => {}); });`,
      `a name shadowed by an array destructured parameter | describe("g", () => { const T = [["a"]]; const U = [["b"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); (([T]) => { it.each(T)("%s", () => {}); })([U]); });`,
      `a pin under a local bound to a runner's name | describe("g", () => { const T = [["a"]]; const test = it.skip; test("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin under a local arrow carrying a runner's name | describe("g", () => { const T = [["a"]]; const test = (n, fn) => {}; test("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin under a runner imported from somewhere other than the runner | import { it } from "./not-the-runner"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a generator curried on a runner member that is no generator property | describe("g", () => { const T = [["a"]]; it.over(T)("%s", () => {}); });`,
      `a pin under a call this file declares nowhere and no runner names | describe("g", () => { const T = [["a"]]; elsewhere("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin under a callee that carries no name to match | describe("g", () => { const T = [["a"]]; (it as any)("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin under a namespace import of the runner's module | import * as it from "vitest"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin under a default import from the runner's module | import it from "vitest"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin under another export of the runner's module renamed to a runner | import { describe as it } from "vitest"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
    ]);
  });

  it.each(ACCEPTED)("accepts %s", (_name, source) => {
    expect(groupsWithNoLivePin(source)).toEqual([]);
  });

  /**
   * The rows above, rendered. `asRow` holds why they are written out, and
   * `asRows` refuses a column this rendering cannot tell apart.
   */
  it("holds exactly the acceptances listed here, cell by cell", () => {
    expect(asRows(ACCEPTED)).toEqual([
      `a pin written above the generator it holds | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin written below the generator it holds | describe("g", () => { const T = [["a"]]; it.each(T)("%s", () => {}); it("pin", () => { expect(asRows(T)).toEqual([]); }); });`,
      `a pin written in the block body rather than in an arm | describe("g", () => { const T = [["a"]]; expect(asRows(T)).toEqual([]); it.each(T)("%s", () => {}); });`,
      `a pin written in a function expression arm | describe("g", () => { const T = [["a"]]; it("pin", function () { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a nested group driving the table its parent pins | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); describe("inner", () => { it.each(T)("%s", () => {}); }); });`,
      `a callback parameter of another name between the binding and the group | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); [1].forEach((row) => { it.each(T)("%s", () => {}); }); });`,
      `a population pinned as itself rather than through the renderer | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(T).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a generator spelled as a block | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); describe.each(T)("%s", () => {}); });`,
      `a generator reached under a computed name | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it["each"](T)("%s", () => {}); });`,
      `an arm holding a name of its own that no generator drives | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it("other", () => { const U = [1]; expect(U).toEqual([1]); }); it.each(T)("%s", () => {}); });`,
      `a table declared outside the block that drives and pins it | const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `two sibling blocks whose tables carry one name | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); }); describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a generator spelled for over a pinned table | describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.for(T)("%s", () => {}); });`,
      `a type alias beside a table the group reaches through the module body | type Rows = string; const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `an interface beside a table the group reaches through the module body | interface Rows { a: number } const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `an enum beside a table the group reaches through the module body | enum Rows { T } const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `an import equals beside a table the group reaches through the module body | import Rows = A.b; const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a namespace beside a table the group reaches through the module body | namespace Rows { } const T = [["a"]]; describe("g", () => { it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
      `a pin under the runner this file imports | import { describe, expect, it } from "vitest"; describe("g", () => { const T = [["a"]]; it("pin", () => { expect(asRows(T)).toEqual([]); }); it.each(T)("%s", () => {}); });`,
    ]);
  });

  it("is blind to a pin an arm holds but never reaches", () => {
    // **The residue with a witness, because a blind spot stated in prose is
    // the row nobody rechecks.** This asks where a pin is written, not
    // whether the statement runs, so a pin behind a condition that is never
    // true reads as live. Closing it is reachability over a body, which is
    // the silent kind of wrong this rule is built to avoid: it would answer
    // "unreachable" by failing to see a path, and failing to see something
    // is what finding nothing looks like.
    const table = `const T = [["a"]];`;
    const generator = `it.each(T)("%s", () => {});`;
    const behind = `it("pin", () => { if (never) { expect(asRows(T)).toEqual([]); } });`;
    expect(
      groupsWithNoLivePin(
        `describe("g", () => { ${table} ${behind} ${generator} });`,
      ),
    ).toEqual([]);

    // It reds the moment the pin is written where the arm cannot reach it at
    // all, which is what makes this a witness rather than a restatement.
    const lifted = `const check = () => { expect(asRows(T)).toEqual([]); }; it("pin", check);`;
    expect(
      groupsWithNoLivePin(
        `describe("g", () => { ${table} ${lifted} ${generator} });`,
      ),
    ).not.toEqual([]);
  });

  it("is blind to a rendering reaching the expected value by any other route", () => {
    // **The second blind spot, with its five witnesses**, because the walk
    // into an initialiser is narrower than it reads: it follows a name only
    // where the identifier is a declarator's own `id` and only into that
    // declarator's initialiser. Each of these is the refused row one token
    // out, and each is accepted. Closing any of them reds here, which is
    // what stops the paragraph at `namesAgain` going stale against the code.
    const table = `const T = [["a"]];`;
    const generator = `it.each(T)("%s", () => {});`;
    const past = [
      `function rendered() { return asRows(T); } expect(asRows(T)).toEqual([...rendered()]);`,
      `class C { static rows = asRows(T); } expect(asRows(T)).toEqual([...C.rows]);`,
      `const [rendered] = [asRows(T)]; expect(asRows(T)).toEqual([...rendered]);`,
      `const { rendered } = { rendered: asRows(T) }; expect(asRows(T)).toEqual([...rendered]);`,
      `let rendered; rendered = asRows(T); expect(asRows(T)).toEqual([...rendered]);`,
    ];
    for (const body of past)
      expect(
        groupsWithNoLivePin(
          `describe("g", () => { ${table} it("pin", () => { ${body} }); ${generator} });`,
        ),
      ).toEqual([]);

    // The one route it does follow, so this reads as a boundary rather than
    // as the walk doing nothing.
    const caught = `const rendered = asRows(T); expect(asRows(T)).toEqual([...rendered]);`;
    expect(
      groupsWithNoLivePin(
        `describe("g", () => { ${table} it("pin", () => { ${caught} }); ${generator} });`,
      ),
    ).not.toEqual([]);
  });
});

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
   * The rows above, rendered. `asRow` holds why they are written out, and
   * `asRows` refuses a column this rendering cannot tell apart.
   */
  it("holds exactly the shapes listed here, cell by cell", () => {
    expect(asRows(SHAPES)).toEqual([
      "a declaration taking a File is refused | export function draftFromX(file: File): BookDraft {} | true",
      "an arrow assigned to a const is refused | export const draftFromX = (file: File): BookDraft => 0; | true",
      "an overload is refused for what it declares, not what it implements | export function draftFromX(file: File): BookDraft;\nexport function draftFromX(input: unknown): BookDraft {} | true",
      "an anonymous default export is refused | export default function (file: File): BookDraft {} | true",
      "a callable held as an object property is refused | export const built = { draftFromX: (file: File) => 0 }; | true",
      "a File behind two other parameters is refused | export function draftFromX(c: NameClues, done: () => void, f: File) {} | true",
      "a builder renamed out of the family is refused for its return | function make(cover: File): BookDraft {} | true",
      "an array view is refused, and not only a File | export function draftFromX(bytes: Uint8Array): BookDraft {} | true",
      "a buffer view sharing no name with an array is refused | export function draftFromX(bytes: DataView): BookDraft {} | true",
      "a Blob is refused, which is the pair this rule was written for | export function draftFromX(bytes: Blob): BookDraft {} | true",
      "so is what a Blob is built out of, which a bare name admitted | export function draftFromX(bytes: BlobPart): BookDraft {} | true",
      "a buffer named without the word array is refused | export function draftFromX(bytes: BufferSource): BookDraft {} | true",
      "bytes that arrive a chunk at a time are refused | export function draftFromX(bytes: ReadableStream): BookDraft {} | true",
      "a handle onto a file the member picked is refused | export function draftFromX(picked: FileList): BookDraft {} | true",
      "a builder taking the parsed record is admitted | export function draftFromX(record: FileMetadata): BookDraft {} | false",
      "a parameter merely named for an array is admitted: a name is not a type | export function draftFromX(bookArray: NameClues): BookDraft {} | false",
      "a function that builds no draft is admitted | export function elsewhere(file: File): Request {} | false",
    ]);
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

  // This file writes the shapes down in order to forbid them, so it is left
  // out. **It used to remove nothing**, because a module is excluded from its
  // own `import.meta.glob` and the pattern was written here: a probe run from
  // a sibling file saw `./houseRules.test.ts` among the keys and run from here
  // it was absent. The corpus comes from `tests/testModules.ts` now, which
  // holds this file, so the exclusion is live and `testEntriesBesides` reds if
  // it ever names a file the tree does not hold. **The key itself is
  // `SELF`, written once at module scope**, because the group rule above
  // reads this file by the same key and two spellings of one path are two
  // chances to drift.

  function everything(): [string, string][] {
    return [
      ...entries(),
      ...testEntriesBesides(SELF).map(([path, source]): [string, string] => [
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

  it("is not scanning itself, and the exclusion above is what stops it", () => {
    // **The inverse of what stood here.** While the pattern was written in
    // this file the bundler kept it out and the filter was decoration; this
    // arm pinned the absence so that nobody read the filter as evidence. The
    // shared corpus holds every test module, so the file is in the set and
    // the line above is the only thing keeping it out of this rule, which it
    // has to be: the fixture below carries a deliberately unreserved address.
    expect(testEntries().map(([path]) => path)).toContain(SELF);
    expect(everything().map(([path]) => path)).not.toContain(
      "tests/houseRules.test.ts",
    );
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
    const offenders = testEntries()
      .filter(([path, source]) => replacesAModule(source, langOf(path)))
      .map(([path]) => path.replace("./", "tests/"));

    expect(offenders).toEqual([]);
  });

  it("reads the test tree at all", () => {
    // **A floor of a hundred used to stand here, then the directories.** The
    // floor was over 219 keys of which `tests/pages/` is 118, so excluding
    // that one directory cleared it with every page test unread. The
    // directory equality that replaced it was right and it was written here,
    // beside one of the three rules it armed, which is the arrangement the
    // source side had already stopped using. `tests/testModules.ts` refuses a
    // corpus that is not the tree and throws rather than handing back a short
    // one, so what is left to say here is that the refusal is reached.
    expect(() => testEntries()).not.toThrow();
  });

  it("parses every file it reads", () => {
    // **The one failure mode the parser has and the line filter did not.** A
    // file it throws on takes the rule above down with it, which is loud, and
    // this is where that arrives naming the file rather than as a stack in the
    // middle of a rule about mocks. Measured across the whole suite tree when
    // the swap landed: nothing here fails to parse.
    const refused = testEntries()
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

  /**
   * The rows above, rendered. `asRow` holds why they are written out, and
   * `asRows` refuses a column this rendering cannot tell apart.
   */
  it("holds exactly the constructions listed here, cell by cell", () => {
    expect(asRows(SHAPES)).toEqual([
      `const d = new TextDecoder("utf-16be"); | ts | true`,
      `export const d = new TextDecoder("utf-16be"); | ts | true`,
      `let d: TextDecoder = new TextDecoder("utf-16be"); | ts | true`,
      `const all = { be: new TextDecoder("utf-16be") }; | ts | true`,
      `const d = new globalThis.TextDecoder("utf-16be"); | ts | true`,
      `const d = (() => new TextDecoder("utf-16be"))(); | ts | true`,
      `const d = (function () { return new TextDecoder("x"); })(); | ts | true`,
      `const d = (() => new TextDecoder("utf-16be")).call(null); | ts | true`,
      `const ds = ["utf-16be"].map((l) => new TextDecoder(l)); | ts | true`,
      `Array.from([1], () => new TextDecoder("utf-16be")); | ts | true`,
      `const d = new TextDecoder(LABEL); | ts | true`,
      `class C { d = new TextDecoder("utf-16be"); } | ts | true`,
      `const view = <p x={new TextDecoder("utf-16be")} />; | tsx | true`,
      `function f() { return new TextDecoder("utf-16be"); } | ts | false`,
      `const f = () => new TextDecoder("utf-16be"); | ts | false`,
      `const o = { f() { return new TextDecoder("utf-16be"); } }; | ts | false`,
      `const o = { get f() { return new TextDecoder("utf-16be"); } }; | ts | false`,
      `class C { f() { return new TextDecoder("utf-16be"); } } | ts | false`,
      `function f() { return [1].map(() => new TextDecoder("x")); } | ts | false`,
      `const d = new TextDecoder("utf-8"); | ts | false`,
      `const d = new TextDecoder("UTF-8"); | ts | false`,
      `const d = new TextDecoder(); | ts | false`,
    ]);
  });
});

/**
 * `.` and `..` resolved, against a base given as segments.
 *
 * **One home, because a document's key and a citation's target have to land in
 * the same space.** They did not. The document half of `citingFiles` keyed by
 * string replacement and `normalised` resolved, so the two documents the glob
 * below reaches from its own directory were keyed against the repository root
 * and a relative citation written in either resolved from there.
 */
function resolveSegments(base: readonly string[], path: string): string[] {
  const parts = [...base];
  for (const part of path.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") parts.pop();
    else parts.push(part);
  }
  return parts;
}

/**
 * Where every glob in this file is written from, which is where this file sits.
 *
 * A move reds `reads every published document the glob hands over`: the
 * directory set it asserts loses the test tree by name.
 */
const GLOBBED_FROM = ["frontend", "tests"];

/** A glob key as a path from the repository root. */
function repositoryPath(key: string): string {
  return resolveSegments(GLOBBED_FROM, key).join("/");
}

/**
 * Every document sitting under a directory that reproduces part of the tree.
 *
 * **The materialised publish tree, read off what it is rather than off what it
 * is called.** The publish script takes its output directory as an argument
 * and only falls back to a default, so a filter naming that default is blind
 * to every other run. Measured by running the script for real at three
 * directories, the default, another name at the root and one nested: each
 * landed a copy of every published document in the corpus, and this returned
 * exactly the copies at each.
 *
 * **Two conditions, and each has a shape that reds on its own** in `a
 * directory reproducing the tree is read as a copy of it`. A directory counts
 * as a copy when **every** document under it shadows a document outside it,
 * and when **at least one** of those shadowed documents is itself inside a
 * directory.
 *
 * **Both conditions pay for themselves on the live tree.** Without the first,
 * a directory holding its own documents and one shadow is read as a copy.
 * Without the second, so is every directory whose only document is a
 * `README.md`, because the repository root holds one of those too, and the
 * live tree reports under that mutation rather than staying clean.
 *
 * ## What this cannot see, and why it is not alone
 *
 * **The first condition is all or nothing over one directory**, because only
 * the directory at depth one can ever satisfy it: the nested ones inside a
 * copy shadow a handful of the documents under them and never all. So the
 * whole verdict rests on one predicate over the whole copy, and **one
 * document renamed or deleted in the working tree since the run takes it from
 * every copy to none.** Driven against a real run of the script:
 *
 * | the tree after the run | copies this returns |
 * |---|---|
 * | unchanged | all of them |
 * | a document added | all of them |
 * | **a published document renamed** | **none** |
 * | **a root document renamed** | **none** |
 * | **a published document deleted** | **none** |
 *
 * A stale copy is exactly the case most likely to carry a path that has since
 * gone, so this is blind in the state it exists for. That is why
 * `thePublishTreeIn` does not use it alone.
 *
 * **What it refuses that is not a copy is silent, not loud.** A directory
 * wrongly read as a copy drops out of the corpus and **no arm reds**, because
 * the published set is derived from the same corpus, so both sides of the
 * count equality shrink together. Three planted non copies went unjudged in
 * silence.
 *
 * **So the residual is accepted on how narrow the shape is, and the margin is
 * one document.** Three directories on a clean checkout already satisfy the
 * first condition, each holding a single document that shadows the one at the
 * repository root. **One document added under any of them is enough**: it
 * supplies the nested tail the second condition wants, and because it is
 * itself a copy of something the corpus holds it keeps the first condition
 * intact, so the directory and the live document beside it both leave the
 * corpus. Driven end to end over such an addition: nothing reds and a
 * published document goes unjudged.
 *
 * **Re-derive the margin as that count of directories**, not as a count of
 * nested tails. Group the corpus by every directory prefix and count the
 * prefixes where **every** document held shadows one outside; a sentence
 * counting the nested tails instead reports zero and reads as safety, which
 * is the reading this paragraph replaced.
 *
 * **It is scoped to the corpus a run reads, which is not this filesystem.**
 * The archive that ships the tree drops the agent working directories, each a
 * whole checkout and so a wholesale shadow. **And it is deliberately not an
 * arm**: an arm whose verdict depends on which filesystem it is read from is
 * one whoever hits it deletes, and what it would guard is the justification
 * for an accepted residual rather than a property of the thing judged.
 *
 * ## What was declined
 *
 * **Keying the corpus on what the repository versions** is the closure the
 * rules below name, since an untracked document reaches no mirror. The suite
 * runs in a container holding the working tree with the repository's own
 * metadata directory excluded from the archive that ships it, so **no test
 * there can query the repository.** A committed manifest of versioned paths
 * would put the answer back within reach; it is not written because a
 * manifest is a copy of a derived fact, which is the thing this repository
 * keeps paying for, and because `UNVERSIONED_AT_THE_ROOT` gets the one
 * directory that matters out of a statement the repository already maintains.
 *
 * **And refusing a corpus that holds two documents with the same path tail was
 * measured and does not work.** Read as a basename, and read as a segment
 * suffix, the live tree is already full of legitimate pairs: every directory
 * holding a `README.md` shadows the one at the repository root. The two
 * conditions above are what a bare tail test is short of.
 */
function materialisedCopies(paths: readonly string[]): string[] {
  const corpus = new Set(paths);
  const under = new Map<string, { held: number; shadowed: string[] }>();

  for (const path of paths) {
    const segments = path.split("/");
    for (let depth = 1; depth < segments.length; depth += 1) {
      const directory = segments.slice(0, depth).join("/");
      const tail = segments.slice(depth).join("/");
      const seen = under.get(directory) ?? { held: 0, shadowed: [] };
      seen.held += 1;
      if (corpus.has(tail)) seen.shadowed.push(tail);
      under.set(directory, seen);
    }
  }

  const copies = [...under]
    .filter(
      ([, seen]) =>
        seen.shadowed.length === seen.held &&
        seen.shadowed.some((tail) => tail.includes("/")),
    )
    .map(([directory]) => directory);

  return [...paths]
    .filter((path) => copies.some((copy) => path.startsWith(`${copy}/`)))
    .sort();
}

/**
 * The directories this repository refuses to version at its own root.
 *
 * **Derived from the ignore file rather than named here, and that is what
 * makes it a pin rather than the literal it replaced.** The reason it is safe
 * to drop everything under one of these is that nothing legitimate can live
 * there, and that is a statement the repository already maintains, in the one
 * place that is checked whenever somebody commits. A name written here would
 * be a guess about where the publish script gets pointed; this is a fact
 * about where its output cannot be kept.
 *
 * **A leading separator anchors an ignore entry to the repository root and a
 * trailing one makes it a directory**, so this is the exact class a publish
 * output tree falls into, and it is one member today. `pins the directory the
 * repository refuses to version at its own root` is the arm, and it holds
 * both directions: the pin's subject is a directory absent on every tree a
 * run sees, so nothing in a corpus can witness it and the ignore file saying
 * so is the whole of the evidence.
 *
 * **The file this reads is available wherever this is read**, which a
 * derivation over a file in a repository that strips things on publish does
 * not get for free. Verified three ways: it is tracked, the archive that
 * ships the tree to the suite container carries it because that exclusion
 * matches a path component rather than a prefix, and it reaches the mirror
 * byte identical.
 *
 * **Deliberately not every ignored directory.** That is the closure above,
 * and it would take the working notes out of the corpus too, which the
 * document subset arm's own reasoning is built on today.
 */
const UNVERSIONED_AT_THE_ROOT: string[] = ignoreRules
  .split("\n")
  .map((line) => line.trim())
  // **The obvious pattern for this reacts to a comment probe, and the way
  // back from that is the one thing not to do.** A separator, a run of
  // anything else, a separator is the shape of a block comment: written that
  // way it matches three of the probes `withoutProse.test.ts` drives every
  // matcher in this tree against, so that rule reads this file as having
  // grown a second comment stripper and reds. Its corpus is every test entry
  // besides itself, so the road back to green is an exemption entry for the
  // largest rules file in the tree, which is where the next corpus rule
  // lands. Found by the full run; a targeted run of this file cannot see it.
  //
  // **It is the spelling that reacts, not patterns in general**, and the
  // distinction is worth the line because the next reader will reach for one.
  // A pattern excluding the metacharacters as well is clean under the same
  // probes, measured, and would have closed the dead member case the arm
  // below closes. So this chain is a preference, not a forced move.
  .filter(
    (line) =>
      line.length > 2 &&
      line.startsWith("/") &&
      line.endsWith("/") &&
      !line.slice(1, -1).includes("/"),
  )
  .map((line) => line.slice(1, -1));

/**
 * Everything in a corpus that belongs to a materialised publish tree.
 *
 * **A union of a property and a pinned fact, because neither covers the
 * other.** `materialisedCopies` reads a copy off its shape and so finds one
 * under any directory name, and it goes blind on a copy that is stale, which
 * is the state the exclusion exists for. The pin covers the one directory
 * whose contents are output by construction, whatever has happened to the
 * tree since, and covers nothing else. Measured: with a published document
 * renamed after a real run at the default directory, the shape half returns
 * nothing and the union returns every copy.
 *
 * **One home used by both sides of `reads the same documents a second pattern
 * reaches`, and that does not collapse its two instruments.** The instruments
 * there are the two glob patterns, which stay independently written: a
 * narrowing in either shows up as a disagreement, demonstrated by planting
 * one. What a change here does move on both sides is covered elsewhere, each
 * half by its own arm: the shape by the corpus rows, the pin by the
 * membership assertion beside them.
 *
 * **What the union still misses is a conjunction, and it is not the state
 * measured above.** A run whose output directory is neither the one the
 * repository refuses to version at its root nor still a whole shadow of the
 * tree, which is any other directory over a tree that has since lost a
 * published path, is caught by neither half. **Measured in that state: every
 * published document sits in the corpus twice, one copy carries a path the
 * source no longer has, and the whole file is green.** Deleting this filter
 * outright reds nothing there, which is the honest statement of what it is
 * worth in that corner.
 */
function thePublishTreeIn(paths: readonly string[]): string[] {
  const pinned = paths.filter((path) =>
    UNVERSIONED_AT_THE_ROOT.some((directory) =>
      path.startsWith(`${directory}/`),
    ),
  );
  const rest = paths.filter((path) => !pinned.includes(path));
  return [...pinned, ...materialisedCopies(rest)].sort();
}

/** The glob's answer less the publish tree, by either route to it. */
function withoutThePublishTree(
  documents: Record<string, string>,
): Record<string, string> {
  const copies = new Set(
    thePublishTreeIn(Object.keys(documents).map(repositoryPath)),
  );
  return Object.fromEntries(
    Object.entries(documents).filter(
      ([key]) => !copies.has(repositoryPath(key)),
    ),
  );
}

/**
 * Every Markdown document on the filesystem, the machinery trees aside.
 *
 * **Read through `DOCUMENTS` and not directly.** This one still holds the
 * publish tree when somebody has run the script locally, and a stale copy in
 * the corpus reports a violation the source no longer has: measured
 * 2026-09-10, a four day old copy of `docs/featurelist.md` failed the column
 * count rule on a sentence deleted in the same merge. Whether that tree exists
 * at all depends on whether somebody ran the script, which is not something a
 * test result may turn on.
 */
const GLOBBED_DOCUMENTS = import.meta.glob(
  [
    "../../**/*.md",
    "!../../**/node_modules/**",
    "!../../**/.venv/**",
    "!../../**/.git/**",
  ],
  {
    query: "?raw",
    import: "default",
    eager: true,
  },
) as Record<string, string>;

/**
 * Every Markdown document this repository versions.
 *
 * **The exclusion is stated and it is build output, not a corner of the
 * tree.** An earlier draft globbed the repository root and one level of
 * `docs/`, which is an inclusion list: it left most of the published
 * documents unjudged, `DOCKERHUB.md` among them, which is derived from the
 * README's feature bullets and so is the likeliest place a deleted sentence
 * is copied back to. `backend/tests/test_roster_counts.py` measured that same
 * shape, replaced it and pinned against it. The two counts that stood in this
 * sentence were taken over a corpus that has since grown by half, and a
 * reader takes a figure in a docstring as current.
 *
 * **What decides publication is the declaration in a document's header**,
 * applied by `scope` below. It is the property the publish gate reads, so the
 * two cannot drift, and a document added anywhere needs no entry anywhere.
 */
const DOCUMENTS = withoutThePublishTree(GLOBBED_DOCUMENTS);

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
describe("a directory reproducing the tree is read as a copy of it", () => {
  // **Each row is a family the live tree or the publish script produces, and
  // each of the reader's three decisions has one row that reds under its
  // mutant and no other row.** A decision with no mutant of its own is
  // decoration that reads like an arm, so they are named rather than
  // counted. **The claim is scoped to these rows**, because relaxing the
  // first condition also reds the per entry witness below, which is a
  // different arm and not a reason to think the row is doing less work. The
  // other two leave that witness green.
  //
  // **Relaxing "every document under it shadows one outside it"** reds `a
  // directory of its own documents holding one copy of a nested one`.
  // **Dropping "one shadowed document is itself inside a directory"** reds `a
  // directory whose one document shares a root document's name`, and the live
  // corpus with it. **Dropping the separator from the prefix test that
  // collects a copy's documents** reds `a copy beside a directory whose name
  // begins the same way`, and nothing else in the file sees it: measured,
  // that one token takes documents out of the corpus with every other arm
  // green.
  /** One name for the copy and the sibling below it, so they move together. */
  const COPY = "mirror";

  const SHAPES: [string, string[], string[]][] = [
    [
      "a copy of the tree under a name that is not the default",
      ["README.md", "docs/api.md", "mirror/README.md", "mirror/docs/api.md"],
      ["mirror/README.md", "mirror/docs/api.md"],
    ],
    [
      "a copy nested below the root",
      [
        "README.md",
        "docs/api.md",
        "build/out/README.md",
        "build/out/docs/api.md",
      ],
      ["build/out/README.md", "build/out/docs/api.md"],
    ],
    [
      "a directory whose one document shares a root document's name",
      ["README.md", "docs/api.md", "doubles/README.md"],
      [],
    ],
    [
      "a directory of its own documents, one of them sharing a name",
      ["README.md", "docs/api.md", "docs/README.md"],
      [],
    ],
    [
      "a directory of its own documents holding one copy of a nested one",
      ["README.md", "docs/api.md", "notes/docs/api.md", "notes/own.md"],
      [],
    ],
    [
      "a directory holding nothing but a copy of a nested document",
      ["docs/api.md", "keep/docs/api.md"],
      ["keep/docs/api.md"],
    ],
    [
      "a copy beside a directory whose name begins the same way",
      [
        "README.md",
        "docs/api.md",
        `${COPY}/README.md`,
        `${COPY}/docs/api.md`,
        // **Built from the same name, so the sibling cannot drift off the
        // prefix in one token.** Written as two independent literals, renaming
        // this one leaves the row green on shipped code while its name still
        // claims the property, which is this file's own commonest defect.
        // **Its document must shadow nothing**: give it a name the corpus
        // holds and the directory is a copy on its own merits, the expected
        // set changes, and the row stops being about the separator at all.
        `${COPY}ed/own.md`,
      ],
      [`${COPY}/README.md`, `${COPY}/docs/api.md`],
    ],
    ["nothing at all", [], []],
  ];

  it.each(SHAPES)("reads %s", (_name, corpus, copies) => {
    expect(materialisedCopies(corpus)).toEqual(copies);
  });

  /**
   * The rows above, rendered. `asRow` holds why they are written out, and
   * `asRows` refuses a column this rendering cannot tell apart.
   *
   * The row built from `COPY` is spelled through `COPY` here too, so renaming
   * that fixture moves the table and this list together: measured, a rename
   * reds nothing in this file, and reds this arm once the same line is
   * written with the fixture's value instead.
   */
  it("holds exactly the corpora listed here, cell by cell", () => {
    expect(asRows(SHAPES)).toEqual([
      "a copy of the tree under a name that is not the default | [README.md, docs/api.md, mirror/README.md, mirror/docs/api.md] | [mirror/README.md, mirror/docs/api.md]",
      "a copy nested below the root | [README.md, docs/api.md, build/out/README.md, build/out/docs/api.md] | [build/out/README.md, build/out/docs/api.md]",
      "a directory whose one document shares a root document's name | [README.md, docs/api.md, doubles/README.md] | []",
      "a directory of its own documents, one of them sharing a name | [README.md, docs/api.md, docs/README.md] | []",
      "a directory of its own documents holding one copy of a nested one | [README.md, docs/api.md, notes/docs/api.md, notes/own.md] | []",
      "a directory holding nothing but a copy of a nested document | [docs/api.md, keep/docs/api.md] | [keep/docs/api.md]",
      `a copy beside a directory whose name begins the same way | [README.md, docs/api.md, ${COPY}/README.md, ${COPY}/docs/api.md, ${COPY}ed/own.md] | [${COPY}/README.md, ${COPY}/docs/api.md]`,
      "nothing at all | [] | []",
    ]);
  });

  it("pins the directory the repository refuses to version at its own root", () => {
    // **Derive it and then assert it, which is this repository's standing
    // remedy for a derived set feeding anything wider than itself.** The
    // behaviour stays derived: nothing matches on this name. What the literal
    // holds is that the ignore file still says what the pin was built on,
    // which is the one thing a derivation cannot notice about itself.
    //
    // **Removal was armed and widening was not**, and the difference matters
    // because they fail in opposite directions. Losing the entry leaves the
    // union as the shape half alone, which goes blind on a stale copy. Gaining
    // one takes a directory of documents out of the corpus unjudged. Measured
    // with the ignore file grown by one root anchored entry over a directory
    // holding documents: three documents left the corpus, this arm was
    // **green**, and the only red was the cross check below, whose message
    // names neither the ignore file nor the pin. That red is collateral and it
    // goes away once that arm is correct, so this line is what replaces it.
    expect(UNVERSIONED_AT_THE_ROOT).toEqual(["public"]);

    // **What the prefix test can match at all.** An entry reaching here is
    // used as a literal path prefix, so one carrying a separator or a glob
    // metacharacter is admitted as a member that matches nothing: measured,
    // an ignore file carrying a starred or a single character wildcard entry
    // yields members the test below never fires on, and the separator only
    // version of this line refused neither. A name this refuses is refused
    // loudly, at the line, for somebody to decide: the alternative is
    // dropping it inside the derivation, where a pin that has quietly stopped
    // covering a directory looks exactly like one that never did.
    expect(
      UNVERSIONED_AT_THE_ROOT.filter((one) => !/^[\w.-]+$/.test(one)),
    ).toEqual([]);

    // **Four single token changes to the derivation above survive both lines
    // and get no arm of their own, on purpose.** Dropping the length floor,
    // either the trailing separator test or the interior one, or the trim,
    // each returns the identical set against today's ignore file, so there is
    // nothing to assert; dropping the **leading** separator widens it to
    // every ignored directory and the membership equality above names them.
    // An arm per no op is an arm that passes for a reason unrelated to what
    // it says.
    //
    // **They are masked rather than inert, and three of the four are bounded
    // while one is not.** What makes them no ops is the leading separator
    // test plus an ignore file carrying exactly one anchored line, so the
    // harmlessness is a joint property and not a fact about each token.
    // Driven one plausible future entry at a time: a root anchored file, a
    // nested directory and a bare separator each make their own token
    // **widen** the set, and the equality reds. **The trim narrows**, and an
    // equality against a literal cannot see a narrowing: with an indented
    // entry in the ignore file, dropping the trim misses it, the derived set
    // is again exactly the literal, the equality is green, and the pin has
    // silently stopped covering a directory the repository refuses to
    // version. That is the removal direction this arm's own first paragraph
    // says fails silently, reached through the derivation instead of through
    // the file.
  });

  it.each(UNVERSIONED_AT_THE_ROOT)(
    "reads a stale copy under %s that the shape alone cannot",
    (pinned) => {
      // **The witness for the union, and it reds if either half goes.** The
      // shape half needs every document under a directory to shadow one
      // outside it, so a single rename in the working tree since the run
      // takes it to nothing, which is measured on a real run of the script
      // and written up at `materialisedCopies`. A stale copy is the case the
      // exclusion exists for, so the half that is blind there is the half
      // that matters.
      //
      // Driven over every entry rather than the first, because picking one by
      // position is how a guard's subject moves when a file it reads changes.
      // The arm above is what stops this going vacuous at zero entries.
      const sources = ["README.md", "docs/api.md", "docs/legend.md"];
      const copies = sources.map((path) => `${pinned}/${path}`);
      const renamedSince = [
        "README.md",
        "docs/the-api.md",
        "docs/legend.md",
        ...copies,
      ];

      expect(materialisedCopies(renamedSince)).toEqual([]);
      expect(thePublishTreeIn(renamedSince)).toEqual([...copies].sort());

      // **The separator in the pin's own prefix test, which had no mutant.**
      // Dropping it admits any sibling whose name merely begins the same way,
      // and measured, that one token empties documents out of the corpus with
      // every other arm in the file green.
      expect(thePublishTreeIn([`${pinned}sibling/own.md`])).toEqual([]);
    },
  );
});

describe("the number of table columns is not written down", () => {
  const count = Object.keys(COLUMN_SPECS).length;

  function scope(): [string, string][] {
    return [
      ...sourcesAsImported(),
      ...testEntries(),
      ...Object.entries(DOCUMENTS).filter(
        ([, source]) => !declaresItselfInternal(source),
      ),
    ];
  }

  it("reads the source documents and not a materialised copy of them", () => {
    // **Armed by splicing a copy into the live corpus, because no run ever
    // sees one.** This asserted that no key began with the directory the
    // publish script writes to by default. That directory is an argument to
    // the script, so the arm was green with a copy of every published document
    // in the corpus under any other name, which is the state that reports a
    // correct rename as a violation out of a stale copy. The arm was named for
    // the property and held the spelling.
    //
    // **The name spliced in here is deliberately not the default**, so what
    // reds is the property. The corpus is the live one rather than a fixture,
    // so the arm cannot go stale against a document added beside it.
    const sources = Object.keys(DOCUMENTS).map(repositoryPath);
    const spliced = sources.map((path) => `elsewhere/${path}`);

    expect(thePublishTreeIn([...sources, ...spliced])).toEqual(
      [...spliced].sort(),
    );
    // And the filter above took, so the corpus the rules read holds no copy
    // whatever the directory it was written to was called.
    expect(thePublishTreeIn(sources)).toEqual([]);
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
    expect(testEntries()).not.toEqual([]);
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
const WALLPAPER_MODULE = "theme/patterns.ts";
const WALLPAPER = `../src/${WALLPAPER_MODULE}`;

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
    return [...sourcesAsImported(), ...testEntries()];
  }

  it("leaves none of them unreached", () => {
    expect(
      unreferenced(WALLPAPER, sourceText(WALLPAPER_MODULE), scope()),
    ).toEqual([]);
  });

  it("is reading a door and a tree, not two empty sets", () => {
    // Both halves of the comparison, asserted: a subject with no exports and a
    // scope with no importers agree, and the arm above cannot tell that from a
    // rule that holds.
    expect(exportedBy(WALLPAPER, sourceText(WALLPAPER_MODULE))).toContain(
      "patternDataUri",
    );
    expect(
      exportedBy(WALLPAPER, sourceText(WALLPAPER_MODULE)).length,
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
    const reached = sourcesAsImported()
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
    const source = sourceText(SCAN_REASONS);
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
    const declared = declaredIn(QUEUE, sourceText(QUEUE), "CatalogueAnswer");
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
    const answers = declaredIn(QUEUE, sourceText(QUEUE), "CatalogueAnswer");
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
 * Spelled in the space `sourcesAsImported` keys, because `unreferenced`
 * resolves importers' specifiers into that space, and spelled plainly beside
 * it for the arms that walk `entries()`.
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
   * **A dated field rendered with no formatting call at all writes no name**, so
   * it is out on a different axis from the four above: each of those is a place
   * this rule cannot look, and this one is a defect with nothing to look for.
   * Widening the watched list can never reach it. The rule below this block is
   * keyed on the field rather than on the call and reports one shape of it, a
   * field named in a JSX child with no door call handed that field. **It closes
   * no part of the class, including inside that position**: a field bound to a
   * local name before the child reads it sits in a JSX child and is reported by
   * neither rule, which that rule's own arm asserts. Whoever reads this row
   * reads the table there rather than taking the position as a boundary.
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
  // exists for`; and the door's own source is asserted by the door arm below,
  // which asks `sourceText` for it and is handed a throw if the module moves.
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
    // used to make: `tests/lib/date.test.ts` imports every export by name, so
    // with tests in scope every `src` caller could go away and this arm would
    // stay green on the test file alone, which is exactly the dead door it said
    // it caught. **No count of callers sits here**, because the arm below is the
    // measurement: it reds the day an export has no caller under `src`. An
    // earlier version of this comment carried per export figures and a module
    // total, and both were false within the hour, when a sixth export arrived
    // from another branch in the same wave.
    expect(
      unreferenced(
        THE_DATE_DOOR,
        sourceText(THE_DATE_DOOR_MODULE),
        sourcesAsImported(),
      ),
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

/**
 * The committed schema, which is where the dated field names come from.
 *
 * Read the way `lib/bookBounds.test.ts` and `lib/bookRequest.test.ts` read it,
 * so there is one idiom for "ask the API what it declares" rather than three.
 */
const SCHEMA = import.meta.glob("../openapi.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** As much of a JSON Schema node as the walk below has to understand. */
interface SchemaNode {
  type?: unknown;
  format?: unknown;
  properties?: Record<string, SchemaNode>;
  anyOf?: SchemaNode[];
  items?: SchemaNode;
  [key: string]: unknown;
}

let schema: SchemaNode | undefined;

/**
 * Parsed once, because the rule below asks for it per module.
 *
 * Half a megabyte of JSON parsed three hundred times is minutes, and this file
 * already states what a test environment costs a run.
 */
function schemaDocument(): SchemaNode {
  const raw = SCHEMA["../openapi.json"] ?? "";
  // A glob that matched nothing would make every field name below disappear
  // and the rule pass over an empty subject.
  expect(raw.length).toBeGreaterThan(1000);
  schema ??= JSON.parse(raw) as SchemaNode;
  return schema;
}

/**
 * The members of one property's schema that are not the null branch.
 *
 * A nullable field is `anyOf: [{the real thing}, {"type": "null"}]`, which is
 * the same flattening `lib/bookBounds.test.ts` does for a bound. Written here
 * rather than imported because that one keeps only the four keys a bound uses
 * and drops `format`, which is the whole subject of this rule.
 */
function branchesOf(property: SchemaNode): SchemaNode[] {
  const parts = [property, ...(property.anyOf ?? [])];
  const items = parts
    .map((part) => part.items)
    .filter((part) => part !== undefined);
  return [...parts, ...items].filter((part) => part.type !== "null");
}

/**
 * Every property name the API declares as a date or a timestamp.
 *
 * **Derived from the committed schema, never listed.** A written list of dated
 * fields is the defect this repository has paid for repeatedly: it is right on
 * the day it is written and silently short on the day a migration adds a
 * column. `format` is the thing to key on rather than a name suffix, because
 * `failing_since` and `missing_since` carry no `_at` and `root_confirmed`
 * carries no date.
 *
 * **The schema is the backend's own output and the suite holds it byte
 * identical**, so this cannot drift from what the API sends without a red in
 * the other suite first.
 */
let dated: string[] | undefined;

function datedFields(): string[] {
  if (dated !== undefined) return dated;
  const names = new Set<string>();
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) {
      for (const item of node as unknown[]) walk(item);
      return;
    }
    if (typeof node !== "object" || node === null) return;
    const record = node as SchemaNode;
    for (const [name, property] of Object.entries(record.properties ?? {}))
      if (
        branchesOf(property).some(
          (part) => part.format === "date" || part.format === "date-time",
        )
      )
        names.add(name);
    for (const value of Object.values(record)) walk(value);
  };
  walk(schemaDocument());
  dated = [...names].sort();
  return dated;
}

/** The non null types those fields are declared with, as a set. */
function datedFieldTypes(): string[] {
  const types = new Set<string>();
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) {
      for (const item of node as unknown[]) walk(item);
      return;
    }
    if (typeof node !== "object" || node === null) return;
    const record = node as SchemaNode;
    for (const property of Object.values(record.properties ?? {}))
      for (const part of branchesOf(property))
        if (part.format === "date" || part.format === "date-time")
          types.add(
            typeof part.type === "string"
              ? part.type
              : `${JSON.stringify(part.type)}`,
          );
    for (const value of Object.values(record)) walk(value);
  };
  walk(schemaDocument());
  return [...types].sort();
}

/**
 * The expression kinds that hand their own value to an expression inside them.
 *
 * **Read by `resultsOf` rather than stated beside it.** Written as a list and
 * dispatched on a `switch`, the list is prose: a kind added to the switch and
 * not to the list, or the reverse, changes the rule while every arm here stays
 * green. The dispatch is this record, so there is one home and no second
 * spelling to drift against.
 *
 * **The closed set this is drawn from is the grammar**, which is the only
 * reason the rule below can claim to close anything: these are the ESTree
 * expression kinds whose result is the result of a sub expression. The question
 * is not "what else could somebody write", which does not terminate.
 *
 * **A kind missing from here is silent, not loud, and the first version of this
 * comment had that backwards.** Reading a node whole pools the names of every
 * branch into one set, so a missing kind turns a split into a pooling; where
 * the same field is also handed to the door elsewhere in that node, the pooling
 * clears it. The fix for the direction is not in this list, it is that nothing
 * is cleared by sharing a node with a door call: a field is cleared only where
 * it is itself an argument of one. What this list still owes is the arm below
 * that refuses a kind classified in neither half.
 *
 * **`&&` forwards only its right side, and that rests on the schema rather
 * than on taste.** It yields its left side when that side is falsy, and every
 * dated field is declared `string` or null, so a falsy one is `""`, `null` or
 * `undefined` and React renders none of the three. The arm below asserts that
 * type, and it asserts one spelling of it: the type on the branch that carries
 * the date format. A field that kept a dated string branch and gained a second
 * branch typed something else would pass that arm and break this row, because
 * the second branch carries no format for the walk to find it by.
 *
 * **Not censused against the tree, where its other half is.** A forwarding row
 * earns its place by being right when the kind arrives, not by occurring today:
 * the comma operator occurs nowhere under `src` and is here because it parses
 * inside a conditional branch and would otherwise pool. That is the same ground
 * `RENDERS_A_DATE_WITHOUT_A_LOCALE` sits on above, two lists with different
 * grounds rather than one list with an exception.
 */
const FORWARDS_ITS_VALUE: Record<
  string,
  ((node: Node) => unknown[]) | undefined
> = {
  ChainExpression: (node) => [node.expression],
  ParenthesizedExpression: (node) => [node.expression],
  TSAsExpression: (node) => [node.expression],
  TSNonNullExpression: (node) => [node.expression],
  TSSatisfiesExpression: (node) => [node.expression],
  ConditionalExpression: (node) => [node.consequent, node.alternate],
  LogicalExpression: (node) =>
    text(node.operator) === "&&" ? [node.right] : [node.left, node.right],
  SequenceExpression: (node) =>
    (Array.isArray(node.expressions)
      ? (node.expressions as unknown[])
      : []
    ).slice(-1),
};

/**
 * The kinds a result position hands this rule that are read whole.
 *
 * **Censused against the tree in both directions**, which is the half the
 * forwarding record above cannot have: a kind the corpus produces and nobody
 * classified is a kind whose branches are being pooled with nothing said, and a
 * kind here the corpus no longer produces is a row that has outlived its
 * reason. That is the discipline `oxlintRatchet.test.ts` applies to its own
 * suppressions and `backend/book_columns.py` to its columns.
 *
 * **It is brittle on purpose, and the brittle rows are not the ones a reader
 * guesses.** The row nearest to emptying is the render prop, and the template
 * is next. A comment written as a child reads like the fragile one and is not:
 * it sits behind the element and the call, third from the safe end. Emptying a
 * row reds the arm by name, which is a line of diff for whoever did it and the
 * price of the other direction being watched. No counts are written beside the
 * rows: the census arm recomputes them every run, and a figure here would be
 * the one thing in this block nothing recounts.
 *
 * **This is the top of a child, which is narrower than where the reader
 * applies the record.** Those were the same set until the reader began
 * forwarding at depth; it now stands on kinds this census never sees, arrays,
 * binaries, objects and spreads among them, and classifies none of them. The
 * arm below says so rather than claiming a partition over the reader's whole
 * population.
 */
const READ_WHOLE: string[] = [
  // The three ways a value arrives already computed.
  "CallExpression",
  "Identifier",
  "MemberExpression",
  // A literal, and a template, which is read whole because its substitutions
  // are all rendered: there is no discarded position in one.
  "Literal",
  "TemplateLiteral",
  // An element renders itself, and its own children are visited separately, so
  // the reader stops at it and this row contributes no name.
  "JSXElement",
  "JSXFragment",
  // `{/* a comment */}`, which holds no expression at all.
  "JSXEmptyExpression",
  // A render prop handed down as a child. Its body is read whole like any
  // other: every live one happens to be an element, which is a fact about this
  // tree today and not the reason the row is safe.
  "ArrowFunctionExpression",
];

/** Every expression a result position can evaluate to, with nothing between. */
function resultsOf(node: Node): Node[] {
  const forward = FORWARDS_ITS_VALUE[node.type];
  if (forward === undefined) return [node];
  return forward(node).flatMap((value) =>
    isNode(value) ? resultsOf(value) : [],
  );
}

/**
 * The kinds the corpus actually puts in a result position.
 *
 * **Taken over `src` alone and never over a fixture**, because a probe written
 * into the population it measures is counted by it: the synthetic sources in
 * the arms below would otherwise add kinds to this census and classify
 * themselves.
 */
function terminalKindsUnderSrc(): string[] {
  const kinds = new Set<string>();
  for (const [path, source] of entries())
    for (const value of renderedExpressionsIn(path, source))
      for (const result of resultsOf(value)) kinds.add(result.type);
  return [...kinds].sort();
}

/**
 * Does this kind carry a type rather than a value?
 *
 * **One rule derived from the forwarding record, where a list of key names
 * stood before.** That list had four entries and one mutant between them, and
 * three of the four were masked rather than inert: a parameter's annotation is
 * already walked with collection off, and two of the others lead to nodes whose
 * next key is one of those. Three rows read as arms and one was doing the work.
 *
 * **A `TS` prefix is the whole test, less the kinds that forward.** Those are
 * expressions carrying a value through a type, so they are read; everything
 * else `TS` prefixed is a type, and a type that happens to spell a door export
 * or a field name is not a call and not a read. Descending into `expression`
 * rather than stopping keeps `foo(x.due_at as string)` visible, which is what
 * sank the first version of this: dropping every `TS` node unsaw it entirely.
 *
 * **The descent is insurance rather than a live path.** No `TS` prefixed kind
 * that forwards nothing and carries a value somewhere other than `expression`
 * is reachable from inside a child today, so the line costs a traversal and
 * buys the direction being loud when one arrives.
 */
function carriesATypeOnly(node: Node): boolean {
  return (
    node.type.startsWith("TS") && FORWARDS_ITS_VALUE[node.type] === undefined
  );
}

/**
 * The identifiers written under one node, as names.
 *
 * **Identifiers and not literals, which is narrower than the reader beside
 * it.** This one answers "does this function call the door", and a string
 * equal to a door export's name is not a call to it. The reader below collects
 * literals on purpose, because `book["due_at"]` is a read.
 */
function identifiersUnder(value: unknown): Set<string> {
  const names = new Set<string>();
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) {
      for (const item of node as unknown[]) walk(item);
      return;
    }
    if (!isNode(node)) return;
    if (node.type === "JSXElement" || node.type === "JSXFragment") return;
    if (carriesATypeOnly(node)) {
      walk(node.expression);
      return;
    }
    if (node.type === "Identifier") {
      const name = text(node.name);
      if (name !== null) names.add(name);
    }
    for (const key of Object.keys(node)) walk(node[key]);
  };
  walk(value);
  return names;
}

/**
 * Every value a module writes into a JSX child position.
 *
 * **The position is read off the grammar and not off a list of places.** A
 * `JSXElement` and a `JSXFragment` each hold a `children` array, and that array
 * holds five kinds: text, a nested element, a nested fragment, an expression
 * container and a spread child. The first three carry no expression to check,
 * and the two nested kinds are reached by the walk on their own account. The
 * last two each carry one `expression`, which is what this reads.
 *
 * **Whole containers, not split into results.** The reader below applies the
 * forwarding record at every node it meets rather than only here, so splitting
 * twice would be two applications of one rule. `resultsOf` is still what the
 * census arm reads, which is the one thing that wants the terminals by
 * themselves.
 */
function renderedExpressionsIn(path: string, source: string): Node[] {
  const results: Node[] = [];
  visitNodes(parseAst(source, { lang: langOf(path) }), (node) => {
    if (node.type !== "JSXElement" && node.type !== "JSXFragment") return;
    for (const child of Array.isArray(node.children)
      ? (node.children as unknown[])
      : []) {
      if (!isNode(child) || !isNode(child.expression)) continue;
      results.push(child.expression);
    }
  });
  return results;
}

let doorNames: Set<string> | undefined;

/**
 * The door's exported names.
 *
 * **One export reads a date rather than writing one.** `endOfDayInstant` turns
 * a picked day into an ISO instant, so a field handed to it is cleared here
 * although rendering the answer would be the same defect. No child position
 * under `src` hands it one, and it is accepted rather than excluded by name
 * because the door is the unit this rule is written against: a list of door
 * exports kept here would be the stale list the whole design avoids.
 *
 * **Taken through `exportedBy`, which the arm above this block already uses**,
 * so a rename moves both at once and neither can be the stale one.
 */
function doorExports(): Set<string> {
  doorNames ??= new Set(
    exportedBy(THE_DATE_DOOR_MODULE, sourceText(THE_DATE_DOOR_MODULE)),
  );
  return doorNames;
}

/**
 * Every name a module binds at its top level, under any form.
 *
 * **A declarator id goes through `identifiersIn` and not through `.name`.**
 * A pattern has no `name`, so reading the property direct answers `undefined`
 * for `const { numericDate } = helpers` and for the array form, and both were
 * cleared. That reader is the file's one home for the names a binding target
 * writes, and this is the fourth time the same shape has been paid for here.
 *
 * **An import binds too, and only one from somewhere other than the door.**
 * `import { numericDate } from "./elsewhere"` has no `id` at all, so a door
 * name imported from a module that is not the door was cleared. Both halves of
 * that are silent, which is what makes them worth a reader rather than a
 * sentence. The door's own import is deliberately not counted: subtracting it
 * would take the trust away from every correct caller in the tree, which is
 * the one way this fix could be worse than the miss it closes.
 */
function declaredAtTopLevel(path: string, source: string): Set<string> {
  const names = new Set<string>();
  const ast = parseAst(source, { lang: langOf(path) }) as unknown as {
    body: unknown[];
  };
  const take = (node: unknown): void => {
    if (!isNode(node)) return;
    if (node.type === "ExportNamedDeclaration") {
      take(node.declaration);
      return;
    }
    if (node.type === "ImportDeclaration") {
      const from = isNode(node.source) ? text(node.source.value) : null;
      if (
        from !== null &&
        resolvedFrom(path, from) === flatten(THE_DATE_DOOR_MODULE.split("/"))
      )
        return;
      for (const one of Array.isArray(node.specifiers) ? node.specifiers : [])
        if (isNode(one) && isNode(one.local))
          for (const name of identifiersIn(one.local)) names.add(name);
      return;
    }
    if (node.type === "VariableDeclaration") {
      for (const one of Array.isArray(node.declarations)
        ? node.declarations
        : [])
        if (isNode(one) && isNode(one.id))
          for (const name of identifiersIn(one.id)) names.add(name);
      return;
    }
    const id = node.id;
    const name = isNode(id) ? text(id.name) : null;
    if (name !== null) names.add(name);
  };
  for (const node of ast.body) take(node);
  return names;
}

/**
 * The names a call to which means "the door formatted this", in one module.
 *
 * **The door's own exports, less what the module declares for itself, plus one
 * hop.** A module that writes its own `const numericDate = (x) => x` and never
 * imports the door used to clear every field it handed that function. The
 * subtraction closes it, and it costs nothing live: the door is the only module
 * under `src` declaring any of these names.
 *
 * **The subtraction and not an import seeded set, which is a trade and not an
 * oversight.** Reading the trust set off the module's own import of the door
 * would additionally clear an alias, `import { numericDate as nd }`. Here `nd`
 * is reported instead, which is a false refusal, loud, at the line somebody
 * writes it, and there are none. What that buys is that this needs no import
 * resolution and has no shape of import it can throw on.
 *
 * **The alias runs both ways and only one way is loud, so both are written.**
 * An alias **of** the door loses the trust and is reported. An alias **onto** a
 * door name from elsewhere, `import { formatIt as numericDate }`, would have
 * taken the trust and cleared silently, which is the dangerous half; the
 * subtraction below reads an import's local name and closes it. **Neither reading
 * closes a nested shadow**: a binding inside one function, in a module that
 * does import the door, keeps the trust either way, and only a scope walk
 * closes that. A scope walk is wrong by answering yes, which is silent.
 *
 * **The hop is one deep.** `SenderHealthLine` binds
 * `const when = (iso) => longMonthDate(iso, locale)` and renders `when(...)`,
 * which is a correct call site the door's exports alone do not explain: without
 * it, both of the lines that component draws are refused, and it is the only
 * module under `src` that has one. A wrapper of a wrapper is refused, loudly,
 * at the line where somebody writes the second one.
 *
 * **The hop is earned by naming a door export as an identifier**, never by a
 * string or a template chunk equal to one: a name in quotes is not a call.
 *
 * **It takes `const` bound functions and not declarations**, and the stated
 * reason used to be only half of what the exclusion does. Trusting a
 * component's own name would explain any mention of it, and `LoanPanel`,
 * `TrashRow` and `SenderHealthLine` are the components this would trust. But
 * `lend` in `LoanPanel` is a declared helper and not a component, so the
 * exclusion is about the declaration form rather than about components.
 *
 * **Those four are named rather than counted**, which is not a refusal to
 * measure: this function's own reader is what found them. Three instruments
 * answered the question with three figures, differing on whether the door's own
 * declarations count and on whether the walk reads a string equal to a door
 * name, and two of them agree on exactly these four once both are fixed. A
 * reader can check four names; nobody re-runs a census to check a total.
 */
function formattingNamesIn(path: string, source: string): Set<string> {
  const declared = declaredAtTopLevel(path, source);
  const door = new Set(
    [...doorExports()].filter((name) => !declared.has(name)),
  );
  const names = new Set(door);
  visitNodes(parseAst(source, { lang: langOf(path) }), (node) => {
    if (node.type !== "VariableDeclarator" || !isNode(node.init)) return;
    if (
      node.init.type !== "ArrowFunctionExpression" &&
      node.init.type !== "FunctionExpression"
    )
      return;
    const bound = isNode(node.id) ? text(node.id.name) : null;
    if (bound === null) return;
    if ([...identifiersUnder(node.init)].some((name) => door.has(name)))
      names.add(bound);
  });
  return names;
}

/**
 * The name a call writes for its callee, where that is a plain name.
 *
 * **A member call is not a door call, and the branch that read one is gone.**
 * The door is reached by a named import, which `importedFrom` in this file
 * already refuses to resolve through a namespace, so `date.numericDate(x)`
 * cannot be a door call here. Reading the property name off a member call only
 * ever widened what gets cleared: any `x.clockTime(book.due_at)` on an
 * unrelated object cleared the field. No live door call is a member call.
 */
function calleeNameOf(node: Node): string | null {
  const callee = node.callee;
  if (!isNode(callee) || callee.type !== "Identifier") return null;
  return text(callee.name);
}

/**
 * Every dated field a value reads, less the ones it hands to a door call.
 *
 * **The discard rule applies at every node and not only at the top of the
 * child, which is the whole correction over the version before it.** Splitting
 * a conditional into its branches at the result position and then reading the
 * rest of the expression whole means that inside a terminal the branches are
 * pooled again. A door call in a branch that never runs then cleared the branch
 * that does: `{t(k, { x: ok ? numericDate(b.due_at, l) : b.due_at })}` was
 * green. One walk, applying `resultsOf` wherever it stands, closes it.
 *
 * **So the clearing is per occurrence, and the reading that made per field
 * necessary is gone.** Each read is judged where it sits: `ReadingPanel` writes
 * `book.my_started_at && longMonthDate(book.my_started_at, locale)`, and the
 * first mention is the discarded left of a logical rather than a mention
 * cleared by its neighbour. A second raw mention of the same field elsewhere in
 * that value is now reported, which per field could not do.
 *
 * **A door call hands over everything inside it**, so the walk stops there
 * rather than subtracting a set afterwards. That is also why a string literal
 * inside a door call no longer clears a field beside it: there is no set to
 * pollute.
 *
 * **Both halves come from this one function**, with the door set emptied to ask
 * what the value reads at all. Two readers for the two halves would be two
 * chances to disagree about what a read is.
 *
 * **A parameter list is a binding and not a read**, so it is walked with
 * collection off: `{rows.map(({ due_at }) => <Cell />)}` names the field and
 * reads nothing, where its undestructured twin was already clean, and reporting
 * one and not the other is a false refusal keyed on spelling. Parameters are
 * the whole of that rule: a set of pattern kinds stood beside it and reddened
 * nothing when deleted, because inside a child expression the only route to a
 * pattern is a parameter list. The residual is that a default value in a
 * parameter, `({ a = book.due_at }) => ...`, is a read and is not collected.
 * The tree has none.
 *
 * **A property key is not a read either**, in either spelling. `{ due_at: v }`
 * and `{ "due_at": v }` both name the field and read `v`, and a computed key is
 * left alone because `{ [due_at]: v }` does read it.
 */
function fieldsReadIn(
  value: unknown,
  door: Set<string>,
  fields: string[],
): Set<string> {
  const found = new Set<string>();
  const walk = (node: unknown, binds: boolean): void => {
    if (Array.isArray(node)) {
      for (const item of node as unknown[]) walk(item, binds);
      return;
    }
    if (!isNode(node)) return;
    // A nested element renders itself, and the walk reaches it on its own
    // account. Without this, a field handed to a child component as an
    // attribute is reported as a rendering.
    if (node.type === "JSXElement" || node.type === "JSXFragment") return;
    if (carriesATypeOnly(node)) {
      walk(node.expression, binds);
      return;
    }
    if (node.type === "CallExpression") {
      const callee = calleeNameOf(node);
      if (callee !== null && door.has(callee)) return;
    }
    // The forwarding record, applied through the same function the census
    // reads, so there is one application of it rather than two.
    const results = resultsOf(node);
    if (results.length !== 1 || results[0] !== node) {
      for (const result of results) walk(result, binds);
      return;
    }
    if (!binds) {
      const written: (string | null)[] = [
        node.type === "Identifier" ? text(node.name) : null,
        node.type === "TemplateElement"
          ? text((node.value as { cooked?: unknown })?.cooked)
          : null,
        text(node.value),
      ];
      for (const name of written)
        if (name !== null && fields.includes(name)) found.add(name);
    }
    for (const key of Object.keys(node)) {
      if (key === "key" && node.type === "Property" && !node.computed) continue;
      walk(node[key], key === "params" ? true : binds);
    }
  };
  walk(value, false);
  return found;
}

/** One row per dated field a module names in a value a reader is shown. */
interface RenderedDate {
  readonly field: string;
  /** Whether every mention of it in that value went into a door call. */
  readonly handed: boolean;
}

function datesRenderedIn(path: string, source: string): RenderedDate[] {
  const fields = datedFields();
  const door = formattingNamesIn(path, source);
  const rows: RenderedDate[] = [];
  for (const value of renderedExpressionsIn(path, source)) {
    const unhanded = fieldsReadIn(value, door, fields);
    for (const field of fieldsReadIn(value, new Set(), fields))
      rows.push({ field, handed: !unhanded.has(field) });
  }
  return rows;
}

/** The ones handed to nothing, as sentences, which is the refusal. */
function datesRenderedRawIn(path: string, source: string): string[] {
  return [
    ...new Set(
      datesRenderedIn(path, source)
        .filter((row) => !row.handed)
        .map((row) => `${path} renders ${row.field} unformatted`),
    ),
  ].sort();
}

/**
 * A dated field named in a JSX child is handed to a door call in that child.
 *
 * **Keyed on the field, where the block above is keyed on the call.** That
 * block collects the names the platform publishes, so a field rendered with no
 * formatting call writes no name and is invisible to it however wide the name
 * list grows. This asks the schema which fields carry a date instead.
 *
 * **The name of this rule is the whole of what it holds, deliberately.** It
 * does not say the field was rendered through the door, because it cannot see
 * whether the value the door returned is the value that reached the page; it
 * says every mention of the field in that child sits inside a door call. An
 * earlier version said "goes through the door" while clearing on co-residence,
 * which is a weaker property under a stronger name, and that is the defect this
 * file charges for most often.
 *
 * ## What it does not reach, which is most of the class
 *
 * **It closes no part of the class outright, including inside its own
 * position.** Both rows below that are about a value sit in a JSX child, so a
 * reader must not take the position as the boundary of what is covered.
 *
 * **A field bound to a local name first is invisible, in a JSX child.**
 * `SecurityRecord` writes `const resetOn = security.password_reset_at` and
 * renders `numericDate(resetOn, locale)`: correct, and the child names no dated
 * field, so this rule never looks at it. The same mechanism hides the wrong
 * version. Witnessed by an arm below rather than left here as a sentence.
 *
 * **A read whose value is rendered as something other than a date is still
 * reported, which is what clearing per occurrence costs.** Only a door call
 * clears, so a field compared, handed to a helper that is not the door, or
 * written into a dependency array inside a child is refused although no date
 * reaches the page. The same read in a discarded position is clean, so this is
 * narrower than "any read that is not a date". It is the mirror of the
 * residual the per field reading had: that one cleared too much silently, this
 * one refuses too much loudly, at the line somebody writes it. **None is live
 * and one is an inline away**: `LoanRow` already draws a day count beside a
 * formatted date, and the count is computed above the child rather than in it.
 * Witnessed below, both halves.
 *
 * **A field carried out of the component in a structure is invisible**, and
 * this is the shape the defect that prompted the rule actually took:
 * `["copy.purchasedAt", book.purchased_at]` is an array element whose siblings
 * are already rendered strings, mapped through `String(value)` later and drawn
 * by another part of the file. The parent kind of that read is an
 * `ArrayExpression`, which is also the parent kind of a React dependency array,
 * so no rule over the parent kind separates the two. What would close the class
 * is a type the door returns and a display slot requires, which is a change to
 * the application rather than a guard over it.
 *
 * **An attribute is out of scope deliberately.** `title=`, `aria-label`, `alt`
 * and `placeholder` each put a string in front of a reader, and the set of
 * attributes that do is not fixed by anything: it is an enumeration of places,
 * which is the shape that does not terminate. No mention of a dated field under
 * `src` sits in one today, so the choice costs nothing on arrival.
 *
 * ## The false refusals, measured before the rule shipped and not after
 *
 * **Every live mention of a dated field under `src` was derived from the schema
 * and driven through this pass before it was written into the file.** No figure
 * is written here, because the arms below are the measurement and they move
 * with the tree: one says nothing is refused, one says the set that is allowed
 * is not empty, and a green on the first alone is also what a pass over no
 * render positions produces. The live shapes are driven as fixtures further
 * down, so a sharpening that starts refusing one reds by name.
 */
describe("a dated field named in a JSX child is handed to a door call", () => {
  it("hands every dated field a child names to the door", () => {
    // **What the walk consumed is recorded, not asserted about afterwards.**
    // An earlier version said in a comment that there was no filter here, which
    // is a property of the text rather than an arm: a three line filter at this
    // site hid two live modules and left the run green. This collects the paths
    // the walk actually reached, so a filter shortens the record and reds.
    const walked: string[] = [];
    const reported = entries().flatMap(([path, source]) => {
      walked.push(path);
      return datesRenderedRawIn(path, source);
    });

    expect(walked).toEqual(entries().map(([path]) => path));
    expect(reported).toEqual([]);
  });

  it("finds dated fields in child positions that the door is handed", () => {
    // **The anti vacuity line, and it is a difference rather than a floor.**
    // The arm above is an empty list, which is also what a pass that finds no
    // render position produces, what a schema walk returning no field produces,
    // and what a corpus with no `.tsx` in it produces. This says the set the
    // rule allows is not empty today.
    //
    // **A row is one field in one child, which is a smaller unit than it used
    // to be.** The reader took each split terminal separately before and takes
    // the whole container now, so two mentions of one field in one child that
    // were two rows are one. Any count of these rows taken before that change
    // is larger for that reason and not because a site was lost.
    const handed = entries()
      .flatMap(([path, source]) => datesRenderedIn(path, source))
      .filter((row) => row.handed);

    expect(handed.length).toBeGreaterThan(0);
  });

  it("classifies every kind at the top of a child, exactly once", () => {
    // **The partition, which is what makes the closure argument an arm.**
    // Defaulting an unclassified kind to "read whole" is silent: reading whole
    // pools the branches, and a pooled field handed to the door once used to
    // clear its neighbours. Now it is refused by name instead, which is the
    // discipline `backend/book_columns.py` applies to its columns.
    //
    // **Its population is the top of a child, and the reader's is larger.**
    // The two were the same set until the reader began applying the forwarding
    // record at every node rather than only here; it now stands on kinds this
    // never sees, among them arrays, binaries, objects and spreads, and this
    // arm says nothing about any of them. What it still holds is that nothing
    // arrives at the top of a child unclassified, which is where a kind with
    // discarded positions would otherwise be read whole and pool them.
    //
    // **The forwarding half is deliberately outside this census**, for the
    // reason its own comment gives: a row there earns its place by being right
    // when the kind arrives rather than by occurring today.
    const seen = terminalKindsUnderSrc();
    const forwarding = Object.keys(FORWARDS_ITS_VALUE);

    expect(seen.filter((kind) => !READ_WHOLE.includes(kind))).toEqual([]);
    expect(READ_WHOLE.filter((kind) => !seen.includes(kind))).toEqual([]);
    expect(READ_WHOLE.filter((kind) => forwarding.includes(kind))).toEqual([]);
  });

  it("takes its field names from the schema and nothing else", () => {
    // Three claims the rest of this block rests on, each failing on its own.
    // The schema is reachable and names fields; the fields are the ones the
    // API declares rather than ones chosen by a suffix; and every one of them
    // is a string, which is what the `&&` row of `FORWARDS_ITS_VALUE` rests on.
    const fields = datedFields();

    expect(fields).toContain("purchased_at");
    // No `_at` and no `_on`, so a rule keyed on a name shape would miss it.
    expect(fields).toContain("failing_since");
    // Dated by neither name nor meaning, so the derivation is not a suffix.
    expect(fields).not.toContain("purchase_source");
    expect(datedFieldTypes()).toEqual(["string"]);
  });

  it("takes its door names from the door and from one local hop", () => {
    const door = exportedBy(
      THE_DATE_DOOR_MODULE,
      sourceText(THE_DATE_DOOR_MODULE),
    );
    expect(door).toContain("numericDate");
    for (const name of door)
      expect(formattingNamesIn("x.tsx", "const a = 1;")).toContain(name);

    // The hop, which is the live shape `SenderHealthLine` writes.
    const wrapper =
      "const when = (iso: string) => longMonthDate(iso, locale);\n" +
      "const no = (iso: string) => iso;\n";
    expect(formattingNamesIn("x.tsx", wrapper)).toContain("when");
    expect(formattingNamesIn("x.tsx", wrapper)).not.toContain("no");

    // A door name in a type position is not a call, so it earns no hop.
    expect(
      formattingNamesIn(
        "x.tsx",
        "const f = (x: string) => x as unknown as numericDate;",
      ),
    ).not.toContain("f");

    // Nor is a door name in quotes, or in a template, which is what a reader
    // collecting literals alongside identifiers would take for a call.
    expect(
      formattingNamesIn(
        "x.tsx",
        'const g = (x: string) => pick("numericDate");',
      ),
    ).not.toContain("g");
    expect(
      formattingNamesIn("x.tsx", "const h = (x: string) => pick(`clockTime`);"),
    ).not.toContain("h");

    // A nested element ends the hop reader, and it is the only thing keeping
    // every arrow component out of the trust set: without it, an ordinary
    // component rendering a formatted date earns the hop, and then calling
    // that component clears whatever it is handed.
    expect(
      formattingNamesIn(
        "x.tsx",
        "const Row = ({ d }: P) => <p>{numericDate(d, l)}</p>;",
      ),
    ).not.toContain("Row");

    // And a name the module binds for itself is not the door's, in every form
    // a top level binding takes. Each of these clears nothing: the plain
    // `const`, the exported one, the two patterns, and a door name imported
    // from somewhere that is not the door, which is the silent half of the
    // alias trade.
    const SHADOWS = [
      "const numericDate = (x: string) => x;",
      "export const numericDate = (x: string) => x;",
      "const { numericDate } = helpers;",
      "const [numericDate] = makers;",
      'import { numericDate } from "./elsewhere";',
      'import { formatIt as numericDate } from "./elsewhere";',
    ];
    for (const shadow of SHADOWS) {
      expect(formattingNamesIn("x.tsx", shadow)).not.toContain("numericDate");
      expect(
        datesRenderedRawIn(
          "x.tsx",
          `${shadow}\nconst C = () => <p>{numericDate(b.due_at)}</p>;`,
        ),
      ).toEqual(["x.tsx renders due_at unformatted"]);
    }

    // The door's own import is not a shadow, which is the line between this
    // and taking the trust away from every correct caller in the tree.
    expect(
      formattingNamesIn(
        "pages/components/Row.tsx",
        'import { numericDate } from "../../lib/date";',
      ),
    ).toContain("numericDate");

    // And a declaration is not a hop, which is what keeps a component that
    // names a door export from explaining every mention of itself.
    expect(
      formattingNamesIn(
        "x.tsx",
        "function Panel() { return numericDate(a, l); }",
      ),
    ).not.toContain("Panel");
  });

  it("reports a dated field written straight into a child", () => {
    // The plain spelling, which is what the defect that prompted this rule
    // would have looked like had it been written one layer in.
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{book.purchased_at}</p>;",
      ),
    ).toEqual(["x.tsx renders purchased_at unformatted"]);

    // Through a fragment, which is the other node carrying children.
    expect(
      datesRenderedRawIn("x.tsx", "const C = () => <>{book.due_at}</>;"),
    ).toEqual(["x.tsx renders due_at unformatted"]);

    // A computed read, which a matcher over `.due_at` would not see.
    expect(
      datesRenderedRawIn("x.tsx", 'const C = () => <p>{book["due_at"]}</p>;'),
    ).toEqual(["x.tsx renders due_at unformatted"]);

    // A template, which is a kind with no forwarding row, so it is read whole.
    expect(
      datesRenderedRawIn("x.tsx", "const C = () => <p>{`${book.due_at}`}</p>;"),
    ).toEqual(["x.tsx renders due_at unformatted"]);

    // And the door clears it, which is the same source with one call added.
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{numericDate(book.due_at, locale)}</p>;",
      ),
    ).toEqual([]);
  });

  it("reports a field beside a handed one rather than clearing it", () => {
    // **The finding the co-residence rule could not see.** The first version
    // cleared any field sharing a value with a door name, so the first source
    // here was green and the second, the same source with the call removed, was
    // red: the arm moved on the presence of the call and not on what the call
    // was handed. This is the pair that separates the two.
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{t(k, { a: numericDate(b.due_at, l), b: b.loaned_at })}</p>;",
      ),
    ).toEqual(["x.tsx renders loaned_at unformatted"]);
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{t(k, { a: b.due_at, b: b.loaned_at })}</p>;",
      ),
    ).toEqual([
      "x.tsx renders due_at unformatted",
      "x.tsx renders loaned_at unformatted",
    ]);

    // **The same field, once handed and once raw, and the raw one is
    // reported.** Clearing per field name let this through and was taken
    // because the stronger reading refused `ReadingPanel`. It no longer does:
    // that component's first mention is the discarded left of a logical, which
    // the walk now skips wherever it stands rather than only at the top of the
    // child, so the stronger reading costs nothing and is what runs.
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{t(k, { a: numericDate(b.due_at, l), b: b.due_at })}</p>;",
      ),
    ).toEqual(["x.tsx renders due_at unformatted"]);
  });

  it("reports a branch that runs beside a door call in one that does not", () => {
    // **The pooling the split at the top of a child could not reach.** The
    // forwarding record used to be applied once, at the result position, and
    // the rest of the value read whole, so a door call anywhere inside a
    // terminal cleared the field for every other branch of it. All three of
    // these were green.
    for (const body of [
      // A door call in the branch that does not run.
      "<p>{t(k, { x: ok ? numericDate(b.due_at, l) : b.due_at })}</p>",
      // The same, inside an interpolation.
      "<p>{`${ok ? numericDate(b.due_at, l) : b.due_at}`}</p>",
      // The reading panel's own shape with one extra raw mention.
      "<p>{[b.due_at && numericDate(b.due_at, l), b.due_at].join(' ')}</p>",
    ])
      expect(datesRenderedRawIn("x.tsx", `const C = () => ${body};`)).toEqual([
        "x.tsx renders due_at unformatted",
      ]);
  });

  it("stops at a nested element when it looks for a door call", () => {
    // **The stop is load bearing on both halves of the reader and was armed on
    // only one.** A door call inside a nested element belongs to that element,
    // which the walk reaches on its own account, so it cannot clear a field
    // written beside it out here.
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{[<X key={1}>{numericDate(b.due_at, l)}</X>, b.due_at]}</p>;",
      ),
    ).toEqual(["x.tsx renders due_at unformatted"]);
  });

  it("splits a branch that reading the node whole would pool", () => {
    // **The three rows of `FORWARDS_ITS_VALUE` that are observable, each with
    // both of its sides.** The discarded position answers clean where reading
    // whole would report, and the yielded position answers reported. A row
    // needs both: with only the clean side, emptying the row's accessor is
    // green, because a row that yields nothing makes the whole child vanish
    // and every field in it with it. That is the shape this file warns about,
    // a replacement stronger in the dimension it was written for and silently
    // weaker in one nobody re-checked.
    //
    // The other five rows are inert by construction, not by luck: their kind
    // has one expression child, so forwarding it and reading it whole visit the
    // same nodes. The arm below says which, so the distinction is a measurement
    // rather than this sentence.
    const SPLITS: [string, string, string][] = [
      // The test of a conditional is not its value; its branches are.
      [
        "ConditionalExpression",
        '<p>{book.due_at ? "a" : "b"}</p>',
        '<p>{ok ? book.due_at : "b"}</p>',
      ],
      // The left of `&&` is yielded only when falsy, and a falsy date is "".
      [
        "LogicalExpression",
        '<p>{book.due_at && "a"}</p>',
        "<p>{ok && book.due_at}</p>",
      ],
      // Every element of a comma but the last is discarded.
      [
        "SequenceExpression",
        '<p>{ok ? (book.due_at, "a") : "b"}</p>',
        '<p>{ok ? (a, book.due_at) : "b"}</p>',
      ],
    ];

    for (const [, discarded, yielded] of SPLITS) {
      expect(
        datesRenderedRawIn("x.tsx", `const C = () => ${discarded};`),
      ).toEqual([]);
      expect(
        datesRenderedRawIn("x.tsx", `const C = () => ${yielded};`),
      ).toEqual(["x.tsx renders due_at unformatted"]);
    }

    // Every kind not named above forwards one child, so it cannot be observed
    // this way. Stated as the relationship, so a kind added to the record with
    // more than one child fails here until it has a case.
    const observable = new Set(SPLITS.map(([kind]) => kind));
    const single = Object.keys(FORWARDS_ITS_VALUE).filter(
      (kind) => !observable.has(kind),
    );
    expect(single).toEqual([
      "ChainExpression",
      "ParenthesizedExpression",
      "TSAsExpression",
      "TSNonNullExpression",
      "TSSatisfiesExpression",
    ]);
  });

  it("reads a kind it forwards and a kind it does not the same way", () => {
    // The five inert rows, driven so that "inert" is a measurement. Each
    // carries the field in the one position its kind forwards, so dropping its
    // row changes nothing: both readings reach the same node.
    for (const body of [
      "<p>{book?.due_at}</p>",
      "<p>{book.due_at as string}</p>",
      "<p>{book.due_at!}</p>",
      "<p>{book.due_at satisfies string}</p>",
    ])
      expect(datesRenderedRawIn("x.tsx", `const C = () => ${body};`)).toEqual([
        "x.tsx renders due_at unformatted",
      ]);

    // `ParenthesizedExpression` has no case because this parser keeps no node
    // for a bracket, which is asserted rather than assumed.
    const kinds = new Set<string>();
    visitNodes(parseAst("const a = (b);", { lang: "ts" }), (node) =>
      kinds.add(node.type),
    );
    expect([...kinds]).not.toContain("ParenthesizedExpression");
  });

  it("refuses a comma at the top of a child and not below it", () => {
    // **Where the parser's refusal holds, which is narrower than it looked.**
    // JSX refuses the comma operator as the whole of a container, and that is
    // all it refuses: inside a conditional branch it parses, which is why
    // `SequenceExpression` has a forwarding row at all. The earlier version
    // read the top level refusal as covering the kind.
    expect(() =>
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{(ok, book.due_at)}</p>;",
      ),
    ).toThrow();
    expect(
      datesRenderedRawIn(
        "x.tsx",
        'const C = () => <p>{ok ? (a, book.due_at) : "b"}</p>;',
      ),
    ).toEqual(["x.tsx renders due_at unformatted"]);

    // An angle bracket assertion is an element in a `.tsx` file and unwritable
    // in a `.ts` one, which has no JSX child, so it has no row either.
    expect(() =>
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{<string>book.due_at}</p>;",
      ),
    ).toThrow();
  });

  it("leaves the shapes this tree already writes alone", () => {
    // **The false refusal surface, driven rather than argued.** A rule that
    // reddens any of these is not shippable, so they are asserted here rather
    // than measured once and written into the prose above.
    //
    // **Most are live shapes under `src`, reduced to the part this rule reads,
    // and the two attribute rows are not.** Two instruments measure no dated
    // field in a JSX attribute today, and the destructured one was written for
    // this arm. They are kept because the attribute carry is the shape the
    // element stop exists for, and a rule whose only evidence is the tree stops
    // being evidence the day the tree changes.
    const CLEAN = [
      // A predicate gating an element, which is `ReadingPanel` and `LoanRow`.
      "const C = () => <div>{(book.my_started_at || book.my_finished_at) && <p>x</p>}</div>;",
      // The deadline branch of `LoanRow`, whose test names the field twice.
      "const C = () => <span>{n > 0 && loan.due_at ? t(k, { date: numericDate(loan.due_at, locale) }) : t(j)}</span>;",
      // Not live: a field carried into a child component as an attribute.
      "const C = () => <ul>{rows.map((row) => <Cell when={row.due_at} />)}</ul>;",
      // Not live either: the same, destructured, which used to be refused for
      // its spelling.
      "const C = () => <ul>{rows.map(({ due_at }) => <Cell when={due_at} />)}</ul>;",
      // The one hop wrapper, which is `SenderHealthLine`.
      "const C = () => { const when = (iso: string) => longMonthDate(iso, locale); return <p>{t(k, { when: when(health.last_run_at) })}</p>; };",
      // A list joined before it is rendered, which is `ReadingPanel`: the field
      // is a predicate in one element and the door's argument in the next.
      "const C = () => <p>{[book.my_started_at && longMonthDate(book.my_started_at, l)].filter(Boolean).join(' ')}</p>;",
      // A key is not a read, in either spelling.
      "const C = () => <p>{t(k, { due_at: 1 })}</p>;",
      'const C = () => <p>{t(k, { "due_at": 1 })}</p>;',
    ];

    for (const source of CLEAN)
      expect(datesRenderedRawIn("x.tsx", source)).toEqual([]);
  });

  it("refuses a read in a child that renders no date", () => {
    // **What clearing per occurrence costs, as an arm rather than a
    // sentence.** Only a door call clears and only a discarded position is
    // skipped, so a read that reaches the page as something other than a date
    // is still reported. The direction is the opposite of the residual this
    // replaced: that one cleared too much and said nothing, this one refuses
    // too much at the line somebody writes it.
    //
    // **The `LoanRow` shape is the one an inline away from live.** That
    // component draws a day count beside a formatted date and computes the
    // count above the child; written inside it, this is what it becomes.
    //
    // **The same comparison as a conditional's test is not refused**, which is
    // narrower than this residual first read: `{b.due_at < now ? "a" : "b"}`
    // is clean, because a test is a discarded position. So the residual is a
    // read whose value is rendered as something other than a date, not every
    // read that is not a date.
    for (const body of [
      // A comparison operand, in a position whose value is rendered.
      "<p>{b.due_at < now}</p>",
      // An argument to a helper that is not the door.
      "<p>{daysBetween(b.due_at, now)}</p>",
      // A dependency array written in the child.
      "<p>{useMemo(() => n, [b.due_at])}</p>",
      // A comparator.
      "<p>{rows.sort((x, y) => cmp(x.due_at, y.due_at)).length}</p>",
      // A class name derived from the field.
      "<p>{b.due_at ? cx(b.due_at) : null}</p>",
    ])
      expect(datesRenderedRawIn("x.tsx", `const C = () => ${body};`)).toEqual([
        "x.tsx renders due_at unformatted",
      ]);

    expect(
      datesRenderedRawIn(
        "x.tsx",
        'const C = () => <p>{b.due_at < now ? "a" : "b"}</p>;',
      ),
    ).toEqual([]);
  });

  it("is blind to a dated field bound to a local name first", () => {
    // **The blind spot with a witness, because a blind spot stated in prose is
    // the row nobody rechecks.** Both of these render the field, one correctly
    // and one not, and this rule reports neither: the child names the binding
    // rather than the field. The second is the shape the defect this rule was
    // written after actually took, one indirection further out. Both sit in a
    // JSX child, which is why the row above this block says the position is not
    // the boundary of what is covered.
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => { const on = book.purchased_at; return <p>{on}</p>; };",
      ),
    ).toEqual([]);
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => { const f = [['k', book.purchased_at]]; return <p>{f.map(([k, v]) => String(v))}</p>; };",
      ),
    ).toEqual([]);

    // It reds the day the binding is skipped, which is what makes this a
    // witness rather than a restatement: the same field written in the child
    // directly is reported.
    expect(
      datesRenderedRawIn(
        "x.tsx",
        "const C = () => <p>{book.purchased_at}</p>;",
      ),
    ).toEqual(["x.tsx renders purchased_at unformatted"]);
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

/**
 * A comment continuation joined back up.
 *
 * **Because the thing being read wraps and the formatter is what wraps it.**
 * Prose here is reflowed to eighty columns, so a citation long enough to be
 * worth writing is usually split across two lines and sometimes three. A line
 * by line scan reads half a path and half a label and finds nothing, which is
 * the quiet failure: it reports clean over a tree it never read.
 */
function unwrapped(source: string): string {
  return source.replace(/\n[ \t]*(?:\*|\/\/)?[ \t]*/g, " ");
}

/**
 * A citation: a code span holding a test file's path, `::`, and a name.
 *
 * **The population is this shape, never a list of the files that write it.**
 * Every guard here whose population came from naming its members has been
 * wrong at least once, so what decides membership is a property of the cited
 * thing: the path ends in the suffix `vite.config.ts` collects tests by. That
 * is what keeps the rest of the tree out by construction rather than by
 * exception, and the rest is most of it. This tree cites a source module's
 * export in the same two colon shape, and cites backend tests by class and by
 * function, and none of those is a vitest label or this rule's business.
 *
 * **The code span is required, and it is not decoration.** It is how every
 * citation in the repository is already written, counted over the versioned
 * tree, so requiring it costs nothing; and it leaves an author a way to write
 * the shape without asserting it, which is what the probes below need and
 * what a blanket exemption for this file would otherwise have to buy. What
 * the span costs is a silent gap, so an unfenced one is its own arm.
 *
 * **One fence or two, because a label may hold a delimiter of its own.** Four
 * test names in this tree already do, counted off the parse. Under a single
 * fence the label stops at the first one and the rule reports a name nobody
 * wrote, so a correct citation is refused and a publish waits on an unrelated
 * sentence being rewritten. Two backticks is markdown's own escape for it, and
 * the fence width is matched rather than guessed.
 */
const TEST_FILE = String.raw`[\w./-]+\.test\.tsx?`;
const CITATION = new RegExp("(``?)(" + TEST_FILE + ")::(.+?)\\1", "g");

/** A path under the test tree, by the one spelling of the suffix above. */
const IS_TEST = new RegExp("^tests/" + TEST_FILE + "$");

/** The bare shape, for the arm refusing one written outside a span. */
const UNFENCED = new RegExp("(" + TEST_FILE + ")::", "g");

/**
 * A printf token, which is what vitest expands and an author copies.
 *
 * A citation has to be spelled the way the source writes the name, and what a
 * reader sees in a run is the expansion. Thirty three declared names in this
 * tree carry one, counted off the parse, and the orphan that bought this rule
 * was reported in its expanded form, so the rule as first written would have
 * refused the report that motivated it. Read on the miss path only, so nothing
 * that already resolves literally can move.
 */
const PRINTF = /%[sdifjo#]/;

/**
 * A repository path in the space a citation is written in.
 *
 * The code halves of the corpus are keyed `src/` and `tests/`, so a path under
 * the frontend tree loses that segment. One home, because a citation's target
 * and the key it has to find have both got to arrive here.
 */
const inCitationSpace = (path: string): string =>
  path.replace(/^frontend\//, "");

/** The cited path with `.` and `..` resolved, and the repository root off. */
function normalised(from: string, cited: string): string {
  const base = cited.startsWith(".") ? from.split("/").slice(0, -1) : [];
  return inCitationSpace(resolveSegments(base, cited).join("/"));
}

/**
 * A document's glob key, in the space a citation inside it resolves into.
 *
 * **Resolved rather than replaced, and that is the fix.** This was
 * `path.replace("../../", "")`, which is correct for every key the glob
 * reaches by climbing out of the directory it is written in and wrong for
 * every key it reaches without climbing. The two documents under the test tree
 * arrive `./COVERAGE.md` and `./doubles/README.md`, carry no prefix to strip,
 * and were handed to `normalised` as their own base: a citation at or below
 * such a document's own directory then resolved from the repository root, and
 * only a citation climbing back into the source tree was right, because the
 * stray segment is popped by the first `..`. None is written today, so this
 * was silent, and it cost a review seat a wrong expectation.
 */
const citationKey = (globKey: string): string =>
  inCitationSpace(repositoryPath(globKey));

/**
 * Every string constant a module holds, folded where folding is exact.
 *
 * A literal, a template with nothing interpolated, and a concatenation of
 * those: the three spellings a test name is written in here. Read off the
 * parse rather than matched out of the text, for the reason `withoutProse`
 * exists: a name inside a comment is not a node, so a stale name quoted in
 * prose cannot satisfy a citation to it.
 */
function constantsIn(source: string, lang: "ts" | "tsx"): Set<string> {
  const found = new Set<string>();

  const fold = (node: Node): string | null => {
    if (node.type === "Literal") return text(node.value);
    if (node.type === "TemplateLiteral") {
      const parts = node.expressions as unknown[];
      if (parts.length > 0) return null;
      return (node.quasis as Node[])
        .map(
          (quasi) => text((quasi.value as { cooked?: unknown }).cooked) ?? "",
        )
        .join("");
    }
    if (node.type === "BinaryExpression" && node.operator === "+") {
      const left = isNode(node.left) ? fold(node.left) : null;
      const right = isNode(node.right) ? fold(node.right) : null;
      return left === null || right === null ? null : left + right;
    }
    return null;
  };

  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      value.forEach(walk);
      return;
    }
    if (!isNode(value)) return;
    const folded = fold(value);
    if (folded !== null) found.add(folded);
    for (const key of Object.keys(value)) walk(value[key]);
  };

  walk(parseAst(source, { lang }) as unknown as Node);
  return found;
}

/**
 * The citations in `files` that resolve to nothing, as sentences.
 *
 * Pure and handed its whole world, so the probe below drives the same code the
 * rule does rather than a second implementation of it.
 *
 * **What is checked is that the name is still a string constant in the file
 * cited, which is weaker than that it is still a test's name**, and the
 * difference is stated rather than closed: a name that survives as some other
 * literal in that file satisfies this. Closing it means deciding which call is
 * a declaration, and the spellings are open, `each`, `only`, `skip`, `for` and
 * whatever the next version adds, so the arm would refuse a legitimate one
 * before it caught anything. The class this exists for is a rename, and a
 * rename takes the old string out of the file altogether.
 *
 * **An unqualified basename matching several files is checked against their
 * union.** One citation in the tree is of that shape. The lenient direction is
 * deliberate: a name found in a sibling satisfies it, and nothing here can
 * tell which of five files somebody meant.
 *
 * **A full name is split on the separator vitest joins with**, so a citation
 * naming an enclosing block and its arm is read as both rather than as one
 * name no call writes.
 *
 * **Three leniencies on the miss path.** A name matching no constant
 * literally is tried again against any constant whose printf tokens stand for
 * anything, so the expansion a reader copies out of a run resolves. A cited
 * path is resolved against the citing file when it is written relatively,
 * which is how every import in these files is written. And a single fenced
 * name that is a prefix of a real one is reported as **cut at a delimiter**
 * rather than as missing, because the fix is a second backtick and telling an
 * author their test is gone sends them the wrong way.
 *
 * **What the first of those accepts, stated rather than bounded.** A template
 * is a wildcard, so `reads %s` accepts `reads anything`, including names no
 * case in that table produces. That is the leniency being bought and it is
 * held in check only by the template's own fixed text, which is why
 * `isTemplate` refuses a constant that has none. An earlier version of this
 * paragraph claimed no leniency here could turn green a citation that was not
 * already pointing somewhere real; the bare token was its counterexample, and
 * the remedy is this sentence rather than a better claim.
 */
/**
 * Whether a constant is a template that still constrains what it matches.
 *
 * **A name that is nothing but a token is not a template, it is a hole.**
 * `"%s"` expands to an anchored match-anything, and since every string
 * constant in a cited file is tried, one such literal makes **every** citation
 * to that file resolve. Two files here declare exactly that name, this one and
 * `withoutProse.test.ts`, both as the label of an `each`, so the file the rule
 * lives in was the file it had stopped guarding: measured, renaming an arm
 * this file's own callers cite left the run green.
 *
 * **Non whitespace, not merely non empty**, which is the part worth deriving
 * rather than copying: `"%s %s"` keeps a space between its tokens and matches
 * any label containing a space, which is very nearly all of them. Measured
 * both ways against the string "literally any label at all", which `"%s"` and
 * `"%s %s"` accept and which `"reads %s"` refuses.
 */
function isTemplate(constant: string): boolean {
  return PRINTF.test(constant) && /\S/.test(constant.split(PRINTF).join(""));
}

/** One constant's printf tokens standing for anything, anchored whole. */
function expansionOf(constant: string): RegExp {
  return new RegExp(
    `^${constant
      .split(PRINTF)
      .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`))
      .join(String.raw`[\s\S]*`)}$`,
  );
}

/**
 * Every citation these files hold, read but not yet resolved.
 *
 * Split out so the diagonal below plants from the tree rather than from a
 * list written beside it. A citation added tomorrow is planted too.
 */
function citationsIn(
  files: Record<string, string>,
): { from: string; fence: string; cited: string; label: string }[] {
  const out: { from: string; fence: string; cited: string; label: string }[] =
    [];
  for (const [from, source] of Object.entries(files)) {
    CITATION.lastIndex = 0;
    // A citation spelled from the repository root, or relative to the citing
    // file, resolves the same way. Leniency in the direction that cannot
    // refuse a citation that is doing its job.
    for (const match of unwrapped(source).matchAll(CITATION))
      out.push({
        from,
        fence: match[1]!,
        cited: normalised(from, match[2]!),
        label: match[3]!,
      });
  }
  return out;
}

/**
 * The constant a name is read through, if any of them reads it.
 *
 * **One resolver, because two of them contradicted each other.** The rule
 * asked the parse and the wildcard; the plant below asked a raw text search
 * for the same thing. A citation written in the expanded form a run prints,
 * against a source declaring the template, resolves here and is held by no
 * text search, so the plant's accounting called a healthy citation a silent
 * dropout and reddened on it. Accepting that form is the whole reason the
 * wildcard exists, so the two rounds of machinery were refusing each other.
 *
 * Returning the constant rather than a boolean is what collapses them: the
 * plant needs to know **which** name to rename, and that is the same question
 * the rule answers to decide whether the citation reads at all.
 */
function resolvedBy(constants: Set<string>, part: string): string | undefined {
  if (constants.has(part)) return part;
  return [...constants].find(
    (one) => isTemplate(one) && expansionOf(one).test(part),
  );
}

function unwritten(files: Record<string, string>): string[] {
  const tests = Object.keys(files).filter((path) => IS_TEST.test(path));
  const constants = new Map<string, Set<string>>();
  const constantsOf = (path: string): Set<string> => {
    const had = constants.get(path);
    if (had) return had;
    const made = constantsIn(files[path] ?? "", langOf(path));
    constants.set(path, made);
    return made;
  };

  const found: string[] = [];
  for (const { from, fence, cited, label } of citationsIn(files)) {
    {
      const targets = tests.filter(
        (path) => path === cited || path.endsWith(`/${cited}`),
      );
      if (targets.length === 0) {
        // **The label belongs in this message even though nothing resolved
        // it.** Without it every citation from one document to one absent
        // path produces the same sentence, so the outstanding list below keys
        // on a class rather than an instance and one entry absorbs the next
        // dead citation written beside it. Measured: a second, new dead
        // citation to the same absent file survived. It also says which
        // sentence is waiting on repair, which the entry could not.
        found.push(
          `${from} names ${cited} for the test ${label}, ` +
            `and there is no such test file here`,
        );
        continue;
      }
      const written = new Set(
        targets.flatMap((path) => [...constantsOf(path)]),
      );
      if (
        label
          .split(" > ")
          .every((part) => resolvedBy(written, part) !== undefined)
      )
        continue;
      const cutShort = [...written].find(
        (one) => one !== label && one.startsWith(label),
      );
      found.push(
        fence === "`" && cutShort !== undefined
          ? `${from} names ${cited} and a name cut at a code span ` +
              `delimiter, "${label}": write it in a double fence`
          : `${from} names ${cited} and the test ${label}, unwritten`,
      );
    }
  }
  return found;
}

/**
 * Everything that can carry a citation: both code trees, this file, and the
 * documents.
 *
 * **The markdown is not an extra, it is the family the rule exists for.** The
 * reason written above is that the citing files publish and the mirror does
 * not unpublish, and `docs/` is the published prose. Left out of the first
 * version of this rule, and the cost was immediate: a citation there names a
 * test file that exists nowhere in the tree, it predates this branch, and it
 * is on the mirror now. That is the second of the two shapes this rule
 * reddens, and the rule could not see it.
 *
 * **A document declaring itself internal is not read**, by the same helper
 * and for the same reason the published prose rule above uses it: this rule's
 * subject is what reaches the mirror, and an internal document does not.
 *
 * **That is the whole of what the filter does, and the sentence here used to
 * claim more.** It said the filter also keeps out whatever an agent's working
 * directory holds. It does not: such a document is excluded only when it
 * carries the declaration, and measured against the gate's own pattern over
 * the eight documents in one, six are read. The exposure is the glob's rather
 * than this rule's, and the rule above reads the same six. The property that
 * would actually close it is what the repository versions, since an untracked
 * document reaches no mirror; `materialisedCopies` says why that is not
 * available to a test here and what closes the one shape of it that bit.
 *
 * **Named by the declaration rather than by directory on purpose.** The
 * publish gate refuses a published file that spells a stripped path, and this
 * file publishes, so the first version of this filter was rejected by the gate
 * for writing the directory's name.
 */
function citingFiles(): Record<string, string> {
  return {
    ...Object.fromEntries(
      entries().map(([path, source]) => [`src/${path}`, source]),
    ),
    ...Object.fromEntries(
      testEntries().map(([path, source]) => [
        path.replace("./", "tests/"),
        source,
      ]),
    ),
    ...Object.fromEntries(
      Object.entries(DOCUMENTS)
        .map(([path, source]): [string, string] => [citationKey(path), source])
        .filter(([, source]) => !declaresItselfInternal(source)),
    ),
  };
}

/**
 * The dead citations this branch is not allowed to repair, and their expiry.
 *
 * **`docs/decisions.md` is a shared register**, and the working agreement for
 * this wave is that a branch drafts against one and never edits it, because
 * several branches would otherwise write the same file. So the entry sits
 * here, in the rule, where it is read on every run, rather than as a sentence
 * somebody has to find.
 *
 * **It is a ratchet and not a suppression list**, which is the difference the
 * oxlint config's own two lists turn on: the arm below fails when an entry
 * stops describing something live, so this cannot outlive the repair. The
 * label that citation means is written in
 * `AboutSettingsPage.test.tsx`, under a name the file no longer has.
 */
const NOT_OURS_TO_REPAIR: string[] = [];

describe("a test cited by name still carries that name", () => {
  /**
   * **Bought by a live one, on the branch that added this.** Two files pointed
   * at an arm in the card's suite by name. The arm was renamed when it grew
   * from one reading status to every one, the two pointers did not move, and
   * both of those files publish while the mirror does not unpublish. So a
   * pointer to a test that no longer exists shipped.
   *
   * **Nothing was going to catch it and the backend guard says so itself.**
   * The name anchor guard over there states in its own docstring that a vitest
   * label is outside its population by spelling, neither covered nor refused,
   * and that closing it belongs to the house rules here. It is named rather
   * than linked because the publish gate strips it and refuses a published
   * file that spells a stripped path: this sentence cited it by path in its
   * first draft and the gate rejected the tree, which is the second thing on
   * this branch found by the check rather than by the author. A green backend
   * suite is silent about this class, which is the worst shape a gap can have:
   * a guard next door that looks like it covers you.
   *
   * ## What this rule sees, and what goes past it
   *
   * **A narrowing is a decision; a hole is a thing nobody has closed.** Kept
   * apart on purpose: the first list is not work waiting, the second is.
   *
   * **Seen.** A citation in a code span, of one or two backticks, naming a
   * path ending in the suffix the config collects tests by, in either code
   * tree, in this file, and in the published documents. The path resolved
   * exactly or by suffix, relative segments resolved against the citing file,
   * a repository root prefix stripped. The name matched against the string
   * constants of the cited file's parse, folding a template with nothing
   * interpolated and a concatenation of literals, and against a printf
   * template's expansion. A full name split on the separator vitest joins
   * with.
   *
   * **Narrowed on purpose.**
   *
   * - **A constant, not a test's name.** A name surviving as some other
   *   literal in the cited file satisfies this. Deciding which call is a
   *   declaration means enumerating spellings that are open, and the arm
   *   would refuse a legitimate one before it caught anything.
   * - **An ambiguous basename is checked against the union** of the files it
   *   could mean. Nothing here can tell which one somebody meant.
   * - **A template is a wildcard**, so `reads %s` accepts `reads anything`,
   *   including names no case in that table produces. It is bounded only by
   *   the template's own fixed text, which is why a constant with none is
   *   not treated as a template at all.
   * - **A document declaring itself internal is not read**, because the
   *   subject is what reaches the mirror.
   *
   * **Open, and these are holes.**
   *
   * - **A citation inside a fenced code block reads as unfenced** and is
   *   reported by the arm below rather than resolved, because the unwrapper
   *   joins the fence line to the next. None today; the documents are in the
   *   population now, where code blocks are ordinary.
   * - **An untracked document that does not declare itself internal is
   *   read.** Measured over one working directory: six of eight. What would
   *   close it is what the repository versions, and that is a change to a
   *   glob three rules share rather than to this one.
   * - **One dead citation is outstanding rather than repaired**, in a shared
   *   register this branch may not edit, carried below with a ratchet.
   */
  it("leaves no cited test name unwritten", () => {
    expect(
      unwritten(citingFiles()).filter(
        (one) => !NOT_OURS_TO_REPAIR.includes(one),
      ),
    ).toEqual([]);
  });

  it("keeps no entry that has stopped describing a live one", () => {
    // What makes the list above a ratchet. Without this an entry outlives the
    // repair it is waiting on, and the rule is then quiet about a shape it
    // reddens everywhere else.
    const live = unwritten(citingFiles());

    expect(NOT_OURS_TO_REPAIR.filter((one) => !live.includes(one))).toEqual([]);
  });

  it("is reading citations in all three families, not an empty set", () => {
    // A pattern whose subject was respelled passes by matching nothing, which
    // is how this file's column rule once passed while asserting the opposite
    // of what it meant. All three, because the documents were the family left
    // out of the first version and the only one carrying a live defect.
    const citing = Object.entries(citingFiles())
      .filter(([, source]) => {
        CITATION.lastIndex = 0;
        return CITATION.test(unwrapped(source));
      })
      .map(([path]) => path);
    CITATION.lastIndex = 0;

    expect(citing.length).toBeGreaterThan(5);
    expect(citing.some((path) => path.startsWith("src/"))).toBe(true);
    expect(citing.some((path) => path.startsWith("tests/"))).toBe(true);
    expect(citing.some((path) => path.endsWith(".md"))).toBe(true);
  });

  it("refuses a citation written outside a code span", () => {
    // **The gap the span requirement opens, converted from silent to loud.**
    // A dead citation with no span was reported as nothing at all, which is
    // the worst of the three outcomes: the rule is not merely unable to
    // resolve it, it never sees it. Costs nothing today, counted over the
    // versioned tree: every citation in the repository is already fenced.
    //
    // **A citation inside a fenced code block reports here**, because the
    // unwrapper joins the fence line to the next one and the span delimiters
    // stop lining up. None today, and the documents are now in the population
    // where code blocks are ordinary, so the next author to hit it is being
    // told the fix rather than left to hunt: write the citation inline, in a
    // span of its own.
    const loose = Object.entries(citingFiles()).flatMap(([path, source]) => {
      const flat = unwrapped(source);
      CITATION.lastIndex = 0;
      const spans = [...flat.matchAll(CITATION)].map(
        (match) => [match.index, match.index + match[0].length] as const,
      );
      UNFENCED.lastIndex = 0;
      return [...flat.matchAll(UNFENCED)]
        .filter(
          (match) =>
            !spans.some(
              ([from, to]) => from <= match.index && match.index < to,
            ),
        )
        .map((match) => `${path}: ${match[1]}`);
    });

    expect(loose).toEqual([]);
  });

  it("is built for the suffix the config still collects tests by", () => {
    // **The suffix was written out three times and read from nowhere.** A
    // `.spec` include added to the config would leave this rule reading a
    // shrinking tree with nothing red anywhere, which is the shape of a guard
    // that stops guarding without failing. One spelling now, checked here
    // against the config that decides it.
    expect(viteConfig).toContain('include: ["tests/**/*.test.{ts,tsx}"]');
    expect(IS_TEST.test("tests/theme/palettes.test.ts")).toBe(true);
    expect(IS_TEST.test("tests/theme/palettes.spec.ts")).toBe(false);
  });

  it("is reading this file, which is where its own subject lives", () => {
    // Unlike the address rule above, this one is not exempt from itself: vite
    // keeps the importing module out of its own glob, so the source is added
    // back by hand and the file is an ordinary member. It has to be, because
    // it carries a citation of its own. What lets the probe below write the
    // shape without asserting it is the code span, not an exemption.
    expect(Object.keys(citingFiles())).toContain("tests/houseRules.test.ts");
  });

  it("reports the shapes it exists for", () => {
    // **Assembled rather than written out**, so none of these is a citation in
    // this file's own source and the rule above reads this file for real.
    const cite = (path: string, label: string) =>
      "`" + path + "::" + label + "`";
    const probe = (test: string, comment: string) =>
      unwritten({
        "tests/a.test.ts": test,
        "src/x.ts": `// ${comment}\nexport const x = 1;`,
      });

    // The two it is for. A renamed arm, which is the live one, and a cited
    // file that is not there.
    expect(
      probe(
        `it("the new name", () => {});`,
        cite("tests/a.test.ts", "the old name"),
      ),
    ).toEqual([
      "src/x.ts names tests/a.test.ts and the test the old name, unwritten",
    ]);
    expect(
      probe(
        `it("still here", () => {});`,
        cite("tests/gone.test.ts", "still here"),
      ),
    ).toEqual([
      "src/x.ts names tests/gone.test.ts for the test still here, " +
        "and there is no such test file here",
    ]);

    // And the legitimate spellings, every one of which a stricter reading
    // refuses. A rule that refuses these is worse than none, because the next
    // author deletes it rather than obeying it.
    const accepted: [string, string][] = [
      [`it.each([[1, 2]])("labels %s as %s", () => {});`, "labels %s as %s"],
      [
        `it("a label written " + "in two halves", () => {});`,
        "a label written in two halves",
      ],
      [`it(\`a template label\`, () => {});`, "a template label"],
      [
        `it.each([{ n: 1 }])("handles $n cleanly", () => {});`,
        "handles $n cleanly",
      ],
      [
        `const NAME = "a hoisted label"; it(NAME, () => {});`,
        "a hoisted label",
      ],
      [`describe("outer", () => { it("inner", () => {}); });`, "outer > inner"],
      [`describe("outer", () => { it("inner", () => {}); });`, "inner"],
    ];
    for (const [test, label] of accepted)
      expect(probe(test, cite("tests/a.test.ts", label))).toEqual([]);
  });

  it("resolves a name a reader copied out of a run", () => {
    // The expansion, not the template. Thirty three declared names here carry
    // a printf token, and the orphan this rule was bought by was reported to
    // its author in exactly this form, so a rule refusing it would have
    // refused the report that motivated it.
    const cite = (path: string, label: string) =>
      "`" + path + "::" + label + "`";
    const declared = `it.each(["a"])("draws the %s pill", () => {});`;
    const probe = (label: string) =>
      unwritten({
        "tests/a.test.ts": declared,
        "src/x.ts": `// ${cite("tests/a.test.ts", label)}\nexport const x = 1;`,
      });

    expect(probe("draws the unread pill")).toEqual([]);
    expect(probe("draws the %s pill")).toEqual([]);
    // And it is a wildcard rather than a hole: the rest still has to match.
    expect(probe("paints the unread pill")).toEqual([
      "src/x.ts names tests/a.test.ts and the test paints the unread pill, unwritten",
    ]);
  });

  it("reads a name carrying a delimiter of its own, in a double fence", () => {
    // Four names in this tree hold one. Under a single fence the label stops
    // there and the rule names something nobody wrote, so a correct citation
    // is refused and an unrelated sentence has to be rewritten to publish.
    const label = "counts the `n` rows";
    const declared = `it(${JSON.stringify(label)}, () => {});`;
    // Assembled, path and separator included, for the reason the arm above
    // enforces: written out, this fixture is an unfenced citation in this
    // file's own source, and that arm reddened on it.
    const probe = (fence: string) =>
      unwritten({
        "tests/a.test.ts": declared,
        "src/x.ts":
          "// " +
          fence +
          "tests/a.test.ts" +
          "::" +
          label +
          fence +
          "\nexport const x = 1;",
      });

    expect(probe("``")).toEqual([]);
    // The single fence cannot carry it, and says which fix is wanted rather
    // than reporting a test that is right there as gone.
    expect(probe("`")).toEqual([
      "src/x.ts names tests/a.test.ts and a name cut at a code span " +
        'delimiter, "counts the ": write it in a double fence',
    ]);
  });

  it("refuses a name that is only a token, which resolved everything", () => {
    // **The hole the wildcard opened, and it is not hypothetical here.** Two
    // files declare `%s` as the label of an `each`, this one among them, and
    // every string constant of a cited file is tried, so one such name made
    // every citation to that file resolve. The file the rule lives in was the
    // file it had stopped guarding.
    const cite = (path: string, label: string) =>
      "`" + path + "::" + label + "`";
    const probe = (declared: string, label: string) =>
      unwritten({
        "tests/a.test.ts": declared,
        "src/x.ts": `// ${cite("tests/a.test.ts", label)}\nexport const x = 1;`,
      });
    const gone = [
      "src/x.ts names tests/a.test.ts and the test a name nobody wrote, unwritten",
    ];
    const holes = [
      `it.each(["a"])("%s", () => {});`,
      `it.each(["a"])("%s %s", () => {});`,
    ];

    for (const hole of holes) {
      const declared = `${hole} it("the real name", () => {});`;
      expect(probe(declared, "the real name")).toEqual([]);
      expect(probe(declared, "a name nobody wrote")).toEqual(gone);
    }
    // Non whitespace rather than non empty, which is the half worth deriving:
    // a name almost always holds a space, so a fixed part that is only a
    // space constrains nothing.
    expect(isTemplate("%s")).toBe(false);
    expect(isTemplate("%s %s")).toBe(false);
    expect(isTemplate("reads %s")).toBe(true);
  });

  // **The timeout is explicit because the default is not a measurement.** This
  // arm re runs `unwritten()` over the whole file set once per citation, so it
  // costs citations times files and grows with the tree rather than staying
  // put. Measured 2026-09-29 in isolation on the eight core worker: 1,863 ms,
  // which is the figure the comment below quotes. Under the full parallel run
  // on the four core worker it went past the 5,000 ms default, reproducibly,
  // two runs of two there against zero of two on the other node, which is why
  // the number here is not a node's timing plus a margin.
  //
  // **30 seconds is chosen to survive ordinary growth, not to sit above
  // today's cost.** A number close to the measurement re breaks on the next
  // wave that adds citations, and the failure it produces says `timed out`
  // rather than naming a rule, which reads as a defect in the tree. The cost
  // to a healthy run is nothing, because the arm never waits.
  //
  // **A red here also suppresses the coverage register**, whose reporter
  // returns early unless the run passed, so a timeout costs a silent check
  // as well as this one. That is the reason this is pinned rather than left
  // to the default.
  it(
    "reddens on a rename of any name this tree cites",
    { timeout: 30_000 },
    () => {
      // **The cheapest diagonal in the file, and the one that caught the bare
      // token.** Every citation the tree actually holds, planted one at a time
      // by renaming the name it is read through, which is exactly the class
      // this rule exists for. Derived from the tree rather than from a list, so
      // a citation added tomorrow is planted too.
      //
      // **It finds that name through the parse, using the rule's own
      // resolver.** It used to search the source text for the label, which is a
      // second answer to a question the rule had already answered differently:
      // a citation written in the form a run prints, against a source declaring
      // the template, resolves for the rule and is invisible to a text search,
      // so the accounting below called a healthy citation a dropout and went
      // red on it. Sharing `resolvedBy` makes that a plant instead, and the
      // silent skip the accounting was added to name cannot occur, because a
      // citation the rule can read is by construction one this can rename.
      //
      // **It is the slowest arm here, about a second and a half, and that is
      // the price of the instrument rather than an accident.** Trimming it to a
      // sample would leave the rule certified by whichever citations the sample
      // happened to take.
      //
      // **Accounted against the population, never against a floor.** This said
      // `planted.length` was above five while planting 22 of 23, so sixteen
      // citations could have stopped being planted with nothing red.
      const files = citingFiles();
      const all = citationsIn(files);
      const tests = Object.keys(files).filter((path) => IS_TEST.test(path));
      const reported = unwritten(files);
      const constants = new Map<string, Set<string>>();
      const constantsOf = (path: string): Set<string> => {
        const had = constants.get(path);
        if (had !== undefined) return had;
        const made = constantsIn(files[path] ?? "", langOf(path));
        constants.set(path, made);
        return made;
      };

      const planted: string[] = [];
      const unreadable: typeof all = [];
      const selfCited: string[] = [];
      const survived: string[] = [];

      for (const one of all) {
        const targets = tests.filter(
          (path) => path === one.cited || path.endsWith(`/${one.cited}`),
        );
        // Every name, in every file, the citation is read through. All of them,
        // because a basename matching several files resolves against their
        // union, so renaming one copy would leave the citation reading another
        // and this arm would call a working plant a survival.
        const through = one.label.split(" > ").flatMap((part) =>
          targets.flatMap((path) => {
            const constant = resolvedBy(constantsOf(path), part);
            return constant === undefined
              ? []
              : [[path, constant] as [string, string]];
          }),
        );
        const readable = one.label
          .split(" > ")
          .every((part) =>
            targets.some((path) => resolvedBy(constantsOf(path), part)),
          );

        if (!readable) {
          unreadable.push(one);
          continue;
        }
        if (through.some(([path]) => path === one.from)) {
          selfCited.push(`${one.from} to ${one.cited}`);
          continue;
        }
        planted.push(`${one.from} to ${one.cited}`);
        const renamed = { ...files };
        for (const [path, constant] of through)
          renamed[path] = renamed[path]!.split(constant).join(
            "a name nobody wrote",
          );
        if (!unwritten(renamed).some((report) => report.includes(one.label)))
          survived.push(`${one.from} to ${one.cited}`);
      }

      expect(survived).toEqual([]);
      // Nothing falls out of the walk unaccounted for.
      expect(planted.length + unreadable.length + selfCited.length).toBe(
        all.length,
      );
      // A citation this cannot plant is one the rule cannot read, so the rule
      // is already reporting it. Both sides now answer through `resolvedBy`, so
      // this is the two branches agreeing rather than one instrument checking
      // another, and what it still catches is a classification drifting apart
      // from the message it produces.
      expect(
        unreadable
          .filter(
            (one) => !reported.some((report) => report.includes(one.label)),
          )
          .map((one) => `${one.from} to ${one.cited}`),
      ).toEqual([]);
      // A file citing a name it declares itself would need a different plant,
      // since renaming the declaration rewrites the citation with it. None
      // today, and one appearing is worth reading rather than skipping.
      expect(selfCited).toEqual([]);
    },
  );

  it("is watching a population that has not collapsed", () => {
    // **The only absolute number this describe holds, and it has to exist
    // before the outstanding entry below leaves.** That entry is currently
    // the one arm that reddens if the citations come back empty: the
    // resolution arm and the plant arm both pass over an empty population and
    // the fixture arms drive maps written here. The merge repairs the
    // register and removes the entry in the same commit, and the backstop
    // would leave with it.
    //
    // **Counted on citations rather than on citing files**, because one file
    // can carry several and the file count is the looser of the two. 23 over
    // the versioned tree today. The floor is set for a collapse, a glob that
    // stops matching or a pattern respelled, and **not** for erosion: it says
    // nothing about citations disappearing a few at a time, and nothing here
    // does.
    expect(citationsIn(citingFiles()).length).toBeGreaterThan(10);
  });

  it("keeps one outstanding citation from covering the next one", () => {
    // **The entry was keyed on a message carrying no label**, so every
    // citation from one document to one absent path produced the same
    // sentence and one entry filtered all of them. Measured: a second, new
    // dead citation to the same absent file survived, in the largest register
    // in the repository, which is where citations are written.
    const cite = (path: string, label: string) =>
      "`" + path + "::" + label + "`";

    expect(
      unwritten({
        "tests/a.test.ts": `it("the real name", () => {});`,
        "docs/notes.md":
          cite("gone.test.ts", "one name") +
          " and " +
          cite("gone.test.ts", "another name"),
      }),
    ).toEqual([
      "docs/notes.md names gone.test.ts for the test one name, " +
        "and there is no such test file here",
      "docs/notes.md names gone.test.ts for the test another name, " +
        "and there is no such test file here",
    ]);
  });

  it("resolves a path written the way an import here is written", () => {
    const cite = (path: string, label: string) =>
      "`" + path + "::" + label + "`";

    expect(
      unwritten({
        "tests/theme/a.test.ts": `it("the name", () => {});`,
        "src/pages/x.ts": `// ${cite("../../tests/theme/a.test.ts", "the name")}\nexport const x = 1;`,
      }),
    ).toEqual([]);
    expect(
      unwritten({
        "tests/theme/a.test.ts": `it("the name", () => {});`,
        "docs/notes.md": cite("../frontend/tests/theme/a.test.ts", "the name"),
      }),
    ).toEqual([]);
  });

  it("resolves a citation written inside a document under the test tree", () => {
    // **The two documents the glob reaches without climbing out of its own
    // directory**, keyed here through `citationKey` rather than written out,
    // so this reds if that resolution regresses rather than agreeing with a
    // literal somebody kept up to date.
    //
    // **The first case is the one that was wrong and the second is the one
    // that was not.** A citation at or below such a document's own directory
    // used to resolve from the repository root; a citation climbing back into
    // the source tree landed correctly anyway, because the stray segment is
    // popped by the first `..`. Both are here so the repair is not credited
    // for the half it did not change.
    const cite = (path: string, label: string) =>
      "`" + path + "::" + label + "`";
    const home = citationKey("./doubles/README.md");

    expect(
      unwritten({
        "tests/doubles/a.test.ts": `it("the name", () => {});`,
        [home]: cite("./a.test.ts", "the name"),
      }),
    ).toEqual([]);
    expect(
      unwritten({
        "tests/theme/a.test.ts": `it("the name", () => {});`,
        [home]: cite("../../../frontend/tests/theme/a.test.ts", "the name"),
      }),
    ).toEqual([]);
  });

  it("reads a citation the formatter wrapped, at any depth", () => {
    // The shape that makes a line by line scan report clean over a tree it
    // never read. Three lines, because two is what an author writes on purpose
    // and three is what the reflow produces without being asked.
    //
    // **Assembled, and this arm is why that rule is written down.** Its first
    // draft spelled the opening of the citation in a string literal, which put
    // a real citation in this file's own source pointing at a fixture that
    // does not exist, and the rule above went red naming it. Caught by the
    // thing it is testing, which is the only reason it is not still there.
    const label = "a name long enough that the reflow puts it on its own lines";
    const words = ("`" + "tests/a.test.ts" + "::" + label + "`").split(" ");
    const wrapped = [
      "/**",
      " * see " + words.slice(0, 5).join(" "),
      " * " + words.slice(5, 9).join(" "),
      " * " + words.slice(9).join(" ") + " for the rest.",
      " */",
      "export const x = 1;",
    ].join("\n");

    expect(
      unwritten({
        "tests/a.test.ts": `it(${JSON.stringify(label)}, () => {});`,
        "src/x.ts": wrapped,
      }),
    ).toEqual([]);
  });

  it("leaves everything else spelled with two colons alone", () => {
    // The false refusal that would have made this rule unlivable: the tree
    // cites a source module's export, and a backend test's class, in the same
    // shape. Neither is a vitest label and neither is read here.
    const cite = (path: string, label: string) =>
      "`" + path + "::" + label + "`";

    expect(
      unwritten({
        "tests/a.test.ts": `it("only this", () => {});`,
        "tests/helper.ts": `export const thing = 1;`,
        "src/x.ts":
          `// ${cite("tests/helper.ts", "thing")} and ` +
          `${cite("src/lib/kobo.ts", "isTrue")} and ` +
          `${cite("backend/tests/test_shelf.py", "TestTheShelfIsTheOnlyWayIn")}\n` +
          `export const x = 1;`,
      }),
    ).toEqual([]);
  });
});

/**
 * Every pattern an `import.meta.glob` call in this file is given.
 *
 * **Read off the syntax rather than matched in the text, because a text match
 * was beaten by two spellings already in this tree.** The first version
 * anchored on the call followed by a double quote. Driven against four
 * spellings, it read one: the array form, which two calls here already use
 * and one of those already points into `src/`, and a backticked pattern both
 * walked past it, and a blind matcher is silent rather than loud. The backend
 * paid for the same lesson twice and its own guards record it: read the shape
 * off the node, never the text.
 *
 * **An argument this cannot read comes back as the empty string, and the
 * silence is the bundler's rather than this rule's.** It takes a literal, or
 * an array of them, and nothing else: measured by handing it an identifier,
 * which fails at transform time with `Invalid glob import syntax: Could only
 * use literals` and takes the file out of the run. So a pattern this cannot
 * see is a pattern that does not run, which is an enforced limit rather than
 * a stated one, and is why no arm chases it.
 *
 * **The raw text of a template, not the cooked value**, which is what the
 * bundler itself reads. They differ only on a backslash escape inside a
 * template, and taking the cooked one errs toward flagging rather than
 * toward silence, but exact is cheaper than a sentence explaining the
 * direction.
 */
function globPatterns(source: string, lang: "ts" | "tsx"): string[] {
  const out: string[] = [];
  const patternsOf = (node: unknown): string[] => {
    if (!isNode(node)) return [];
    if (node.type === "Literal") {
      const value = text(node.value);
      return value === null ? [] : [value];
    }
    if (node.type === "TemplateLiteral") {
      const parts = (node.quasis as Node[] | undefined) ?? [];
      if (parts.length !== 1) return [""];
      const raw = (parts[0]!.value as { raw?: unknown }).raw;
      return [text(raw) ?? ""];
    }
    if (node.type === "ArrayExpression")
      return ((node.elements as unknown[]) ?? []).flatMap(patternsOf);
    return [""];
  };
  const walk = (value: unknown): void => {
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
      callee.object.type === "MetaProperty" &&
      isNode(callee.property) &&
      callee.property.name === "glob"
    )
      out.push(...patternsOf(((value.arguments as unknown[]) ?? [])[0]));
    for (const key of Object.keys(value)) walk(value[key]);
  };
  walk(parseAst(source, { lang }));
  return out;
}

/**
 * Whether a pattern written in one file can match a module under `src/`.
 *
 * **Resolved rather than spelled**, because a pattern need not name the
 * directory it reaches: `../**` written in `tests/` arrives at the frontend
 * root and descends into `src/` without the word appearing anywhere.
 *
 * **A wildcard is what makes a pattern a corpus.** A glob naming one module
 * answers for that module or for nothing; `namesOneFileIn` below owns that
 * case and says what it is really worth. A glob with a `*` or a brace in it
 * answers for whatever the pattern reaches, and narrowing one is how a rule
 * comes to report nothing over a tree that still holds the violation.
 *
 * **A brace with no star is a glob and was read by neither half.** This
 * returned early on the missing star and `namesOneFileIn` returns early on
 * the brace, so `../{src,public}/lib/pdf.ts` was silent in both. One token,
 * and the brace loop below already handles it: checked against every row of
 * the table driving this function, no `misses` row carries a brace without a
 * star, so the table is unmoved and two rows are added for the new case.
 * None exists in the tree today.
 *
 * **What it deliberately does not flag**: a pattern whose own last segment
 * admits no module or stylesheet suffix. `../../**\/*.md` from this file
 * reaches the root and descends everywhere, and it cannot match a module. A
 * suffix list is an enumeration, so it is the same list the corpus itself is
 * stated with and goes stale with it rather than on its own.
 *
 * **What it newly over flags, which is the half worth stating**: a brace in a
 * directory position is read as able to name the source tree, so one that
 * cannot, `../{public,assets}/*.ts`, is reported. None exists today, checked
 * over every pattern the tree writes, and the direction is loud rather than
 * silent.
 *
 * **And one shape no reader of a pattern can ever see**: a `base` option
 * resolves the pattern against a directory of its own, so `./**\/*.ts` with
 * `base: "../src"` reaches the tree while this answers false and is right
 * about the argument it was given. That is refused at the input instead, by
 * the arm below that holds the option keys to the three this tree uses.
 */
/** The suffixes the two corpus modules can hand a reader. */
const SERVED = ["*", "ts", "tsx", "css"];

/**
 * Whether a pattern's own last segment admits a file either corpus serves.
 *
 * **The last dot, not the first.** `*.d.ts` read from the first dot is the
 * one token `d.ts`, which no suffix list holds, so every declaration file
 * pattern answered false. Two such files are in the corpus this guards.
 */
function servesAModule(pattern: string): boolean {
  const last = pattern.split("/").pop()!;
  const suffixes = last.includes(".")
    ? last
        .slice(last.lastIndexOf(".") + 1)
        .replace(/[{}]/g, "")
        .split(",")
    : ["*"];
  return suffixes.some((one) => SERVED.includes(one));
}

/**
 * Where a pattern written in one file lands, and whether it can go deeper.
 *
 * **One home, because copying it bought a defect already**: the brace with no
 * star was invisible to both readers precisely because each wrote its own
 * early returns beside its own copy of this walk. What is shared is the
 * resolution and nothing else: the suffix gate, the wildcard test and what
 * each caller does with `descends` stay at the call sites, which is where
 * they differ.
 *
 * **A leading slash is the project root, not a segment of the importer.** It
 * is the shortest correct way to spell a tree and the first thing somebody
 * reaches for when the dots get long.
 *
 * **A brace in a directory position is a wildcard**, because one of its
 * branches can be the tree: `../{src,public}/*.ts` reaches it by expansion
 * while reading as a literal directory named `{src,public}`.
 */
function resolveFrom(
  from: string,
  pattern: string,
): { at: string[]; descends: boolean } {
  const segments = pattern.split("/");
  const at: string[] = pattern.startsWith("/")
    ? []
    : ["tests", ...from.replace("./", "").split("/")].slice(0, -1);
  let descends = false;
  for (const [index, part] of segments.entries()) {
    if (part.includes("*") || part.includes("{")) {
      descends = index < segments.length - 1;
      break;
    }
    if (part === "." || part === "") continue;
    if (part === "..") at.pop();
    else at.push(part);
  }
  return { at, descends };
}

/** Whether a pattern written in one file can match a module under `tree`. */
function reachesTheTree(from: string, pattern: string, tree: string): boolean {
  if (pattern === "" || pattern.startsWith("!")) return false;
  if (!pattern.includes("*") && !pattern.includes("{")) return false;
  if (!servesAModule(pattern)) return false;

  const { at, descends } = resolveFrom(from, pattern);
  const base = at.join("/");

  // Both trees sit directly under the project root, so the root is their only
  // ancestor and a walk that stopped above one reaches it only by descending.
  return (
    base === tree || base.startsWith(`${tree}/`) || (base === "" && descends)
  );
}

function reachesTheSourceTree(from: string, pattern: string): boolean {
  return reachesTheTree(from, pattern, "src");
}

/**
 * The same question about `tests/`, which had no asker at all.
 *
 * Three rules each carried a pattern over this tree and the extraction into
 * one home shipped without the ratchet that keeps them there, so a fourth
 * home was free. What this closes, and what it still allows, is at the rule
 * below.
 */
function reachesTheTestTree(from: string, pattern: string): boolean {
  return reachesTheTree(from, pattern, "tests");
}

/**
 * The option keys every `import.meta.glob` call in one file passes.
 *
 * Read off the same node as the pattern, because the option that matters
 * cannot be seen from the pattern at all: `base` resolves it against a
 * directory of its own.
 */
function globOptionKeys(source: string, lang: "ts" | "tsx"): string[] {
  const out: string[] = [];
  const walk = (value: unknown): void => {
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
      callee.object.type === "MetaProperty" &&
      isNode(callee.property) &&
      callee.property.name === "glob"
    ) {
      const options = ((value.arguments as unknown[]) ?? [])[1];
      if (isNode(options) && options.type === "ObjectExpression")
        for (const property of (options.properties as unknown[]) ?? []) {
          if (!isNode(property)) continue;
          const key = property.key;
          const name = isNode(key) ? (text(key.name) ?? text(key.value)) : null;
          out.push(name ?? "an option this rule could not read");
        }
    }
    for (const key of Object.keys(value)) walk(value[key]);
  };
  walk(parseAst(source, { lang }));
  return out;
}

/** Every file in the test tree writing a pattern that reaches a tree. */
const homesOver = (reaches: (from: string, pattern: string) => boolean) =>
  testEntries()
    .filter(([path, source]) =>
      globPatterns(source, langOf(path)).some((pattern) =>
        reaches(path, pattern),
      ),
    )
    .map(([path]) => path)
    .sort();

/**
 * The files permitted to write a pattern over each tree, stated once.
 *
 * At module scope because three arms compare against them and a fourth
 * compares them against the keys of `CORPUS_HOMES` below. Written out twice
 * is how a permitted home comes to be named in one place and not the other.
 *
 * `./sourceModules.ts` and `./testModules.ts` are the two homes.
 * `./sourceModules.test.ts` and `./testModules.test.ts` hold the patterns
 * the rules used to carry, deliberately outside the module each checks,
 * because an enumeration checked only by its own neighbours is checked by
 * nothing when one diff narrows them together. `./api/invalidate.test.ts`
 * globs the generated endpoint modules as values rather than as text, which
 * is not what that module serves, and its own comment says why its pattern
 * stops at one directory level.
 */
const SOURCE_CORPUS_HOMES = [
  "./api/invalidate.test.ts",
  "./sourceModules.test.ts",
  "./sourceModules.ts",
];
const TEST_CORPUS_HOMES = ["./testModules.test.ts", "./testModules.ts"];

describe("the corpus under src has one pattern", () => {
  const corpusPatterns = (): string[] => homesOver(reachesTheSourceTree);

  it("reads a pattern however the call spells it", () => {
    // **The instrument, driven, because its first version read one of these
    // four.** Each is a spelling Vite accepts, two of them are written in
    // this tree today, and a matcher blind to one reports nothing while the
    // equality below still holds on the three it can see.
    const probe = [
      'const a = import.meta.glob("../src/**/*.ts");',
      'const b = import.meta.glob(["../src/**/*.tsx", "!../src/x.ts"]);',
      "const c = import.meta.glob(`../src/**/*.css`);",
      "const d = import.meta.glob(`../src/${name}/*.ts`);",
    ].join("\n");

    expect(globPatterns(probe, "ts")).toEqual([
      "../src/**/*.ts",
      "../src/**/*.tsx",
      "!../src/x.ts",
      "../src/**/*.css",
      "",
    ]);
  });

  it("asks where a pattern lands rather than whether it spells the tree", () => {
    // **Four families of this were wrong and every error was a silent
    // miss**, which is the direction that costs: a pattern that reaches the
    // tree and answers false is a rule nobody is holding. Each row below is
    // one of them or its control, and the table is the arm rather than the
    // prose above it.
    const reaches: [string, string][] = [
      // The ordinary spelling, from two depths.
      ["./lib/x.test.ts", "../../src/**/*.ts"],
      ["./x.test.ts", "../src/**/*.{ts,tsx}"],
      // Reaching the tree without naming it.
      ["./x.test.ts", "../**/*.ts"],
      ["./x.test.ts", "../*/**/*.ts"],
      // Root relative, which is the shortest correct way to say it.
      ["./lib/x.test.ts", "/src/**/*.ts"],
      ["./x.test.ts", "/src/lib/*.ts"],
      // A brace naming the tree among others, by expansion.
      ["./x.test.ts", "../{src,public}/**/*.ts"],
      ["./x.test.ts", "../{src,public}/*.ts"],
      // Declaration files, which the suffix read from the first dot missed.
      ["./x.test.ts", "../src/**/*.d.ts"],
      ["./x.test.ts", "/src/**/*.d.ts"],
      // The stylesheet half of the corpus.
      ["./theme/x.test.ts", "../../src/**/*.css"],
      // The known over flag: a brace that cannot name the tree.
      ["./x.test.ts", "../{public,assets}/**/*.ts"],
      // **A brace with no star**, which was read by neither half: this one
      // returned early on the missing star and the one file reader returns
      // early on the brace. One row per tree position it can take.
      ["./x.test.ts", "../{src,public}/lib/pdf.ts"],
      ["./lib/x.test.ts", "../../{src,dist}/index.css"],
    ];
    const misses: [string, string][] = [
      // No wildcard, so it answers for one module or for nothing.
      ["./x.test.ts", "../src/lib/zip.ts"],
      ["./lib/x.test.ts", "../../src/index.css"],
      // The test tree, which is a different corpus.
      ["./x.test.ts", "./**/*.{ts,tsx}"],
      ["./lib/x.test.ts", "./*.test.ts"],
      // Reaching the root and descending, but admitting no module.
      ["./x.test.ts", "../../**/*.md"],
      ["./theme/x.test.ts", "../../../docs/*.md"],
      // A sibling of the tree rather than the tree.
      ["./x.test.ts", "../public/**/*"],
      // An exclusion, which narrows a pattern rather than being one.
      ["./x.test.ts", "!../src/**/*.ts"],
      // The frontend root with no descent, which is not the tree.
      ["./x.test.ts", "../*.ts"],
      // Unreadable, which the bundler refuses before this ever sees it.
      ["./x.test.ts", ""],
    ];

    expect(
      reaches.filter(([from, pattern]) => !reachesTheSourceTree(from, pattern)),
      "a pattern that reaches the source tree and is answered false",
    ).toEqual([]);
    expect(
      misses.filter(([from, pattern]) => reachesTheSourceTree(from, pattern)),
      "a pattern that reaches nothing under src and is answered true",
    ).toEqual([]);
  });

  it("is passed only the options this tree has decided on", () => {
    // **The one shape no reader of a pattern can see.** `base` resolves the
    // pattern against a directory of its own, so `./**/*.ts` with
    // `base: "../src"` walks the source tree while every arm above answers
    // correctly about the argument it was given. Nothing read off the first
    // argument can ever catch that, so it is refused at the input.
    //
    // **An equality over a derived set**, which is the idiom the rule below
    // uses and for the same reason: an empty offender list is also what a
    // reader that stopped reading produces.
    //
    // **Its own false refusal, stated**: a legitimate new option reds here.
    // That is one line to clear plus a reading of why the option was added,
    // which is the trade the equality below already makes.
    const keys = testEntries().flatMap(([path, source]) =>
      globOptionKeys(source, langOf(path)),
    );

    expect([...new Set(keys)].sort()).toEqual(["eager", "import", "query"]);
  });

  it("writes every pattern relative to the file that holds it", () => {
    // The other input constraint, and the one that keeps the resolution
    // above honest: two prefixes are in use, and anything else is a spelling
    // whose resolution nobody here has checked. A root relative pattern reds
    // by name, and is answered correctly by the reach test as well, so this
    // is the loud half of a pair rather than the only half.
    const prefixes = testEntries()
      .flatMap(([path, source]) => globPatterns(source, langOf(path)))
      .filter((pattern) => pattern !== "")
      .map((pattern) => `${pattern.replace(/^!/, "").split("/")[0]!}/`);

    expect([...new Set(prefixes)].sort()).toEqual(["../", "./"]);
  });

  it("is globbed in the module that arms it and in two named others", () => {
    // **An equality and not an empty offender list**, because an instrument
    // that stopped reading would report nothing, and that looks exactly like
    // a clean tree. Naming the files that must be found means a matcher
    // going blind, or the home being deleted, reds here. Which files, and
    // why each is permitted, is at `SOURCE_CORPUS_HOMES` above.
    expect([...new Set(corpusPatterns())]).toEqual(SOURCE_CORPUS_HOMES);
  });

  it("is asked for by every other rule over that tree", () => {
    // The half that moves: a rule written tomorrow asks that module for the
    // corpus, and a pattern written beside the rule instead is named here.
    expect(
      corpusPatterns().filter((path) => !SOURCE_CORPUS_HOMES.includes(path)),
    ).toEqual([]);
  });
});

/**
 * Every pattern each permitted corpus home is allowed to write, in full.
 *
 * **Naming the homes is not enough, and the measurement is what says so.**
 * The rule above caps who may write a pattern over `src/`; nothing capped
 * who may write one over `tests/`, so a fourth home was free. And on either
 * tree, narrowing an existing home is cheaper than adding one: appending
 * `"!./pages/SettingsPage/**"` to each of the home's patterns and to the
 * patterns its own test checks them against is five one token edits in two
 * files, after which 34 modules are unread by every rule over that tree and
 * nothing is red. An exclusion is not a pattern that reaches a tree, so a
 * rule that only asks where a pattern lands never sees it arrive.
 *
 * **So the patterns are stated, exclusions included.** A narrowing now has
 * to be written here as well, in the file holding the rules it would
 * disarm, which is the one place somebody reviewing a corpus change is
 * already reading.
 *
 * **What this still allows, and the condition is the finding rather than a
 * size.** A narrowing applied **after** the glob rather than inside it, as a
 * filter over the result in both corpus modules consistently, changes no
 * pattern and is invisible to everything here. Planted both ways, one change
 * per mutant: a filter excluding the settings page directory hides 34
 * modules and **reds**, and the identical filter excluding the authors page
 * directory hides 5 and **does not**. No corpus arm fires in either. What
 * caught the first is the rule about documents citing tests by name, which
 * reaches this tree through the same entries accessor and fired only because
 * two documents happen to cite files inside that directory. So **a
 * subdirectory survives if no file in it is cited by name by a document**,
 * which today bounds it at five modules and moves the day a document is
 * reworded. A size written here instead would be a property of the
 * documentation.
 *
 * **Closing it needs a derivation of the tree that is not a glob, and
 * `tests/COVERAGE.md` is the wrong one rather than the only one.** Its
 * reporter already checks a row per collected file, and a corpus guard
 * standing on it would be red on every branch that adds a test, for reasons
 * that have nothing to do with the corpus, which is how a rule teaches
 * people to edit it. A filesystem walk is the other candidate and is not
 * refused here: `node:fs` is already imported across this test tree and the
 * type check is green on it, so the dependency is paid. What is missing is a
 * measurement of what it costs and how it behaves under the container
 * layout, and an unmeasured closure is a proposal.
 *
 * **And its own false refusal, stated**: a legitimate new pattern, or a
 * legitimate new home, reds here. That is one line to clear plus a reading
 * of why the pattern was added, which is the trade the option key equality
 * above already makes.
 */
const CORPUS_HOMES: Record<string, string[]> = {
  "./sourceModules.ts": [
    "../src/**/*",
    "../src/*",
    "../src/*/**/*",
    "../src/**/*.{ts,tsx}",
    "../src/**/*.css",
  ],
  "./sourceModules.test.ts": [
    "../src/**/*.{ts,tsx}",
    "../src/lib/*.ts",
    "../src/**/*.css",
    "../src/**/*",
  ],
  "./api/invalidate.test.ts": ["../../src/api/generated/endpoints/*/*.ts"],
  "./testModules.ts": ["./**/*", "./*", "./*/**/*", "./**/*.{ts,tsx}"],
  "./testModules.test.ts": ["./**/*.{ts,tsx}", "./**/*"],
};

describe("the corpus over tests has one home too, and both trees' are pinned", () => {
  const testCorpusPatterns = (): string[] => homesOver(reachesTheTestTree);

  it("is globbed in the home and in the module that checks the home", () => {
    // **An equality and not an empty offender list**, for the reason the
    // source side gives: an instrument that stopped reading reports nothing.
    expect(testCorpusPatterns()).toEqual(TEST_CORPUS_HOMES);
  });

  it("states a pattern list for every permitted home and for no other file", () => {
    // **The arm the map could not do without, and the shortest way past this
    // rule until it existed.** The comparison below builds its left side by
    // filtering the tree's entries to the keys of the map, so deleting a key
    // deletes it from both sides and the equality stays green over a home
    // nobody is checking any more. The ratchet beside it asks only whether a
    // named home still exists, never whether an existing home is still
    // named. That is the failure this whole rule is about, one level up.
    expect([...Object.keys(CORPUS_HOMES)].sort()).toEqual(
      [...SOURCE_CORPUS_HOMES, ...TEST_CORPUS_HOMES].sort(),
    );
  });

  it("writes in each home the patterns that home is allowed, and no others", () => {
    // The arm that sees a narrowing. An exclusion appended to a pattern
    // array lands here, where asking where a pattern reaches does not see it
    // at all.
    // Sorted on both sides, so reordering two calls in a file is free and
    // only the set of patterns is held. A reorder is not a narrowing.
    const written = Object.fromEntries(
      testEntries()
        .filter(([path]) => path in CORPUS_HOMES)
        .map(([path, source]) => [
          path,
          globPatterns(source, langOf(path)).sort(),
        ]),
    );
    const stated = Object.fromEntries(
      Object.entries(CORPUS_HOMES).map(([path, patterns]) => [
        path,
        [...patterns].sort(),
      ]),
    );

    expect(written).toEqual(stated);
  });

  it("names a home that exists, in both directions", () => {
    // The ratchet half: an entry above outliving the file it speaks for is a
    // stated list that has stopped measuring anything. It does not say that
    // every permitted home is still named, which is the arm above.
    const present = testEntries().map(([path]) => path);

    expect(
      Object.keys(CORPUS_HOMES).filter((path) => !present.includes(path)),
      "a corpus home named above that the test tree does not hold",
    ).toEqual([]);
  });
});

/**
 * Where a pattern naming exactly one file lands, as a path from the frontend
 * root.
 *
 * **The other half of `reachesTheSourceTree`, and the sentence that stood
 * here was wrong twice.** That function's docstring says a glob naming one
 * module "answers for that module or for nothing, and a rule reading it
 * fails loudly either way", and the first version of this paragraph called
 * that false. Driven at `b4a8fbec` by feeding each of the ten reads the
 * value its miss actually produces: **ten of ten files reddened.** The
 * mechanisms it named were not the ones in the tree, and its three
 * categories accounted for nine of a stated ten.
 *
 * **What is true is one level down, and this is the third attempt at the
 * paragraph**, each one over wide in a different direction. Driven at the
 * base by feeding each read the value its miss produces, at arm
 * granularity: **two arms of seventeen go green**, both negated matches over
 * an empty string in `tests/lib/fileName.test.ts`, whose anchor is an arm of
 * its own that neither calls. Everywhere else the anchor is in the call path
 * of the arms it guards, so the file reds at the first one. **And the
 * anchors are mostly redundant**: delete all ten and thirteen of sixteen
 * arms still red by themselves. What the shared refusal buys is those two
 * arms, a third that a tidied floor would expose, and ten hand written
 * anchors deleted.
 *
 * **And eight of the ten were doubly anchored**, because the module read is
 * one the same file imports by static specifier, which the bundler refuses
 * before any arm runs. The two that are not: `src/app/routes.tsx` read from
 * `tests/pages/SettingsPage/types.test.ts`, and `src/index.css` read from
 * `tests/setup.ts`, which is the one this rule exempts.
 *
 * So the resolution is shared with that function and the wildcard test is
 * inverted: a pattern with no wildcard in it names one file, and the file it
 * names is one its tree's enumeration can serve.
 *
 * **What is out of scope, and it is the extent claim this replaces.** A
 * `tests/` file that is not a module, which today is the two in
 * `NOT_MODULES`, has no accessor to go through: `testText` refuses it by
 * construction. So the suffix gate below is the same one `reachesTheSourceTree`
 * applies, and a read of a non module is not this rule's business.
 */
function namesOneFileIn(from: string, pattern: string): string | null {
  if (pattern === "" || pattern.startsWith("!")) return null;
  // A brace is a glob however many files it names, so it belongs to
  // `reachesTheTree` and not here.
  if (pattern.includes("*") || pattern.includes("{")) return null;
  if (!servesAModule(pattern)) return null;

  const path = resolveFrom(from, pattern).at.join("/");
  return path.startsWith("src/") || path.startsWith("tests/") ? path : null;
}

describe("one file of either tree is read by name from that tree's corpus", () => {
  /**
   * The suite's own setup file, read off the config rather than named here.
   *
   * **The one read that keeps its own glob, and the exemption is blast
   * radius alone.** `tests/setup.ts` runs for every file in the suite, so an
   * arming failure reached from there is every file red rather than the
   * files that read the corpus. It reads one stylesheet and already throws
   * on a short one, which is the property this rule is about.
   *
   * **The memory argument that stood here was refuted and is gone.**
   * `vite.config.ts` sets `isolate: false`, so a worker evaluates
   * `tests/sourceModules.ts` once and the source text is resident already
   * for every file that worker runs. Routing this read through it adds
   * nothing to carry. No count of the readers stands here either: one was
   * written in the commit that changed it.
   *
   * Taken from `setupFiles` so that pointing the suite at another file moves
   * the exemption with it, and so that an entry left here after the config
   * stops naming it reds.
   */
  function setupFiles(): string[] {
    const declared = /setupFiles:\s*\[([^\]]*)\]/.exec(viteConfig);
    expect(declared, "vite.config.ts declares no setupFiles").not.toBeNull();
    return [...declared![1]!.matchAll(/"([^"]+)"/g)].map((match) =>
      match[1]!.replace(/^\.\/tests\//, "./"),
    );
  }

  /** Every file in the test tree reading one named file of either tree. */
  const readers = (): string[] =>
    testEntries()
      .filter(([path, source]) =>
        globPatterns(source, langOf(path)).some(
          (pattern) => namesOneFileIn(path, pattern) !== null,
        ),
      )
      .map(([path]) => path)
      .sort();

  it("resolves a one file pattern the way the corpus rule resolves a glob", () => {
    // **Each row is a read this tree had when the rule was written, or its
    // control.** The two trees, both depths, the array form and the shapes
    // that must not be flagged: a file outside both trees, which has no
    // corpus to come from, and a wildcard, which the rule above owns.
    const named: [string, string, string][] = [
      ["./setup.ts", "../src/index.css", "src/index.css"],
      ["./lib/pdf.test.ts", "../../src/lib/pdf.ts", "src/lib/pdf.ts"],
      [
        "./pages/Home/hooks.test.tsx",
        "../../../src/pages/Home/hooks.ts",
        "src/pages/Home/hooks.ts",
      ],
      ["./lib/x.test.ts", "../setup.ts", "tests/setup.ts"],
      [
        "./pages/ScanPage/types.test.ts",
        "../../lib/fileName.test.ts",
        "tests/lib/fileName.test.ts",
      ],
      ["./x.test.ts", "/src/lib/zip.ts", "src/lib/zip.ts"],
    ];
    const outside: [string, string][] = [
      // No corpus to come from, so nothing here can name them.
      ["./lib/x.test.ts", "../../openapi.json"],
      ["./lib/sqlite.test.ts", "../../package.json"],
      ["./pages/ScanPage/hooks.test.tsx", "../../../../backend/ratelimit.py"],
      ["./houseRules.test.ts", "../vite.config.ts"],
      // **Inside `tests/` and still outside, because it is not a module.**
      // Both of these are in that corpus module's `NOT_MODULES`, so
      // `testText` refuses them by construction and there is no accessor to
      // send a reader to. Flagging one demanded a route that does not exist,
      // and the only way to clear the red was to add the file to
      // `setupFiles`.
      ["./lib/x.test.ts", "../COVERAGE.md"],
      ["./lib/x.test.ts", "../doubles/README.md"],
      // A wildcard is a corpus, which is the neighbouring rule's subject.
      ["./x.test.ts", "../src/**/*.ts"],
      ["./x.test.ts", "./**/*.{ts,tsx}"],
      ["./x.test.ts", "../{src,public}/*.ts"],
      // A brace names more than one file however few stars it has, so it is
      // the neighbouring rule's too.
      ["./x.test.ts", "../{src,public}/lib/pdf.ts"],
      // An exclusion narrows a pattern rather than being one.
      ["./x.test.ts", "!../src/lib/zip.ts"],
      // Unreadable, which the bundler refuses before this ever sees it.
      ["./x.test.ts", ""],
    ];

    expect(
      named.map(([from, pattern]) => namesOneFileIn(from, pattern)),
    ).toEqual(named.map(([, , landing]) => landing));
    expect(
      outside.filter(([from, pattern]) => namesOneFileIn(from, pattern)),
      "a pattern naming nothing in either tree and answered as if it did",
    ).toEqual([]);
  });

  it("is read through the corpus everywhere but the suite's setup file", () => {
    // **An offender list with its own arming witness, and not an equality.**
    // The equality that stood here compared a sorted list against config
    // order and demanded that every setup file be a one file reader, so a
    // second entry in `setupFiles` reddened a correct tree twice over. What
    // an equality was bought for is that an instrument which stopped reading
    // reports nothing, and the witness below is what buys that instead.
    expect(readers().filter((path) => !setupFiles().includes(path))).toEqual(
      [],
    );
    expect(
      readers(),
      "the reader found nothing at all, so it has stopped reading",
    ).toContain("./setup.ts");
  });

  it("takes the exemption from the config rather than from a list here", () => {
    // **The derivation, driven, and what it is worth is narrower than it
    // reads.** The literal is still written out below, so what the parse
    // buys is the rename case: move or rename the setup file and the
    // exemption follows it, where a name written at the rule would not. A
    // second entry is handled by the arm above rather than here.
    expect(setupFiles()).toEqual(["./setup.ts"]);
    expect(viteConfig).toContain('setupFiles: ["./tests/setup.ts"]');
  });
});

/**
 * A member citation: a code span holding a module's path, `::`, and a name.
 *
 * **The sibling of the rule above, one tree over.** That one asks whether a
 * backticked `path::name` names a test; this one asks whether it names
 * something the module has. The shape is the same and the populations do not
 * overlap: membership there is that the path ends in the suffix the config
 * collects tests by, so every other two colon citation falls here, and that
 * rule's own docstring says it leaves them alone by name.
 *
 * **The backend half of this is older and is where the shape comes from.** It
 * resolves a dotted token's head segment to a module and asks whether the
 * module declares the final segment. What is copied is the mechanism and not
 * the spelling: a module here has no import root, two suffixes and generated
 * code, and what this tree writes is a path rather than a stem.
 *
 * **Anchored on the token, with its two delimiters checked where they stand,
 * and that is load bearing rather than a style.** The first version paired a
 * span over the unwrapped text, `(``?)([^`]+?)\1`. The unwrapper turns every
 * line break into a space, so a fenced code block arrives as three backticks
 * inline, the pair reads two of them as a fence and swallows the region to the
 * next pair, and **every citation after the first fence in that file is
 * unread**. Measured by appending one citation at the end of each published
 * document: the paired reading loses it in **15 of 23**, the anchored reading
 * in **0 of 23**. What the anchored reading gains on this tree is stated as
 * the difference rather than as two totals, because a total over this corpus
 * counts the citations in this comment and moves when the comment is edited:
 * the paired reading misses the two correctly fenced citations in
 * `docs/decisions.md`, and it misses the two written here. **The figures that
 * stood here were taken one commit before the one that published them**, by
 * this comment's own doing: writing the old pattern as a span of backticks
 * mispairs under the reading it describes.
 *
 * **What makes that form safe is that each half names its site, not that the
 * difference cannot move.** It can: it was two at one tip and four at two
 * others, because this file is in the corpus it measures. A reader who wants
 * the number counts the sites named. The backend
 * half records the same lesson from the other direction, a stray backtick
 * inverting a whole file, and anchoring is what makes a mispaired delimiter
 * cost one citation rather than a region.
 *
 * **Squeezed after matching, because the formatter breaks a long token.** The
 * token admits at most two runs of whitespace and they are removed before the
 * shape is read, which is the backend half's arrangement. **What it costs** is
 * that a two word span whose words squeeze into this shape is read as a
 * citation.
 *
 * **The cap is load bearing in both directions and each has an arm.** Below
 * it, a citation the formatter broke is unread, which `reads a citation the
 * formatter wrapped across a line` holds. Above it, ordinary prose becomes a
 * citation: an unbounded cap squeezes a backticked sentence into a path and a
 * member and reports the ones that resolve, which the prose row in `leaves
 * everything the sibling rule owns, and prose, alone` is blind to because its
 * subject is prose under either cap. **The refusal the cap buys** is a
 * citation broken four ways, which the formatter cannot produce: the longest
 * live citation is 47 characters against an 80 column width, so a fourth
 * break needs a token three times longer than anything written.
 *
 * **Qualification is the property, and refusing the two unqualified forms is a
 * measurement.** Taken over this corpus at `167f4e5a`, by the same index this
 * rule uses:
 *
 * | the form | population | naming nothing a module declares |
 * |---|---|---|
 * | a two segment dotted token whose head is a module stem | 700 | 589 |
 * | a bare backticked identifier | 7,874 | 4,416 |
 *
 * Reading the first finds file names (`importing.py`, `en.ts`, `index.html`)
 * and backend table columns (`books.isbn`, `users.username`) whose first word
 * happens to be a module stem; the second is most of the prose in the
 * repository, including every name belonging to the backend, to a library or
 * to a member's own data. Neither is a gate. Both are a census that would
 * refuse by accident, which is this repository's recorded reason for not
 * shipping a phrase pattern over prose.
 *
 * **The escape is dropping the backticks**, which is the backend half's one
 * mechanism and is taken here for its reason: a sentence recording a name that
 * was deliberately removed writes it without a span. That is a real difference
 * from the rule above, which refuses an unfenced citation outright, and the
 * difference is the subject: a dead test is always a defect, a member written
 * down as gone is a register doing its job.
 *
 * **Nothing in the tree uses that escape today, and its absence is not a
 * reason to drop the span requirement.** The requirement is what the escape
 * is, so removing it removes the only way to write a name down as gone.
 * Counted over this corpus: zero unfenced citations, so the shape is available
 * and unused rather than depended on. **A review seat briefly found two live
 * users and both were correctly fenced citations its instrument had misread
 * through the paired span defect above**, which is the measurement to repeat
 * rather than the claim to carry.
 *
 * ## What goes past it
 *
 * **A path resolving to no module of either tree, unless the citation spells
 * the tree.** `vite.config.ts`, `orval.config.ts` and `scripts/check-build.ts`
 * are real files outside both corpora, so an absence there is this rule's
 * ignorance rather than a defect. Where the path is written from `src/` or
 * `tests/` the tree is enumerated and an absence is a fact, so that half is
 * reported. **No citation in the tree is tree prefixed**, measured, so that
 * condition catches none of them and the index arming below is what stands in
 * its place rather than a residue somebody will notice.
 *
 * **A module whose every candidate re-exports from somewhere else.** Its
 * surface is not in its own parse. **One barrel among several candidates no
 * longer silences the rest**, which it did: `index.ts` is the name of 29
 * modules and two of them are generated barrels, so a citation to any
 * `index.ts` member was silent while the path qualified spelling of the same
 * citation was reported.
 *
 * **That repair buys a false refusal and this is where it is said.** A
 * citation to a name a generated barrel genuinely re-exports, written as a
 * basename **several modules share**, was accepted before and is reported
 * now, because the readable candidates beside the barrel keep the union non
 * empty. Ambiguity is the property, not bareness: an unambiguous basename
 * resolves to the barrel alone and is still skipped. Driven on real tree data with three such types; none is
 * live. Closing it means following `export *`, which is a resolver rather
 * than a line, so the cost is stated instead of paid.
 *
 * **The middle segments of a dotted name.** The name resolves if the module
 * declares the whole of it or any of its dotted tails, so
 * `kobo.ts::KoboBook.contentId` resolves on `contentId` and
 * `en.ts::nav.library` resolves on the whole, because a message key is itself
 * a dotted name. A member filed under the wrong type is green, which is the
 * backend half's line and is taken for its reason: checking the type means
 * reading the inheritance a sentence is allowed to skip.
 *
 * **Those two examples are members of the population rather than
 * illustrations**, which is this docstring's one piece of luck: the second is
 * the live citation that reds the rule when the resolution is narrowed back to
 * the final segment, so the sentence explaining the widening is also the
 * witness for it.
 *
 * **That witness is readable only under the anchored reading**, because it
 * sits after this comment's own span of backticks, so two fixes shipped in
 * one commit hold it up together. It is not the only thing holding the
 * widening: the `nav.library` row in `reports the shapes it exists for`
 * carries the same mutation on text written there, so a revert of either
 * half alone still reds.
 *
 * **A document declaring itself internal**, because `citingFiles` excludes one
 * and the subject is what reaches the mirror.
 *
 * **Aboutness.** A name that resolves and is the wrong name for what the
 * sentence says is green here.
 */
const MODULE_FILE = String.raw`[\w./-]+\.tsx?`;

/** The one spelling of the test suffix, which is the sibling rule's subject. */
const CITES_A_TEST = new RegExp(`^${TEST_FILE}$`);

/** One dotted run of identifiers, which is what a member name is written as. */
const MEMBER_NAME = String.raw`[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*`;

/**
 * The characters a citation is made of, and the whitespace a wrap leaves.
 *
 * **`:` is in the set because `::` is part of the token.** The token is
 * matched first and validated second, which is what keeps a stray backtick
 * from swallowing a region: see the docstring above for the measurement.
 */
const CITATION_CHAR = String.raw`[\w./$:-]`;
const CITATION_TOKEN =
  CITATION_CHAR + "+(?:[ \\t]+" + CITATION_CHAR + "+){0,2}";
const MEMBER_SPAN = new RegExp("(``?)(" + CITATION_TOKEN + ")\\1", "g");
const MEMBER_CITATION = new RegExp(
  "^(" + MODULE_FILE + ")::(" + MEMBER_NAME + ")$",
);

/**
 * Each corpus reader's half, keyed the two ways this file keys them.
 *
 * **One home, because two arms compare against them**: the index builder's
 * output and the citing corpus's code halves. Written out at each arm is how
 * one of the two comes to be checked and the other not, which is the defect
 * those arms exist for, one level up.
 */
/**
 * The same documents, globbed a second way, and filtered by nothing.
 *
 * **A second derivation rather than a third arm, because the count equality
 * beside it cannot see its own narrowing**: both sides of that one come from
 * `DOCUMENTS`, so a pattern added there moves both together and reddens
 * nothing. This pattern carries the three machinery exclusions and **no
 * filter after the glob**, so any further narrowing written into `DOCUMENTS`
 * alone shows up as a disagreement rather than as a smaller corpus nobody
 * sees. Narrowing the corpus now has to be written in two places.
 *
 * **It is deliberately not passed through `withoutThePublishTree`.** The arm
 * that compares the two derives the difference it allows from this pattern's
 * own keys, and running both sides through one filter is one instrument
 * twice.
 *
 * **Names only and never read**, so this costs a directory walk and no file
 * contents. It reaches no module and no stylesheet, so it is outside
 * everything the two corpus modules arm.
 */
const EVERY_DOCUMENT = import.meta.glob([
  "../../**/*.md",
  "!../../**/node_modules/**",
  "!../../**/.venv/**",
  "!../../**/.git/**",
]);

const theSourceHalf = (): string[] => entries().map(([path]) => `src/${path}`);
const theTestHalf = (): string[] =>
  testEntries().map(([path]) => path.replace("./", "tests/"));

const sortedPaths = (paths: readonly string[]): string[] => [...paths].sort();

/** Every module of either tree, keyed the way a citation spells a path. */
function citableModules(): Record<string, string> {
  return {
    ...Object.fromEntries(
      entries().map(([path, source]) => [`src/${path}`, source]),
    ),
    ...Object.fromEntries(
      testEntries().map(([path, source]) => [
        path.replace("./", "tests/"),
        source,
      ]),
    ),
  };
}

/**
 * The nodes that declare a member rather than a module level name.
 *
 * **`Property` is in it and seven legitimate spellings turned on it.**
 * Measured over twenty spellings this tree writes or can write: without it an
 * object literal property, a nested one, an object literal getter, a quoted
 * key and an `as const` were all refused, 7 of 20 against 0 of 20 with it and
 * the namespace descent below. **The live cost was the message catalogue**,
 * where the keys are quoted object properties: `src/i18n/en.ts` indexed **3**
 * names against the **1,160** it declares, so every citation of a message key
 * was a false refusal.
 */
const DECLARES_A_MEMBER = new Set([
  "TSPropertySignature",
  "TSMethodSignature",
  "PropertyDefinition",
  "AccessorProperty",
  "MethodDefinition",
  "TSEnumMember",
  "Property",
]);

/** The declaration kinds that carry the declared name in `id`. */
const DECLARES_A_NAME = new Set([
  "FunctionDeclaration",
  "ClassDeclaration",
  "TSInterfaceDeclaration",
  "TSTypeAliasDeclaration",
  "TSEnumDeclaration",
  "TSModuleDeclaration",
]);

/**
 * Every name one declaration binds, however the target is shaped.
 *
 * **Every identifier under the target, not the targets that are an
 * identifier.** A destructured binding is a member like any other, and this
 * tree writes them at module scope. The type annotation is skipped, because
 * the identifiers in one are types this module names rather than names it
 * binds, and admitting them resolves a citation to a type declared somewhere
 * else.
 */
function namesBound(node: unknown, into: Set<string>): void {
  if (Array.isArray(node)) {
    for (const item of node as unknown[]) namesBound(item, into);
    return;
  }
  if (!isNode(node)) return;
  if (node.type === "Identifier") {
    const name = text(node.name);
    if (name !== null) into.add(name);
    return;
  }
  for (const key of Object.keys(node))
    if (key !== "typeAnnotation") namesBound(node[key], into);
}

/**
 * Every member name a declaration's class, interface, enum, type or object
 * body holds.
 *
 * **It stops at a function body**, which is the backend half's line and the
 * same one: a local is not a member a sentence can cite, and admitting one
 * makes this rule green on exactly the citation it exists to report. The arm
 * named `does not resolve a member of a type declared inside a function` is
 * the only thing that holds it.
 */
function membersDeclaredIn(node: unknown, into: Set<string>): void {
  if (Array.isArray(node)) {
    for (const item of node as unknown[]) membersDeclaredIn(item, into);
    return;
  }
  if (!isNode(node)) return;
  if (DECLARES_A_MEMBER.has(node.type)) {
    // **`key` or `id`, because the two are not one convention.** A property
    // signature, a method signature, an object property and a class member
    // name themselves in `key`; an enum member names itself in `id`, measured
    // off this parser. Reading `key` alone left every enum member out of the
    // index, which is a false refusal of every citation to one.
    const named = isNode(node.key) ? node.key : node.id;
    const name = isNode(named) ? (text(named.name) ?? text(named.value)) : null;
    if (name !== null) into.add(name);
  }
  // **It stops at a call as well, and that bound is what keeps the object
  // key admission to objects a module declares.** Admitting keys is what
  // indexes a message catalogue; without this line it also indexes the keys
  // of a call's arguments, of a default parameter value and of a type
  // annotation object, none of which is a member a sentence can cite.
  // **Measured as differences, because the totals count this file.** The
  // index reads every module of both trees including this one, so a total
  // moves whenever an arm is added here, and the three that stood in this
  // comment were each exactly three low by the time the commit carrying them
  // landed. The differences do not have that problem: the key admission adds
  // **3,335** names and this stop costs **101**, and both hold on the tree
  // this comment ships in as well as on the two before it, where the totals
  // moved under them each time. The catalogue's **1,160** is unaffected either way,
  // because the catalogue is not the file doing the counting.
  // Admitting one of those keys is a false acceptance, which is the direction
  // no sweep finds, and the reason this is a bound rather than a preference.
  //
  // **What it refuses, and the tidy up that reopens the hole it closed.** An
  // export whose object passes through a call is not indexed at all, so
  // `export const en = Object.freeze({ ... })` would make every citation of a
  // message key a false refusal again, which is exactly the defect the key
  // admission was added to close. Nothing is live because `src/i18n/en.ts`
  // declares its object directly, and that is an unstated property of one
  // file rather than anything held here: freeze the catalogue, or wrap it in
  // any helper, and the citations to it start reporting.
  if (node.type === "BlockStatement" || node.type === "CallExpression") return;
  for (const key of Object.keys(node)) membersDeclaredIn(node[key], into);
}

/**
 * Every name a statement list declares, and the one place it descends.
 *
 * **A namespace body, and nothing else.** A descent into the branches of an
 * `if`, a `try` and a bare block stood here for one round and is gone: two
 * seats drove it independently, it reddened no arm and left the index byte
 * identical, and what it admitted was a block scoped declaration as a module
 * member, which is what the function body stop in `membersDeclaredIn`
 * deliberately refuses. A line no mutant reds on is a line the next reader
 * deletes, and it contradicted its neighbour besides.
 *
 * **It answers `false` for a module that re-exports everything**, because the
 * names such a module provides are declared elsewhere and refusing a citation
 * to one would be a false refusal over a file nobody wrote by hand.
 */
function declaresInto(body: unknown, into: Set<string>): boolean {
  if (!Array.isArray(body)) return true;
  for (const statement of body as unknown[]) {
    if (!isNode(statement)) continue;
    if (statement.type === "ExportAllDeclaration") return false;
    let node = statement;
    if (
      node.type === "ExportNamedDeclaration" ||
      node.type === "ExportDefaultDeclaration"
    ) {
      for (const specifier of (node.specifiers as unknown[]) ?? []) {
        if (!isNode(specifier)) continue;
        const exported = specifier.exported;
        const name = isNode(exported)
          ? (text(exported.name) ?? text(exported.value))
          : null;
        if (name !== null) into.add(name);
      }
      const inner = node.declaration;
      if (!isNode(inner)) continue;
      node = inner;
    }
    if (DECLARES_A_NAME.has(node.type)) {
      const id = node.id;
      const name = isNode(id) ? text(id.name) : null;
      if (name !== null) into.add(name);
      membersDeclaredIn(node, into);
      if (node.type === "TSModuleDeclaration" && isNode(node.body))
        declaresInto(node.body.body, into);
      continue;
    }
    if (node.type === "VariableDeclaration") {
      for (const declarator of (node.declarations as unknown[]) ?? []) {
        if (!isNode(declarator)) continue;
        namesBound(declarator.id, into);
        membersDeclaredIn(declarator.id, into);
        membersDeclaredIn(declarator.init, into);
      }
      continue;
    }
  }
  return true;
}

/** What a module has, or nothing when its surface is not in its own parse. */
function namesDeclaredIn(
  source: string,
  lang: "ts" | "tsx",
): Set<string> | null {
  const found = new Set<string>();
  const body = (parseAst(source, { lang }) as unknown as Node).body;
  return declaresInto(body, found) ? found : null;
}

/** The whole dotted name, then each of its tails. */
function theNameAndItsTails(name: string): string[] {
  const segments = name.split(".");
  return segments.map((_, at) => segments.slice(at).join("."));
}

/** Every member citation these files hold, read but not yet resolved. */
function memberCitationsIn(
  files: Record<string, string>,
): { from: string; cited: string; name: string }[] {
  const out: { from: string; cited: string; name: string }[] = [];
  for (const [from, source] of Object.entries(files)) {
    MEMBER_SPAN.lastIndex = 0;
    for (const span of unwrapped(source).matchAll(MEMBER_SPAN)) {
      const written = MEMBER_CITATION.exec(span[2]!.replace(/[ \t]+/g, ""));
      if (written === null) continue;
      const cited = normalised(from, written[1]!);
      if (CITES_A_TEST.test(cited)) continue;
      out.push({ from, cited, name: written[2]! });
    }
  }
  return out;
}

/**
 * The member citations in `files` that resolve to nothing, as sentences.
 *
 * Pure and handed its whole world, so the probes below drive the same code the
 * rule does rather than a second implementation of it.
 *
 * **An unqualified basename matching several modules is checked against their
 * union**, which is the sibling rule's leniency and is taken for its reason:
 * nothing here can tell which of them somebody meant.
 */
function unheld(
  files: Record<string, string>,
  modules: Record<string, string>,
): string[] {
  const paths = Object.keys(modules);
  const index = new Map<string, Set<string> | null>();
  const declaredBy = (path: string): Set<string> | null => {
    if (!index.has(path))
      index.set(path, namesDeclaredIn(modules[path] ?? "", langOf(path)));
    return index.get(path) ?? null;
  };

  const found: string[] = [];
  for (const { from, cited, name } of memberCitationsIn(files)) {
    const targets = paths.filter(
      (path) => path === cited || path.endsWith(`/${cited}`),
    );
    if (targets.length === 0) {
      // **Reported only where the citation spells a tree this rule
      // enumerates.** A bare basename naming nothing may be a file outside
      // both corpora, and refusing one is this rule's ignorance read as a
      // defect.
      if (cited.startsWith("src/") || cited.startsWith("tests/"))
        found.push(
          `${from} names ${cited} for the member ${name}, ` +
            `and there is no such module here`,
        );
      continue;
    }
    // **A barrel among the candidates no longer answers for the others.** The
    // first version skipped the citation when **any** candidate re-exported
    // everything, and `index.ts` is the name of 29 modules two of which are
    // generated barrels, so one union covered every page folder's own
    // `index.ts` and the rule was silent over all of them. Measured: the bare
    // spelling was silent while the path qualified spelling of the same
    // citation was reported.
    const readable = targets
      .map(declaredBy)
      .filter((names): names is Set<string> => names !== null);
    if (readable.length === 0) continue;
    const declared = new Set(readable.flatMap((names) => [...names]));
    if (theNameAndItsTails(name).some((one) => declared.has(one))) continue;
    found.push(`${from} names ${cited} and the member ${name}, undeclared`);
  }
  return found;
}

describe("a module member cited in prose is still declared there", () => {
  /**
   * **The shape the rule above cannot see, by its own account.** That rule
   * reads a two colon citation only when the path is a test file, and its own
   * arms assert that it leaves a source module's export alone. So the tree has
   * one instrument for a renamed test and none for a renamed member, while the
   * backend has had the second since the MARC reader split.
   *
   * **A guard next door that looks like it covers you** is how the sibling
   * describes the gap it was built into, and this is the same sentence one
   * tree over: a green run of either neighbour says nothing about this class.
   */
  it("leaves no cited member undeclared", () => {
    expect(unheld(citingFiles(), citableModules())).toEqual([]);
  });

  it("reads citations in all three families, not an empty set", () => {
    // **The arming, and it is a property of the population rather than its
    // size.** A corpus narrowed by directory keeps a count up while losing
    // the family that carries the defect, which is what a floor cannot see.
    // The documents are the family the sibling rule shipped without and the
    // only one that was carrying a live defect.
    const citing = new Set(
      memberCitationsIn(citingFiles()).map(({ from }) =>
        from.startsWith("src/")
          ? "src"
          : from.startsWith("tests/")
            ? "tests"
            : "a document",
      ),
    );

    expect([...citing].sort()).toEqual(["a document", "src", "tests"]);
  });

  it("indexes every module both corpus readers hand over", () => {
    // **Set equality against the readers, and the set assertions that stood
    // here could not do this job.** They held the first path segments and the
    // suffixes, so **687 of 689 modules could be dropped inside the index
    // builder with every arm green.**
    //
    // **And the loss is silent, not loud.** No citation in the tree is tree
    // prefixed, so a citation whose target leaves the index resolves to
    // nothing and is dropped by the ignorance condition in `unheld` rather
    // than reported. No sibling guard reddens on it either, so there is no
    // collateral catch.
    //
    // **Set rather than count, because a count holds neither identity nor
    // membership**: dropping one module and adding a renamed copy keeps every
    // count where it was. The sets are free, since both sides are derived
    // from the readers already.
    expect(sortedPaths(Object.keys(citableModules()))).toEqual(
      sortedPaths([...theSourceHalf(), ...theTestHalf()]),
    );
  });

  it("reads every module both corpus readers hand over", () => {
    // **The same arm one tree over, because the citing corpus had the hole
    // the index one had just closed.** The index is where a citation is
    // resolved; `citingFiles` is where one is found, and nothing held its two
    // code halves. Driven on the real arms: with a real stale citation live,
    // a single directory filter written inside that reader takes the run back
    // to green, where the same filter in the index builder reds by name. The
    // document half is held by the arm below and the two code halves by this
    // one.
    //
    // **Its independence stops at the reader, and a run of this file alone
    // cannot see that.** Both sides of both equalities call `sourceEntries`
    // and `testEntries`, so a narrowing written **inside** one of those
    // readers moves both sides together and reddens nothing here: what
    // catches it is `tests/sourceModules.test.ts` and `tests/testModules.ts`'s
    // own arm file, which enumerate those trees a second way. A top level
    // narrowing reds here loudly; a subdirectory one is theirs. Said because
    // this guard has been graded by targeted runs of this file, and a
    // targeted run is the one thing that cannot observe the division.
    //
    // **Split by suffix and not by prefix.** The document half is keyed the
    // way a citation inside a document resolves, which puts the documents
    // under the test tree in the same namespace as the test modules; a
    // prefix alone then hands them to the equality below and reds it.
    const modules = Object.keys(citingFiles()).filter(
      (path) => !path.endsWith(".md"),
    );

    expect(
      sortedPaths(modules.filter((path) => path.startsWith("src/"))),
    ).toEqual(sortedPaths(theSourceHalf()));
    expect(
      sortedPaths(modules.filter((path) => path.startsWith("tests/"))),
    ).toEqual(sortedPaths(theTestHalf()));
  });

  it("reads every published document the glob hands over", () => {
    // **Two instruments, because one of them cannot see its own narrowing.**
    // The count equality catches a filter added between the glob and the
    // corpus, which is where a narrowing would be written; it cannot catch a
    // narrowing written **into** the glob, because that moves both sides
    // together. The directory set catches that one, and reds by name on a new
    // directory of documents too, which is the loud direction.
    //
    // **The document family's own arming was a population of one**: of the
    // 23 published documents exactly one carried a citation, so dropping the
    // other 22 left the families arm, the rule and the self arm all green.
    // The two counts that stood here naming the other two families are gone
    // rather than registered, which is this repository's own remedy for a
    // count in prose: one of them read as a roster count and the census that
    // walks every published file reported it.
    //
    // **The count equality is also what refuses a key collision, and it is
    // the only thing that can be.** `citingFiles` builds its corpus by
    // spread, so two documents resolving to one key silently become one
    // entry; keying a document the way a citation in it resolves is what
    // makes that reachable, since two documents at the same path below
    // different trees now meet. It shows up here as a corpus one document
    // short of the glob and reds in both directions. An arm comparing
    // document keys against module keys **cannot** stand in for this: the
    // module corpora are typescript globs, so no string ends in both
    // suffixes and the intersection is empty whatever the keying does.
    // Driven with a key function collapsing one document onto another's key.
    const published = Object.entries(DOCUMENTS).filter(
      ([, source]) => !declaresItselfInternal(source),
    );
    const read = Object.keys(citingFiles()).filter((path) =>
      path.endsWith(".md"),
    );
    //
    // **The test tree is in the list below because two documents live there**,
    // and it is the live witness that a document is keyed the way a citation
    // inside it resolves. Those two used to arrive keyed against the
    // repository root, carrying the globbing directory's own `./`, and the
    // list named that instead: an arm naming the defect rather than reddening
    // on it. `citationKey` holds what went wrong underneath.
    const where = new Set(
      read.map((path) =>
        path.includes("/") ? path.split("/")[0]! : "the repository root",
      ),
    );

    //
    // **A subset rather than an equality, and the equality was wrong in the
    // one place it fired.** The glob reads the filesystem rather than what
    // the repository versions, so a checkout holding working notes reads them
    // too, and most of what one holds can be notes under a directory nobody
    // versions. The counts that stood here were taken over an agent working
    // directory, which is a population that moves between two runs on one
    // machine, so they are gone rather than re-derived. An
    // equality reds there permanently, on the presence of a scratch directory
    // and on no citation at all, and a permanent red for normal working state
    // is what teaches the next reader to delete the arm. The subset still
    // reds on the narrowing this exists for and gives up reddening on a new
    // documents directory, which is the cost.
    const missing = [
      "backend",
      "conformance",
      "docs",
      "tests",
      "the repository root",
    ].filter((one) => !where.has(one));

    expect(read.length).toBe(published.length);
    expect(missing).toEqual([]);
  });

  it("reads the same documents a second pattern reaches", () => {
    // **The arm the two above cannot be**, and the shape the backend's own
    // register gate uses: a direct glob less an exclusion set, compared
    // against the corpus. A partial narrowing written inside `DOCUMENTS`
    // reddened neither of them, the count because both its sides derive from
    // that one glob, the directory subset because the directory survives a
    // narrowing that drops only part of it.
    //
    // **What the two patterns are allowed to differ by is derived, not
    // listed.** This filtered the difference by the directory the publish
    // script writes to by default, which said nothing about a run given any
    // other directory: that is an argument to the script, and a copy
    // materialised under another name was in both patterns, so the two
    // agreed and this arm was green while the corpus held every published
    // document twice.
    //
    // **The right hand side is a second derivation and not a restatement of
    // the left.** It rebuilds the allowed difference from the second
    // pattern's own keys, so a narrowing written into the first pattern alone
    // arrives here as a disagreement rather than as a smaller corpus. Empty
    // on both sides on a checkout nobody has run the script in, which is why
    // `materialisedCopies` carries its own arms over planted corpora: an
    // equality between two empty sets witnesses nothing by itself.
    //
    // **Through the whole union, not the shape half.** The left hand side is
    // what the corpus dropped, which is the union; rebuilding it from the
    // shape alone asserts that the pin found nothing the shape did not, which
    // is the same sentence as the pin being redundant. The union exists
    // because it is not. Driven over a checkout carrying a real publish tree:
    // with one published document renamed or deleted since that run, the
    // shape half finds nothing, the corpus is **correct**, and the shape
    // sided version reds and names neither the pin nor the ignore file. One
    // rename on the trunk without re-running the script is enough, and the
    // history makes that ordinary.
    //
    // **It is still two instruments and the arm keeps its subject.** The
    // instruments are the two patterns, and the filter is not an instrument.
    // Driven in the same place: narrowing either pattern by a directory reds
    // this, before and after.
    const theirs = Object.keys(DOCUMENTS);
    const mine = Object.keys(EVERY_DOCUMENT);
    const onlyInTheSecond = mine.filter((path) => !theirs.includes(path));
    const onlyInTheFirst = theirs.filter((path) => !mine.includes(path));

    expect(sortedPaths(onlyInTheSecond.map(repositoryPath))).toEqual(
      thePublishTreeIn(mine.map(repositoryPath)),
    );
    expect(onlyInTheFirst).toEqual([]);
  });

  it("reads a citation written after a fenced code block", () => {
    // **The defect this rule shipped with, and the reason the span is
    // anchored on the token.** The unwrapper turns a break into a space, so a
    // fence arrives as three backticks inline; a paired span reads two of them
    // as a delimiter and swallows everything to the next pair. Measured over
    // the published documents, a citation appended at the end was unread in 15
    // of 23 before and 0 of 23 after.
    const document = [
      "# A document",
      "",
      "```ts",
      "const example = 1;",
      "```",
      "",
      "And `thing.ts" + "::theOldName` is gone.",
    ].join("\n");

    expect(
      unheld(
        { "docs/a.md": document },
        { "src/thing.ts": `export const theNewName = 1;` },
      ),
    ).toEqual([
      "docs/a.md names thing.ts and the member theOldName, undeclared",
    ]);
  });

  it("reports the shapes it exists for", () => {
    // **Assembled rather than written out**, so none of these is a citation
    // in this file's own source and the rule above reads this file for real.
    const cite = (path: string, name: string) => "`" + path + "::" + name + "`";
    const probe = (module: string, comment: string) =>
      unheld(
        { "src/x.ts": `// ${comment}\nexport const x = 1;` },
        { "src/thing.ts": module },
      );

    // The two it is for. A renamed member, and a module that is not there.
    expect(
      probe(`export const theNewName = 1;`, cite("thing.ts", "theOldName")),
    ).toEqual([
      "src/x.ts names thing.ts and the member theOldName, undeclared",
    ]);
    expect(
      probe(`export const kept = 1;`, cite("src/gone.ts", "kept")),
    ).toEqual([
      "src/x.ts names src/gone.ts for the member kept, " +
        "and there is no such module here",
    ]);

    // And the legitimate spellings, every one of which a stricter reading
    // refuses. A rule that refuses these is worse than none, because the next
    // author deletes it rather than obeying it. **Seven of these were refused
    // by the first version**: the five object literal rows, and both
    // namespace rows.
    const accepted: [string, string][] = [
      [`export const kept = 1;`, cite("thing.ts", "kept")],
      [`function kept() {}`, cite("thing.ts", "kept")],
      [`const [kept, other] = [1, 2];\nvoid other;`, cite("thing.ts", "kept")],
      [`export type Kept = { field: string };`, cite("thing.ts", "Kept")],
      [`export interface Kept { field: string }`, cite("thing.ts", "field")],
      [`interface Kept { run(): void }`, cite("thing.ts", "run")],
      [`enum Kept { Member = 1 }`, cite("thing.ts", "Member")],
      [`class Kept { run() {} }`, cite("thing.ts", "run")],
      [`class Kept { get only() { return 1; } }`, cite("thing.ts", "only")],
      [
        `const kept = 1;\nexport { kept as renamed };`,
        cite("thing.ts", "renamed"),
      ],
      [`export default function named() {}`, cite("thing.ts", "named")],
      // The object literal family, which is how the message catalogue is
      // written and was the whole of the live false refusal.
      [`export const o = { prop: 1 };`, cite("thing.ts", "prop")],
      [`export const o = { a: { b: 1 } };`, cite("thing.ts", "b")],
      [
        `export const o = { get only() { return 1; } };`,
        cite("thing.ts", "only"),
      ],
      [`export const o = { a: 1 } as const;`, cite("thing.ts", "a")],
      // A quoted key that is itself dotted, resolved on the whole name.
      [
        `export const en = { "nav.library": "Library" };`,
        cite("thing.ts", "nav.library"),
      ],
      // A namespace, both halves.
      [
        `export namespace N { export const inner = 1; }`,
        cite("thing.ts", "inner"),
      ],
      [
        `declare namespace N { interface Inner { f: string } }`,
        cite("thing.ts", "Inner"),
      ],
      // The dotted tail, whose middle segments are prose.
      [
        `export interface Kept { field: string }`,
        cite("thing.ts", "Kept.field"),
      ],
      [
        `export interface Kept { field: string }`,
        cite("thing.ts", "Other.field"),
      ],
      // The path spelled from the repository root, and from the tree.
      [`export const kept = 1;`, cite("frontend/src/thing.ts", "kept")],
      [`export const kept = 1;`, cite("src/thing.ts", "kept")],
    ];
    for (const [module, comment] of accepted)
      expect(probe(module, comment), comment).toEqual([]);
  });

  it("lets one barrel among several candidates answer for none of them", () => {
    // **The hole two leniencies composed into.** The union over an ambiguous
    // basename is deliberate; skipping a module that re-exports everything is
    // deliberate; skipping the citation when **any** candidate was a barrel
    // made the rule silent over every `index.ts` in the tree, 29 modules of
    // which two are generated barrels. All three spellings are driven here
    // because the bare one was silent while the qualified one reported, which
    // is the shape that makes a rule look like it works.
    const modules = {
      "src/api/generated/model/index.ts": `export * from "./x.ts";`,
      "src/pages/Home/index.ts": `export { Home } from "./Home.tsx";`,
      "src/thing.ts": `export const kept = 1;`,
    };
    const citing = (cited: string) => ({
      "src/x.ts": "// `" + cited + "::gone`\nexport const x = 1;",
    });

    // The bare name, whose candidates include a barrel and a real module.
    expect(unheld(citing("index.ts"), modules)).toEqual([
      "src/x.ts names index.ts and the member gone, undeclared",
    ]);
    // The qualified spelling of the same citation, which always reported.
    expect(unheld(citing("src/pages/Home/index.ts"), modules)).toEqual([
      "src/x.ts names src/pages/Home/index.ts and the member gone, undeclared",
    ]);
    // And a citation whose only candidate is a barrel is still skipped,
    // because that module's surface is genuinely not in its own parse.
    expect(unheld(citing("src/api/generated/model/index.ts"), modules)).toEqual(
      [],
    );
  });

  it("leaves everything the sibling rule owns, and prose, alone", () => {
    const span = (inner: string) => "`" + inner + "`";
    const probe = (comment: string) =>
      unheld(
        { "src/x.ts": `// ${comment}\nexport const x = 1;` },
        { "src/thing.ts": `export const kept = 1;` },
      );

    // A test file is the sibling's population by the one spelling of the
    // suffix, so this rule says nothing about one even where it resolves to
    // nothing. **Assembled, like the sibling's own probes**, because the
    // whole shape written out here is an unfenced citation in this file's
    // source and that rule reports one.
    const aTest = (name: string) => span("src/a.test.ts" + "::" + name);
    expect(probe(aTest("a label nobody wrote"))).toEqual([]);
    expect(probe(aTest("gone"))).toEqual([]);
    // The escape, driven rather than described.
    expect(probe("thing.ts" + "::gone is the one that went")).toEqual([]);
    // A path outside both corpora, which this rule cannot answer for.
    expect(probe(span("vite.config.ts" + "::gone"))).toEqual([]);
    // The two refused forms the docstring measures.
    expect(probe(span("thing.gone"))).toEqual([]);
    expect(probe(span("gone"))).toEqual([]);
    // A prose span of more words than a wrapped token can carry.
    expect(probe(span("a sentence. with a dot"))).toEqual([]);
    // **The row that discriminates, which the one above does not.** That one
    // is prose under either cap. This one is prose at the cap the token
    // carries and a reported false refusal without it: squeezed it reads as
    // this probe's own module and a member it does not declare, so an
    // unbounded cap turns a sentence about a renamed reader into a citation
    // nobody wrote.
    //
    // **The module has to be one this probe's world holds.** The row was
    // handed over naming a real module of the tree and measured green at
    // both caps here, because a path the probe's two module world does not
    // hold leaves the population through the ignorance condition before any
    // cap applies. A row whose subject is dropped for an unrelated reason
    // discriminates nothing.
    expect(probe(span("thing.ts" + "::kept but renamed twice"))).toEqual([]);
  });

  it("does not resolve a name that is only a local", () => {
    // **The widening this rule has to stay closed against**, which is the one
    // mutation that takes it green over a live defect: index every identifier
    // a declaration holds rather than the names it declares. Measured with
    // `namesBound(node, found)` added to the declaration branch, which is the
    // one line that does it: this arm and the one below it both red, which is
    // the honest size of that mutant rather than evidence about this arm
    // alone.
    //
    // **The two obvious weakenings are not that one**, measured rather than
    // assumed: removing the stop at a function body leaves this green, and so
    // does reading the member key alone. Each has an arm of its own, the
    // first below and the second in the enum row above, because a line no
    // mutant reds on is a line the next reader deletes.
    const module = `export function run() {\n  const local = 1;\n  return local;\n}`;

    expect(
      unheld(
        { "src/x.ts": "// `thing.ts" + "::local`\nexport const x = 1;" },
        { "src/thing.ts": module },
      ),
    ).toEqual(["src/x.ts names thing.ts and the member local, undeclared"]);
  });

  it("does not resolve a key handed to a call", () => {
    // **What the stop at a call is for, and the only thing holding it.**
    // Admitting object keys is what indexes a message catalogue, and the same
    // descent reaches the keys of a call's arguments, which are an argument's
    // shape rather than anything the module provides. Nothing in the tree
    // cites one, because the direction is false acceptance and a citation to
    // such a key would quietly pass, so the subject is planted.
    const module = `export const x = configure({ notAMember: 1 });`;

    expect(
      unheld(
        { "src/x.ts": "// `thing.ts" + "::notAMember`\nexport const x = 1;" },
        { "src/thing.ts": module },
      ),
    ).toEqual([
      "src/x.ts names thing.ts and the member notAMember, undeclared",
    ]);
  });

  it("does not resolve a member of a type declared inside a function", () => {
    // **What the stop at a function body is for**, and it is the only thing
    // that holds it: measured, removing that line reddens nothing else, here
    // or over the tree. A type declared inside a function is not a member a
    // sentence can reach, and admitting one resolves a citation against a
    // name no caller of the module can name.
    const module = `export function run() {\n  interface Inner { hidden: string }\n  return null as unknown as Inner;\n}`;

    expect(
      unheld(
        { "src/x.ts": "// `thing.ts" + "::hidden`\nexport const x = 1;" },
        { "src/thing.ts": module },
      ),
    ).toEqual(["src/x.ts names thing.ts and the member hidden, undeclared"]);
  });

  it("reads a citation the formatter wrapped across a line", () => {
    // The wrap the formatter mandates over eighty columns, which a line
    // oriented reading misses. Nothing in this corpus wraps today, counted by
    // comparing the reading with and without the unwrapper, so the arm is
    // planted rather than live.
    expect(
      unheld(
        {
          "src/x.ts":
            "// see `thing.ts" +
            "::\n// theOldName` for it\nexport const x = 1;",
        },
        { "src/thing.ts": `export const theNewName = 1;` },
      ),
    ).toEqual([
      "src/x.ts names thing.ts and the member theOldName, undeclared",
    ]);
  });

  it("is reading this file, which carries its own subject", () => {
    // **Membership is not the subject, and the name was for the subject.**
    // Stripping every citation out of this file while leaving the file in
    // the corpus reddened nothing: the arm held that the file is read, which
    // is a weaker claim than the one it is named for. What makes this file a
    // member worth reading is the citations it writes, so those are what is
    // asserted.
    //
    // **They are a subject rather than a fixture**, which is the line between
    // a guard sitting in its own population legitimately and one planting its
    // own evidence: both name a real module and both must resolve like any
    // other prose in the corpus. The fixtures that used to sit here named a
    // module the tree does not have and could only ever be dropped in
    // silence, which is why they are assembled now.
    const mine = memberCitationsIn(citingFiles()).filter(
      ({ from }) => from === "tests/houseRules.test.ts",
    );

    expect(Object.keys(citingFiles())).toContain("tests/houseRules.test.ts");
    expect(mine.length).toBeGreaterThan(0);
  });
});
