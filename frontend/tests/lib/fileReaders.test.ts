import { describe, expect, it } from "vitest";

import { READERS, readerFor, type FileReader } from "../../src/lib/fileReaders";
import {
  FORMAT_FOR_EXTENSION,
  SUPPORTED_EXTENSIONS,
} from "../../src/lib/fileName";
import {
  BookFormat,
  BookIdentifierScheme,
} from "../../src/api/generated/model";

/**
 * Every registered extension and the export its module answers with.
 *
 * **The property is that each key opens the function its own module exports**,
 * which is not what a per format `it` asserts. Seven of them stood here, one or
 * two per format, and each asked only that `readerFor` answered *some*
 * function: measured 2026-09-08, `".pdf": async () => (await
 * import("./epub")).readEpub` passed the whole suite at `2967 passed`, and
 * every PDF would open as a zip and be reported "not an EPUB", a sentence
 * `FILE_FAILURES` already has for a member to read.
 *
 * **Total over the registry rather than an arm per format**, so the table is
 * what a ninth registration has to be added to. Its totality is a runtime
 * assertion below and not yet a compile error: `READERS` carries a type
 * annotation, so `keyof typeof READERS` is all ten supported extensions rather
 * than the eight registered. The year band ticket prices the `satisfies`
 * narrowing that would close it.
 *
 * **Resolved by `await import` and not by a static import at the top of this
 * file.** A reader whose module throws while evaluating would, under a static
 * import, take this whole file out of collection rather than fail it, so the
 * count drops and no name is reported.
 *
 * Measured with an evaluation fault injected into `pdf.ts`, its module scope
 * decoder label replaced with one no runtime knows: `tests/lib/pdf.test.ts`
 * collects `0 test` and names nothing, where on an unaltered tree it collects
 * 45 and passes. It holds the same static import this avoids, at its line 21.
 * Resolved here, the same fault fails a named test instead.
 */
async function opensWith(): Promise<Record<string, FileReader>> {
  const [epub, mobi, fb2, cbz, pdf] = await Promise.all([
    import("../../src/lib/epub"),
    import("../../src/lib/mobi"),
    import("../../src/lib/fb2"),
    import("../../src/lib/cbz"),
    import("../../src/lib/pdf"),
  ]);
  return {
    ".epub": epub.readEpub,
    // One container under three names, so all three answer one function.
    ".mobi": mobi.readMobi,
    ".azw": mobi.readMobi,
    ".azw3": mobi.readMobi,
    // Two keys and two functions, which is the pair most able to be wrong: the
    // document and the same document inside an archive.
    ".fb2": fb2.readFb2,
    ".fb2.zip": fb2.readFb2Archive,
    ".cbz": cbz.readCbz,
    ".pdf": pdf.readPdf,
  };
}

describe("which reader opens a picked file", () => {
  it("names every registered extension in the table below", async () => {
    // Without this the table is an inclusion list again: a ninth registration
    // the table does not name is simply not checked by the test that follows.
    expect(Object.keys(await opensWith()).sort()).toEqual(
      Object.keys(READERS).sort(),
    );
  });

  it("opens each registered extension with the function its module exports", async () => {
    const expected = await opensWith();
    const wrong: string[] = [];
    for (const [extension, reader] of Object.entries(expected)) {
      // Named rather than asserted in the loop, so a failure says which
      // extension rather than that one of eight was not a function.
      if ((await readerFor(`book${extension}`)) !== reader)
        wrong.push(extension);
    }

    expect(wrong).toEqual([]);
  });
  it("answers nothing for a supported format with no reader", async () => {
    // Not an error, and audio is the standing case: `.m4b` and `.mp3` are read
    // by `lib/audiobook.ts` on a separate path, because which files are one
    // book is decided before any of them is drafted from.
    expect(await readerFor("chapter.m4b")).toBeNull();
  });

  it("answers nothing for a file the walk does not take", async () => {
    expect(await readerFor("notes.txt")).toBeNull();
  });

  it("registers no extension the walk does not consider", () => {
    // The failure this catches is a reader added under a spelling the picker
    // never offers it, which would look like a reader that silently never runs.
    const registered = Object.keys(READERS);
    expect(registered).not.toHaveLength(0);
    for (const extension of registered) {
      expect(SUPPORTED_EXTENSIONS).toContain(extension);
    }
  });

  it("leaves an extension readerless only where another route takes the file", async () => {
    // The failure this catches is the one every test above is blind to: a
    // format joined to `SUPPORTED_EXTENSIONS` and to the total
    // `FORMAT_FOR_EXTENSION` and never reaching a reader. Those tests name one
    // format each and are written by the ticket that adds the reader, so the
    // format nobody registered is the format nobody wrote a test for. Measured
    // 2026-09-08: a `.prc` added to both of those maps and to no reader
    // typechecks, because `READERS` is a `Partial`, and the whole frontend
    // suite passed while the file took the filename path in silence.
    //
    // **Asked of `readerFor` and never of `READERS`, which is three failures
    // for one assertion.** A missing key, a key whose value is not a reader,
    // and a door that drops an extension the map does carry all come back as
    // one answer here, where reading the map catches the first and needs its
    // own reasoning for each of the others.
    //
    // None of the three is hypothetical. `exactOptionalPropertyTypes` is off in
    // `frontend/tsconfig.json`, so `".prc": undefined` is a legal value rather
    // than an absent key and satisfies `in`. And `.fb2` and `.fb2.zip` are
    // passed to `readerFor` by no other test in this suite, so an early return
    // for either is a format lost in silence that no reading of the map sees.
    //
    // **The exclusion is the routing predicate and not a list of extensions.**
    // `ScanPage/hooks.ts` sends a file to the grouping path when
    // `FORMAT_FOR_EXTENSION` calls it an audiobook, and that is the only route
    // that is not this registry, so it is the only thing that may answer for an
    // absent reader. Asserted in both directions: an audio extension that grows
    // a reader has grown one nothing reaches, because the picker routes the
    // file away before `readerFor` is ever asked.
    //
    // `book.fb2.zip` resolves to the archive because **`.fb2` does not match it
    // at all**: `"book.fb2.zip".endsWith(".fb2")` is false, so `.fb2.zip` is the
    // only member the name ends with. Order decides nothing here and neither
    // does length, which is `fileName.ts`'s own sentence: what would make order
    // matter is one extension being a suffix of another, and none is.
    const answered = await Promise.all(
      SUPPORTED_EXTENSIONS.map((extension) => readerFor(`book${extension}`)),
    );
    const routedElsewhere = SUPPORTED_EXTENSIONS.filter(
      (extension) => FORMAT_FOR_EXTENSION[extension] === BookFormat.audiobook,
    );
    const readerless = SUPPORTED_EXTENSIONS.filter(
      (_, index) => typeof answered[index] !== "function",
    );

    // Two empty lists are equal, which is how an assertion like this passes for
    // ever once the sets it compares stop being populated.
    expect(routedElsewhere.length).toBeGreaterThan(0);
    expect([...readerless].sort()).toEqual([...routedElsewhere].sort());
  });

  it("is case insensitive, because a file picker is not", async () => {
    expect(await readerFor("DRACULA.EPUB")).toBeTypeOf("function");
  });
});

