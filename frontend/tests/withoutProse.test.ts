/**
 * @vitest-environment node
 *
 * Reads sources as text and parses them. No DOM, and building a jsdom costs
 * more than this file spends running.
 */
/**
 * What the one stripper keeps, what it removes, and the rule that no second one
 * appears beside it.
 *
 * The fixtures came from `houseRules.test.ts`, where the stripper lived while
 * it had one reader. They move with it rather than being copied, so there is
 * one statement of what stripping means.
 *
 * **The rule at the foot is a ratchet and not a prohibition**, because this
 * tree holds ten other modules that match a comment for themselves and three of
 * them are right to: the home parses TypeScript, and CSS and JSONC are not
 * TypeScript. Each entry says which it is. The list is re-derived on every run
 * and an entry that has stopped carrying an instrument fails, so it cannot
 * outlive its reason. Same arrangement as `oxlintRatchet.test.ts`, for the same
 * reason: a list that only grows stops being a ratchet.
 */

import { describe, expect, it } from "vitest";
import { parseAst } from "vite";

import { langOf, withoutProse } from "./withoutProse";

const SOURCES = import.meta.glob("../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const TESTS = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/**
 * What the stripper keeps and what it removes.
 *
 * **Every row is a source the regex pair this replaced got wrong**, and each
 * one is a shape rather than an instance: a slash pair in a string, in a
 * template chunk and in JSX text, and an opening block marker written inside a
 * string and inside a line comment. The last two are the expensive pair,
 * because they do not truncate a line, they delete every line up to the next
 * closing marker.
 *
 * The last row is the other direction, prose in every place a module can put
 * it, and it is the only row carrying a comment inside a template
 * interpolation and one trailing live code. Every row refuses a stripper that
 * returned its source unchanged, because every row states what must be cut.
 *
 * **The first row carries live code after the marker bearing string, on the
 * same line**, which is the arm the hand written scanner in
 * `zipFailureVocabulary.test.ts` had and this table did not: the URL surviving
 * is also satisfied by a stripper that drops the rest of the line after it, and
 * that is exactly what a line shape does. The row that follows a string with a
 * marker in it covers the next line, not this one.
 */
const STRIPPING: [string, "ts" | "tsx", string, string[], string[]][] = [
  [
    "a slash pair inside a string literal",
    "ts",
    'const at = "https://example.com/a"; const b = 1; // the note\n',
    ["https://example.com/a", "const b = 1;"],
    ["the note"],
  ],
  [
    "a slash pair inside a template chunk",
    "ts",
    "const at = `https://example.com/a`; // the note\n",
    ["https://example.com/a"],
    ["the note"],
  ],
  [
    "a slash pair between two JSX tags",
    "tsx",
    "const el = <p>https://example.com/a</p>; // the note\n",
    ["https://example.com/a"],
    ["the note"],
  ],
  [
    "an opening block marker inside a string literal",
    "ts",
    'const accept = "image/*";\nconst kept = 1;\n/* the note */\n',
    ["const kept = 1;"],
    ["the note"],
  ],
  [
    "an opening block marker inside a line comment",
    "ts",
    "// a wildcard, */*\nconst kept = 2;\n/* the note */\n",
    ["const kept = 2;"],
    ["a wildcard", "the note"],
  ],
  [
    "prose in every place a module can put it",
    "ts",
    "/**\n * the header\n */\n// the line\n" +
      "const kept = `x${/* the interpolated */3}`; // the trailing\n",
    ["const kept = `x${3}`;"],
    ["the header", "the line", "the interpolated", "the trailing"],
  ],
  [
    "a line comment ended by a terminator that is not a newline",
    "ts",
    // Written as escapes because `prettier --check` rewrites all three to a
    // newline in source, which would quietly delete this row's subject.
    "const kept = 1; // the note\u2028const alsoKept = 2;\n" +
      "const third = 3; // the other note\rconst andFourth = 4;\n" +
      "const fifth = 5; // a third note\u2029const andSixth = 6;\n",
    [
      "const kept = 1;",
      "const alsoKept = 2;",
      "const andFourth = 4;",
      "const andSixth = 6;",
    ],
    ["the note", "the other note", "a third note"],
  ],
];

describe("prose is stripped by the parser, not by a line shape", () => {
  it.each(STRIPPING)("%s", (_label, lang, source, kept, cut) => {
    const code = withoutProse(source, lang);

    for (const survivor of kept) expect(code).toContain(survivor);
    for (const gone of cut) expect(code).not.toContain(gone);
  });

  it("strips every module the rules read", () => {
    // A parser refuses text a regex returns something for, so a module this
    // throws on takes down whichever of the fifteen readers reached it first.
    // This is where that arrives naming the file.
    //
    // The floor that keeps this from passing over nothing is the arm below,
    // which reads the same glob: with the stripper in its own module this file
    // reads `src/` itself rather than borrowing `houseRules.test.ts`'s reader.
    const refused = Object.entries(SOURCES)
      .filter(([path, source]) => {
        try {
          withoutProse(source, langOf(path));
          return false;
        } catch {
          return true;
        }
      })
      .map(([path]) => path);

    expect(refused).toEqual([]);
  });

  it("reads the source tree at all", () => {
    // A glob that matched nothing would make the arm above pass for ever.
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
  });
});

/**
 * This file, which writes the instruments down in order to forbid them.
 *
 * Vite excludes the importing module from its own `import.meta.glob`, measured
 * at the address rule in `houseRules.test.ts`, so this filter removes nothing
 * today. It is one line and it is what keeps the rule working if that ever
 * changes.
 */
const SELF = "./withoutProse.test.ts";

/**
 * The home, which carries a marker as a literal because it is the thing that
 * looks for one.
 *
 * The parser says which offsets are code; finding the opener inside those is
 * still a text search, so `withoutProse.ts` spells both markers. Exempt by
 * identity and not by shape: being the one place that spells them is what the
 * rule below means.
 */
const HOME = "./withoutProse.ts";

/**
 * A marker is two characters, so ask about the pair.
 *
 * **Not a list of the ways a stripper can be spelled**, which is the guard
 * shape this repository keeps paying for. Every regex a module writes is run
 * against text that is a comment and against text that is not, and what
 * separates them decides. `/[*_`]/` in `houseRules.test.ts` matches a bare
 * asterisk, so it is reacting to a character a marker happens to contain and is
 * not flagged; `/\/\*[\s\S]*?\*\//` matches neither half alone and is.
 *
 * A URL is deliberately not in the second row. `//` inside one is exactly what
 * a hand rolled line stripper eats, so a regex matching it is the thing being
 * looked for rather than an exemption.
 *
 * **The corpus carries a doc block as well as a bare one**, because a matcher
 * written for a doc block alone needs the two stars and a body and matches
 * neither of the four character entries. Widening the corpus is not widening a
 * list of spellings: what is added is a comment, and every comment belongs
 * here.
 */
const IS_A_COMMENT = ["//", "/*", "/**/", "/* a */", "// a", "/** a */"];
const IS_NOT = ["/", "*", "a", "a b c", "const x = 1;"];

function reactsToAMarker(pattern: string, flags: string): boolean {
  let regex: RegExp;
  try {
    // `g` and `y` both carry `lastIndex` between calls, which would make the
    // answer depend on the order of the probes. Two flags and not a list of
    // them: they are the two ECMAScript defines as stateful.
    regex = new RegExp(pattern, flags.replace(/[gy]/g, ""));
  } catch {
    return false;
  }
  return (
    IS_A_COMMENT.some((text) => regex.test(text)) &&
    !IS_NOT.some((text) => regex.test(text))
  );
}

/**
 * A whole literal that is a marker, which is how a scanner finds one, written
 * as a quoted string or as a template.
 */
const MARKERS = ["//", "/*", "*/"];

/**
 * The modules carrying an instrument of their own, derived rather than listed.
 *
 * Two instruments, and each is asked about the marker rather than about a
 * spelling: a regex that reacts to one, and a marker written as text, which is
 * what a scanner needs to find the end of a block. The second is asked in both
 * spellings a string has, since a template chunk is not a `Literal`. The
 * closing marker is named in words here rather than written out, because a
 * block comment quoting its own closer ends there, which is how the first draft
 * of this file stopped parsing.
 *
 * **Two things escape both, and neither gets an arm.** A scanner comparing
 * single characters, because `"/"` alone is a literal wherever this tree writes
 * a route, so an arm on it would report those instead. And a pattern assembled
 * from a string, which is no more a regex literal than it is a marker. A case
 * per spelling is the guard shape this tree keeps paying for, and what these
 * two cost is a miss rather than a false report.
 *
 * No count of any of that stands here: one written beside a rule is read as
 * current long after it stops being so.
 */
function carriesAnInstrument(source: string, lang: "ts" | "tsx"): boolean {
  let carries = false;
  const walk = (value: unknown): void => {
    if (carries) return;
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (typeof value !== "object" || value === null) return;
    const node = value as Record<string, unknown>;
    if (node.type === "Literal") {
      const regex = node.regex as { pattern: string; flags: string } | null;
      if (regex && reactsToAMarker(regex.pattern, regex.flags)) carries = true;
      if (typeof node.value === "string" && MARKERS.includes(node.value))
        carries = true;
    }
    if (node.type === "TemplateElement") {
      // The other node kind a string can be written as. The scanner this rule
      // replaced is caught by the quoted spelling above, its `indexOf("*/",
      // at)`, and by neither regex it wrote; the same call with a template
      // argument was caught by nothing until this. Two kinds is what the
      // grammar has, so this is a closed set and not a second spelling.
      const cooked = (node.value as { cooked?: unknown } | undefined)?.cooked;
      if (typeof cooked === "string" && MARKERS.includes(cooked))
        carries = true;
    }
    for (const key of Object.keys(node)) walk(node[key]);
  };
  walk(parseAst(source, { lang }));
  return carries;
}

function carriers(): string[] {
  return Object.entries(TESTS)
    .filter(
      ([path, source]) =>
        path !== SELF &&
        path !== HOME &&
        carriesAnInstrument(source, langOf(path)),
    )
    .map(([path]) => path)
    .sort();
}

/**
 * The three whose matcher is for a language this home does not parse.
 *
 * A refusal rather than a backlog entry: `withoutProse` is `parseAst`, so
 * handing it a stylesheet or a config file fails. The matcher is what is
 * refused, and it is the only thing these entries speak for: two of the three
 * modules also read TypeScript, and what they do with it is their own rule's
 * business rather than this list's.
 */
const ANOTHER_LANGUAGE: Record<string, string> = {
  "./setup.ts": "CSS, the palette out of index.css",
  "./theme/palettes.test.ts": "CSS, the palettes under src/",
  "./oxlintRatchet.test.ts": "JSONC, the oxlint config",
};

/**
 * The seven that strip TypeScript with a regex pair, which is the instrument
 * this home replaced.
 *
 * **Each is a rule reading less of its subject than it says it does.** Measured
 * over the 461 modules under `src/`: a block arm and a line arm, both regexes,
 * edit code in 12 of them, and the variant whose line arm fires only at the
 * start of a line edits code in 8. `api/mutator.ts` loses the `Request` its
 * rules are about under both. The two shapes are written out in the probe of
 * `tells a matcher from a character a marker happens to contain` below, where
 * they are strings and cannot end this comment.
 *
 * They are a backlog and not a refusal: each needs its own reading, because a
 * parser strips more prose than the pair does and a rule that then sees less
 * text is a rule that can go green without being satisfied. Converting one is a
 * measurement per file, not an edit per file.
 */
const STILL_ITS_OWN: Record<string, string> = {
  "./lib/adobeDigitalEditions.test.ts": "one reader's source",
  "./lib/bookRequest.test.ts": "src, line comments at a line start only",
  "./lib/fileName.test.ts": "one module's source",
  "./lib/fileReaders.test.ts": "src, line comments at a line start only",
  "./lib/stores.test.ts": "the store seam and its readers",
  "./lib/xmlEntities.test.ts": "src/lib",
  "./pages/ScanPage/types.test.ts": "one module's source",
};

describe("the stripping has one home", () => {
  const KNOWN = [
    ...Object.keys(ANOTHER_LANGUAGE),
    ...Object.keys(STILL_ITS_OWN),
  ].sort();

  // Parsed once for both arms. The home caches its own strippings for this
  // reason and the same figure applies here: parsing the test tree is the whole
  // cost of this rule.
  const CARRYING = carriers();

  it("grows no instrument this rule has not already read", () => {
    // The arm that fires on the next copy. A module reaching for its own
    // matcher imports `withoutProse` instead, and a module that cannot, because
    // it is reading another language, says so above.
    expect(CARRYING.filter((path) => !KNOWN.includes(path))).toEqual([]);
  });

  it("keeps no entry that has stopped carrying one", () => {
    // What makes this a ratchet. Without it an entry outlives its reason and
    // the list only ever grows, which is how a suppression list stops being a
    // measurement of anything.
    expect(KNOWN.filter((path) => !CARRYING.includes(path))).toEqual([]);
  });

  it("reads a scanner that finds a marker as text, in either spelling", () => {
    // Driven through the rule, because the module this rule replaced was
    // caught by this arm and by no other: it matched no comment with a regex,
    // it searched for the closing marker with `indexOf`. Both spellings of a
    // string, and the shape that must not be flagged.
    expect(
      carriesAnInstrument('const end = source.indexOf("*/", at);', "ts"),
    ).toBe(true);
    expect(
      carriesAnInstrument("const end = source.indexOf(`*/`, at);", "ts"),
    ).toBe(true);
    expect(
      carriesAnInstrument('const at = "https://example.com/a";', "ts"),
    ).toBe(false);
  });

  it("tells a matcher from a character a marker happens to contain", () => {
    // Driven through the rule rather than asserted about its source, and both
    // directions, because a probe that answers true to everything would make
    // the ratchet above a list of every file in this tree and a probe that
    // answers false to everything would make it empty.
    expect(reactsToAMarker(String.raw`\/\*[\s\S]*?\*\/`, "g")).toBe(true);
    expect(reactsToAMarker(String.raw`^\s*\/\/.*$`, "gm")).toBe(true);
    expect(reactsToAMarker("[*_`]", "g")).toBe(false);
    expect(reactsToAMarker(String.raw`https?:\/\/[\w.]+`, "")).toBe(false);
  });

  it("reads the test tree at all", () => {
    // A glob that matched nothing would make the first arm pass for ever.
    expect(Object.keys(TESTS).length).toBeGreaterThan(50);
  });
});
