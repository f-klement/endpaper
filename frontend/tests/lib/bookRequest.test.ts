/**
 * @vitest-environment node
 *
 * Touches no DOM. Building one costs more than this file spends running.
 */
/**
 * Tests for src/lib/bookRequest.ts.
 *
 * What a source record becomes on the wire, checked against the committed
 * `openapi.json` rather than against a copy of it kept here: a bound that
 * agrees with a constant somebody typed is a bound that agrees with nothing.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { BookIdentifierScheme } from "../../src/api/generated/model";
import { boundIdentifiers, boundRecord } from "../../src/lib/bookRequest";
import type { SourceRecord } from "../../src/lib/sourceRecord";
import type { StoreIdentifierScheme } from "../../src/lib/stores";

const SOURCES = import.meta.glob("../../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function modules(): [string, string][] {
  return Object.entries(SOURCES).map(([path, source]) => [
    path.replace("../../src/", ""),
    source,
  ]);
}

const SCHEMA = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../openapi.json", import.meta.url)),
    "utf-8",
  ),
) as {
  components: {
    schemas: {
      BookCreate: { properties: Record<string, unknown> };
      BookIdentifierIn: { properties: { value: { maxLength: number } } };
    };
  };
};

/** What the endpoint says an identifier may be, read back rather than typed. */
const IDENTIFIER_CEILING =
  SCHEMA.components.schemas.BookIdentifierIn.properties.value.maxLength;

/**
 * How many the endpoint will take in one request, read back the same way.
 *
 * A payload over this is a 422 for the whole book rather than for the extra
 * entry, so it is the fourth rule `boundIdentifiers` has to keep.
 */
const IDENTIFIER_LIMIT = (
  SCHEMA.components.schemas.BookCreate.properties as {
    identifiers: { maxItems: number };
  }
).identifiers.maxItems;

/**
 * A source that stated everything, and one that stated nothing.
 *
 * **Typed as `SourceRecord` rather than widened**, which is one half of the
 * diagonal below: a field added to that interface makes both of these a
 * compile error, and the arm that drops each field in turn then says whether
 * the door reads it.
 */
const EVERYTHING_STATED: SourceRecord = {
  title: "Dune",
  authors: ["Frank Herbert"],
  isbn: "9780441013593",
  publisher: "Chilton Books",
  year: 1965,
  language: "eng",
  description: "A desert planet.",
  seriesName: "Dune Chronicles",
  seriesIndex: 1,
};

const NOTHING_STATED: SourceRecord = {
  title: null,
  authors: [],
  isbn: null,
  publisher: null,
  year: null,
  language: null,
  description: null,
  seriesName: null,
  seriesIndex: null,
};

