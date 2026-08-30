/**
 * @vitest-environment node
 *
 * Pure functions and a JSON file, so this needs no DOM. Building one costs more
 * than the file spends running: `environment` was 168s of a 245s suite run,
 * paid once per file.
 */
/**
 * Tests for src/lib/bookFilters.ts.
 *
 * Two jobs. The first half is the URL round trip, which is ordinary unit
 * testing. The second half is the guard: `BookFilters` exists on both sides of
 * the wire, `backend/shelf.py` has its own, and until now nothing checked that
 * the two describe the same set of filters.
 */

import { describe, expect, it } from "vitest";

import {
  BookFormat,
  BookSort,
  LendingWillingness,
  OwnershipStatus,
  ReadStatus,
} from "../../src/api/generated/model";
import { readFilters, toParams } from "../../src/lib/bookFilters";
import { DEFAULT_FILTERS, type BookFilters } from "../../src/pages/Home/types";

function read(search: string): BookFilters {
  return readFilters(new URLSearchParams(search));
}

describe("readFilters", () => {
  it("gives the defaults for a bare URL", () => {
    expect(read("")).toEqual(DEFAULT_FILTERS);
  });

  it("starts on the ownership a link names", () => {
    // The link the Goodreads import result offers, and the one the unconfirmed
    // banner uses. It has to survive a full page load, not just an in-app click.
    expect(read("?ownership=unknown").ownership).toBe(OwnershipStatus.unknown);
  });

  it("ignores a value that is not an ownership state", () => {
    expect(read("?ownership=maybe").ownership).toBeNull();
  });

  it("starts on the read status a link names", () => {
    expect(read("?status=read").status).toBe(ReadStatus.read);
  });

  it("ignores a status that is not one of the five", () => {
    expect(read("?status=abandoned").status).toBeNull();
  });

  it("starts on the sort a link names", () => {
    expect(read("?sort=year_desc").sort).toBe(BookSort.year_desc);
  });

  it("falls back to the default sort rather than sending a made up one", () => {
    // The one field with no null: an unrecognised value here would reach the
    // API as a sort it answers 422 to.
    expect(read("?sort=vibes").sort).toBe(DEFAULT_FILTERS.sort);
  });

  it("starts on the format a link names", () => {
    expect(read("?format=ebook").format).toBe(BookFormat.ebook);
  });

  it("ignores a format that is not one of the five", () => {
    expect(read("?format=scroll").format).toBeNull();
  });

  it("starts on the lending willingness a link names", () => {
    expect(read("?lending=never").lending).toBe(LendingWillingness.never);
  });

  it("ignores a willingness that is not one of the three", () => {
    expect(read("?lending=sometimes").lending).toBeNull();
  });

  it("treats a bare ?discuss as on", () => {
    // What a link somebody typed looks like. Reading it as off would make the
    // link silently do nothing.
    expect(read("?discuss").discuss).toBe(true);
  });

  it("treats ?discuss=false as off", () => {
    expect(read("?discuss=false").discuss).toBe(false);
  });

  it("keeps a series, an author and a location verbatim", () => {
    // No guard is possible: any string is a plausible one, and the author may
    // be a display name or the folded key the authors endpoint issues.
    const filters = read(
      "?series=Dune&author=ursula%20k%20le%20guin&location=loft",
    );
    expect(filters.series).toBe("Dune");
    expect(filters.author).toBe("ursula k le guin");
    expect(filters.location).toBe("loft");
  });

  it("starts on the collection a link names", () => {
    expect(read("?collection=4").collection).toBe(4);
  });

  it("starts on the unfiled books", () => {
    expect(read("?collection=unfiled").collection).toBe("unfiled");
  });

  it("ignores a collection that is neither an id nor unfiled", () => {
    expect(read("?collection=everything").collection).toBeNull();
  });

  it("ignores a collection id that is not a positive whole number", () => {
    expect(read("?collection=0").collection).toBeNull();
    expect(read("?collection=-3").collection).toBeNull();
    expect(read("?collection=1.5").collection).toBeNull();
  });
});