/**
 * Every module, read as text, because the rules below are about the import
 * graph and a module's own exports, neither of which is visible from a value.
 *
 * `import.meta.glob` rather than `node:fs`, for the reason
 * `tests/houseRules.test.ts` gives at its own copy: a guard test is a poor
 * reason to add `@types/node` and widen the global types.
 *
 * **Here rather than beside that copy**, which is where a tree wide rule
 * belongs, because this one is about a single seam and this is that seam's test
 * file. `houseRules.test.ts` is also owned by another change this wave, and a
 * rule about `fileReaders.ts` should not need an edit there to be added.
 */
const SOURCES = import.meta.glob("../../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const SEAM = "lib/fileReaders.ts";
const ENTITY_GUARD = "lib/xmlEntities.ts";
const YEAR_RULES = "lib/year.ts";

/**
 * The family's shared vocabulary, and which module declares each part of it.
 *
 * **Three homes rather than one, because the family shares three different
 * kinds of thing.** The seam says what a reader is and what it answers with,
 * which every reader produces; the entity refusal is a rule about handing a
 * member's document to a parser, which four readers apply and which nothing in
 * the contract consults; the year rules say what a number has to be to be a
 * publication year, which eight readers reach for and which is neither the seam
 * nor a bound on a request body. A `FileReading` is the same shape whether or
 * not the bytes went through a parser at all, so the second was moved out, and
 * the third for the same reason one module over.
 *
 * **The rules below are the same for all three and are written once**, which is
 * what makes a fourth home a row here rather than a fourth arm: whatever a home
 * declares, it declares under no second name, and every module using one of
 * those names takes it from that home.
 */
const SHARED_HOMES = [
  {
    path: SEAM,
    /** Spelled with the opening brace, so a re-export cannot satisfy it. */
    declarations: [
      "export interface FileMetadata {",
      "export interface FileIdentifier {",
    ],
    names: ["FileMetadata", "FileIdentifier"],
  },
  {
    path: ENTITY_GUARD,
    declarations: ["export function declaresEntities("],
    names: ["declaresEntities"],
  },
  {
    // What a year is, which four readers had spelled as their own function and
    // four more reach for the window of. A row rather than a fourth arm, which
    // is what this table is for.
    path: YEAR_RULES,
    declarations: [
      "export function plausibleYear(",
      "export function leadingYear(",
    ],
    names: ["plausibleYear", "leadingYear"],
  },
] as const;

/** `[clause, path]` for every `import ... from` and `export ... from`. */
function bindings(source: string): [string, string, string][] {
  return [
    ...source.matchAll(
      /\b(import|export)\b\s*(?:type\s*)?\{([^}]*)\}\s*from\s*"([^"]+)"/g,
    ),
  ].map(([, kind, clause, path]) => [kind!, clause!, path!]);
}

/** Whether a clause names one of the vocabulary a home declares. */
function names(clause: string, home: readonly string[]): boolean {
  return home.some((name) => new RegExp(`\\b${name}\\b`).test(clause));
}

function modules(): [string, string][] {
  return Object.entries(SOURCES).map(([path, source]) => [
    path.replace("../../src/", ""),
    source,
  ]);
}