describe("a source record as the request names its fields", () => {
  it("sends no name the endpoint does not take", () => {
    // The failure this catches is a field renamed on the schema and left here,
    // which passes the type check while the server ignores it. Asked of the
    // door rather than of a builder, because all three builders spread it.
    const allowed = new Set(
      Object.keys(SCHEMA.components.schemas.BookCreate.properties),
    );

    expect(
      Object.keys(boundRecord(EVERYTHING_STATED)).filter(
        (name) => !allowed.has(name),
      ),
    ).toEqual([]);
  });

  it("reads every field the record states, or has stopped reading one", () => {
    // The diagonal: each field dropped in turn has to move the answer. A field
    // wired into the record and never into the door sends nothing and fails
    // nowhere else, which is the class this module exists to close.
    const whole = JSON.stringify(boundRecord(EVERYTHING_STATED));
    const fields = Object.keys(EVERYTHING_STATED) as (keyof SourceRecord)[];

    const unread = fields.filter(
      (field) =>
        JSON.stringify(
          boundRecord({ ...EVERYTHING_STATED, [field]: NOTHING_STATED[field] }),
        ) === whole,
    );

    expect(unread).toEqual([]);
  });

  it("answers one request field a record field, neither more nor fewer", () => {
    // The anchor the arm above cannot be: a fixture that lost its fields would
    // report nothing unread. Both sides are counted rather than written down,
    // so a field added to one and not the other fails here.
    expect(Object.keys(boundRecord(EVERYTHING_STATED))).toHaveLength(
      Object.keys(EVERYTHING_STATED).length,
    );
  });

  it("joins authors with the separator the server splits on", () => {
    expect(
      boundRecord({
        ...EVERYTHING_STATED,
        authors: ["Terry Pratchett", "Neil Gaiman"],
      }).author,
    ).toBe("Terry Pratchett, Neil Gaiman");
  });

  it("says nothing about a source that named no author", () => {
    // An empty list joins to `""`, and a caller reading `author` to decide
    // whether the source named one would take that for a name.
    expect(boundRecord(NOTHING_STATED).author).toBeNull();
  });

  it("cuts a title the column cannot hold rather than losing the book", () => {
    const wide = "x".repeat(10_000);
    const title = boundRecord({ ...EVERYTHING_STATED, title: wide }).title;

    expect(title).not.toBeNull();
    expect(title!.length).toBeLessThan(wide.length);
  });

  it("drops a language code the column cannot hold rather than cutting it", () => {
    // `lib/bookBounds.ts`' split: a title cut is the same book through a
    // narrower window, and a language code cut names a different language.
    expect(
      boundRecord({ ...EVERYTHING_STATED, language: "x".repeat(200) }).language,
    ).toBeNull();
  });

  it("drops a number the column's range does not hold, never clamping it", () => {
    // A year of 9999 is a fact the source got wrong, and storing the ceiling
    // would turn a wrong number into a plausible one.
    expect(boundRecord({ ...EVERYTHING_STATED, year: 9999 }).year).toBeNull();
  });

  it("answers a null title rather than refusing the record", () => {
    // What an absent title means is the caller's: `null` for an import nobody
    // is watching, an editable blank on the scan page. The door says only that
    // the source stated none.
    expect(boundRecord(NOTHING_STATED).title).toBeNull();
  });
});

/** Block comments and whole line `//` comments removed. */
function withoutProse(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/** The text between a brace and its match, starting at `open`. */
function balanced(source: string, open: number): string {
  let depth = 0;
  for (let end = open; end < source.length; end++) {
    const character = source[end]!;
    if ("([{".includes(character)) depth += 1;
    else if (")]}".includes(character)) {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, end);
    }
  }
  return source.slice(open + 1);
}

/**
 * Every `function name(params)` in a module, with what follows it.
 *
 * **The body runs to the next declaration rather than to a matching brace**,
 * and that is a correction rather than a shortcut. Brace matching has to pick
 * the brace that opens the body, and a return type annotation opens one first:
 * `function f(r: SourceRecord): { a: string } {` hands back the annotation,
 * which contains no call, so a builder writing its own bound inside such a
 * function passes with nothing red. This tree has such a signature in this very
 * file. Slicing to the next `function` over reads instead, which reports the
 * wrong name and fails loudly.
 *
 * The exclusion: a nested `function` declaration truncates its parent's body,
 * so a bound written after one is invisible. There is none in the population
 * this rule selects, and the direction is the same one the annotation hazard
 * was traded away for.
 */