/**
 * How each field arrives in a link, and the two that do not.
 *
 * **A link and a request do not use the same vocabulary**, which this table
 * exists to make visible. `?collection=3` is the app's own route parameter and
 * `collection_id=3` is the listing endpoint's: `readFilters` reads the first
 * and `toParams` writes the second, and feeding one into the other is what
 * this test caught when it was written the naive way.
 *
 * A thirteenth field added to the shape is in neither table, so this fails.
 */
const CARRIED_BY_A_LINK: { [K in keyof BookFilters]?: [string, string] } = {
  status: ["status", ReadStatus.read],
  ownership: ["ownership", OwnershipStatus.owned],
  series: ["series", "Dune"],
  author: ["author", "frank herbert"],
  location: ["location", "loft"],
  format: ["format", BookFormat.ebook],
  lending: ["lending", LendingWillingness.happy],
  collection: ["collection", "3"],
  discuss: ["discuss", "1"],
  sort: ["sort", BookSort.author],
  // Both spellings the classification filter uses. `classification` repeats
  // rather than joining, because an LCSH heading carries commas; `ddc` joins,
  // because a division is three digits. One entry each is enough here: the
  // repetition and the encoding are pinned by their own tests below.
  headings: ["classification", "lcsh:Mental health"],
  ddcDivisions: ["ddc", "150"],
};

/**
 * Fields a link deliberately cannot carry, with the parameter names somebody
 * would reach for and the reason for each.
 *
 * **The parameter names, not the field names**, for the same reason the table
 * above carries them: a link and a request do not use the same vocabulary. The
 * first version of this probed `?query=` and `?tagIds=`, which nothing emits,
 * so wiring `query` to `?q=` left it green. Measured.
 */
const NOT_CARRIED_BY_A_LINK: Record<string, { params: string[]; why: string }> =
  {
    query: {
      params: ["q", "query"],
      why:
        "the search box's contents. A link naming somebody's half typed search " +
        "is not something this app produces.",
    },
    tagIds: {
      params: ["tags", "tagIds"],
      why:
        "a set of tag ids, which are this deployment's row ids. A link carrying " +
        "them means something different in every library.",
    },
  };

describe("readFilters covers the fields a link carries", () => {
  it("accounts for every field in the shape", () => {
    const unaccounted = Object.keys(SAMPLES).filter(
      (field) =>
        !(field in CARRIED_BY_A_LINK) && !(field in NOT_CARRIED_BY_A_LINK),
    );

    expect(unaccounted).toEqual([]);
  });

  it.each(Object.entries(CARRIED_BY_A_LINK))(
    "reads %s out of a link",
    (field, entry) => {
      const [parameter, value] = entry as [string, string];
      const read = readFilters(new URLSearchParams(`${parameter}=${value}`));

      expect(read[field as keyof BookFilters]).not.toEqual(
        DEFAULT_FILTERS[field as keyof BookFilters],
      );
    },
  );

  it.each(
    Object.entries(NOT_CARRIED_BY_A_LINK).flatMap(([field, entry]) =>
      entry.params.map((parameter) => [field, parameter] as const),
    ),
  )("does not quietly start carrying %s through ?%s=", (field, parameter) => {
    // The other direction: if one of these ever round trips, the reason in the
    // table above is stale. Every spelling is probed, because the one somebody
    // would wire up is the parameter name and not the field name.
    const read = readFilters(new URLSearchParams(`${parameter}=anything`));

    expect(read[field as keyof BookFilters]).toEqual(
      DEFAULT_FILTERS[field as keyof BookFilters],
    );
  });
});

