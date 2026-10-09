/**
 * The one enumeration of the source tree, and the check that it is still the
 * whole of it.
 *
 * **A rule that walks `src/` is only as wide as the pattern it walks**, and a
 * pattern is one line in the file of whoever wants the rule green. Every rule
 * that walked this tree carried its own, so a narrowing cost one edit at the
 * site of the rule it disarmed, and the rule went on reporting nothing with a
 * real violation live. Measured twice: cut to `.ts` the corpus loses every
 * `.tsx` module, which is every card and the rendering half of every page
 * folder, while keeping enough files to clear any plausible floor; narrowed by
 * directory it keeps both extensions, keeps every exempted file, and drops
 * every page and card. Each time the arm added afterwards closed the shape
 * that had just been shown.
 *
 * **So the glob literals live here and nowhere else, and this module refuses
 * to hand over a corpus that is not the tree.** The refusal is four
 * enumerations compared against each other and against two stated lists:
 *
 * | what | why it cannot be narrowed alone |
 * |---|---|
 * | every file under `src/`, names only | the others are checked against it |
 * | the same tree assembled per top level entry | a different pattern shape, so one narrowing does not write both |
 * | every module, as text | bound to the module half of the names |
 * | every stylesheet, as text | bound to the other half |
 *
 * **Three of those patterns are unrestricted, and that is load bearing.**
 * Restricting them to the extensions the tree holds today is a no op on this
 * tree and a hole tomorrow: the first image added under `src/` would then be
 * invisible to all four enumerations at once, which is the event the
 * unrestricted sweep exists to catch. What refuses that narrowing is an
 * unrestricted pattern in `tests/sourceModules.test.ts`, outside this file.
 *
 * **What it does not close, and the resolution is the thing to state.** This
 * module's finest grain is the top level entry: narrowing every pattern here
 * to exclude one **subdirectory** moves neither stated list, because the entry
 * above it survives, and the four enumerations then agree on a smaller tree.
 * Driven against the arming function with a fixture carrying real depth: zero
 * failures. What refuses it is the second home, `tests/sourceModules.test.ts`,
 * which holds the patterns the rules used to carry and compares file for file.
 * So a narrowing that stays green has to be written into the patterns here,
 * into whichever stated list it disturbs if any, and again into the patterns
 * and the fixture over there. No number is written for that, because a count
 * in prose has nothing to recount it.
 *
 * **The arming is a pure function so it can be driven**, which is the half a
 * glob cannot have: a pattern is resolved when the module is transformed, so
 * no test can narrow one at run time. `tests/sourceModules.test.ts` hands
 * `armingFailures` each narrowing by hand instead.
 *
 * **`import.meta.glob` rather than `node:fs`**, which is where the readers
 * this replaced each stated their own copy of the reason: a guard test is a
 * poor reason to add `@types/node` and widen the global types, which this
 * project does not otherwise want. It is also what lets one module serve a
 * reader running under happy-dom, where `import.meta.url` is not a `file:`
 * URL and `fileURLToPath` throws before an assertion runs.
 *
 * **A pattern resolves against the module that writes it**, so these are
 * written once here and every caller gets the same corpus whatever its own
 * depth under `tests/`. That property is what makes one home possible.
 *
 * **What importing it costs, measured rather than left to be found.** The
 * module text is an eager `?raw` sweep, so any caller inlines the whole of
 * `src/` as strings: the palette test reads two stylesheets and now carries
 * megabytes to do it, tens of times what its own pattern cost. The run is
 * green and the cost is affordable, so it is recorded rather than fixed. The
 * remedy if it ever bites is to split the stylesheet door into its own module
 * with the name level patterns, leaving the text sweep behind it.
 */

/** Where the patterns below are rooted, and the prefix every key carries. */
const PREFIX = "../src/";

/**
 * What lives under `src/` and is not a module, as the tree holds it today.
 *
 * **Stated, because it is what no narrowing can keep by accident.** A pattern
 * that misses a directory loses one of these, and both sit in directories a
 * module scan would otherwise have no reason to reach: one at the root of
 * `src/` and one a level down. The cost is real: a third stylesheet, or any
 * other kind of file under `src/`, fails every reader here until somebody
 * names it. A person deciding whether a new kind of file belongs in a source
 * scan is the point rather than the price.
 */
export const NOT_MODULES: readonly string[] = [
  "index.css",
  "theme/palettes.css",
];