function functions(
  code: string,
): { name: string; params: string; body: string }[] {
  const starts = [...code.matchAll(/\bfunction\s+(\w+)\s*\(/g)];
  return starts.flatMap((match, index) => {
    const open = match.index! + match[0].length - 1;
    const params = balanced(code, open);
    const after = open + params.length + 2;
    const next = starts[index + 1]?.index ?? code.length;
    return after >= next
      ? []
      : [{ name: match[1]!, params, body: code.slice(after, next) }];
  });
}

describe("the mapping from a source record to the wire has one home", () => {
  /**
   * The names of every record type, derived and never listed.
   *
   * A fourth family joins this rule by writing `extends SourceRecord`, which is
   * the line that makes it one, and needs no edit here.
   */
  function recordTypes(): string[] {
    const extending = modules().flatMap(([, source]) =>
      [
        ...source.matchAll(/\bexport interface (\w+) extends SourceRecord\b/g),
      ].map((match) => match[1]!),
    );
    return ["SourceRecord", ...extending];
  }

  /**
   * Which `bound*` field names the door owns, read off the door itself.
   *
   * **Not written down**, so a field added to `boundRecord` widens this rule
   * the same day. `bookBounds` keys its ceilings by the request's own field
   * names, which is what makes the two comparable at all.
   */
  function doorFields(): string[] {
    return Object.keys(boundRecord(EVERYTHING_STATED));
  }

  /** Every `boundText("x"` or `boundNumber("x"` in a body, as the name `x`. */
  function boundsApplied(body: string): string[] {
    return [...body.matchAll(/\bbound(?:Text|Number)\(\s*"([^"]+)"/g)].map(
      (match) => match[1]!,
    );
  }

  /**
   * The module the door lives in, found by the declaration rather than named.
   *
   * **Asserted to be exactly one**, which is what stops the exemption below
   * covering a second home: a `boundRecord` declared beside a builder would
   * otherwise exempt that builder from the whole rule.
   */
  function home(): string {
    const declaring = modules()
      .filter(([, source]) => source.includes("export function boundRecord("))
      .map(([path]) => path);

    expect(declaring).toHaveLength(1);
    return declaring[0]!;
  }

  it("reads a function's parameters and its body apart", () => {
    // Asked of a literal, because a scanner that stopped matching would report
    // no offender below and pass for ever.
    const parsed = functions(
      'function f(a: CalibreBook, b: number): X {\n  return boundText("title", a);\n}',
    );

    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.params).toContain("CalibreBook");
    expect(boundsApplied(parsed[0]!.body)).toEqual(["title"]);
  });

  it("reads past a return type that opens a brace of its own", () => {
    // The spelling the first draft of `functions` was blind to, held as a
    // literal because nothing in the population writes it today and so nothing
    // in the tree would fail if this went back. A matching brace finds the
    // annotation and reports a body with no call in it.
    const parsed = functions(
      "function g(r: SourceRecord): { a: string } {\n" +
        '  return { a: boundText("title", r) };\n' +
        "}",
    );

    expect(boundsApplied(parsed[0]!.body)).toEqual(["title"]);
  });

  it("knows a record type by the clause that makes it one", () => {
    // Both directions: a derivation selecting nothing but `SourceRecord` would
    // make the rule below pass over an empty population.
    expect(recordTypes().length).toBeGreaterThan(1);
    expect(doorFields().length).toBeGreaterThan(0);
  });

  /** Every function outside the door that takes a whole source record. */
  function takers(): { path: string; name: string; body: string }[] {
    const types = recordTypes();
    const door = home();
    return modules()
      .filter(([path]) => path !== door)
      .flatMap(([path, source]) =>
        functions(withoutProse(source))
          .filter((one) =>
            types.some((type) =>
              new RegExp(`:\\s*${type}\\b`).test(one.params),
            ),
          )
          .map((one) => ({ path, name: one.name, body: one.body })),
      );
  }

  it("is watching functions that take one, and there are some", () => {
    // A rule over a population nothing selects passes for ever, and the three
    // builders this exists for are all outside the door.
    expect(takers().length).toBeGreaterThan(0);
  });

  it("keys every field by the name it sends, never by another field's", () => {
    // **The hole a type cannot see, and the one the door made worth closing.**
    // `boundText` picks the ceiling and the cut versus drop decision off its
    // quoted key, so `publisher: boundText("description", record.publisher)`
    // compiles, takes that field's ceiling from 255 to 10,000, and sends a
    // value the column refuses: a 422 for the whole book on all three import
    // paths. Nothing else here would see it: the key arm above compares names
    // and would still find nine right ones, the diagonal and the count are
    // blind to a ceiling, and no arm anywhere feeds an over length `author`,
    // `publisher`, `description` or `series_name` through a builder.
    //
    // **How many of the nine an existing arm would still catch is not stated
    // here**, because it is not a property of the door: it depends on whether
    // the fixture's own value happens to fall outside the wrongly chosen bound,
    // and `series_index` at 1 is inside `year`'s window as well as its own. A
    // guard resting on a fixture's values is one a later edit to the fixture
    // turns off.
    //
    // **Not a regression, and that is why it belongs here rather than in a
    // ticket.** The same mis-keying was equally invisible at each of the three
    // sites this door replaced. What changed is that one edit now moves all
    // three at once, which is the depth working and is also what makes a wrong
    // key worth a guard.
    //
    // **Asserted in order, which costs nothing and buys the swapped pair.** The
    // key and the property it fills are written on one line, so a reordering of
    // the literal moves both, and two fields keyed as each other differ from
    // the property order in two places rather than none.
    //
    // The over read `functions` performs is what this reads: the door's body
    // runs to the next declaration, so anything between it and
    // `boundIdentifiers` is included. Nothing there applies a scalar bound, and
    // one that did would arrive as a name in this list rather than silently.
    const source = modules().find(([path]) => path === home())![1];
    const door = functions(withoutProse(source)).find(
      (one) => one.name === "boundRecord",
    );

    expect(door).toBeDefined();
    expect(boundsApplied(door!.body)).toEqual(
      Object.keys(boundRecord(EVERYTHING_STATED)),
    );
  });

  it("lets no function taking a record bound a field the door owns", () => {
    // The class: a fourth family spelling the field mappings out again,
    // which compiles, passes every other test, and drifts from the other three
    // one field at a time. `subtitle` is the field a file bounds for itself and
    // the door does not own, so this rule says nothing about it.
    //
    // **The exclusion, in full, because this catches one shape of five and a
    // stated bound that names two of its four misses is the shape this
    // repository keeps paying for.** Measured by the design seat, each as a
    // probe module against the real `src/` map: the control fires and these
    // four do not.
    //
    // - **The mapping written out with no bound at all**, `author:
    //   book.authors.join(", ")`. This is the target case plus an unbounded
    //   value on the wire, so it is strictly worse than what is refused here,
    //   and nothing sees it.
    // - A builder declared `export const f = (book: StoreBook) =>`, which
    //   `functions` does not match: it reads the `function` keyword and nothing
    //   else. Stated rather than chased because the shape is not one this tree
    //   writes. Re-derived 2026-09-18 over `src/` less `api/generated/`, with
    //   both patterns named so the pair is checkable: a top level
    //   `const <name> = (…) =>` matches **1** file, `lib/sqlite.ts`'s zero
    //   parameter engine loader, against **761** occurrences of
    //   `function <name>(`.
    // - A builder taking `books: readonly StoreBook[]` rather than one record.
    // - `boundText(TITLE, …)` with the field name held in a const, which
    //   `boundsApplied` reads as no name at all.
    //
    // **Not closed by a further arm, and that is the decision rather than the
    // omission.** The parameter pattern, the declaration form and the literal
    // spelling are three open sets, so an arm each makes the rule look thorough
    // while the fifth spelling walks past. What actually bounds the family is
    // that a fourth family arrives as an interface saying `extends
    // SourceRecord`, which is the line this walk reads and the one a person
    // writing one cannot avoid.
    const owned = new Set(doorFields());

    const offenders = takers().flatMap((one) =>
      boundsApplied(one.body)
        .filter((field) => owned.has(field))
        .map((field) => `${one.path}: ${one.name} bounds ${field}`),
    );

    expect(offenders).toEqual([]);
  });
});