describe("toParams", () => {
  it("sends nothing but the sort for an unfiltered library", () => {
    // Empty values are omitted rather than sent blank, so the query key, and
    // therefore the cache entry, is the same as an unfiltered request.
    expect(toParams(DEFAULT_FILTERS)).toEqual({ sort: DEFAULT_FILTERS.sort });
  });

  it("does not decide the page size", () => {
    // Paging belongs to whoever is reading, not to the filter set.
    expect(toParams(DEFAULT_FILTERS)).not.toHaveProperty("page_size");
  });

  it("joins several tag ids with commas", () => {
    expect(toParams({ ...DEFAULT_FILTERS, tagIds: [1, 2] }).tags).toBe("1,2");
  });

  it("sends a collection as an id", () => {
    expect(toParams({ ...DEFAULT_FILTERS, collection: 4 })).toEqual({
      sort: DEFAULT_FILTERS.sort,
      collection_id: 4,
    });
  });

  it("asks for the unfiled books with their own parameter", () => {
    // Never both: the API answers 422 to a request naming a collection and the
    // unfiled books at once, so one field has to produce one or the other.
    expect(toParams({ ...DEFAULT_FILTERS, collection: "unfiled" })).toEqual({
      sort: DEFAULT_FILTERS.sort,
      unfiled: true,
    });
  });

  it("sends the discussion filter only when it is on", () => {
    expect(toParams({ ...DEFAULT_FILTERS, discuss: true }).discuss).toBe(true);
    expect(toParams(DEFAULT_FILTERS)).not.toHaveProperty("discuss");
  });

  it("sends headings as a repeated parameter, not a joined string", () => {
    // The one filter that cannot follow `tags`. An LCSH number is the
    // authorised heading string and those carry commas, so a joined list
    // cannot be taken apart again on the other side.
    expect(
      toParams({
        ...DEFAULT_FILTERS,
        headings: ["lcsh:Mental health, Public", "ddc:004"],
      }).classification,
    ).toEqual(["lcsh:Mental health, Public", "ddc:004"]);
  });

  it("joins divisions, which is safe because a division is three digits", () => {
    expect(
      toParams({ ...DEFAULT_FILTERS, ddcDivisions: ["150", "330"] }).ddc,
    ).toBe("150,330");
  });

  it("omits both when nothing is selected", () => {
    expect(toParams(DEFAULT_FILTERS)).not.toHaveProperty("classification");
    expect(toParams(DEFAULT_FILTERS)).not.toHaveProperty("ddc");
  });
});

describe("a link carrying classifications", () => {
  it("reads a repeated heading parameter, commas and all", () => {
    const filters = readFilters(
      new URLSearchParams(
        "classification=lcsh:Mental health, Public&classification=ddc:004",
      ),
    );

    expect(filters.headings).toEqual(["lcsh:Mental health, Public", "ddc:004"]);
  });

  it("reads divisions from one comma separated parameter", () => {
    expect(
      readFilters(new URLSearchParams("ddc=150,330")).ddcDivisions,
    ).toEqual(["150", "330"]);
  });

  it("carries neither when the link names neither", () => {
    const filters = readFilters(new URLSearchParams(""));

    expect(filters.headings).toEqual([]);
    expect(filters.ddcDivisions).toEqual([]);
  });

  it("drops an empty value rather than filtering on nothing", () => {
    // `?ddc=` and `?classification=` are what a cleared control puts in a URL.
    const filters = readFilters(new URLSearchParams("ddc=&classification="));

    expect(filters.headings).toEqual([]);
    expect(filters.ddcDivisions).toEqual([]);
  });
});

/**
 * One non-default value per field.
 *
 * Typed as a total mapping of `BookFilters`, so a field added to the shape and
 * not to this table is a compile error rather than a filter nothing checks.
 */
const SAMPLES: { [K in keyof BookFilters]-?: BookFilters[K] } = {
  query: "dune",
  status: ReadStatus.read,
  ownership: OwnershipStatus.owned,
  series: "Dune",
  author: "frank herbert",
  location: "loft",
  format: BookFormat.ebook,
  lending: LendingWillingness.happy,
  collection: 4,
  discuss: true,
  sort: BookSort.year_desc,
  tagIds: [1, 2],
  headings: ["lcsh:Mental health", "ddc:004"],
  ddcDivisions: ["150", "330"],
};

