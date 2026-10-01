/**
 * The one enumeration of the test tree, and the check that it is still the
 * whole of it.
 *
 * **The other half of `tests/sourceModules.ts`**, which did this for `src/`.
 * The rules walking `tests/` kept their own patterns while that landed, for a
 * reason worth stating rather than repeating: the bundler excludes the
 * importing module from its own `import.meta.glob`, so moving three patterns
 * into one module changes what each of their rules sees. That is a population
 * change wearing an extraction's clothes, and it is the thing this module is
 * built to make visible rather than to hide.
 *
 * **What it does about it: the corpus handed over is the whole tree, this
 * module included.** The glob cannot see this file, so the text of it arrives
 * by a `?raw` specifier instead, which is a different module id and so a
 * string rather than a cycle. The exclusion is pinned by an arm rather than
 * relied on, because if the bundler ever stops excluding the importer the
 * supply below becomes a second copy, and a duplicate is exactly the failure
 * nobody would read.
 *
 * **So every caller gets the same set, and each one states its own
 * exclusions.** Those used to be written and to remove nothing, because the
 * bundler had already done it: `SELF` in two rules here was a filter over a
 * key that was never present. They remove something now, and
 * `testEntriesBesides` refuses a name the tree does not hold, so a renamed
 * rule file is a red line rather than a filter that quietly stops filtering.
 *
 * **The arming is four enumerations compared against each other and against
 * two stated lists**, which is the arrangement `tests/sourceModules.ts`
 * argues for in full and this one does not restate:
 *
 * | what | why it cannot be narrowed alone |
 * |---|---|
 * | every file under `tests/`, names only | the others are checked against it |
 * | the same tree assembled per top level entry | a different pattern shape |
 * | every module, as text | bound to the module half of the names |
 * | this module's own text | the one file no pattern here can reach |
 *
 * **What is stated and what is derived, and the two differ from the source
 * side on purpose.** `src/` is directories, so that module states every top
 * level entry. `tests/` carries twenty odd helpers at its root, and a stated
 * list of those would red on every new helper, which teaches the next person
 * to edit the guard. So the closed set stated here is the **directories**,
 * which is a decision worth a red line, and the root is held by a property
 * instead: it holds modules, and the files under `tests/` that are not
 * modules are named.
 *
 * **The arming is a pure function so it can be driven.** A pattern is
 * resolved when the module is transformed, so no test can narrow one at run
 * time; `tests/testModules.test.ts` hands `armingFailures` each narrowing by
 * hand, and holds the patterns the rules used to carry, outside this file so
 * that one diff cannot narrow both.
 *
 * **Keyed as a specifier relative to `tests/`, which is where this differs
 * from the source side.** `tests/sourceModules.ts` keys below `src/` and its
 * callers re-spell each one as `../src/<path>`, because the scopes in
 * `tests/houseRules.test.ts` mix the two trees and resolve an import
 * specifier against the key. A test module's key is already in that space, so
 * stripping the dot slash here would mean putting it back at every one of
 * those sites.
 *
 * **What importing it costs**: an eager `?raw` sweep of the test tree, so a
 * caller inlines every test module as a string. The three rules that read it
 * were each already doing exactly that, so this is one copy where there were
 * three.
 */

/**
 * This file's own text, which no glob here can supply.
 *
 * A `?raw` specifier is a different module id, so this is a string and not a
 * cycle. `tests/houseRules.test.ts` reads itself the same way and for the
 * same reason.
 */
import ownText from "./testModules.ts?raw";

/**
 * This module, as the bundler names it, and as this module's callers do.
 *
 * **It is the one file no pattern written here can match**, so it is read by
 * specifier above and asserted absent from the sweep below it.
 */
const SELF = "./testModules.ts";

