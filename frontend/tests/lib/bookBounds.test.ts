/**
 * @vitest-environment node
 *
 * A JSON file and two pure functions, so this needs no DOM.
 */
/**
 * Tests for src/lib/bookBounds.ts.
 *
 * **The guard recomputes every number from `openapi.json` rather than restating
 * it.** A table of ceilings copied out of a schema is a table that stops being
 * true the first time a column moves, silently and in the safe-looking
 * direction: a stale ceiling that is too small only drops fields, so nothing
 * fails and the app quietly stops sending a publisher. Recomputing is what a
 * careful reader cannot do once.
 *
 * **One number is the exception and it is stated rather than recomputed**: the
 * plausibility window `bookBounds.plausibleYear` applies has no schema behind
 * it, so `1450` and `2100` are written out below. What stands in for the
 * recomputation is three arms: the pair against `boundNumber`'s wider range,
 * a scan asserting the numbers have one home under `src/`, and a scan asserting
 * which modules call the function.
 */

import { describe, expect, it } from "vitest";

import {
  boundNumber,
  boundText,
  CUT_TO_FIT,
  KEPT_WHOLE,
  NUMBER_RANGES,
  plausibleYear,
  QUERY_CEILING,
  QUERY_FLOOR,
  TEXT_CEILINGS,
} from "../../src/lib/bookBounds";