/**
 * Whether a specifier names a given module, extension or not.
 *
 * **One predicate for every use, because they fail in opposite directions.**
 * Asking `endsWith("/fileReaders")` reports a legitimate import as an offender
 * when the path carries an extension, which is loud, and stops seeing a
 * re-export of the seam, which is silent and reopens the rename evasion below.
 * A guard with one fail open and one fail closed use of the same test is worth
 * fixing whatever the spelling's odds, and the odds are not long. Measured over
 * `src/`, occurrences rather than files, counting a relative specifier ending
 * `.ts`, `.tsx`, `.js` or `.jsx`: **305**, in 84 files, every one of them
 * generated under `api/generated/` and none elsewhere. `tsconfig.json` sets
 * `allowImportingTsExtensions`, so the spelling typechecks and a future author
 * has a working precedent in this tree to copy.
 *
 * **The pattern is stated because it is what the number turns on**, not the
 * range: the same question asked of `./` alone answers 292, and the 13 between
 * them are the `../` specifiers this predicate also has to accept.
 *
 * The exclusion, which is what one optional group buys over a list of suffixes:
 * a sibling module named `fileReaders.<word>` would read as the seam here. None
 * exists, and a name with two dots does not match.
 *
 * **Built from the module's own path rather than written out per home**, so a
 * third home cannot arrive with a predicate that is subtly a different
 * question. The basename is taken from the path in the table, which is the same
 * string the declaration arm reads the module by.
 */
function specifierFor(path: string): (from: string) => boolean {
  const basename = path
    .split("/")
    .pop()!
    .replace(/\.tsx?$/, "");
  return (from: string) => new RegExp(`/${basename}(\\.\\w+)?$`).test(from);
}

const isSeam = specifierFor(SEAM);

/** Every `import ... from` and `export ... from`, with its `type` marker. */
const FROM_CLAUSE =
  /\b(?:import|export)\b\s*(type\b\s*)?[^;]*?from\s*"([^"]+)"/g;

/** An `export ... from`, whether it names members or re-exports everything. */
const REEXPORT =
  /\bexport\b\s*(?:type\s*)?(?:\*|\{[^}]*\})\s*from\s*"([^"]+)"/g;