/**
 * Every top level entry of `src/`, files included.
 *
 * **A closed set completed rather than a floor.** Narrowing by directory is
 * the evasion that survived the extension check, and it is this list that
 * reddens on it, by name. The set is closed at any moment and moves when
 * somebody adds a top level directory, which is a decision worth a red line
 * rather than an accident.
 */
export const TOP_LEVEL: readonly string[] = [
  "api",
  "app",
  "components",
  "i18n",
  "index.css",
  "lib",
  "main.tsx",
  "pages",
  "theme",
  "vite-env.d.ts",
];

/**
 * The two languages a module under `src/` is written in.
 *
 * **Its own check, because the top level partition catches a narrowing by
 * extension only by accident.** Cut the tree to `.ts` and every directory is
 * still populated: `pages` keeps 55 modules while losing 126, and what reds is
 * `main.tsx` leaving the root. That is one file nobody chose, and spelled
 * `main.ts` instead the arming would be silent on a narrowing that removes
 * every `.tsx` module in the tree. This is the property the skill prescribes
 * in its place, and it does not depend on where a file happens to sit.
 */
const LANGUAGES: readonly string[] = ["ts", "tsx"];

const isModule = (path: string): boolean => /\.tsx?$/.test(path);

const extensionOf = (path: string): string => path.split(".").pop() ?? "";

const sorted = (paths: Iterable<string>): string[] => [...paths].sort();

const missingFrom = (whole: string[], part: string[]): string[] =>
  whole.filter((path) => !part.includes(path));

/** The corpus as this module reads it, every path stated below `src/`. */
export interface Corpus {
  /** Every file under `src/`, from the recursive pattern. */
  named: string[];
  /** The same tree, assembled from one pattern per depth. */
  decomposed: string[];
  /** The keys of the sweep that reads module text. */
  moduleKeys: string[];
  /** The keys of the sweep that reads stylesheet text. */
  stylesheetKeys: string[];
}

/**
 * What is wrong with a corpus, as sentences, or nothing.
 *
 * **One sentence per way a corpus can stop being the tree**, rather than one
 * assertion: a narrowing usually breaks several at once, and reporting all of
 * them is what tells the next reader whether a pattern moved or the tree did.
 */
export function armingFailures(corpus: Corpus): string[] {
  const failures: string[] = [];
  const named = sorted(corpus.named);
  const decomposed = sorted(corpus.decomposed);

  if (named.join("\n") !== decomposed.join("\n")) {
    failures.push(
      "the two enumerations of src/ disagree, so one of the patterns in " +
        "tests/sourceModules.ts no longer reaches the whole tree: " +
        `only in the recursive sweep ${JSON.stringify(
          missingFrom(named, decomposed),
        )}, only in the per directory sweep ${JSON.stringify(
          missingFrom(decomposed, named),
        )}`,
    );
  }

  const tops = sorted(new Set(named.map((path) => path.split("/")[0] ?? "")));
  const stated = sorted(TOP_LEVEL);
  if (tops.join("\n") !== stated.join("\n")) {
    failures.push(
      "src/ no longer holds the top level entries this module states, so " +
        "either a pattern was narrowed by directory or the tree moved: " +
        `lost ${JSON.stringify(
          missingFrom(stated, tops),
        )}, gained ${JSON.stringify(missingFrom(tops, stated))}`,
    );
  }

  const others = named.filter((path) => !isModule(path));
  if (others.join("\n") !== sorted(NOT_MODULES).join("\n")) {
    failures.push(
      "what lives under src/ besides the modules is not what NOT_MODULES in " +
        "tests/sourceModules.ts says: name a new kind of file there if the " +
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
      "the sweep the scans read is not the module half of the tree: " +
        `only in the tree ${JSON.stringify(
          missingFrom(expectedModules, modules),
        )}, only in the sweep ${JSON.stringify(
          missingFrom(modules, expectedModules),
        )}`,
    );
  }

  const sheets = sorted(corpus.stylesheetKeys);
  const expectedSheets = named.filter((path) => path.endsWith(".css"));
  if (sheets.join("\n") !== expectedSheets.join("\n")) {
    failures.push(
      "the stylesheet sweep is not the stylesheets the tree holds: " +
        `found ${JSON.stringify(sheets)}, expected ${JSON.stringify(
          expectedSheets,
        )}`,
    );
  }

  return failures;
}

/**
 * Names only, and no content.
 *
 * **The enumeration that measures the reach reads nothing**, because an eager
 * `?raw` sweep of everything would decode the first binary asset added under
 * `src/` as UTF-8 and inline it into this bundle before failing on it, which
 * is the one event this enumeration exists to catch.
 */
