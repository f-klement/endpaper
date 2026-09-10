import { describe, expect, it } from "vitest";

import { READERS, readerFor, type FileReader } from "../../src/lib/fileReaders";
import {
  FORMAT_FOR_EXTENSION,
  SUPPORTED_EXTENSIONS,
} from "../../src/lib/fileName";
import { BookFormat } from "../../src/api/generated/model";

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

/** The three names the reader family shares, which `fileReaders.ts` declares. */
const SHARED = ["OpfRecord", "OpfIdentifier", "declaresEntities"];

/** `[clause, path]` for every `import ... from` and `export ... from`. */
function bindings(source: string): [string, string, string][] {
  return [
    ...source.matchAll(
      /(import|export)\s+(?:type\s+)?\{([^}]*)\}\s*from\s*"([^"]+)"/g,
    ),
  ].map(([, kind, clause, path]) => [kind!, clause!, path!]);
}

/** Whether a clause names one of the shared three. */
function namesShared(clause: string): boolean {
  return SHARED.some((name) => new RegExp(`\\b${name}\\b`).test(clause));
}

function modules(): [string, string][] {
  return Object.entries(SOURCES).map(([path, source]) => [
    path.replace("../../src/", ""),
    source,
  ]);
}

const SEAM = "lib/fileReaders.ts";

/**
 * Whether a specifier names the seam, extension or not.
 *
 * **One predicate for both uses, because the two fail in opposite directions.**
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
 */
const isSeam = (from: string) => /\/fileReaders(\.\w+)?$/.test(from);

/** Every `import ... from` and `export ... from`, with its `type` marker. */
const FROM_CLAUSE = /(?:import|export)\s+(type\s+)?[^;]*?from\s*"([^"]+)"/g;

/** An `export ... from`, whether it names members or re-exports everything. */
const REEXPORT = /export\s+(?:type\s+)?(?:\*|\{[^}]*\})\s*from\s*"([^"]+)"/g;

describe("the vocabulary the readers share", () => {
  it("is declared at the seam and nowhere else", () => {
    // The half an import rule cannot assert. `fileReaders.ts` re-exporting these
    // from somewhere else satisfies every import below while moving the
    // declaration back out of the seam, which is the whole of what this ticket
    // did. Measured: without this arm, moving all three to a new module and
    // re-exporting them here goes green.
    const seam = modules().find(([path]) => path === SEAM);
    expect(seam).toBeDefined();
    const source = seam![1];

    expect(source).toContain("export interface OpfRecord {");
    expect(source).toContain("export interface OpfIdentifier {");
    expect(source).toContain("export function declaresEntities(");
    // Declared, not passed through: an `export ... from` here would satisfy the
    // three above only if it also spelled the bodies, which it cannot.
    expect(
      bindings(source).filter(
        ([kind, clause]) => kind === "export" && namesShared(clause),
      ),
    ).toEqual([]);
  });

  it("is imported from the seam by everything that uses it", () => {
    // `OpfRecord`, `OpfIdentifier` and `declaresEntities` were declared in
    // `lib/opf.ts`, so five modules that parse no package document imported the
    // EPUB half of the app to say what a book is, and the author of a sixth
    // reader would have had to do the same.
    //
    // **The rule is the seam and not one forbidden module**, which is the
    // correction that bought this arm. Its first draft asserted the set of
    // modules importing `lib/opf`, and that is a rule about one path: adding
    // `export type { OpfRecord } from "./fileReaders"` to `lib/epub.ts` and
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
    // rule one token short: `export { type OpfRecord as BookRecord } from
    // "./fileReaders";` in `epub.ts` passes the path test, and `import type {
    // BookRecord } from "./epub";` in `pdf.ts` then names none of the three, so
    // the defect returns through a module named for a format with every arm
    // green. So no module but the seam may re-export from the seam at all,
    // whatever it calls what it takes: that enumerates no name and needs no edit
    // when a fourth shared thing is added.
    //
    // **Matched on import syntax rather than on the word**, so a docstring
    // naming `OpfRecord` is not an offender, which several are. The exclusion,
    // stated because it costs a different instrument to close: a local alias,
    // `import { type OpfRecord } from "./fileReaders"; export type BookRecord =
    // OpfRecord;`, is not an `export ... from` and no import syntax matcher
    // sees it. What this closes is the direct import and the re-export, which
    // are what a reader writes.
    const reachedFromElsewhere = ([path, source]: [string, string]) =>
      bindings(source)
        .filter(([, clause]) => namesShared(clause))
        .filter(([, , from]) => !isSeam(from))
        .map(([, , from]) => `${path} <- ${from}`);

    const republished = ([path, source]: [string, string]) =>
      [...source.matchAll(REEXPORT)]
        .filter(([, from]) => isSeam(from!))
        .map(([, from]) => `${path} re-exports ${from}`);

    const offenders = modules()
      .filter(([path]) => path !== SEAM)
      .flatMap((entry) => [
        ...reachedFromElsewhere(entry),
        ...republished(entry),
      ])
      .sort();

    expect(offenders).toEqual([]);
  });

  it("reaches the rest of the app eagerly through one module only", () => {
    // What keeps the graph acyclic, asserted because today it is an accident.
    // `opf.ts` imports `declaresEntities` from here as a value, so there is a
    // runtime edge from a reader's dependency into the seam. Nothing breaks
    // only because every edge the other way is erased or deferred: the failure
    // types are `import type` and the registry loads each reader with `await
    // import`. One ordinary import added here closes a cycle, and no other test
    // in this tree goes red when it does.
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
});
