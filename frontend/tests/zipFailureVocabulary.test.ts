/**
 * @vitest-environment node
 *
 * Reads sources as text and calls one pure function. No DOM, and building a
 * jsdom costs more than this file spends running.
 */
/**
 * A zipped format's reader does not say for itself what a zip's refusal means.
 *
 * `lib/zip.ts`'s `zipFailureAs` is the one declaration, and a reader supplies
 * only its own "this is a different kind of file" sentence. The compiler holds
 * what it can: the answers are total over `ZipFailure`, an answer outside
 * `ZipSharedFailure` fails at every caller. What no type can say is that a fourth
 * reader has to call the helper at all, and this file is that half.
 *
 * **It does not reach a reader that calls the helper and then rewrites the
 * answer.** Measured: `failure: said === "unsupported" ? "damaged" : said` at a
 * reader's own catch passes the compiler and every test in this tree. That is a
 * line at one call site rather than a table anybody would copy, and the copy is
 * what this rule is for.
 *
 * **So the rule is enforced here and nowhere else.** Delete this file and
 * nothing goes red: a fourth reader is stopped by a test, not by a construction
 * it cannot express.
 *
 * **It is a rule over the source tree rather than a test of a module**, so it
 * sits beside `houseRules.test.ts` rather than in `tests/lib/`, which mirrors
 * modules. It carries the seam's name rather than joining the general rules,
 * because it is worth nothing on the day `lib/zip.ts` goes.
 *
 * **Every name it matches on is derived at run time**, so it recounts rather
 * than restates: a member added to `ZipFailure` arrives here without an edit,
 * and a name that stops being zip's own stops being forbidden.
 *
 * **The scope is `src/` less what Orval writes.** A test naming these failures
 * is asserting on them, which is what `tests/lib/zip.test.ts` and the three
 * readers' own tests do; and `src/api/generated/` is written from the backend's
 * schema, cannot import this seam, and already holds a `truncated` field that
 * misses the scan below on punctuation alone.
 */

import { describe, expect, it } from "vitest";

import { ZipError, zipFailureAs, type ZipFailure } from "../src/lib/zip";