const EVERY_FILE = import.meta.glob("../src/**/*");

/**
 * The same tree, written as two patterns of a different shape.
 *
 * **This is the second derivation and not a second arm.** A narrowing has to
 * be written into the recursive pattern and into both of these consistently
 * before the corpus can shrink in silence, and the three do not narrow the
 * same way: a directory dropped from the recursive pattern is still named by
 * the one that walks a level at a time.
 */
const ROOT_FILES = import.meta.glob("../src/*");
const NESTED_FILES = import.meta.glob("../src/*/**/*");

const MODULE_TEXT = import.meta.glob("../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const STYLESHEET_TEXT = import.meta.glob("../src/**/*.css", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const below = (key: string): string =>
  key.startsWith(PREFIX) ? key.slice(PREFIX.length) : key;

const MODULES: Record<string, string> = Object.fromEntries(
  Object.entries(MODULE_TEXT).map(([key, text]) => [below(key), text]),
);

const STYLESHEETS: Record<string, string> = Object.fromEntries(
  Object.entries(STYLESHEET_TEXT).map(([key, text]) => [below(key), text]),
);

let failures: string[] | undefined;

/**
 * Refuse a corpus that is not the tree, before any caller reads it.
 *
 * Thrown rather than asserted, so that a caller reading the corpus at module
 * scope fails the same way as one reading it inside a test.
 */
function armed(): void {
  failures ??= armingFailures({
    named: Object.keys(EVERY_FILE).map(below),
    decomposed: [
      ...Object.keys(ROOT_FILES).map(below),
      ...Object.keys(NESTED_FILES).map(below),
    ],
    moduleKeys: Object.keys(MODULES),
    stylesheetKeys: Object.keys(STYLESHEETS),
  });
  if (failures.length > 0) {
    throw new Error(
      `the corpus under src/ is not the source tree, so every rule reading it is narrower than it says:\n${failures.join(
        "\n",
      )}`,
    );
  }
}

/** Every module under `src/` as text, keyed by its path below `src/`. */
export function sourceModules(): Record<string, string> {
  armed();
  return MODULES;
}

/** The same, as pairs, which is the shape most rules walk. */
export function sourceEntries(): [string, string][] {
  return Object.entries(sourceModules());
}

/**
 * One module's text, named by its path below `src/`.
 *
 * **It throws rather than answering nothing.** A lookup defaulting to the
 * empty string turns a renamed module into a rule that reads a file with no
 * violations in it, which is green.
 */
export function sourceText(path: string): string {
  const text = sourceModules()[path];
  if (text === undefined) {
    throw new Error(`no module at src/${path}`);
  }
  return text;
}

/**
 * The modules under one top level directory of `src/`.
 *
 * **The directory is checked against the armed corpus**, so this cannot be
 * narrowed to a prefix that happens to match fewer files: the only argument it
 * accepts is a directory the tree has, and what lies under that directory is
 * settled by the enumeration rather than by a pattern. A top level **file**
 * is refused here too, because a prefix naming one matches nothing and
 * silence is the answer this module exists to refuse.
 */
export function modulesUnder(directory: string): [string, string][] {
  const entries = sourceEntries();
  const directories = sourceDirectories();
  if (!directories.includes(directory)) {
    throw new Error(
      `src/${directory} is not a directory of src/: ${JSON.stringify(
        directories,
      )}`,
    );
  }
  return entries.filter(([path]) => path.startsWith(`${directory}/`));
}

/**
 * The top level directories a set of paths below `src/` reaches.
 *
 * **For a rule that filters this corpus before walking it.** An exclusion
 * written at the rule, `api/generated/` or a module exempted by name, is
 * outside everything this module arms: widening one to swallow a directory is
 * a narrowing by another route, and a floor under the result does not see it.
 * Compared against `sourceDirectories()` it reds by name.
 */
export function directoriesIn(paths: readonly string[]): string[] {
  return sorted(
    new Set(
      paths
        .filter((path) => path.includes("/"))
        .map((path) => path.split("/")[0] ?? ""),
    ),
  );
}

/** The directories the armed tree holds, which is what a filtered one keeps. */
export function sourceDirectories(): string[] {
  armed();
  return directoriesIn(Object.keys(EVERY_FILE).map(below));
}

/** One stylesheet's text, named by its path below `src/`. */
export function stylesheetText(path: string): string {
  armed();
  const text = STYLESHEETS[path];
  if (text === undefined) {
    throw new Error(`no stylesheet at src/${path}`);
  }
  return text;
}
