/**
 * @vitest-environment node
 *
 * Reads sources as text and calls pure functions. No DOM, and building one
 * costs more than this file spends running.
 */
/**
 * Tests for tests/testModules.ts.
 *
 * **A glob cannot be narrowed at run time**, because a pattern is resolved
 * when the module is transformed. So the arming is a pure function over a
 * corpus and the narrowings are fixtures, which is the arrangement
 * `tests/sourceModules.test.ts` argues for and this file does not restate.
 *
 * **What is different on this side is the self exclusion.** The module under
 * test globs the tree it lives in, so the bundler keeps it out of its own
 * result and it supplies its own text by specifier instead. Both halves of
 * that are pinned here rather than there: a file cannot see itself missing.
 */

import { describe, expect, it } from "vitest";

import {
  NOT_MODULES,
  TOP_LEVEL_DIRECTORIES,
  armingFailures,
  testDirectories,
  testDirectoriesIn,
  testEntries,
  testEntriesBesides,
  testModules,
  testText,
  type Corpus,
} from "./testModules";

/**
 * The module under test, read the way it reads itself.
 *
 * **A `?raw` specifier and not a one file glob.** The two look alike and fail
 * differently: the bundler refuses a specifier naming a file that is not
 * there, so a rename is a failed transform, where a glob matching nothing is
 * an empty result and whatever the caller defaults to. That difference is the
 * subject of the rule at the foot of `houseRules.test.ts`.
 */
import homeText from "./testModules.ts?raw";

/**
 * A tree with one file in every directory the real one has, plus a root.
 *
 * Built against the stated lists rather than against `tests/`, so these arms
 * say what the check does and not what the tree holds today.
 */
const INTACT = [
  "./COVERAGE.md",
  "./api/invalidate.test.ts",
  "./app/App.test.tsx",
  "./components/Button.test.tsx",
  "./conformance/sru.test.ts",
  "./doubles/README.md",
  "./doubles/zxing.ts",
  "./i18n/catalogue.test.ts",
  "./lib/zip.test.ts",
  "./pages/Home/Home.test.tsx",
  "./setup.ts",
  "./theme/palettes.test.ts",
  "./utils.tsx",
];

const isModule = (path: string) => /\.tsx?$/.test(path);

/**
 * The three patterns the rules carried before the module under test existed.
 *
 * **A second home for a pattern, and it is the point rather than an
 * oversight.** Every enumeration `testModules.ts` arms against is written
 * inside that file, so one editor narrowing all of them in one diff is
 * refused by nothing in there. This one is outside it, and it is the pattern
 * all three of those rules used to carry: two in `houseRules.test.ts` and one
 * in `withoutProse.test.ts`, byte identical.
 *
 * Names only, so nothing is read and nothing is inlined into this bundle.
 */
const AS_THE_RULES_GLOBBED_IT = import.meta.glob("./**/*.{ts,tsx}");

/**
 * The tree with no extension on the pattern at all.
 *
 * **The one thing the module under test cannot check for itself**, for the
 * reason its source side twin states: restricting its unrestricted patterns
 * to the extensions the tree holds today is a no op, and then the first
 * fixture added under `tests/` in another format is invisible to all of them.
 */
const WITH_NO_EXTENSION_AT_ALL = import.meta.glob("./**/*");

/** A corpus whose enumerations all agree, which is the honest case. */
function corpusOf(files: string[]): Corpus {
  return {
    named: files,
    decomposed: files,
    moduleKeys: files.filter(isModule),
    self: { supplied: true, inTheSweep: false },
  };
}

/** The one failure a fixture is meant to produce, refusing two. */
function soleFailure(corpus: Corpus): string {
  const failures = armingFailures(corpus);
  expect(failures).toHaveLength(1);
  return failures[0]!;
}

