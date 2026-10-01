/**
 * @vitest-environment node
 *
 * Reads sources as text and calls pure functions. No DOM, and building a
 * jsdom costs more than this file spends running.
 */
/**
 * Tests for tests/sourceModules.ts.
 *
 * **A glob cannot be narrowed at run time**, because a pattern is resolved
 * when the module is transformed. That is why every previous attempt at this
 * rule was closed against the one narrowing somebody had demonstrated: the
 * only way to show an arm working was to edit the pattern by hand, so only
 * the shape already in view got an arm.
 *
 * **So the arming is a pure function over a corpus, and the narrowings are
 * fixtures.** Each one below is a way of shrinking the tree that keeps
 * whatever the previous round's arm looked at, and each is driven here rather
 * than described.
 */

import { describe, expect, it } from "vitest";

import {
  NOT_MODULES,
  TOP_LEVEL,
  armingFailures,
  modulesUnder,
  sourceEntries,
  sourceModules,
  sourceText,
  stylesheetText,
  type Corpus,
} from "./sourceModules";

/**
 * A tree with one file in every top level entry the real one has.
 *
 * Built against the stated lists rather than against `src/`, so these arms
 * say what the check does and not what the tree holds today.
 */
const INTACT = [
  "api/books.ts",
  "app/App.tsx",
  "components/Button.tsx",
  "i18n/en.ts",
  "index.css",
  "lib/zip.ts",
  "main.tsx",
  "pages/Home/Home.tsx",
  "theme/palettes.ts",
  "theme/palettes.css",
  "vite-env.d.ts",
];

const isModule = (path: string) => /\.tsx?$/.test(path);

/**
 * The three patterns the rules carried before the module under test existed.
 *
 * **A second home for a pattern, and it is the point rather than an
 * oversight.** Every enumeration `sourceModules.ts` arms against is written
 * inside that file, so one editor narrowing all of them in one diff is
 * refused by nothing in there. These are outside it, and they are the
 * patterns those rules each used to carry: what the rules walk now has to
 * equal what their own pattern matched, and the two edits are in two files.
 *
 * Names only, so nothing is read and nothing is inlined into this bundle.
 */
const AS_THE_RULES_GLOBBED_IT = import.meta.glob("../src/**/*.{ts,tsx}");
const AS_THE_LIB_RULES_GLOBBED_IT = import.meta.glob("../src/lib/*.ts");
const AS_THE_STYLESHEET_RULES_GLOBBED_IT = import.meta.glob("../src/**/*.css");

/**
 * The tree with no extension on the pattern at all.
 *
 * **The one thing the module under test cannot check for itself.** Three of
 * its four enumerations are unrestricted, and restricting all three to the
 * extensions the tree holds today is a no op: they would still agree, both
 * stated lists would still hold, and the map handed over would be byte
 * identical. The first image added under `src/` would then be seen by none of
 * them, which is the event the unrestricted sweep is there to catch.
 *
 * So the question is asked from outside, over the exported surface alone:
 * every file under `src/` is a module the rules are given, or a file named as
 * not one. Sound by the module's own two facts and blind to neither half.
 */
const WITH_NO_EXTENSION_AT_ALL = import.meta.glob("../src/**/*");

const below = (keys: Record<string, unknown>): string[] =>
  Object.keys(keys)
    .map((path) => path.replace("../src/", ""))
    .sort();

/** A corpus whose four enumerations all agree, which is the honest case. */
function corpusOf(files: string[]): Corpus {
  return {
    named: files,
    decomposed: files,
    moduleKeys: files.filter(isModule),
    stylesheetKeys: files.filter((path) => path.endsWith(".css")),
  };
}

/** The one failure a fixture is meant to produce, refusing two. */
function soleFailure(corpus: Corpus): string {
  const failures = armingFailures(corpus);
  expect(failures).toHaveLength(1);
  return failures[0]!;
}

describe("the corpus this tree states", () => {
  it("names every top level entry of the tree it stands for", () => {
    // The fixtures above are only evidence while they are a whole tree. A
    // list that had fallen behind `TOP_LEVEL` would make every narrowing
    // below red for the wrong reason, which is a suite that passes while
    // measuring nothing.
    const tops = [...new Set(INTACT.map((path) => path.split("/")[0]))].sort();

    expect(tops).toEqual([...TOP_LEVEL].sort());
  });

  it("carries each file that is not a module", () => {
    expect(INTACT.filter((path) => !isModule(path)).sort()).toEqual(
      [...NOT_MODULES].sort(),
    );
  });

  it("is accepted whole", () => {
    expect(armingFailures(corpusOf(INTACT))).toEqual([]);
  });
});