describe("the vocabulary the readers share", () => {
  it.each(SHARED_HOMES)(
    "declares its own vocabulary in $path and publishes it under no other name",
    (home) => {
      // The half an import rule cannot assert. A home re-exporting these from
      // somewhere else satisfies every import below while moving the declaration
      // back out, which is the whole of what the ticket behind this file did.
      // Measured: without this arm, moving all three to a new module and
      // re-exporting them at the seam goes green.
      const found = modules().find(([path]) => path === home.path);
      expect(found).toBeDefined();
      const source = found![1];

      for (const declaration of home.declarations) {
        expect(source).toContain(declaration);
      }
      // An anchor, because a home whose table row lost its declarations would
      // pass the loop above vacuously and every arm below with it.
      expect(home.declarations.length).toBeGreaterThan(0);
      // Declared, not passed through: an `export ... from` here would satisfy the
      // declarations above only if it also spelled the bodies, which it cannot.
      expect(
        bindings(source).filter(
          ([kind, clause]) => kind === "export" && names(clause, home.names),
        ),
      ).toEqual([]);

      // **And not re-published under a second name, which is the door with no
      // `from` in it.** `export { type FileMetadata as OpfRecord };` here
      // declares nothing, passes nothing through, and hands every reader the
      // format's name back: measured by the seat that did not write this arm,
      // one line added and `SUITE EXIT: 0` on 128 of 128. Neither the naming arm
      // below nor the import arm sees it, the first because a local alias is not
      // an `export <kind> <name>`, the second because a reader importing
      // `OpfRecord` names nothing this home declares and is filtered out before the
      // path test runs.
      //
      // **It belongs on this arm rather than in a further arm of its own**,
      // because this is the arm that already owns the question of what the seam
      // publishes as against what it declares. An alias is the third answer to
      // it, after the declaration and the re-export.
      //
      // **The `from` is captured and required absent, not excluded by a
      // lookahead.** `\}\s*(?!from)` reads correctly and is wrong: `\s*` gives
      // back the space it matched, the lookahead then sits on ` from` rather
      // than `from`, and every re-export matches too. Measured on all three
      // spellings: an alias, `export { X } from`, and `export type { X } from`.
      // Both patterns are quiet on the clean seam, so nothing here would have
      // failed and the arm would have been reporting the wrong door.
      //
      // **The one direction it is wrong in, stated so nobody loosens it away.**
      // The specifier is matched in double quotes only, so a re-export written
      // with single quotes carries no captured `from` and reads here as an
      // alias. That fires rather than passing, prettier settles the quoting, and
      // the fix if somebody ever meets it is the quote and not this pattern. The
      // same looseness costs one thing worth knowing, and it is two cases rather
      // than the one it is tempting to write down. This half reads the seam's
      // raw source, so the spelling fires from a comment AND from a string
      // literal: `// like export { X } here` and `const s = "export { X }";` are
      // both refused, measured, under this pattern and the one before it. So the
      // seam cannot document this rule by quoting what it forbids.
      //
      // **No `withoutProse` pass, deliberately.** Stripping comments the way
      // `houseRules.test.ts` does at its own copies would answer the first case
      // and not the second, and a guard that handles one of two spellings under
      // a name covering both is the shape this file keeps correcting. Zero
      // occurrences at the seam today, it fails loudly, and if one ever arrives
      // the answer is to decide between a strip and a bound rather than to
      // loosen the pattern.
      //
      // **No name in this half, which is what makes it name blind.** Not
      // structural, and the word matters: the keyword is still matched
      // lexically, which is why every pattern in this file spells it
      // `\bexport\b\s*` rather than `export\s+`. `export{a}` is valid
      // ECMAScript, and the `\s+` spelling let the alias below back in with the
      // space removed, measured green on all 11. Prettier would rewrite it and
      // `format:check` runs in CI, so it could not reach main by the ordinary
      // route, which is a different tool holding a rule this arm claims to hold.
      // The leading `\b` is the other half: without it `myexport {}` matched.
      //
      // Filtering it
      // by `names` the way the `bindings` half is filtered leaves an alias
      // OF a local alias open: `type SeamRecord = FileMetadata;` and then
      // `export { type SeamRecord as OpfRecord };` names none of the three,
      // declares nothing exportable, and was measured green on all 128. Asking
      // instead whether the seam publishes anything under a second name at all
      // closes that, and the alias of an alias of an alias with it, because no
      // name appears in the question.
      //
      // **The two halves are filtered differently because they ask different
      // questions.** `bindings` is about other modules, where an alias cannot be
      // resolved without following it, so there the clause has to name one of
      // the home's own. Here the module is reading itself, and it has no business
      // republishing anything of its own under a second name, which is what this
      // arm's title says.
      //
      // **The cost, stated because it is why somebody would narrow it back**, and
      // it is two spellings rather than one. A legitimate grouping,
      // `export { A, B };`, fails here, and the fix for it is to move `export`
      // onto the two declarations, which this arm's title asks for anyway. The
      // empty module marker, `export {};`, fails too and **has no such fix**,
      // since there is nothing to move `export` onto: a file with exports in it
      // never needs the marker, so the answer there is to delete it, and if a
      // future home genuinely needs one this arm is what has to change. There is
      // no `export {` in either home today, so nothing pays either today.
      const republishedLocally = [
        ...source.matchAll(
          /\bexport\b\s*(?:type\s*)?\{([^}]*)\}\s*(from\s*"[^"]+")?/g,
        ),
      ]
        .filter(([, , from]) => from === undefined)
        .map(([whole]) => whole.trim());

      expect(republishedLocally).toEqual([]);
    },
  );

  it.each(SHARED_HOMES)(
    "is the only route to what it declares, for $path",
    (home) => {
      // The three names above were declared in `lib/opf.ts`, under two other
      // spellings, so five modules that parse no package document imported the
      // EPUB half of the app to say what a book is, and the author of a sixth
      // reader would have had to do the same.
      //
      // **The rule is the home and not one forbidden module**, which is the
      // correction that bought this arm. Its first draft asserted the set of
      // modules importing `lib/opf`, and that is a rule about one path: adding
      // `export type { FileMetadata } from "./fileReaders"` to `lib/epub.ts` and
      // pointing `pdf.ts` at `./epub` restores exactly the defect this ticket
      // removed, through a module named for a format, and measured green on all
      // 427 tests. Asking where each name comes FROM closes the family, because a
      // reader has to name some path and only one of them passes.
      //
      // **Derived from the identifier and not from a list of modules**: a sixth
      // reader naming any of the three joins this rule with no edit here, and a
      // module that stops using them leaves it the same way.
      //
      // **The second door is a re-export, and it is closed structurally rather
      // than by name.** Asking only where the three names come from leaves the
      // rule one token short: `export { type FileMetadata as BookRecord } from
      // "./fileReaders";` in `epub.ts` passes the path test, and `import type {
      // BookRecord } from "./epub";` in `pdf.ts` then names none of the three, so
      // the defect returns through a module named for a format with every arm
      // green. So no module but a home may re-export from that home at all,
      // whatever it calls what it takes: that enumerates no name and needs no edit
      // when a fourth shared thing is added.
      //
      // **Run once per home rather than once for the seam**, because the entity
      // refusal is reached by the same two doors: `export { declaresEntities }
      // from "./xmlEntities";` in `epub.ts` and three readers pointed at `./epub`
      // is the same defect one module over.
      //
      // **Matched on import syntax rather than on the word**, so a docstring
      // naming `FileMetadata` is not an offender, which several are. The exclusion,
      // stated because it costs a different instrument to close: a local alias,
      // `import { type FileMetadata } from "./fileReaders"; export type BookRecord =
      // FileMetadata;`, is not an `export ... from` and no import syntax matcher
      // sees it. What this closes is the direct import and the re-export, which
      // are what a reader writes.
      const isHome = specifierFor(home.path);

      const reachedFromElsewhere = ([path, source]: [string, string]) =>
        bindings(source)
          .filter(([, clause]) => names(clause, home.names))
          .filter(([, , from]) => !isHome(from))
          .map(([, , from]) => `${path} <- ${from}`);

      const republished = ([path, source]: [string, string]) =>
        [...source.matchAll(REEXPORT)]
          .filter(([, from]) => isHome(from!))
          .map(([, from]) => `${path} re-exports ${from}`);

      const elsewhere = modules().filter(([path]) => path !== home.path);
      // An anchor, because a rule over a population nothing selects passes for
      // ever: every one of these names is imported somewhere today, and a
      // predicate that stopped matching would report no offenders rather than no
      // importers.
      expect(
        elsewhere.filter(([, source]) =>
          bindings(source).some(([, clause]) => names(clause, home.names)),
        ).length,
      ).toBeGreaterThan(0);

      const offenders = elsewhere
        .flatMap((entry) => [
          ...reachedFromElsewhere(entry),
          ...republished(entry),
        ])
        .sort();

      expect(offenders).toEqual([]);
    },
  );

  it("is named for the family and never for a module that imports it", () => {
    // The defect this closes shipped once and was argued for in
    // `docs/decisions.md`: the record every reader answers with was
    // `OpfRecord`, declared here, while `opf.ts` is the only module in the
    // family that parses a package document at all. The argument for keeping
    // that name rested on one field, `version`, the `package` element's own
    // attribute and the only value in the record copied verbatim from a
    // package document. It had six write sites and no read, so the name rested
    // on a field nothing consulted.
    //
    // **Derived from the import graph, so it enumerates no format and no
    // spelling.** A module that imports the seam is by construction one the
    // seam must not be named after: the shared vocabulary cannot be named for
    // one of its own consumers. A seventh reader joins this rule by importing,
    // and a module that stops importing leaves it, neither needing an edit
    // here. A list of format names would have needed one for `.opf`, which is
    // not an extension the picker supports and would not have been on it.
    //
    // **Both halves of the file's own vocabulary**, exported declarations and
    // the fields of its interfaces, because `version` was a field rather than a
    // declaration and the same defect one level down is worth no less.
    //
    // **What it holds is a name against the modules importing this one, and
    // not against the idea of a format.** So it refuses only a name sharing a
    // substring with an importer's basename: `OpfRecord`, `EpubRecord`,
    // `CalibreMetadata`, `opfVersion`. A format named in any other way passes,
    // and `packageVersion`, `ComicInfoRecord`, `FictionBookRecord` and
    // `XmpRecord` all do. Measured by the seat that did not write this, one
    // mutation each: `readonly packageVersion` at `SUITE EXIT: 0` against
    // `readonly opfSeriesIndex` at `SUITE EXIT: 1`, this arm named. That gap is
    // not closable by a further arm, since the set of ways to spell a format is
    // open, and the reason the rule is worth having anyway is that the module
    // is where a format's name comes from: somebody naming this after OPF is
    // reading `opf.ts` while they do it. **`packageVersion` is the spelling to
    // hold against, because it is the one the four deleted comments used.**
    //
    // **The direction it is wrong in.** A future reader module whose basename
    // is a substring of an honest name here, `record.ts` say, makes this refuse
    // a name that is fine. That fails loudly and is a visit, where the reverse
    // is a format's name sitting at the seam with nothing red. Written down so
    // that whoever it fires on widens the seam's name rather than narrowing
    // this.
    //
    // **Nor does it hold that every field here has a reader**, which is the
    // other half of the ticket that bought it. A rule saying so would fail
    // today on `identifiers`, which has six write sites and no read off the
    // record, and whether that field goes is a decision about information a
    // file supplied rather than about a name.
    const seam = modules().find(([path]) => path === SEAM)![1];

    const importers = modules()
      .filter(([path]) => path !== SEAM)
      .filter(([, source]) =>
        [...source.matchAll(FROM_CLAUSE)].some(([, , from]) => isSeam(from!)),
      )
      .map(([path]) =>
        path
          .split("/")
          .pop()!
          .replace(/\.tsx?$/, ""),
      );
    // A derivation that selected nothing would make the assertion below pass
    // for ever, and `opf.ts` is the module this rule exists for.
    expect(importers).toContain("opf");

    const declared = [
      // **Modifiers between `export` and the kind, because there are several
      // and `async` is already one of them.** Without it `export async
      // function readerFor` is not a declared name here, and the anchor below
      // is what says so rather than a reading of this line. The list of kinds
      // is an enumeration and is the known weak shape of this half; the three
      // anchors are what stop it going quiet.
      ...[
        ...seam.matchAll(
          /export\s+(?:(?:default|declare|abstract|async)\s+)*(?:interface|type|function|const|let|var|class|enum)\s+(\w+)/g,
        ),
      ],
      // `readonly` optional, because it is a modifier rather than the
      // declaration: every field here carries it today and a field written
      // without it would otherwise be invisible to this half.
      ...[...seam.matchAll(/^\s+(?:readonly\s+)?(\w+)\??:/gm)],
    ].map(([, name]) => name!);
    // **One anchor per arm and not one for the file**, because the arms rot
    // separately and any single anchor leaves the others free to stop matching
    // with nothing red: `FileMetadata` is the plain declaration, `readerFor`
    // the one behind a modifier, `identifiers` a field. Measured by the seat
    // that did not write this: with `FileMetadata` alone, an offending field
    // written without `readonly` went green.
    expect(declared).toContain("FileMetadata");
    expect(declared).toContain("readerFor");
    expect(declared).toContain("identifiers");

    const offenders = declared
      .filter((name) =>
        importers.some((module) =>
          name.toLowerCase().includes(module.toLowerCase()),
        ),
      )
      .sort();

    expect(offenders).toEqual([]);
  });

  it("reaches the rest of the app eagerly through one module only", () => {
    // What keeps the graph acyclic, asserted because today it is an accident.
    // `ScanPage/hooks.ts` imports `readerFor` as a value, so there is a runtime
    // edge into the seam from outside the family, and moving `declaresEntities`
    // to `lib/xmlEntities.ts` removed the one that ran from inside it. Nothing
    // breaks only because every edge the other way is erased or deferred: the
    // failure types are `import type` and the registry loads each reader with
    // `await import`. One ordinary import added here closes a cycle, and no
    // other test in this tree goes red when it does.
    //
    // **Stated as the exclusion and not as a list of readers**, which is the
    // correction that bought this wording. Its first draft forbade only the
    // modules the registry loads with `import()`, and `opf.ts` is not one of
    // them: `import { readOpf } from "./opf";` closed opf into a cycle with the
    // arm green. `calibre.ts` and `zip.ts` were open the same way. The rule is
    // now the file's own property, one eager relative import, so a module that
    // never joins the registry is covered too.
    //
    // **The edge is refused whatever it carries**, because what a cycle costs
    // is decided by the binding and not by the edge: `readOpf` is a hoisted
    // function declaration and survives one, while `opf.ts`'s module scope
    // `const OPF_NAMESPACE` read from inside the same cycle is in its temporal
    // dead zone. A rule that asked which binding was imported would be asking
    // after the edge already existed.
    //
    // **`./fileName` is named rather than counted**, so adding a second eager
    // import is a decision somebody makes here rather than a number that drifts.
    //
    // The exclusion: an inline `import { type X }` is not read as type only, and
    // none is written that way in this file. A bare specifier is a package and
    // cannot close a cycle in this tree, so only relative paths are asked about.
    const seam = modules().find(([path]) => path === SEAM)![1];
    const statements = [...seam.matchAll(FROM_CLAUSE)];
    // A regex that matched nothing would make the assertion below pass for ever.
    expect(statements.length).toBeGreaterThan(0);

    const eager = statements
      .filter(([, isType, from]) => !isType && from!.startsWith("."))
      .map(([, , from]) => from!)
      .filter((from) => from !== "./fileName");

    expect(eager).toEqual([]);
  });

  it("gives the entity refusal a home that depends on nothing", () => {
    // The same rule as the arm above, one module over and stronger, because
    // this one can be: the refusal is a substring test over a string and needs
    // neither the seam nor a reader. A module with no edges out cannot be in a
    // cycle at all, so the four readers that call it can import it eagerly
    // whatever else they import.
    //
    // **Its own anchor rather than the arm above's**, because a pattern that
    // stopped matching would report an empty list here and pass. Asked of a
    // literal, so the anchor holds whatever the tree does.
    expect([...'import x from "./y";'.matchAll(FROM_CLAUSE)]).toHaveLength(1);

    const guard = modules().find(([path]) => path === ENTITY_GUARD)![1];

    expect([...guard.matchAll(FROM_CLAUSE)].map(([, , from]) => from)).toEqual(
      [],
    );
    // **And the import with no clause in it**, which is an eager edge that no
    // `from` matcher sees: `import "./fileReaders";` measured green here by the
    // design seat before this line. It is the spelling a cycle would arrive
    // through if somebody wanted the seam's module scope run first, so the arm
    // above claimed more than it checked.
    expect([...guard.matchAll(/^\s*import\s*"[^"]+"/gm)]).toEqual([]);
    // **And a top level `await import`, which is an eager edge with a call in
    // it**: measured green by the design seat against the two matchers above,
    // and prettier leaves it alone, so nothing else in this tree would have
    // caught it.
    expect([...guard.matchAll(/\bawait\s+import\s*\(/g)]).toEqual([]);
    // **The one spelling all three still miss, stated rather than chased.** A
    // side effect import sharing a line with another statement,
    // `const x = 0;import "./fileReaders";`, defeats the `^\s*` anchor.
    // Prettier splits that line and `format:check` runs in CI, so what closes
    // it is a different tool holding a rule this arm claims, and the honest
    // reading is that these three matchers cover what an author writes.
  });
});

/**
 * What a reader may label an identifier with, and why a page sending none cares.
 *
 * **The decision this guards is `ScanPage/types.draftFromFile`'s**, which puts
 * ten of `FileMetadata`'s eleven fields into a request and sends no
 * `identifiers`. That docstring is the one home of the decision and of the
 * measurement; what it rests on is a property of this family, and a property is
 * a thing a test can hold. A reader that starts labelling a store's identifier
 * makes that decision wrong, and nothing else in the tree would say so.
 *
 * **What an author does when this fires** depends on which way it fired. A new
 * member of `BookIdentifierScheme` forbids every reader here from writing that
 * spelling at once, which is right while no reader produces one; a reader that
 * genuinely produces a store's identifier is the case the decision was taken
 * against, so the answer is to reopen it at `draftFromFile` rather than to
 * widen anything here.
 *
 * **The family is the registry plus whoever names `FileIdentifier`**, so a
 * sixth reader is covered by being registered, by naming the type, or by both.
 * Measured by the design seat against the naming half alone: dropping the
 * import and the return annotation from `mobi.ts` and labelling `"asin"` went
 * green on 19 of 19. The exclusion, stated as what is left out: a module more
 * than one relative import from a registered reader, by either spelling of an
 * import, which nothing is today.
 *
 * **Three costs of reading the source rather than the values**, all loud rather
 * than silent. A `scheme` in a parameter list or a destructuring reads here as
 * a property; a whole line `//` comment is stripped and a trailing one is not,
 * so this rule cannot be documented by writing `{ scheme: "asin" }` after code
 * on one line; and a shorthand is reported as a computed scheme, because what
 * the binding holds is not in this file's reach.
 */
const STORED_SCHEMES = Object.values(BookIdentifierScheme).map((scheme) =>
  scheme.toLowerCase(),
);

/**
 * Readers whose scheme is an expression, and what each one can produce.
 *
 * Required to be exactly the set of readers that compute one, in both
 * directions: a new computed scheme is a decision somebody states here, and a
 * row for a reader that stopped computing one is a claim about code that no
 * longer exists.
 *
 * **What holds a row's words is that reader's own tests and not this table**,
 * whose values are free text nothing reads. Measured by the design seat:
 * `opf.ts` labelling through a constant is caught by `tests/lib/opf.test.ts`,
 * two arms, and `pdf.ts` by `tests/lib/pdf.test.ts > labels an identifier that
 * is not an ISBN with no scheme`, 1 of 3667. A sixth reader added here with a
 * sentence and no such test has nothing holding it.
 */
const COMPUTES_ITS_SCHEME: Record<string, string> = {
  "lib/opf.ts":
    "the file's own label, `opf:scheme` or an `identifier-type` refinement. " +
    "This is the free text the scan flow's decision is about.",
  "lib/pdf.ts":
    "`ISBN` or nothing, decided by parsing the value, because XMP names no " +
    "scheme of its own.",
};

/** Block comments and whole line `//` comments removed. */
function withoutProse(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/**
 * A dynamic import's specifier, in either spelling of a string.
 *
 * One pattern for the registry and for a hop, because they are one question.
 * Quoting is settled by prettier and prettier is a formatter rather than a
 * guard, the same reason the site pattern reads a quoted key.
 */
const IMPORT_CALL = /\bimport\(\s*["']([^"']+)["']\s*\)/g;

/** A string literal and nothing else. */
const LITERAL = /^"[^"]*"$|^'[^']*'$/;

/**
 * The text of every `scheme` property value in a module, as it is written.
 *
 * Scanned to the comma that ends the property rather than matched, because the
 * value may be a call, a ternary or two lines of `??`, and a pattern for each
 * is the enumeration this file keeps correcting.
 *
 * **Four spellings of the key and not one**, two of which both critic seats
 * found independently and by the same mutation: `{ scheme, value }`,
 * `{ "scheme": label }` and `{ ["scheme"]: label }` label an identifier exactly
 * as `scheme:` does, and against the first draft a sixth reader writing
 * `const scheme = "asin"` one line above the shorthand passed 58 of 58. A
 * shorthand has no text to read, so it is reported as a computed scheme and
 * falls to the table below.
 *
 * **The quoted key is here because prettier is not a guard.** `quoteProps` is
 * unset in this repository, so the default `as-needed` rewrites that spelling
 * and `format:check` fails it; `preserve` would reopen the hole in a config
 * change nobody would read as one.
 */
function schemeSites(source: string): string[] {
  const clean = withoutProse(source);
  const sites: string[] = [];
  for (const match of clean.matchAll(
    /[{,]\s*(?:scheme\b|["']scheme["']|\[\s*["']scheme["']\s*\])\s*(?=[:,}])/g,
  )) {
    if (clean[match.index! + match[0].length] !== ":") {
      // A shorthand, `{ scheme, value }`: the label is a binding and what it
      // holds is somewhere else, so it is reported as computed rather than as
      // the empty text it looks like here.
      sites.push("scheme");
      continue;
    }
    const start = match.index! + match[0].length + 1;
    let depth = 0;
    let end = start;
    for (; end < clean.length; end++) {
      const character = clean[end]!;
      if ("([{".includes(character)) depth += 1;
      else if (")]}".includes(character)) {
        if (depth === 0) break;
        depth -= 1;
      } else if (character === "," && depth === 0) break;
    }
    sites.push(clean.slice(start, end).trim());
  }
  return sites;
}

/** The module a relative specifier written inside `lib/` names. */
function libModule(specifier: string): string {
  return `lib/${specifier
    .split("/")
    .pop()!
    .replace(/\.tsx?$/, "")}.ts`;
}

/**
 * Every module this rule is about: the readers the registry loads, whatever is
 * one relative import from one, and everything that names `FileIdentifier`.
 *
 * **Three routes because each is evadable alone.** Naming the type is a line an
 * author can delete, which is how a reader labelling `"asin"` went green on 19
 * of 19; the registry cannot be left, since a format nobody registers is a
 * format nobody can pick; and the hop is what reaches `opf.ts`, which is
 * registered through `epub.ts` rather than directly.
 *
 * **The two routes are anchored by what they contribute rather than by a module
 * name**, since without an anchor both could be deleted in silence: measured by
 * the design seat, the family reduced to the naming route alone passed 58 of
 * 58. `lib/epub.ts` is what they contribute today, it naming no
 * `FileIdentifier`, and naming it in the assertion is what would go stale.
 */
function labellingModules(): [string, string][] {
  const all = modules();
  const seam = all.find(([path]) => path === SEAM)![1];
  const registered = [...seam.matchAll(IMPORT_CALL)].map(([, specifier]) =>
    libModule(specifier!),
  );
  const oneHop = registered.flatMap((path) => {
    const source = all.find(([other]) => other === path)?.[1] ?? "";
    // **A hop is either spelling of an import**, and this is the one pattern
    // the registry is read with, not a second one: two patterns for one
    // question is how the looser half came to be widened alone. Measured by the
    // security seat: a labeller reached by
    // `const { labelFor } = await import("./x")` and writing `"asin"` passed 58
    // of 58 while the from clause half was already closed.
    return [
      ...[...source.matchAll(FROM_CLAUSE)].map(([, , from]) => from!),
      ...[...source.matchAll(IMPORT_CALL)].map(([, from]) => from!),
    ]
      .filter((from) => from.startsWith("."))
      .map(libModule);
  });
  const family = new Set([...registered, ...oneHop]);
  return all.filter(
    ([path, source]) =>
      family.has(path) ||
      bindings(source).some(
        ([, clause, from]) => isSeam(from) && names(clause, ["FileIdentifier"]),
      ),
  );
}

describe("what a reader may label an identifier", () => {
  it("scans a property and not a parameter, a comment or a type", () => {
    // Asked of literals, so the instrument is anchored whatever the tree does:
    // a scanner that stopped matching would report no offender below and pass
    // for ever.
    expect(schemeSites('const one = { scheme: "asin", value: v };')).toEqual([
      '"asin"',
    ]);
    expect(schemeSites("const two = { value: v, scheme: pick(v) };")).toEqual([
      "pick(v)",
    ]);
    expect(schemeSites("const three = { scheme, value };")).toEqual(["scheme"]);
    expect(
      schemeSites('const four = { ["scheme"]: "asin", value: v };'),
    ).toEqual(['"asin"']);
    // The spelling prettier rewrites, held here rather than by a formatter.
    expect(schemeSites('const five = { "scheme": "asin", value: v };')).toEqual(
      ['"asin"'],
    );
    expect(schemeSites("function f(scheme: string | null) {}")).toEqual([]);
    expect(schemeSites('/* scheme: "asin" */')).toEqual([]);
    expect(schemeSites("interface I {\n  readonly scheme: string;\n}")).toEqual(
      [],
    );
  });

  it("labels no identifier with a scheme this app stores", () => {
    const labelling = labellingModules();
    // Three anchors, because the two module routes and the scanner rot
    // separately. `opf.ts` is reached by the hop and by naming the type;
    // `mobi.ts` is registered under three keys and names it too; and the
    // scanner is the arm above's subject read against the real tree.
    expect(labelling.map(([path]) => path)).toContain("lib/opf.ts");
    expect(labelling.map(([path]) => path)).toContain("lib/mobi.ts");
    // **The anchor for the registry and the hop, and it names no module.** The
    // other two are satisfied by the naming route, so neither could hold these:
    // measured by the design seat, the family reduced to the naming route alone
    // passed 58 of 58 before this. Asked as "is anything here through a route
    // other than naming the type", because a module named instead goes stale in
    // one word: `epub.ts` is that module today and already imports
    // `FileMetadata` from the seam, so widening that one import line would move
    // it to the naming route and quietly stop it discriminating.
    //
    // **It holds the two routes together and neither half alone.** `oneHop`
    // derives from `registered`, so emptying the registry extraction empties
    // the family and this fires at 1 of 19, which measures the pair rather than
    // the registry: dropping the registry from the family with the hop intact
    // passes 19 of 19, and so does deleting the hop by itself. What holds each
    // route is the offender arm below, firing on a labeller that route reaches:
    // 1 of 19 for a labeller one import away, and 1 of 19 for a registered
    // module that labels. The middle number is the one a mutation of the
    // extraction cannot produce, since that mutation moves both.
    expect(
      labelling.filter(
        ([, source]) =>
          !bindings(source).some(
            ([, clause, from]) =>
              isSeam(from) && names(clause, ["FileIdentifier"]),
          ),
      ).length,
    ).toBeGreaterThan(0);
    expect(
      labelling.flatMap(([, source]) => schemeSites(source)).length,
    ).toBeGreaterThan(0);
    // The enum is read rather than spelled, so a member added to it widens this
    // without an edit here.
    expect(STORED_SCHEMES.length).toBeGreaterThan(0);

    const offenders = labelling.flatMap(([path, source]) =>
      schemeSites(source)
        .filter((site) =>
          STORED_SCHEMES.some((scheme) =>
            new RegExp(`["']${scheme}["']`, "i").test(site),
          ),
        )
        .map((site) => `${path}: ${site}`),
    );

    expect(offenders).toEqual([]);
  });

  it("computes a scheme only where the reader says what it can compute", () => {
    // What the arm above cannot reach: a computed scheme is a value this test
    // never sees, so the reader has to say what it can be. `opf.ts` says the
    // file, which is the case the scan flow's decision names.
    const computed = labellingModules()
      .filter(([, source]) =>
        schemeSites(source).some((site) => !LITERAL.test(site)),
      )
      .map(([path]) => path);

    expect(computed.sort()).toEqual(Object.keys(COMPUTES_ITS_SCHEME).sort());
  });
});