describe("the corpus this tree states", () => {
  it("names every directory of the tree it stands for", () => {
    // The fixtures are only evidence while they are a whole tree. A list that
    // had fallen behind would make every narrowing below red for the wrong
    // reason, which is a suite that passes while measuring nothing.
    const directories = [
      ...new Set(
        INTACT.filter((path) => path.split("/").length > 2).map(
          (path) => path.split("/")[1],
        ),
      ),
    ].sort();

    expect(directories).toEqual([...TOP_LEVEL_DIRECTORIES].sort());
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
  it("is refused for the language where no directory empties", () => {
    // **The live mechanism, and the fixture has to model it.** On the real
    // tree every directory holds `.ts` as well, so cutting `.tsx` empties
    // none of them and the directory partition says nothing: `tests/pages/`
    // keeps its hooks and loses its components. So every directory is given
    // a `.ts` sibling here, and both halves are asserted, the directories
    // intact and the languages arm naming the cause on its own.
    const narrowed = [
      ...INTACT,
      "./app/routes.test.ts",
      "./components/Button.helpers.test.ts",
      "./pages/Home/hooks.test.ts",
    ].filter((path) => !path.endsWith(".tsx"));
    const directories = [
      ...new Set(
        narrowed
          .filter((path) => path.split("/").length > 2)
          .map((path) => path.split("/")[1]),
      ),
    ].sort();

    expect(directories).toEqual([...TOP_LEVEL_DIRECTORIES].sort());
    expect(narrowed.filter(isModule)).not.toEqual([]);
    expect(soleFailure(corpusOf(narrowed))).toContain("lost a language");
  });
});

describe("a corpus narrowed by directory", () => {
  it("is refused although both languages and both other files survive", () => {
    // **The evasion that survives the extension arm.** Dropping the pages
    // keeps `.ts` and `.tsx`, keeps every file the rules exempt by name, and
    // removes more of this tree than its other eight directories together.
    const narrowed = INTACT.filter((path) => !path.startsWith("./pages/"));
    const extensions = new Set(
      narrowed.filter(isModule).map((path) => path.split(".").pop()),
    );

    expect([...extensions].sort()).toEqual(["ts", "tsx"]);
    expect(narrowed.filter((path) => !isModule(path)).sort()).toEqual(
      [...NOT_MODULES].sort(),
    );
    expect(soleFailure(corpusOf(narrowed))).toContain('lost ["pages"]');
  });

  it("is refused when the helpers at the root go and the directories stay", () => {
    // **The half a directory list cannot see.** `./*/**/*` keeps every
    // directory, keeps both languages, and drops every module sitting beside
    // this one, which is where `setup.ts`, the fixtures and the two corpus
    // modules live. The root is held by a property because a stated list of
    // what is there would red on each new helper.
    const narrowed = INTACT.filter(
      (path) => path.includes("/", 2) || !isModule(path),
    );
    const directories = [
      ...new Set(
        narrowed
          .filter((path) => path.split("/").length > 2)
          .map((path) => path.split("/")[1]),
      ),
    ].sort();

    expect(directories).toEqual([...TOP_LEVEL_DIRECTORIES].sort());
    expect(soleFailure(corpusOf(narrowed))).toContain("no module sits at the");
  });
});

describe("a corpus whose enumerations disagree", () => {
  it("is refused when the per directory sweep is the narrow one", () => {
    const corpus = corpusOf(INTACT);
    corpus.decomposed = INTACT.filter((path) => !path.startsWith("./pages/"));

    expect(soleFailure(corpus)).toContain("the two enumerations");
  });

  it("is refused when the recursive sweep is the narrow one", () => {
    const corpus = corpusOf(
      INTACT.filter((path) => !path.startsWith("./app/")),
    );
    corpus.decomposed = INTACT;

    expect(armingFailures(corpus).join("\n")).toContain("the two enumerations");
  });

  it("is refused when the sweep the rules read is the narrow one", () => {
    // The shape that costs the most and shows the least: the names are the
    // whole tree, so every arm about the tree passes, and the text the rules
    // actually walk is a subset of it.
    const corpus = corpusOf(INTACT);
    corpus.moduleKeys = corpus.moduleKeys.filter(
      (path) => !path.startsWith("./pages/"),
    );

    expect(soleFailure(corpus)).toContain("the module half");
  });
});

/**
 * A file of a kind this tree does not hold, for the arm below.
 *
 * **Named, because the fixture is `[...INTACT, UNCLASSIFIED]` and that is
 * satisfied by a duplicate.** Follow the remedy the arming states for a new
 * kind of file, name it in `NOT_MODULES` and add it to `INTACT`, and the arm
 * below goes on passing: one failure, mentioning `NOT_MODULES`, raised for
 * the repeated entry rather than for the unclassified kind. A red nobody can
 * clear gets fixed; a green that has stopped measuring its own subject does
 * not.
 */
const UNCLASSIFIED = "./theme/logo.svg";

describe("a kind of file nobody has classified", () => {
  it("is refused rather than swept into the module corpus", () => {
    // Placed inside an existing directory on purpose, so the directory check
    // is silent and this is the only thing that speaks.
    expect(NOT_MODULES).not.toContain(UNCLASSIFIED);
    expect(INTACT).not.toContain(UNCLASSIFIED);
    const corpus = corpusOf([...INTACT, UNCLASSIFIED]);

    expect(soleFailure(corpus)).toContain("NOT_MODULES");
  });
});

describe("the file no pattern in the home can reach", () => {
  it("is refused when its text never arrives", () => {
    // Every rule over this tree would then read one file short, and the file
    // is the one holding the patterns they all walk.
    const corpus = corpusOf(INTACT);
    corpus.self = { supplied: false, inTheSweep: false };

    expect(soleFailure(corpus)).toContain("did not arrive by specifier");
  });

  it("is refused when the bundler starts handing it over as well", () => {
    // **The arm that notices the supply becoming a duplicate.** It rests on
    // the bundler excluding the importing module from its own glob, which is
    // behaviour rather than a guarantee, and the honest failure if that ever
    // changes is this line rather than a corpus quietly holding two copies.
    const corpus = corpusOf(INTACT);
    corpus.self = { supplied: true, inTheSweep: true };

    expect(soleFailure(corpus)).toContain("is in its own glob");
  });

  it("is excluded by the bundler, read from here where that is visible", () => {
    // The measurement the home cannot take. This file's own pattern is the
    // one the three rules used to carry, and it reaches the home while it
    // cannot reach this file.
    expect(Object.keys(AS_THE_RULES_GLOBBED_IT)).toContain("./testModules.ts");
    expect(Object.keys(AS_THE_RULES_GLOBBED_IT)).not.toContain(
      "./testModules.test.ts",
    );
  });

  it("is the module's own source and not an empty string", () => {
    expect(testText("./testModules.ts")).toBe(homeText);
    expect(testText("./testModules.ts")).toContain(
      "export function testEntriesBesides",
    );
  });
});

describe("the tree as this module hands it over", () => {
  it("arms against the real corpus", () => {
    expect(() => testModules()).not.toThrow();
  });

  it("is the corpus the three rules' own pattern matched", () => {
    // **The population comparison, kept rather than run once.** Three rules
    // walked that pattern, and an extraction that quietly moved what they see
    // is the failure this whole module is about. The two differ by exactly
    // the importer of each: the home is in this file's pattern and supplies
    // itself, and this file is in the home's corpus and not in its own
    // pattern.
    expect(
      Object.keys(testModules()).sort(),
      "the rules are not walking the tree their own pattern matched: one of " +
        "the patterns in tests/testModules.ts has moved, or this one has",
    ).toEqual(
      [...Object.keys(AS_THE_RULES_GLOBBED_IT), "./testModules.test.ts"].sort(),
    );
  });

  it("holds every file under tests, whatever its extension", () => {
    // **The arm the module under test cannot write for itself.** Its
    // unrestricted patterns can all be restricted to the extensions the tree
    // holds today with nothing red and the same map handed over. This asks
    // the question with no extension in the pattern at all, over the exported
    // surface only: a file here is a module the rules are given, or it is
    // named as not one.
    const modules = testModules();
    const unclassified = Object.keys(WITH_NO_EXTENSION_AT_ALL)
      .filter((path) => !(path in modules) && !NOT_MODULES.includes(path))
      .sort();

    expect(
      unclassified,
      "a file under tests/ that the rules are not given and NOT_MODULES " +
        "does not name: either a pattern in tests/testModules.ts was " +
        "narrowed by extension, or a new kind of file needs naming there",
    ).toEqual([]);
  });

  it("hands back the text of a module and not its name", () => {
    expect(testText("./setup.ts")).toContain("beforeEach");
  });

  it("refuses a module it does not hold, rather than answering nothing", () => {
    // A lookup defaulting to the empty string turns a renamed module into a
    // rule reading a file with no violations in it, which is green.
    expect(() => testText("./lib/notAModule.ts")).toThrow("notAModule.ts");
  });

  it("refuses a key spelled without the prefix without claiming the file is gone", () => {
    // **The refusal has to be about the key, not about the tree.** This said
    // `no module at tests/setup.ts` over a file that is there, which reads
    // as the lookup being too strict, and the one line repair for that is to
    // normalise the key: the widening the module exists to refuse.
    expect(() => testText("setup.ts")).toThrow('keyed "setup.ts"');
    expect(() => testText("setup.ts")).not.toThrow("no module at");
    expect(testText("./setup.ts")).toContain("beforeEach");
  });

  it("removes an exclusion a rule names", () => {
    const paths = testEntriesBesides("./setup.ts").map(([path]) => path);

    expect(paths).not.toContain("./setup.ts");
    expect(paths).toContain("./utils.tsx");
  });

  it("refuses an exclusion naming a file the tree does not hold", () => {
    // **What the filters this replaced could not do.** They were written as
    // an inequality against a key the bundler had already removed, so
    // pointing one at a file that does not exist changed nothing and the rule
    // went on reading the same corpus.
    expect(() => testEntriesBesides("./gone.test.ts")).toThrow("gone.test.ts");
  });

  it("reports the directories a filtered corpus keeps", () => {
    expect(testDirectories()).toEqual([...TOP_LEVEL_DIRECTORIES].sort());
    expect(testDirectoriesIn(["./lib/a.ts", "./b.ts"])).toEqual(["lib"]);
    // **A subset and not an equality, which is the second half of the dead
    // end this arm was in.** `testDirectories()` answers for every file and
    // the modules are a part of that, so a directory holding only fixtures
    // is legitimate and used to leave this red with no edit that could clear
    // it.
    //
    // **It has no mutant, and that is said rather than left to be found.**
    // The arming already asserts the module keys are the module half of the
    // names, and the accessor above reads those same names, so a module in
    // a directory the tree does not report cannot arise without the arming
    // throwing first. This restates a property established by construction
    // and is kept as the statement of it. What catches a rule swallowing a
    // directory is the comparison in `withoutProse.test.ts`, over a corpus
    // that has actually been filtered.
    const held = testDirectories();

    expect(
      testDirectoriesIn(testEntries().map(([path]) => path)).filter(
        (directory) => !held.includes(directory),
      ),
      "a module sits in a directory the armed tree does not report",
    ).toEqual([]);
  });
});