// `import.meta.glob` and not `node:fs`, for the reason `houseRules.test.ts`
// gives at its own: a guard test is a poor reason to add `@types/node` and
// widen the global types.
const SOURCES = import.meta.glob("../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const ZIP_MODULE = "lib/zip.ts";
const GENERATED = "api/generated/";

function entries(): [string, string][] {
  return Object.entries(SOURCES).map(([path, source]) => [
    path.replace("../src/", ""),
    source,
  ]);
}

/**
 * The source with its comments removed, because the prose here quotes the
 * vocabulary this file is about.
 *
 * A scanner rather than a regex pair: `//` inside a string literal is a URL and
 * not a comment, and stripping from there would delete the rest of a line of
 * code, which is a rule that quietly stops looking rather than one that fails.
 *
 * **The exclusion is a regular expression literal**, whose `\/\/` this reads as
 * the start of a comment and skips the rest of the line for. `src/` holds none
 * today, and what it would produce is a miss rather than a false report, so it
 * is stated rather than defended against: the fix is a parser, and this rule is
 * not worth a dependency.
 */
function withoutComments(source: string): string {
  let out = "";
  let at = 0;
  while (at < source.length) {
    const here = source[at]!;
    const next = source[at + 1];
    if (here === "/" && next === "*") {
      const end = source.indexOf("*/", at + 2);
      at = end === -1 ? source.length : end + 2;
      out += " ";
      continue;
    }
    if (here === "/" && next === "/") {
      const end = source.indexOf("\n", at);
      at = end === -1 ? source.length : end;
      out += " ";
      continue;
    }
    if (here === '"' || here === "'" || here === "`") {
      out += here;
      at += 1;
      while (at < source.length) {
        const inner = source[at]!;
        out += inner;
        at += 1;
        if (inner === "\\") {
          out += source[at] ?? "";
          at += 1;
          continue;
        }
        if (inner === here) break;
      }
      continue;
    }
    out += here;
    at += 1;
  }
  return out;
}

/**
 * The union's declaration: the members read out of it, and what was left.
 *
 * Parsed rather than listed, so this file needs no edit when the union grows.
 * The parse is the only instrument for the member list, and it can be wrong in
 * two directions that fail differently. **Too wide is loud**: a name that is
 * not an arm has no answer, which the first assertion below catches, and it has
 * already happened. **Too narrow is silent**, because the forbidden set is the
 * arms less the answers, so a member the regex loses simply stops being
 * forbidden. `unread` is what closes that: anything in the declaration that is
 * not a quoted member, a `|` or whitespace is a member this file did not read,
 * whether it is an alias, a single quoted string or a stray token.
 *
 * **Read with the comments taken out**, because each member of that union is
 * documented and one of the sentences quotes `"deflate-raw"`, which arrives
 * here as a member of its own. A doc comment carrying a `;` would cut the parse
 * short in the same way.
 */
function readZipFailureUnion(): { members: string[]; unread: string } {
  const declaration = /export type ZipFailure =([^;]*);/.exec(
    withoutComments(SOURCES[`../src/${ZIP_MODULE}`] ?? ""),
  );
  const body = declaration?.[1] ?? "";
  return {
    members: [...body.matchAll(/"([^"]+)"/g)].map((match) => match[1]!),
    unread: body.replace(/"[^"]*"/g, "").replace(/[|\s]/g, ""),
  };
}

/** A sentence no format would pick, so an answer equal to it is the supplied one. */
const SUPPLIED = "the-word-its-caller-supplied";

const ARMS = readZipFailureUnion().members;

/** What the helper answers for each arm, asked rather than read. */
const ANSWERS = ARMS.map((arm) =>
  zipFailureAs(
    new ZipError(arm as ZipFailure, "asked for by a test"),
    SUPPLIED,
  ),
);

/**
 * The names the helper answers with for the arms a format does not choose.
 *
 * `string[]` rather than the union the helper returns, because what these are
 * compared against are the parsed arms, which are strings: a narrower type here
 * would only assert that this file typed itself.
 */
const SHARED: string[] = [...new Set(ANSWERS)].filter(
  (answer) => answer !== SUPPLIED,
);

/**
 * The failure names that are `lib/zip.ts`'s own.
 *
 * By subtraction rather than by list: what is left is `not-a-zip`, `zip64`,
 * `encrypted` and `truncated`. The arms whose name is also an answer are
 * exactly the ones a reader's own union carries, so forbidding those would
 * forbid the spelling every reader is required to use. **So this scan does not
 * reach those three at all**, and nothing else does either: what the shape in
 * `lib/zip.ts` removes is the table a fourth reader would copy, not an override
 * written at a reader's own call site. Measured, `unsupported` rewritten at
 * `fb2.ts`'s catch passes the compiler and every test in this tree.
 */
const ZIP_ONLY = ARMS.filter((arm) => !SHARED.includes(arm));

/**
 * How a mapping spells one of those names: as a quoted string, or as the bare
 * key an object literal allows the ones without a hyphen in them.
 */
function spelled(name: string): RegExp {
  return new RegExp(`["'\`]${name}["'\`]|\\b${name}\\s*:`, "g");
}

describe("the names this rule is derived from", () => {
  it("are every one an arm the helper answers for", () => {
    // The parse going wide is what this catches, and it has: the sentence
    // documenting `no-inflate` quotes `"deflate-raw"`, which is not an arm and
    // whose answer is `undefined`.
    expect(ARMS.filter((_, at) => ANSWERS[at] === undefined)).toEqual([]);
  });

  it("are read from a declaration that was found", () => {
    // Without this the assertion above holds over an empty list, and every scan
    // below then has nothing to look for.
    expect(ARMS.length).toBeGreaterThan(0);
  });

  it("are the whole of what that declaration says", () => {
    // The direction the answers cannot check. Measured: aliasing one member to
    // a named type leaves `ZipFailure` identical, `SHARED_ANSWER` total and
    // every other assertion in this file green, while the forbidden set quietly
    // loses a name.
    expect(readZipFailureUnion().unread).toBe("");
  });

  it("leave the caller's own word to the one arm that is the caller's", () => {
    expect(ARMS.filter((_, at) => ANSWERS[at] === SUPPLIED)).toEqual([
      "not-a-zip",
    ]);
  });
});

describe("a module that reads a zip does not map its failures itself", () => {
  const readers = entries()
    .filter(([path]) => path !== ZIP_MODULE && !path.startsWith(GENERATED))
    .map(([path, source]): [string, string] => [path, withoutComments(source)]);

  function naming(needle: string): string[] {
    return readers
      .filter(([, code]) => code.includes(needle))
      .map(([path]) => path)
      .sort();
  }

  it("calls the helper wherever it names the error", () => {
    // `ZipError` is the door to a `ZipFailure`: `error.failure` is reachable
    // through nothing else, so a module naming the one and not the other is
    // deciding for itself what a zip's refusal means. Both sides read the
    // source with its comments gone, so a module that only mentions the error
    // in prose is not held to the rule.
    expect(naming("ZipError")).toEqual(naming("zipFailureAs("));
  });

  it("is one of the three zipped formats and no others", () => {
    // The non vacuity check for the equality above, which two empty lists would
    // also satisfy. Both directions: a fourth reader added and not named here
    // fails, which is the prompt to read the rule above, and a name deleted
    // from here fails too.
    expect(naming("zipFailureAs(")).toEqual([
      "lib/cbz.ts",
      "lib/epub.ts",
      "lib/fb2.ts",
    ]);
  });

  it("never spells a failure name that is zip's own", () => {
    // The copy this replaced spelled all four. Measured: this scan reports
    // nothing across `src/` today and reports every one of them against the
    // three maps as they stood before the helper existed.
    //
    // **Two modules come within a character of it**, so "nothing else has a
    // reason to spell these" is not why it is clean: `lib/pdf.ts` has an
    // `encrypted()` method and `api/generated/model/opdsSyncOut.ts` a
    // `truncated?:` field, and it is the `(` and the `?` that miss. The second
    // is generated and is excluded above; the first would be a false report the
    // day somebody gave that method a getter.
    const offenders = readers.flatMap(([path, code]) =>
      ZIP_ONLY.flatMap((name) =>
        [...code.matchAll(spelled(name))].map(
          (match) => `${path}: ${match[0]}`,
        ),
      ),
    );

    expect(offenders).toEqual([]);
  });

  it("reads the source tree at all", () => {
    // A glob that matched nothing would make the scans above pass for ever.
    expect(readers.length).toBeGreaterThan(50);
  });
});

describe("the comment scanner", () => {
  it("removes a comment", () => {
    expect(withoutComments('a; // "zip64"\nb;')).not.toContain("zip64");
  });

  it("keeps the code after a string that holds the comment marker", () => {
    // The line this exists for: stripping from the `//` inside a URL would
    // delete the rest of that line, and a mapping written on it would go
    // unread. A rule that stops looking passes, which is why it is asserted.
    expect(
      withoutComments('const at = "https://x/y"; const b = "zip64";'),
    ).toContain('"zip64"');
  });

  it("keeps a string that is itself a comment", () => {
    expect(withoutComments('const a = "// zip64";')).toContain("zip64");
  });
});