/** A key with its directory stripped, for the arms that ask about depth. */
const under = (path: string): string => path.replace(/^\.\//, "");

/**
 * What lives under `tests/` and is not a module, as the tree holds it today.
 *
 * **Stated, because it is what no narrowing can keep by accident.** One at the
 * root and one a level down, so a pattern that drops either depth loses one of
 * them. A new kind of file here fails every reader until somebody names it,
 * which is a person deciding whether it belongs in a scan rather than a scan
 * deciding for them.
 */
export const NOT_MODULES: readonly string[] = [
  "./COVERAGE.md",
  "./doubles/README.md",
];

/**
 * Every directory of `tests/`, which mirrors the directories of `src/` plus
 * the ones the suite needs for itself.
 *
 * **A closed set completed rather than a floor.** Narrowing by directory is
 * the evasion that survives an extension check, and it is this list that reds
 * on it, by name. `tests/pages/` alone is more than half the tree, so a
 * pattern excluding it clears any plausible count while every page test goes
 * unread.
 */
export const TOP_LEVEL_DIRECTORIES: readonly string[] = [
  "api",
  "app",
  "components",
  "conformance",
  "doubles",
  "i18n",
  "lib",
  "pages",
  "theme",
];

/**
 * The two languages a module under `tests/` is written in.
 *
 * Its own check, because the directory partition catches a narrowing by
 * extension only by accident: cut the tree to `.ts` and every directory is
 * still populated.
 */
const LANGUAGES: readonly string[] = ["ts", "tsx"];

const isModule = (path: string): boolean => /\.tsx?$/.test(path);

const extensionOf = (path: string): string => path.split(".").pop() ?? "";

const sorted = (paths: Iterable<string>): string[] => [...paths].sort();

const missingFrom = (whole: string[], part: string[]): string[] =>
  whole.filter((path) => !part.includes(path));

/** The corpus as this module reads it, keyed relative to `tests/`. */
export interface Corpus {
  /** Every file under `tests/`, from the recursive pattern. */
  named: string[];
  /** The same tree, assembled from one pattern per depth. */
  decomposed: string[];
  /** The keys of the sweep that reads module text. */
  moduleKeys: string[];
  /** Whether this module's own text arrived, and is not also in the sweep. */
  self: { supplied: boolean; inTheSweep: boolean };
}

/**
 * What is wrong with a corpus, as sentences, or nothing.
 *
 * One sentence per way a corpus can stop being the tree, rather than one
 * assertion: a narrowing usually breaks several at once, and reporting all of
 * them is what tells the next reader whether a pattern moved or the tree did.
 */
export function armingFailures(corpus: Corpus): string[] {
  const failures: string[] = [];
  const named = sorted(corpus.named);
  const decomposed = sorted(corpus.decomposed);

  if (named.join("\n") !== decomposed.join("\n")) {
    failures.push(
      "the two enumerations of tests/ disagree, so one of the patterns in " +
        "tests/testModules.ts no longer reaches the whole tree: " +
        `only in the recursive sweep ${JSON.stringify(
          missingFrom(named, decomposed),
        )}, only in the per directory sweep ${JSON.stringify(
          missingFrom(decomposed, named),
        )}`,
    );
  }

  const directories = sorted(
    new Set(
      named
        .map(under)
        .filter((path) => path.includes("/"))
        .map((path) => path.split("/")[0] ?? ""),
    ),
  );
  const stated = sorted(TOP_LEVEL_DIRECTORIES);
  if (directories.join("\n") !== stated.join("\n")) {
    failures.push(
      "tests/ no longer holds the directories this module states, so either " +
        "a pattern was narrowed by directory or the tree moved: " +
        `lost ${JSON.stringify(
          missingFrom(stated, directories),
        )}, gained ${JSON.stringify(missingFrom(directories, stated))}`,
    );
  }

  // The root is held by a property rather than by a list, for the reason in
  // the header: a stated list of the helpers at the root reds on every new
  // one. A pattern cut to `./*/**/*` keeps every directory and loses this.
  if (!named.map(under).some((path) => !path.includes("/") && isModule(path))) {
    failures.push(
      "no module sits at the root of tests/, so a pattern in " +
        "tests/testModules.ts was narrowed to the directories and the " +
        "helpers beside them are unread",
    );
  }

  const others = named.filter((path) => !isModule(path));
  if (others.join("\n") !== sorted(NOT_MODULES).join("\n")) {
    failures.push(
      "what lives under tests/ besides the modules is not what NOT_MODULES " +
        "in tests/testModules.ts says: name a new kind of file there if the " +
        `scans should skip it. Found ${JSON.stringify(others)}`,
    );
  }

  const modules = sorted(corpus.moduleKeys);
  const languages = sorted(new Set(modules.map(extensionOf)));
  if (languages.join("\n") !== sorted(LANGUAGES).join("\n")) {
    failures.push(
      "the corpus the rules read has lost a language, so a pattern was " +
        `narrowed by extension: found ${JSON.stringify(
          languages,
        )}, stated ${JSON.stringify(sorted(LANGUAGES))}`,
    );
  }

  const expectedModules = named.filter(isModule);
  if (modules.join("\n") !== expectedModules.join("\n")) {
    failures.push(
      "the sweep the rules read is not the module half of the tree: " +
        `only in the tree ${JSON.stringify(
          missingFrom(expectedModules, modules),
        )}, only in the sweep ${JSON.stringify(
          missingFrom(modules, expectedModules),
        )}`,
    );
  }

  if (!corpus.self.supplied) {
    failures.push(
      `${SELF} did not arrive by specifier, so every rule over the test ` +
        "tree is reading one file short and the file is the one holding the " +
        "patterns",
    );
  }

  if (corpus.self.inTheSweep) {
    failures.push(
      `${SELF} is in its own glob, which the bundler used to exclude. The ` +
        "text supplied by specifier beside it is now a second copy: drop " +
        "the supply rather than the arm",
    );
  }

  return failures;
}

/**
 * Names only, and no content.
 *
 * The enumeration that measures the reach reads nothing, because an eager
 * `?raw` sweep of everything would decode the first binary fixture added
 * under `tests/` as UTF-8 and inline it before failing on it, which is the
 * event this enumeration exists to catch.
 */
const EVERY_FILE = import.meta.glob("./**/*");

/**
 * The same tree, written as two patterns of a different shape.
 *
 * The second derivation and not a second arm: a directory dropped from the
 * recursive pattern is still named by the one that walks a level at a time.
 */
const ROOT_FILES = import.meta.glob("./*");
const NESTED_FILES = import.meta.glob("./*/**/*");

const MODULE_TEXT = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const MODULES: Record<string, string> = { ...MODULE_TEXT, [SELF]: ownText };

let failures: string[] | undefined;

/**
 * Refuse a corpus that is not the tree, before any caller reads it.
 *
 * Thrown rather than asserted, so that a caller reading the corpus at module
 * scope fails the same way as one reading it inside a test.
 */
function armed(): void {
  failures ??= armingFailures({
    named: [...Object.keys(EVERY_FILE), SELF],
    decomposed: [
      ...Object.keys(ROOT_FILES),
      ...Object.keys(NESTED_FILES),
      SELF,
    ],
    moduleKeys: Object.keys(MODULES),
    self: {
      supplied: typeof ownText === "string" && ownText.length > 0,
      inTheSweep: SELF in MODULE_TEXT,
    },
  });
  if (failures.length > 0) {
    throw new Error(
      `the corpus under tests/ is not the test tree, so every rule reading it is narrower than it says:\n${failures.join(
        "\n",
      )}`,
    );
  }
}

/** Every module under `tests/` as text, keyed relative to `tests/`. */
export function testModules(): Record<string, string> {
  armed();
  return MODULES;
}

/** The same, as pairs, which is the shape most rules walk. */
export function testEntries(): [string, string][] {
  return Object.entries(testModules());
}

/**
 * The tree less the modules a rule has to leave out, named.
 *
 * **It refuses a name the tree does not hold.** The exclusions this replaced
 * were written as `path !== SELF` over a key the bundler had already removed,
 * so pointing one at a file that does not exist changed nothing and the rule
 * went on reading the same corpus. Here it reds, which is the whole reason a
 * caller states its exclusions rather than inheriting them.
 */
export function testEntriesBesides(...excluded: string[]): [string, string][] {
  const modules = testModules();
  const absent = excluded.filter((path) => !(path in modules));
  if (absent.length > 0) {
    throw new Error(
      `tests/ holds no ${absent.join(", ")}, so excluding it removes ` +
        "nothing: " +
        "a rule naming a file that is not there is reading more than it says",
    );
  }
  return Object.entries(modules).filter(([path]) => !excluded.includes(path));
}

/**
 * One module's text, named by its specifier relative to `tests/`.
 *
 * It throws rather than answering nothing, for the reason `sourceText` in
 * `tests/sourceModules.ts` states: that is what a reader wanting one file is
 * owed, and it is stated once.
 */
export function testText(path: string): string {
  const text = testModules()[path];
  if (text === undefined) {
    // **The key as given, against the key space, and not as a path.** The
    // first version printed the path with its prefix stripped, so
    // `testText("setup.ts")` said `no module at tests/setup.ts` about a file
    // the tree holds. The obvious repair for that sentence is to normalise
    // the key, which is the widening this module exists to refuse.
    throw new Error(
      `tests/ holds no module keyed ${JSON.stringify(path)}; keys are ` +
        'spelled "./..." and only a module has one',
    );
  }
  return text;
}

/**
 * The top level directories a set of keys reaches.
 *
 * **For a rule that filters this corpus before walking it.** An exclusion
 * written at the rule is outside everything this module arms: widening one to
 * swallow a directory is a narrowing by another route, and nothing here sees
 * it. Compared against `testDirectories()` it reds by name.
 */
export function testDirectoriesIn(paths: readonly string[]): string[] {
  return sorted(
    new Set(
      paths
        .map(under)
        .filter((path) => path.includes("/"))
        .map((path) => path.split("/")[0] ?? ""),
    ),
  );
}

/**
 * The directories the armed tree holds, which is what a filtered one keeps.
 *
 * **Read off every file and not off the modules**, which is what the arming
 * compares against and what `sourceDirectories` does on the source side.
 * Taking it from the modules made the two halves disagree about what a
 * directory is: a new directory of fixtures that are not modules reds the
 * arming, naming it in `TOP_LEVEL_DIRECTORIES` clears that, and then this
 * function could not report it and the comparison below went red with no
 * edit anywhere that could clear it. That dead end is the source twin's own,
 * which it fixed once and did not carry across.
 */
export function testDirectories(): string[] {
  armed();
  return testDirectoriesIn([...Object.keys(EVERY_FILE), SELF]);
}