const SCHEMA = import.meta.glob("../../openapi.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

interface Parameter {
  name: string;
  in: string;
}

/** The query parameter names `GET /api/books` documents. */
function apiFilterNames(): string[] {
  const raw = SCHEMA["../../openapi.json"] ?? "";
  // A glob that matched nothing would make every assertion below pass forever.
  expect(raw.length).toBeGreaterThan(1000);

  const schema = JSON.parse(raw) as {
    paths: Record<
      string,
      Record<string, { operationId?: string; parameters?: Parameter[] }>
    >;
  };
  const operations = Object.values(schema.paths).flatMap((methods) =>
    Object.values(methods).filter(
      (operation) => operation.operationId === "list_books",
    ),
  );
  expect(operations).toHaveLength(1);

  const names = (operations[0]!.parameters ?? [])
    .filter((parameter) => parameter.in === "query")
    .map((parameter) => parameter.name);
  // An operation whose parameters moved into a $ref, or a listing that stopped
  // taking filters, would leave both comparisons below asserting nothing.
  expect(names.length).toBeGreaterThan(10);
  return names;
}

/** Every parameter name the app can put on a listing request. */
function sentNames(): string[] {
  const everything = { ...SAMPLES };
  return [
    ...new Set([
      ...Object.keys(toParams(everything)),
      // The one field that produces either of two parameters, never both.
      ...Object.keys(toParams({ ...everything, collection: "unfiled" })),
    ]),
  ];
}

/**
 * Parameters `GET /api/books` accepts that the library grid never sends.
 *
 * Each one is a deliberate omission and says why. The list is the whole point
 * of the guard: an addition to it is a decision somebody made, where a silent
 * difference is a filter one side has and the other does not know about.
 */
const NOT_SENT_BY_THE_GRID: Record<string, string> = {
  // Paging is the caller's, not the filter set's. `useLibrary` adds page_size
  // and React Query's infinite query adds page.
  page: "paging",
  page_size: "paging",
  // Accepted by the API and sent by nothing in this app: grepped 2026-08-26,
  // the only "unrated" in src/ is the message key `rating.unrated`. Named here
  // so that stays a decision rather than a discovery.
  unrated: "no control offers it",
};

/**
 * Filters the app holds that are not query parameters at all.
 *
 * Empty, and that is a claim rather than an omission: `view` is the case this
 * exists for, and it is browser-local rather than a filter, so it is not a
 * `BookFilters` field and never reaches this comparison.
 */
const CLIENT_ONLY: string[] = [];

describe("the filters agree with the API", () => {
  it("sends no parameter the listing endpoint does not accept", () => {
    // A filter the UI sends and the API ignores is silent: a 200, the whole
    // library, and nothing in any log.
    const accepted = new Set(apiFilterNames());
    const unknown = sentNames()
      .filter((name) => !accepted.has(name))
      .filter((name) => !CLIENT_ONLY.includes(name));

    expect(unknown).toEqual([]);
  });

  it("sends every parameter the listing endpoint accepts, or names why not", () => {
    // The other direction, and the one that goes stale on its own: a filter
    // added to the API is a feature the UI cannot reach until somebody wires
    // it up, and nothing else would say so.
    const sent = new Set(sentNames());
    const missing = apiFilterNames().filter(
      (name) => !sent.has(name) && !(name in NOT_SENT_BY_THE_GRID),
    );

    expect(missing).toEqual([]);
  });

  it("puts every filter field on the wire", () => {
    // The frontend half of `test_shelf.py::test_every_filter_field_narrows_
    // something`. A field the UI collects, shows a chip for and never sends is
    // a control that appears to do nothing.
    const unfiltered = JSON.stringify(toParams(DEFAULT_FILTERS));
    const fields = Object.keys(SAMPLES) as (keyof BookFilters)[];
    const unsent = fields.filter(
      (field) =>
        JSON.stringify(
          toParams({ ...DEFAULT_FILTERS, [field]: SAMPLES[field] }),
        ) === unfiltered,
    );

    expect(unsent).toEqual([]);
  });
});