const SCHEMA = import.meta.glob("../../openapi.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

interface Constraint {
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  anyOf?: Constraint[];
}

/** A nullable field is `anyOf: [{the real thing}, {null}]`, so flatten first. */
function flatten(property: Constraint): Constraint {
  const parts = [property, ...(property.anyOf ?? [])];
  return {
    maxLength: parts.find((part) => part.maxLength !== undefined)?.maxLength,
    minimum: parts.find((part) => part.minimum !== undefined)?.minimum,
    maximum: parts.find((part) => part.maximum !== undefined)?.maximum,
  };
}

function bookCreate(): Record<string, Constraint> {
  const raw = SCHEMA["../../openapi.json"] ?? "";
  // A glob that matched nothing would make every assertion below pass forever.
  expect(raw.length).toBeGreaterThan(1000);
  const schema = JSON.parse(raw) as {
    components: {
      schemas: Record<string, { properties: Record<string, Constraint> }>;
    };
  };
  const properties = schema.components.schemas.BookCreate?.properties;
  expect(properties).toBeDefined();
  return Object.fromEntries(
    Object.entries(properties!).map(([name, property]) => [
      name,
      flatten(property),
    ]),
  );
}

describe("the ceilings agree with the schema they describe", () => {
  it("holds every string the API bounds, and only those", () => {
    // **The set as well as the values.** A field gaining a `maxLength` in the
    // schema and not here would be a value sent over-wide and 422'd, and a
    // field here that the schema no longer bounds would be a value cut for no
    // reason. Neither shows up in a diff of this file.
    const bounded = Object.entries(bookCreate())
      .filter(([, property]) => property.maxLength !== undefined)
      .map(([name, property]) => [name, property.maxLength]);

    expect(Object.entries(TEXT_CEILINGS).sort()).toEqual(bounded.sort());
  });

  it("holds every number the API bounds, and only those", () => {
    const bounded = Object.entries(bookCreate())
      .filter(([, property]) => property.minimum !== undefined)
      .map(([name, property]) => [name, [property.minimum, property.maximum]]);

    expect(Object.entries(NUMBER_RANGES).sort()).toEqual(bounded.sort());
  });

  it("classifies every bounded string as cut or kept whole, exactly once", () => {
    // A field with no policy acquires one by default, which is the shape this
    // repository keeps finding. Asserted as a partition rather than as two
    // memberships, so moving a name from one set to the other in one gesture
    // cannot leave both assertions green.
    const names = Object.keys(TEXT_CEILINGS).sort();
    expect([...CUT_TO_FIT, ...KEPT_WHOLE].sort()).toEqual(names);
  });
});

describe("boundText", () => {
  it("trims before it measures, so padding does not cost a field", () => {
    expect(boundText("language", "  en  ")).toBe("en");
  });

  it("is null for nothing at all", () => {
    expect(boundText("title", "   ")).toBeNull();
    expect(boundText("title", null)).toBeNull();
    expect(boundText("title", undefined)).toBeNull();
  });

  it("keeps a value that fits", () => {
    expect(boundText("title", "Dune")).toBe("Dune");
  });

  it("cuts a title, because half a title is still that book", () => {
    const long = "a".repeat(TEXT_CEILINGS.title + 10);
    expect(boundText("title", long)).toHaveLength(TEXT_CEILINGS.title);
  });

  it("never cuts between the halves of a surrogate pair", () => {
    // A lone surrogate is not a string any encoder will emit: pydantic answers
    // `string_unicode` and the whole book is lost to a 422, which is the exact
    // outcome this module exists to prevent. Asserted by round tripping through
    // an encoder rather than by looking at the characters, because a lone
    // surrogate reads as an ordinary character to everything that does not
    // encode it.
    const cut = boundText(
      "title",
      "a".repeat(TEXT_CEILINGS.title - 1) + "\u{1F600}",
    )!;
    expect(new TextDecoder().decode(new TextEncoder().encode(cut))).toBe(cut);
  });

  it("counts code points, because the column and the schema both do", () => {
    // The ceiling belongs to a Python `str` and to a SQLite column, both of
    // which count code points. Counting UTF-16 units refuses at 250 emoji what
    // the server would have taken 500 of.
    const cut = boundText(
      "title",
      "\u{1F600}".repeat(TEXT_CEILINGS.title + 10),
    )!;
    expect([...cut]).toHaveLength(TEXT_CEILINGS.title);
  });

  it("drops a language code rather than cutting it", () => {
    // A cut code names a different language or nothing at all, which is why
    // this half of the policy exists.
    expect(
      boundText("language", "x".repeat(TEXT_CEILINGS.language + 1)),
    ).toBeNull();
  });

  it("drops an over-wide ISBN rather than cutting it", () => {
    // The sharpest case: a cut identifier fails its own checksum, so it names
    // no book, and `books.isbn` is the importer's match key.
    expect(boundText("isbn", "9".repeat(TEXT_CEILINGS.isbn + 1))).toBeNull();
  });
});

describe("boundNumber", () => {
  it("keeps a value inside the range, at both ends", () => {
    expect(boundNumber("year", NUMBER_RANGES.year[0])).toBe(
      NUMBER_RANGES.year[0],
    );
    expect(boundNumber("year", NUMBER_RANGES.year[1])).toBe(
      NUMBER_RANGES.year[1],
    );
  });

  it("drops a value outside it rather than clamping", () => {
    // Clamping turns a number the file got wrong into a plausible one. 3000 is
    // not 2200 seen through a narrower window.
    expect(boundNumber("year", NUMBER_RANGES.year[1] + 1)).toBeNull();
    expect(boundNumber("page_count", 0)).toBeNull();
  });

  it("drops a series index the shelf listing could not survive", () => {
    // `routers/books.list_series` builds `range(1, max + 1)` over the column,
    // so an unbounded value here is minutes of work on every request.
    expect(boundNumber("series_index", 1e9)).toBeNull();
  });

  it("is null for nothing, and for a number that is not one", () => {
    expect(boundNumber("year", null)).toBeNull();
    expect(boundNumber("year", undefined)).toBeNull();
    expect(boundNumber("year", Number.NaN)).toBeNull();
    expect(boundNumber("year", Number.POSITIVE_INFINITY)).toBeNull();
  });
});

const BOOK_BOUNDS = "../../src/lib/bookBounds.ts";

/** What lives under `src/` and is not a module. The scans state it as their reach. */
const STYLESHEETS = ["../../src/index.css", "../../src/theme/palettes.css"];

const isModule = (path: string) => /\.tsx?$/.test(path);

/**
 * Every module under `src/`, as text, over a glob that proves its own reach.
 *
 * **Non-emptiness is not reach, and the difference is the whole guard.** A glob
 * narrowed to `bookBounds.ts` alone satisfies every check that reads
 * `sources[BOOK_BOUNDS]`, and narrowing it is the shape a later simplification
 * takes, so the scans below would sweep the one module they exempt and pass.
 * What is asserted instead is what the glob holds **besides** the modules,
 * stated as the exclusion: the two stylesheets under `src/`. No pattern that
 * misses a directory can still answer that.
 *
 * The cost, since it is real: a third stylesheet, or any other kind of file
 * added under `src/`, fails here until somebody names it. That is the safe
 * direction, and a person deciding whether a new kind of file belongs in a
 * source scan is the point rather than the price.
 */
function sourceModules(): Record<string, string> {
  // **Two globs, and the one that measures the reach reads no content.** Names
  // are all it needs, and an eager `?raw` sweep of everything would decode the
  // first binary asset added under `src/` as UTF-8 and inline it into this
  // bundle before failing on it, which is the one event that assertion exists
  // to catch.
  const everything = import.meta.glob("../../src/**/*");
  const modules = import.meta.glob("../../src/**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  const named = Object.keys(everything);

  // **Both assertions, because either glob alone can be narrowed.** The first
  // says what the tree holds beyond the modules, stated as the exclusion, so a
  // pattern that misses a directory cannot still answer it. The second binds
  // the sweep the scans actually read to it, so narrowing that one is red here
  // rather than in whichever neighbouring arm happens to name enough files.
  expect(
    named.filter((path) => !isModule(path)).sort(),
    "a new kind of file under src/: name it in STYLESHEETS if the scans should skip it",
  ).toEqual(STYLESHEETS);
  expect(
    Object.keys(modules).sort(),
    "the scans have to read every module the tree holds",
  ).toEqual(named.filter(isModule).sort());

  return modules;
}

/** `1_450` is the same literal as `1450` to the compiler, and to a scan. */
function withoutSeparators(text: string): string {
  return text.replace(/(?<=\d)_(?=\d)/g, "");
}

/**
 * The window's two ends, read out of the declaration that owns them.
 *
 * **Derived rather than restated, which is the difference between a guard that
 * moves with the window and two literals that fall out of step with it.** A
 * pair written here again is an enumeration of two: halving it takes an end out
 * of the scan with nothing red, and moving the window in the source leaves the
 * scan hunting a number that is no longer either end.
 *
 * **Anchored, and exactly one.** Unanchored this bound to the first occurrence
 * of the text anywhere in the file, and a docstring quoting a declaration is
 * house style in this tree, so one commented line carrying a superseded pair
 * made the scan below guard numbers that were no longer the window, green. The
 * anchor stops a comment's ` * ` prefix from matching, and the count refuses a
 * decoy standing **alongside** the declaration, since a line at column zero
 * inside a block comment or a template literal is still a line.
 *
 * **What it does not remove**: a sole match at column zero is trusted, so a
 * decoy is still read as the declaration if the real one is indented out of
 * reach, inside a function body.
 *
 * **The decoy's numbers need not be a superseded window, and that is the half
 * with no backstop.** A decoy that moves the window as well goes red at the
 * arms above, which state `1450` and `2100` as literals. One substituted while
 * the window stands still leaves those arms green by construction, and then a
 * real second carrier of the live floor passes unreported: the scan is
 * disarmed rather than weakened. Both measured.
 *
 * Nothing is bought for it here, and **the two ways of closing it do not cost
 * the same**. A count of the identifier fails on prose that quotes a
 * declaration, which is this tree's house style and is how the decoy class
 * arrived in the first place: measured over `bookBounds.ts`, 2 in the real tree
 * and 3 with one JSDoc line quoting the declaration. A match that ignores
 * indentation, asserting one, pays no such tax: 1 in the real tree, 1 with that
 * quoting line, and 2 with a decoy beside the declaration, because a comment's
 * ` * ` prefix never matches it. The precondition, a module constant moved into
 * a function body, is what a diff shows plainly.
 *
 * A renamed, deleted, inlined or reformatted declaration fails here rather than
 * passing quietly, which is the price of reading the source instead of
 * importing `PLAUSIBLE_YEARS`, which is deliberately not exported.
 */
function declaredWindow(sources: Record<string, string>): {
  low: string;
  high: string;
} {
  const declarations = [
    ...withoutSeparators(sources[BOOK_BOUNDS] ?? "").matchAll(
      /^const PLAUSIBLE_YEARS = \[(\d+), (\d+)\]/gm,
    ),
  ];
  expect(declarations).toHaveLength(1);
  const [, low, high] = declarations[0]!;
  return { low: low!, high: high! };
}

describe("plausibleYear", () => {
  it("keeps both ends of the window", () => {
    // Stated as the numbers rather than read off the module: the pair is not
    // exported, and a test importing what it checks would move with it.
    expect(plausibleYear(1450)).toBe(1450);
    expect(plausibleYear(2100)).toBe(2100);
  });

  it("refuses the year either side of it", () => {
    expect(plausibleYear(1449)).toBeNull();
    expect(plausibleYear(2101)).toBeNull();
  });

  it("refuses the year Calibre writes for a book with no date", () => {
    // `0101-01-01T00:00:00+00:00` is Calibre's undefined date and 2 of 69 real
    // MOBI files carry it in EXTH 106. This is the case the window was written
    // for, so it is asserted by its value rather than as another number below
    // the floor.
    expect(plausibleYear(101)).toBeNull();
  });

  it("refuses what the column would have held, which is the whole point", () => {
    // The two windows answer different questions, and this pins the difference
    // rather than the numbers: a reader "simplifying" one into the other passes
    // every assertion above and fails this one, because the wider window
    // reports nothing.
    expect(boundNumber("year", 101)).toBe(101);
    expect(plausibleYear(101)).toBeNull();
  });

  it("is null for nothing, and for a number that is not one", () => {
    expect(plausibleYear(null)).toBeNull();
    expect(plausibleYear(undefined)).toBeNull();
    expect(plausibleYear(Number.NaN)).toBeNull();
    expect(plausibleYear(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it("is the only place in the source carrying either end of the window", () => {
    // Three readers declared `[1450, 2100]` for one job, each unaware of the
    // others, and the third was written by somebody who had read the second.
    // A guard rather than a rule in a document, because the copy is what a
    // reviewer of a new reader would have to notice.
    //
    // **Four evasions found the first three drafts, and none is answered with
    // an arm.** A floor only matcher let `const NOT_IN_THE_FUTURE = 2100`
    // through. `[1_450, 2_100]` is the same literal to the compiler and was not
    // the same string to the scan, so the separator family is normalised away
    // before any match, which covers `14_50` and `1_4_5_0` with it. An
    // alternation over the two ends could be halved back to one with nothing
    // red, so the ends are read out of the declaration and each is asserted on
    // its own. And a commented copy of a superseded pair could stand in for the
    // live one, which `declaredWindow` answers.
    //
    // **Once in the file that owns it, not once per file.** The carrier set
    // says the numbers live in one module; the count says they are one
    // declaration inside it, so a second window under another name in this same
    // module is not the one place this test's name claims. The cost is that
    // prose here may not quote either end.
    //
    // **The exclusion.** It reads the modules under `src/`, so `tests/`,
    // `vite.config.ts`, `scripts/`, `types/`, the stylesheets and the backend
    // are outside it. It catches a copied literal and not a computed one:
    // `1449 + 1` and `0x5aa` are outside any scan of this kind, and a window
    // with different numbers is a different rule. Deriving the ends also makes
    // it depend on them being rare: a window moved onto a number many modules
    // carry turns this red on unrelated files, which is loud and wrong rather
    // than quiet and wrong. `2000` has 3 such carriers today, measured over the
    // modules under `src/` by `grep -rlw` and again by a walk applying the
    // normaliser above.
    const sources = sourceModules();
    const { low, high } = declaredWindow(sources);

    const carriersOf = (end: string) =>
      Object.entries(sources)
        .filter(([, text]) =>
          new RegExp(`\\b${end}\\b`).test(withoutSeparators(text)),
        )
        .map(([path]) => path)
        .sort();

    const timesInItsOwnModule = (end: string) =>
      (
        withoutSeparators(sources[BOOK_BOUNDS] ?? "").match(
          new RegExp(`\\b${end}\\b`, "g"),
        ) ?? []
      ).length;

    expect(carriersOf(low), `the window's floor, ${low}`).toEqual([
      BOOK_BOUNDS,
    ]);
    expect(carriersOf(high), `the window's ceiling, ${high}`).toEqual([
      BOOK_BOUNDS,
    ]);
    expect(
      timesInItsOwnModule(low),
      `the floor, ${low}, in its own module`,
    ).toBe(1);
    expect(
      timesInItsOwnModule(high),
      `the ceiling, ${high}, in its own module`,
    ).toBe(1);
  });

  it("is named and called by the readers that apply it, and by nothing else", () => {
    // The scan above watches the numbers coming back into another module. This
    // one watches the function going out, which is what the old arrangement
    // refused and this one has to be told to refuse: three module private
    // constants could not be reached from outside their own file at all.
    //
    // `plausibleYear` reads as the more specific of the two, and it lives in
    // the module the scan page and the Calibre import already import for
    // `boundNumber("year", ...)`, so the cheap mistake is a page swapping it in
    // on a year a member typed, which drops a genuine 1400 and reports nothing.
    //
    // **Named and called are two facts and each has its own assertion.** The
    // name scan is what catches a module reaching for a window it should not
    // have, and it says nothing about whether a module on the list still uses
    // what it imports: a reader that deletes the call and leaves the identifier
    // in a docstring passes it. **The call scan narrows that and only narrows
    // it**, because it reads `plausibleYear(` and a docstring writing
    // `plausibleYear(101)` is that string, which is the spelling this file
    // itself uses five times. What actually refuses a reader that drops the
    // call is the arm in that reader's own test file, which is the rung below
    // both of these.
    //
    // **The list is the assertion and not a filter**, and it runs both ways: a
    // new caller is a decision about which values get a plausibility window and
    // fails here until somebody makes it, and a reader dropping out fails here
    // too, because `toEqual` on a sorted list is an equality rather than a
    // containment.
    //
    // **The exclusion, stated because the list is an inclusion.** A reader
    // added with no window names nothing and passes here, which is exactly how
    // `opf.ts`, `cbz.ts` and `fb2.ts` sat unwindowed with nothing red. The
    // complement was measured rather than assumed unbuildable. Under
    // `src/lib/`, `grep -rlE '(^|[^A-Za-z_])year\??\s*:'` finds 9 modules
    // carrying a year property, so a complement drawn there needs a three name
    // exclusion. Drawn over the whole of `src/` it needs more than a dozen, and
    // **how many depends on the spelling the pattern allows**: 17 and 23 by two
    // readings of the same question, measured by two people who each thought
    // they had asked it. That disagreement is the argument against drawing the
    // line there, and it is worth more than either number. A predicate over
    // `FileMetadata` is tighter at 9 modules and misses `fileName.ts`, which
    // windows a year and builds no record. Neither is a complement, so neither
    // is here.
    //
    // There is no live exclusion now. `calibre.ts::readYear` was the last one,
    // refusing the literal 101 by name and leaving the rest of the band open,
    // and it joined this list on 2026-09-10. `audiobook.ts` reads no year at
    // all. That the list is complete today is what makes the paragraph above
    // load bearing rather than academic: nothing else stands between an eighth
    // reader and an unwindowed year.
    //
    // **What this closes and what it does not.** Any module outside the list
    // that names `plausibleYear` fails here, whether it imports it from
    // `bookBounds.ts` or from one of the readers, and a plain re-export is
    // covered with them: a consumer of one still has to name the identifier.
    // What it does not see is an alias, `export { plausibleYear as believable }`
    // or `const believable = plausibleYear` re-exported under that name, since
    // from there nothing downstream carries the word. No arm is added: a scan
    // for either spelling reports the family closed while the other walks past
    // it, and the family closes with the module graph or not at all.
    //
    // **Nor does it see a second window a reader keeps beside this one**, which
    // is the class this module was written to end. A caller answering from its
    // own `year > 1000 && year < 2150` and falling through to `plausibleYear`
    // for the rest is green on both scans here and green on the number scan
    // above, since neither 1000 nor 2150 is an end of the window. **What sees
    // it is each reader's own boundary arm**, and that is why those assert the
    // point immediately outside each end rather than a number far outside it:
    // any contiguous widening of an end has to contain that point.
    //
    // Measured 2026-09-08 against the whole frontend suite, 3019 tests, by
    // putting that band into `cbz.readYear` and then into `fb2.yearIn`: 1 red
    // each, the reader's own arm both times. **The first version of those arms
    // asserted 101 and 2199 and the same mutation passed all 3019**, which is
    // this file's own rule about a guard's author picking the case the guard
    // covers. The band was chosen by the seat that wrote none of these arms and
    // the boundary values by the other one.
    //
    // **What is left is an accepted set that touches neither end**, which is
    // wider than a point and is the property rather than an example: the
    // boundary values catch a widening OF an end, and a second window sitting
    // wholly inside this one touches neither. Both `year === 1200` and
    // `year >= 1200 && year <= 1300`, each falling through to `plausibleYear`
    // for the rest, passed all 3019 in the same runs. Nothing cheap catches
    // either, because no arm can name a value it was not told about. What
    // refuses them is a reviewer reading the diff, where a second comparison
    // beside a call to this one is plain.
    const named = Object.entries(sourceModules())
      .filter(([path]) => path !== BOOK_BOUNDS)
      .filter(([, text]) => /\bplausibleYear\b/.test(text));

    const READERS = [
      "../../src/lib/calibre.ts",
      "../../src/lib/cbz.ts",
      "../../src/lib/fb2.ts",
      "../../src/lib/fileName.ts",
      "../../src/lib/kobo.ts",
      "../../src/lib/mobi.ts",
      "../../src/lib/opf.ts",
      "../../src/lib/pdf.ts",
    ];

    expect(named.map(([path]) => path).sort()).toEqual(READERS);
    expect(
      named
        .filter(([, text]) => /\bplausibleYear\(/.test(text))
        .map(([path]) => path)
        .sort(),
      "a reader that names the window has to call it",
    ).toEqual(READERS);
  });
});

/** The `q` parameter of `GET /api/books/search`, read off the schema. */
function searchQueryConstraint(): { maxLength: number; minLength: number } {
  const raw = SCHEMA["../../openapi.json"] ?? "";
  // A glob that matched nothing would make both assertions below pass forever.
  expect(raw.length).toBeGreaterThan(1000);
  const schema = JSON.parse(raw) as {
    paths: Record<
      string,
      {
        get: {
          parameters: {
            name: string;
            schema: { maxLength?: number; minLength?: number };
          }[];
        };
      }
    >;
  };
  const parameter = schema.paths["/api/books/search"]?.get.parameters.find(
    (candidate) => candidate.name === "q",
  );
  expect(parameter).toBeDefined();
  const { maxLength, minLength } = parameter!.schema;
  expect(maxLength).toBeDefined();
  expect(minLength).toBeDefined();
  return { maxLength: maxLength!, minLength: minLength! };
}

describe("the query bounds", () => {
  it("are the search endpoint's own, recomputed rather than restated", () => {
    // The same reason every ceiling above has: a bound
    // copied out of a schema stops being true the first time the schema moves,
    // and it fails in the quiet direction, by asking for less than it could.
    //
    // Moved here with the constants themselves: it was written beside the
    // filename derivation, which was one of the three places that declared
    // the floor rather than the place that owns it.
    const { maxLength, minLength } = searchQueryConstraint();
    expect(QUERY_CEILING).toBe(maxLength);
    expect(QUERY_FLOOR).toBe(minLength);
  });
});
