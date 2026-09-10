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
 * **Every number here is recomputable, and the one that was not has left.**
 * The plausibility window `year.plausibleYear` applies has no schema behind it,
 * so it moved to `lib/year.ts` with the two functions that apply it and is
 * checked by `tests/lib/year.test.ts`, source scans included. What is left here
 * is `boundNumber("year", ...)`, which is the range the column holds, and the
 * arm proving it is the wider of the two lives beside the narrower one.
 */

import { describe, expect, it } from "vitest";

import {
  boundNumber,
  boundText,
  CUT_TO_FIT,
  KEPT_WHOLE,
  NUMBER_RANGES,
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