describe("a corpus narrowed by extension", () => {
  it("is refused when the stylesheets go with it", () => {
    // The first narrowing this rule met: `**/*.{ts,tsx}` cut to `**/*.ts`.
    // It keeps two thirds of the real tree, which is why the count that
    // guarded it first saw nothing.
    const narrowed = INTACT.filter((path) => path.endsWith(".ts"));

    expect(narrowed).not.toEqual([]);
    expect(armingFailures(corpusOf(narrowed)).join("\n")).toContain(
      "NOT_MODULES",
    );
  });

  it("is refused when only one language of module is lost", () => {
    // The same narrowing written so that the stylesheets survive it, which
    // is what an arm reading the non module files alone would accept.
    //
    // **Two failures rather than one, and both are asserted.** The languages
    // check is the one that holds on the live tree: there, cutting `.tsx`
    // leaves every directory populated and the top level check survives on
    // `main.tsx` alone, a single root file nobody chose for the job. This
    // fixture is smaller than the tree, so it loses whole entries as well.
    const narrowed = INTACT.filter(
      (path) => !path.endsWith(".tsx") || !isModule(path),
    );
    const failures = armingFailures(corpusOf(narrowed)).join("\n");

    expect(narrowed.filter(isModule)).not.toEqual([]);
    expect(failures).toContain("lost a language");
    expect(failures).toContain("top level entries");
  });

  it("is refused for the language where no directory empties", () => {
    // **The live mechanism, which the fixture above does not model.** On the
    // real tree every top level directory holds `.ts` as well, so cutting
    // `.tsx` empties none of them: `pages` keeps 55 modules while losing 126.
    // What the top level check has left to report there is `main.tsx`, one
    // root file, and spelled `main.ts` it would report nothing at all. So
    // this gives every directory a `.ts` sibling and asserts both halves:
    // the languages check names the cause, and the partition is down to that
    // single file.
    const narrowed = [
      ...INTACT,
      "app/routes.ts",
      "components/Button.helpers.ts",
      "pages/Home/hooks.ts",
    ].filter((path) => !path.endsWith(".tsx"));
    const emptied = [...TOP_LEVEL].filter(
      (entry) =>
        entry.includes(".") === false &&
        !narrowed.some((path) => path.startsWith(`${entry}/`)),
    );
    const failures = armingFailures(corpusOf(narrowed)).join("\n");

    expect(emptied).toEqual([]);
    expect(failures).toContain("lost a language");
    expect(failures).toContain('lost ["main.tsx"]');
  });
});

describe("a corpus narrowed by directory", () => {
  it("is refused although both languages and both stylesheets survive", () => {
    // **The evasion that survived the extension arm.** Dropping the pages
    // and the components keeps `.ts` and `.tsx` in the corpus, keeps every
    // file the rules exempt by name, and removes the two directories where a
    // violation is actually written. Measured on the live rule it was found
    // in: exit 0 with a real violation in the tree.
    const narrowed = INTACT.filter(
      (path) => !path.startsWith("pages/") && !path.startsWith("components/"),
    );
    const extensions = new Set(
      narrowed.filter(isModule).map((path) => path.split(".").pop()),
    );

    expect([...extensions].sort()).toEqual(["ts", "tsx"]);
    expect(narrowed.filter((path) => !isModule(path)).sort()).toEqual(
      [...NOT_MODULES].sort(),
    );
    expect(soleFailure(corpusOf(narrowed))).toContain(
      'lost ["components","pages"]',
    );
  });

  it("is refused when one directory is dropped and nothing else moves", () => {
    const narrowed = INTACT.filter((path) => !path.startsWith("api/"));

    expect(soleFailure(corpusOf(narrowed))).toContain('lost ["api"]');
  });
});

describe("a corpus whose enumerations disagree", () => {
  it("is refused when the per directory sweep is the narrow one", () => {
    // The second derivation doing its job: the recursive pattern is whole
    // and one of the patterns checked against it is not.
    const corpus = corpusOf(INTACT);
    corpus.decomposed = INTACT.filter((path) => !path.startsWith("pages/"));

    expect(soleFailure(corpus)).toContain("the two enumerations");
  });

  it("is refused when the recursive sweep is the narrow one", () => {
    const corpus = corpusOf(INTACT.filter((path) => !path.startsWith("app/")));
    corpus.decomposed = INTACT;

    expect(armingFailures(corpus).join("\n")).toContain("the two enumerations");
  });

  it("is refused when the sweep the rules read is the narrow one", () => {
    // The shape that costs the most and shows the least: the names are the
    // whole tree, so every arm about the tree passes, and the text the rules
    // actually walk is a subset of it.
    const corpus = corpusOf(INTACT);
    corpus.moduleKeys = corpus.moduleKeys.filter(
      (path) => !path.startsWith("pages/"),
    );

    expect(soleFailure(corpus)).toContain("the module half");
  });

  it("is refused when the stylesheet sweep is the narrow one", () => {
    const corpus = corpusOf(INTACT);
    corpus.stylesheetKeys = ["theme/palettes.css"];

    expect(soleFailure(corpus)).toContain("the stylesheet sweep");
  });
});