describe("the identifiers a source gave, bounded for the wire", () => {
  it("spells every scheme a store can answer the way the endpoint does", () => {
    // The mapping is a total `Record`, the format mapping's rule. What the type
    // cannot see is a value that compiles and is not one the endpoint's own
    // enum holds, which is a 422 in the middle of somebody's device.
    const known = new Set(Object.values(BookIdentifierScheme) as string[]);
    const schemes: StoreIdentifierScheme[] = ["asin", "google_books"];
    for (const scheme of schemes) {
      expect(known).toContain(
        boundIdentifiers([{ scheme, value: "x" }])[0]!.scheme,
      );
    }
  });

  it("writes an ASIN in the form Amazon issues one", () => {
    // A canonicalisation and not an invention: Amazon's token has no lower case
    // in it, so the fold recovers the issued value. `parseIsbn` is the
    // precedent, putting every spelling of an ISBN into one.
    expect(boundIdentifiers([{ scheme: "asin", value: "b00j4yqkhy" }])).toEqual(
      [{ scheme: "asin", value: "B00J4YQKHY" }],
    );
  });

  it("folds every letter of the alphabet it reaches, not most of them", () => {
    // **The whole alphabet in one line, because a handful of literals leaves a
    // letter riding free.** Found by the security seat: with the arms below
    // alone, narrowing the fold to `[a-y]` left both mirrored files green, and
    // a store sending an ASIN with a lower case `z` then earned the duplicate
    // row this table exists to prevent.
    // Written out on both sides rather than computed with `toUpperCase`, which
    // is the builtin the fold is defined not to use: an oracle sharing a
    // dependency with the thing under test is one that agrees with it.
    expect(
      boundIdentifiers([
        { scheme: "asin", value: "abcdefghijklmnopqrstuvwxyz" },
      ]),
    ).toEqual([{ scheme: "asin", value: "ABCDEFGHIJKLMNOPQRSTUVWXYZ" }]);
  });

  it("folds nothing outside the alphabet the scheme is written in", () => {
    // **The door cannot assume its input was vetted**: a store adapter sends
    // what the file said. Measured over all 1,112,064 non surrogate code
    // points, 1,552 change under `toUpperCase` and 1,526 of those are outside
    // `[a-z]`, so a fold spelled that way would send a value this app invented,
    // and 102 of them would change its length as well. `SS` here is what a
    // `toUpperCase` gives and is the failure this arm names.
    expect(boundIdentifiers([{ scheme: "asin", value: "straße" }])).toEqual([
      { scheme: "asin", value: "STRAßE" },
    ]);
  });

  it("leaves a volume id's case alone, its alphabet having both", () => {
    // The other arm of the same table, and the one that says it is a rule
    // rather than a fold somebody applied to everything: `aB3` and `AB3` are
    // two volume ids, and either spelling names a book Google does not.
    expect(
      boundIdentifiers([{ scheme: "google_books", value: "aB3-dE6_gH9j" }]),
    ).toEqual([{ scheme: "google_books", value: "aB3-dE6_gH9j" }]);
  });

  it("folds a repeat of one identifier, whichever reader sent it", () => {
    // Two readers can name one edition, and the ceiling below truncates before
    // the server's own deduplication ever sees the payload, so a repeat left
    // standing costs the book a different identifier.
    expect(
      boundIdentifiers([
        { scheme: "asin", value: "B00J4YQKHY" },
        { scheme: "asin", value: "b00j4yqkhy" },
        { scheme: "google_books", value: "aB3-dE6_gH9j" },
      ]),
    ).toEqual([
      { scheme: "asin", value: "B00J4YQKHY" },
      { scheme: "google_books", value: "aB3-dE6_gH9j" },
    ]);
  });

  it("trims a reader's own padding off a value", () => {
    // A store's XML indents its elements, and the unique index is on the exact
    // characters, so padding would earn a second row for one identifier.
    expect(
      boundIdentifiers([{ scheme: "asin", value: "\n  B00J4YQKHY\n" }]),
    ).toEqual([{ scheme: "asin", value: "B00J4YQKHY" }]);
  });

  it("drops a value the column cannot hold rather than losing the book", () => {
    // `lib/bookBounds.ts`' rule applied to a field it does not cover: an import
    // of nine hundred books must not turn into a 422 over one odd row.
    expect(
      boundIdentifiers([
        { scheme: "asin", value: "B".repeat(IDENTIFIER_CEILING + 1) },
        { scheme: "asin", value: "B00J4YQKHY" },
      ]),
    ).toEqual([{ scheme: "asin", value: "B00J4YQKHY" }]);
  });

  it("keeps a value spending the whole budget", () => {
    // The other side, without which the drop above is satisfied by a rule that
    // drops everything. Exactly on the boundary the schema declares.
    expect(
      boundIdentifiers([
        { scheme: "asin", value: "B".repeat(IDENTIFIER_CEILING) },
      ]),
    ).toHaveLength(1);
  });

  it("measures the budget in code points, never in UTF-16 units", () => {
    // A ceiling belongs to a Python `str` and to a SQLite column, both of which
    // count code points, so measuring in units refuses half of what the server
    // would take. `lib/bookBounds.ts` records the same fault costing a 422.
    expect(
      boundIdentifiers([
        { scheme: "asin", value: "\u{1f4d6}".repeat(IDENTIFIER_CEILING) },
      ]),
    ).toHaveLength(1);
  });

  // **One arm per case `tests/schemas/test_identifier.py` names**, because this
  // filter and that validator have to be the same rule: a character this keeps
  // and the server refuses is a 422 for the whole book, which `writeBooks`
  // files under `failures`. Five of these nine passed the `/\s/u` filter this
  // replaced, measured by both critic seats over every non surrogate code point.
  it.each([
    ["a space in the middle", "B00J4 YQKHY"],
    ["a tab", "B00J4\tYQKHY"],
    ["a no-break space, Zs", "B00J4\u00a0YQKHY"],
    ["a zero width space, Cf", "B00J4\u200bYQKHY"],
    ["a soft hyphen, Cf", "B00J4\u00adYQKHY"],
    ["a byte order mark, Cf", "B00J4\ufeffYQKHY"],
    ["a C1 control, Cc", "B00J4\u0085YQKHY"],
    ["a NUL, which is Cc", "B00J4\u0000YQKHY"],
    ["a left-to-right mark, Cf", "B00J4\u200eYQKHY"],
  ])("drops a value carrying %s", (_name, value) => {
    expect(boundIdentifiers([{ scheme: "asin", value }])).toEqual([]);
  });

  it("keeps the two real shapes, which the same rule must not refuse", () => {
    // The other side, without which the nine arms above are satisfied by a
    // filter that drops everything. Both measured by their own readers: an
    // ASIN is ten characters and a Google volume id is twelve of the URL safe
    // alphabet, which includes the two characters a charset rule would have
    // been tempted to exclude.
    expect(
      boundIdentifiers([
        { scheme: "asin", value: "B00J4YQKHY" },
        { scheme: "google_books", value: "zy-CAlFP_gYC" },
      ]),
    ).toHaveLength(2);
  });

  it("sends no more than one request may carry", () => {
    // Over `maxItems` the endpoint answers 422 for the whole book, so a store
    // that grew a longer list would cost a member the book rather than the
    // extra entry. No store produces more than one today; this binds the case
    // where one does.
    const many = Array.from({ length: IDENTIFIER_LIMIT + 3 }, (_, index) => ({
      scheme: "asin" as const,
      value: `B${String(index).padStart(9, "0")}`,
    }));

    expect(boundIdentifiers(many)).toHaveLength(IDENTIFIER_LIMIT);
  });

  it("drops an empty value", () => {
    expect(boundIdentifiers([{ scheme: "asin", value: "   " }])).toEqual([]);
  });
});