describe("a kind of file nobody has classified", () => {
  it("is refused rather than swept into the module corpus", () => {
    // Placed inside an existing directory on purpose, so the top level check
    // is silent and this is the only thing that speaks.
    const corpus = corpusOf([...INTACT, "theme/logo.svg"]);

    expect(soleFailure(corpus)).toContain("NOT_MODULES");
  });
});

describe("the tree as this module hands it over", () => {
  it("arms against the real corpus", () => {
    expect(() => sourceModules()).not.toThrow();
  });

  it("is the corpus the rules' own pattern matched", () => {
    // The population comparison, kept rather than run once: ten rules each
    // walked that pattern, and an extraction that quietly moved what they
    // see is the failure this whole module is about.
    expect(
      Object.keys(sourceModules()).sort(),
      "the rules are not walking the tree their own pattern matched: one of " +
        "the patterns in tests/sourceModules.ts has moved, or this one has",
    ).toEqual(below(AS_THE_RULES_GLOBBED_IT));
  });

  it("is the lib corpus the two lib rules' own pattern matched", () => {
    // **The two are not the same rule and agree today.** That pattern took
    // `.ts` one level down; a directory corpus takes every module under the
    // directory. A `.tsx` or a subdirectory added under `src/lib/` reddens
    // here, which is the right place for somebody to decide whether the two
    // rules should see it.
    expect(
      modulesUnder("lib")
        .map(([path]) => path)
        .sort(),
    ).toEqual(below(AS_THE_LIB_RULES_GLOBBED_IT));
  });

  it("holds every file under src, whatever its extension", () => {
    // **The arm the module under test cannot write for itself.** Its three
    // unrestricted patterns can all be restricted to the extensions the tree
    // holds today with nothing red and the same map handed over, and then the
    // first image under `src/` is invisible to every one of them. This asks
    // the question with no extension in the pattern at all, over the exported
    // surface only: a file here is a module the rules are given, or it is
    // named as not one.
    const modules = sourceModules();
    const unclassified = Object.keys(WITH_NO_EXTENSION_AT_ALL)
      .map((path) => path.replace("../src/", ""))
      .filter((path) => !(path in modules) && !NOT_MODULES.includes(path))
      .sort();

    expect(
      unclassified,
      "a file under src/ that the rules are not given and NOT_MODULES does " +
        "not name: either a pattern in tests/sourceModules.ts was narrowed " +
        "by extension, or a new kind of file needs naming there",
    ).toEqual([]);
  });

  it("is the stylesheets the palette rules' own pattern matched", () => {
    // **Filtered to the stylesheet suffix, and that is not tidiness.** The
    // remedy the module states for a new kind of file under `src/` is to name
    // it in `NOT_MODULES`. Compared whole, this arm pins that list to the
    // stylesheets, so following the remedy exactly left this red with the new
    // file in the list and no edit anywhere could clear it.
    expect(
      [...NOT_MODULES].filter((path) => path.endsWith(".css")).sort(),
    ).toEqual(below(AS_THE_STYLESHEET_RULES_GLOBBED_IT));
  });

  it("hands back the text of a module and not its name", () => {
    expect(sourceText("lib/zip.ts")).toContain("export type ZipFailure");
  });

  it("refuses a module it does not hold, rather than answering nothing", () => {
    // A lookup defaulting to the empty string turns a renamed module into a
    // rule reading a file with no violations in it, which is green.
    expect(() => sourceText("lib/notAModule.ts")).toThrow("lib/notAModule.ts");
  });

  it("hands back a stylesheet, and refuses one it does not hold", () => {
    expect(stylesheetText("index.css")).toContain("@import");
    expect(() => stylesheetText("theme/none.css")).toThrow("theme/none.css");
  });

  it("puts every module in exactly one top level directory or at the root", () => {
    // That the prefix walk is total, which is what makes a directory corpus
    // a partition of the armed one rather than a second pattern.
    const directories = [
      ...new Set(
        sourceEntries()
          .map(([path]) => path.split("/")[0]!)
          .filter((top) => !isModule(top)),
      ),
    ];
    const gathered = directories.flatMap((directory) =>
      modulesUnder(directory).map(([path]) => path),
    );
    const atTheRoot = sourceEntries()
      .map(([path]) => path)
      .filter((path) => !path.includes("/"));

    expect([...gathered, ...atTheRoot].sort()).toEqual(
      sourceEntries()
        .map(([path]) => path)
        .sort(),
    );
    expect(atTheRoot).not.toEqual([]);
  });

  it("refuses a prefix that is not a directory of the tree", () => {
    // Including a top level file, whose prefix matches nothing: silence is
    // the answer this module exists to refuse.
    expect(() => modulesUnder("index.css")).toThrow("not a directory");
    expect(() => modulesUnder("lib/sql")).toThrow("not a directory");
  });
});
