/**
 * @vitest-environment node
 *
 * Pure functions and a JSON file, so this needs no DOM. Building one costs more
 * than the file spends running.
 */
/**
 * Tests for src/pages/ScanPage/types.ts.
 *
 * Two jobs, the same two as `tests/lib/bookFilters.test.ts`. The first half is
 * what `toScanRequest` builds, which is ordinary unit testing. The second half
 * is the guard: the scan flow is the only place in the app that writes a whole
 * book, and until now nothing checked that what it sends and what
 * `POST /api/books/scan` accepts are the same set. A field the app sends and
 * the API ignores is a 201 with a column silently unset.
 */

import { describe, expect, it } from "vitest";

import {
  BookFormat,
  ClassificationScheme,
} from "../../../src/api/generated/model";
import type { AudiobookGroup } from "../../../src/lib/audiobookGroups";
import {
  blankPending,
  draftFromAudiobook,
  draftFromFile,
  toCopyRequest,
  toScanRequest,
  type BookDraft,
  type PendingBook,
} from "../../../src/pages/ScanPage/types";
import { TEXT_CEILINGS } from "../../../src/lib/bookBounds";
import type { FileMetadata } from "../../../src/lib/fileReaders";
import { CARRIES_A_BOOK } from "../../carriesABook";

/**
 * One value per draft field, all of them set.
 *
 * Typed as a total mapping of `BookDraft`, so a field added to the lookup
 * shape and not to this table is a compile error rather than a field nothing
 * checks.
 */
const DRAFT: { [K in keyof BookDraft]-?: BookDraft[K] } = {
  isbn: "9780441013593",
  title: "Dune",
  subtitle: "A Novel",
  author: "Frank Herbert",
  publisher: "Chilton",
  year: 1965,
  description: "Desert planet politics.",
  cover_url: "https://covers.openlibrary.org/b/isbn/9780441013593-L.jpg",
  language: "en",
  page_count: 412,
  series_name: "Dune",
  series_index: 1,
  classifications: [
    { scheme: ClassificationScheme.ddc, number: "813.54", label: "Fiction" },
  ],
  suggested_tag_ids: [7],
  notFound: false,
};

/** The same, for the whole pending book. Total for the same reason. */
const PENDING: { [K in keyof PendingBook]-?: PendingBook[K] } = {
  draft: DRAFT,
  coverFile: new File(["jpeg bytes"], "cover.jpg", { type: "image/jpeg" }),
  isPrivate: true,
  location: "Loft box 2",
  format: BookFormat.paperback,
  tagIds: [7, 9],
};

/** `PENDING` with one field changed, still carrying a draft. */
function pending(patch: Partial<PendingBook> = {}) {
  return { ...PENDING, ...patch, draft: patch.draft ?? DRAFT };
}

describe("blankPending", () => {
  it("keeps the shelf it is given and nothing else", () => {
    // The carry-over is the whole reason it takes one: a cancel resets the
    // book and keeps the bookcase somebody is standing in front of.
    expect(blankPending("Loft box 2")).toEqual({
      draft: null,
      coverFile: null,
      isPrivate: false,
      location: "Loft box 2",
      format: "",
      tagIds: [],
    });
  });
});

describe("toCopyRequest", () => {
  /**
   * The value half, which the schema guards structurally cannot reach.
   *
   * `puts every field of the pending book on the copy wire` compares **key
   * names**, so a `toCopyRequest` that names `format` and ignores the pending
   * value passes it. Proved by mutation: hard-coding `format: null` left all
   * 141 tests green. `location` was covered by accident, through an end to end
   * assertion in `hooks.test.tsx`; `format` was covered by nothing.
   */
  it("sends the shelf and the format chosen for this copy", () => {
    expect(
      toCopyRequest(
        pending({ location: "  Loft box 2  ", format: BookFormat.paperback }),
      ),
    ).toEqual({ location: "Loft box 2", format: "paperback" });
  });

  it("sends null rather than a blank shelf or format", () => {
    expect(toCopyRequest(pending({ location: "   ", format: "" }))).toEqual({
      location: null,
      format: null,
    });
  });
});

describe("toScanRequest", () => {
  it("sends the metadata the lookup produced", () => {
    expect(toScanRequest(pending())).toMatchObject({
      isbn: "9780441013593",
      title: "Dune",
      author: "Frank Herbert",
      publisher: "Chilton",
      year: 1965,
      language: "en",
      page_count: 412,
      series_name: "Dune",
      series_index: 1,
    });
  });

  it("posts the catalogue headings back", () => {
    // The half of a heading that survives a language. The server writes a row
    // each, so dropping them here loses a record already paid for.
    expect(toScanRequest(pending()).classifications).toEqual([
      { scheme: "ddc", number: "813.54", label: "Fiction" },
    ]);
  });

  it("spells the privacy flag the way the column does", () => {
    const request = toScanRequest(pending({ isPrivate: true }));
    expect(request.is_private).toBe(true);
    expect(request).not.toHaveProperty("isPrivate");
  });

  it("drops the two client-only fields", () => {
    // Neither is a column. `notFound` decides which view the confirm card
    // shows and `suggested_tag_ids` is applied one call at a time afterwards.
    const request = toScanRequest(
      pending({ draft: { ...DRAFT, notFound: true } }),
    );
    expect(request).not.toHaveProperty("notFound");
    expect(request).not.toHaveProperty("suggested_tag_ids");
  });

  it("normalises the shelf", () => {
    expect(
      toScanRequest(pending({ location: "  Loft box 2  " })).location,
    ).toBe("Loft box 2");
  });

  it("sends null rather than a blank shelf or format", () => {
    // The columns are nullable and an empty string is a value: a book filed at
    // "" would answer a location filter and show an empty shelf name.
    const request = toScanRequest(pending({ location: "   ", format: "" }));
    expect(request.location).toBeNull();
    expect(request.format).toBeNull();
  });
});

const SCHEMA = import.meta.glob("../../../openapi.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

interface Operation {
  operationId?: string;
  requestBody?: {
    content?: Record<string, { schema?: { $ref?: string } }>;
  };
}

interface BodySchema {
  properties?: Record<string, unknown>;
  required?: string[];
}

/** The body one endpoint documents: what it accepts and what it insists on. */
function requestSchema(
  operationId: string,
  expectedRef: string,
  minimumProperties: number,
): BodySchema {
  const raw = SCHEMA["../../../openapi.json"] ?? "";
  // A glob that matched nothing would make every assertion below pass forever.
  expect(raw.length).toBeGreaterThan(1000);

  const schema = JSON.parse(raw) as {
    paths: Record<string, Record<string, Operation>>;
    components: { schemas: Record<string, BodySchema> };
  };
  const operations = Object.values(schema.paths).flatMap((methods) =>
    Object.values(methods).filter(
      (operation) => operation.operationId === operationId,
    ),
  );
  expect(operations).toHaveLength(1);

  const ref =
    operations[0]!.requestBody?.content?.["application/json"]?.schema?.$ref;
  // Named rather than only followed: a route that starts taking a different
  // schema is a change somebody should have to make here as well.
  expect(ref).toBe(expectedRef);

  const body = schema.components.schemas[ref!.split("/").pop()!]!;
  // A schema whose properties moved behind a composition keyword would leave
  // both comparisons below asserting nothing.
  expect(Object.keys(body.properties ?? {}).length).toBeGreaterThan(
    minimumProperties,
  );
  return body;
}

/** Every field name the scan flow can put in a scan request. */
function sentNames(): string[] {
  return Object.keys(toScanRequest(pending()));
}

/**
 * Fields `POST /api/books/scan` accepts that the scan flow never sends.
 *
 * Each is a deliberate omission and says why. An addition here is a decision
 * somebody made, where a silent difference is a column one side can fill and
 * the other does not know about.
 */
const NOT_SENT_BY_THE_SCAN_FLOW: Record<string, string> = {
  // Accepted by the endpoint and sent by nothing in the scan flow: the confirm
  // card offers a shelf, a format and a privacy tick, and no collection.
  // Filing happens afterwards from the book's own page. Named here so that
  // stays a decision rather than a discovery.
  collection_id: "the confirm card offers no collection",
};

/**
 * Fields the app holds that are not in the request body at all.
 *
 * **What the app holds and what the request carries are two vocabularies.**
 * These two are the case this exists for: both are real writes, and neither
 * can be made before the book has an id.
 */
const NOT_IN_THE_BODY: Record<string, string> = {
  coverFile: "a multipart POST to /cover once the book exists",
  tagIds: "one POST to /tags/{id} each once the book exists",
};

describe("the scan request agrees with the API", () => {
  it("sends no field the endpoint does not accept", () => {
    // A field the app sends and the API ignores is silent: a 201, a book, and
    // nothing in any log to say a column was never written.
    const accepted = new Set(
      Object.keys(
        requestSchema("scan_add", "#/components/schemas/BookCreate", 10)
          .properties ?? {},
      ),
    );

    expect(sentNames().filter((name) => !accepted.has(name))).toEqual([]);
  });

  it("sends every field the endpoint accepts, or names why not", () => {
    // The other direction, and the one that goes stale on its own: a column
    // added to the API is something the scan flow cannot set until somebody
    // wires it up, and nothing else would say so.
    const sent = new Set(sentNames());
    const missing = Object.keys(
      requestSchema("scan_add", "#/components/schemas/BookCreate", 10)
        .properties ?? {},
    ).filter((name) => !sent.has(name) && !(name in NOT_SENT_BY_THE_SCAN_FLOW));

    expect(missing).toEqual([]);
  });

  it("sends every field the endpoint requires", () => {
    // A 422 on the last press of a scan, after the lookup and the tag picking,
    // is the most expensive place in the app to discover a missing field.
    const sent = new Set(sentNames());
    const missing = (
      requestSchema("scan_add", "#/components/schemas/BookCreate", 10)
        .required ?? []
    ).filter((name) => !sent.has(name));

    expect(missing).toEqual([]);
  });

  it("puts every field of the pending book on the wire, or names why not", () => {
    // A field the confirm card collects, shows a control for and never sends
    // is a control that appears to do nothing.
    const blank = JSON.stringify(
      toScanRequest({ ...blankPending(""), draft: { isbn: "", title: "" } }),
    );
    const fields = Object.keys(PENDING) as (keyof PendingBook)[];
    const unsent = fields.filter(
      (field) =>
        JSON.stringify(
          toScanRequest({
            ...blankPending(""),
            draft: { isbn: "", title: "" },
            [field]: PENDING[field],
          }),
        ) === blank && !(field in NOT_IN_THE_BODY),
    );

    expect(unsent).toEqual([]);
  });
});

/**
 * The copy endpoint, guarded the same way and for the reason it was missed.
 *
 * `addCopy` built its request body from a literal, so the guard above saw the
 * scan request and nothing saw this one. `CopyCreate` and `BookCreate` do not
 * accept the same fields, so one function per endpoint is the only shape that
 * lets both be checked.
 */
describe("the copy request agrees with the API", () => {
  /** Fields `POST /api/books/{id}/copies` accepts that the scan flow omits. */
  const NOT_SENT_WHEN_COPYING: Record<string, string> = {
    collection_id:
      "the scan flow has no collection control at all, on either endpoint. " +
      "Same omission as the scan request records, and the same decision.",
    condition:
      "a per copy note about wear. There is no control for it on the confirm " +
      "step, and adding one is a design change rather than a plumbing one.",
    purchase_price_minor: "no purchase fields on the scan screen.",
    purchase_currency: "no purchase fields on the scan screen.",
    purchase_source: "no purchase fields on the scan screen.",
    purchased_at: "no purchase fields on the scan screen.",
    lending:
      "willingness to lend is a property of the copy and is set on the book " +
      "page afterwards, where the rest of the lending fields live.",
  };

  it("sends no field the endpoint does not accept", () => {
    const accepted = new Set(
      Object.keys(
        requestSchema("add_copy", "#/components/schemas/CopyCreate", 5)
          .properties ?? {},
      ),
    );
    const sent = Object.keys(toCopyRequest(pending()));

    expect(sent.filter((name) => !accepted.has(name))).toEqual([]);
  });

  it("sends every field the endpoint accepts, or names why not", () => {
    const accepted = Object.keys(
      requestSchema("add_copy", "#/components/schemas/CopyCreate", 5)
        .properties ?? {},
    );
    const sent = new Set(Object.keys(toCopyRequest(pending())));

    const unaccounted = accepted.filter(
      (name) => !sent.has(name) && !(name in NOT_SENT_WHEN_COPYING),
    );

    expect(unaccounted).toEqual([]);
  });

  /**
   * Fields of the pending book that a copy deliberately does not carry.
   *
   * **This table is where the privacy answer lives**, because it is the one a
   * test reads. `isPrivate` is collected by a control directly above the
   * add-copy button and `CopyCreate` has no such field, so the copy inherits
   * privacy from the book it copies and the tick is inert for that press.
   */
  const NOT_ON_THE_COPY: Record<string, string> = {
    draft:
      "the bibliographic record, which the copy takes from the book it copies.",
    coverFile:
      "a follow-up upload that needs a book id. A cover taken here would be a " +
      "photo of the same edition anyway.",
    tagIds:
      "a follow-up write that needs a book id, and the book being copied " +
      "already carries the tags.",
    isPrivate:
      "`CopyCreate` has no privacy field: a copy inherits it from the book it " +
      "copies. The tick above the button is inert for this press, which is why " +
      "`copies.fromScanHint` says so before it is pressed.",
  };

  it("puts every field of the pending book on the copy wire, or names why not", () => {
    // Keyed on the pending book rather than on `CopyCreate`, which is what
    // stops a new field with a live control being silently dropped here while
    // the schema guards above stay green: they only compare against the
    // endpoint, and a field the endpoint never had is invisible to them.
    const sent = new Set(Object.keys(toCopyRequest(pending())));

    const unaccounted = Object.keys(PENDING).filter(
      (field) => !sent.has(field) && !(field in NOT_ON_THE_COPY),
    );

    expect(unaccounted).toEqual([]);
  });

  it("sends every field the endpoint requires", () => {
    // `CopyCreate.required` is empty today, so this asserts on an empty list.
    // It is here anyway, for the reason its twin on the scan request is: a
    // required field added to the schema later would 422 on the add-copy
    // press, which is the second most expensive place in this flow to find
    // out, and nothing else in the tree would say so.
    const sent = new Set(Object.keys(toCopyRequest(pending())));
    const missing = (
      requestSchema("add_copy", "#/components/schemas/CopyCreate", 5)
        .required ?? []
    ).filter((name) => !sent.has(name));

    expect(missing).toEqual([]);
  });
});

/** What a file said about a book, with every field present. */
const RECORD: { [K in keyof FileMetadata]-?: FileMetadata[K] } = {
  title: "Dune",
  subtitle: "A Novel",
  authors: ["Frank Herbert", "Brian Herbert"],
  identifiers: [{ scheme: "ISBN", value: "9780441013593" }],
  isbn: "9780441013593",
  publisher: "Chilton",
  year: 1965,
  language: "en",
  description: "Desert planet politics.",
  seriesName: "Dune",
  seriesIndex: 1,
};

function record(patch: Partial<FileMetadata> = {}): FileMetadata {
  return { ...RECORD, ...patch };
}

describe("draftFromFile", () => {
  it("carries what the file said into the confirm step", () => {
    expect(draftFromFile(record())).toMatchObject({
      isbn: "9780441013593",
      title: "Dune",
      subtitle: "A Novel",
      publisher: "Chilton",
      year: 1965,
      language: "en",
      series_name: "Dune",
      series_index: 1,
    });
  });

  it("joins the authors with the separator the server splits on", () => {
    // `backend/authors.py` splits an author line on a comma and on nothing
    // else, so this is the one join that round trips.
    expect(draftFromFile(record()).author).toBe("Frank Herbert, Brian Herbert");
  });

  it("sends an empty ISBN rather than none, which the server reads as absent", () => {
    // Measured over 79 real EPUBs: 4 carried one. A file with no ISBN is the
    // ordinary case and has to be addable.
    expect(draftFromFile(record({ isbn: null })).isbn).toBe("");
  });

  it("offers editable fields, because no catalogue was asked", () => {
    // What is on screen is the file's own claim, and the member is the one who
    // can correct it.
    expect(draftFromFile(record()).notFound).toBe(true);
  });

  it("carries no cover, which is the one thing this path must not send", () => {
    expect(draftFromFile(record())).not.toHaveProperty("cover_url");
  });

  it("cuts a title the column could not hold rather than losing the book", () => {
    const long = "a".repeat(TEXT_CEILINGS.title + 100);
    expect(draftFromFile(record({ title: long })).title).toHaveLength(
      TEXT_CEILINGS.title,
    );
  });

  it("drops a language code the column could not hold rather than cutting it", () => {
    // A cut code names a different language. The book still lands.
    const draft = draftFromFile(
      record({ language: "x".repeat(TEXT_CEILINGS.language + 1) }),
    );
    expect(draft.language).toBeNull();
    expect(draft.title).toBe("Dune");
  });

  it("drops a series index outside what the API accepts", () => {
    expect(draftFromFile(record({ seriesIndex: 1e9 })).series_index).toBeNull();
  });

  it("produces a body the scan endpoint accepts", () => {
    // The half a field by field assertion cannot reach: this is what actually
    // goes on the wire.
    const draft = draftFromFile(record());
    const body = toScanRequest({ ...blankPending(""), draft });
    expect(body).toMatchObject({ title: "Dune", is_private: false });
    expect(body).not.toHaveProperty("notFound");
  });
});

/**
 * One `File` in this module, and it is the cover the page sends on purpose.
 *
 * `tests/houseRules.test.ts` holds this over every draft builder the tree
 * declares, wherever it is written, and gives the reason: taking a `File` there
 * would compile, would pass every other test in the tree, and would put a
 * member's book one spread away from a request body. That guard stays. This one
 * is the same property over the whole module, and the two are not one check
 * twice: that one reads a parameter list, this one reads every line, so a
 * builder holding a file through a closure or a field is refused here and
 * invisible there.
 *
 * **It is about a mention, not about custody.** A `File` does reach
 * `toScanRequest` and `toCopyRequest`, inside `PendingBook.coverFile`, and the
 * page sends a cover on purpose. `houseRules.test.ts` says so. What this refuses
 * is a second one appearing anywhere without somebody deciding it should, and a
 * new field or parameter naming one is meant to fail here and be argued for.
 *
 * **What counts as carrying a book is `CARRIES_A_BOOK`, in `tests/carriesABook.ts`
 * and explained there**, once, and imported by every rule that applies it.
 *
 * **Written as the one line rather than as a parser, because the parser was
 * evaded twice.** This block shipped for one commit matching
 * `export function \w+\(([^)]*)\)` and asserting the match count against a
 * second reading. Both arms went green on `(clues: NameClues, done: () => void,
 * cover: File)`, since `[^)]*` stops at the first bracket and truncates what it
 * captures without changing how many matches there are; and both went green on
 * `export const draftFromBytes = (file: File) => ...`, since the "second
 * reading" anchored on the same literal `export function` and so was the same
 * instrument twice. A count of one string over the source has no signature to
 * parse and no spelling to enumerate.
 */

describe("draftFromAudiobook", () => {
  /** One candidate book, as `groupAudiobooks` describes it. */
  function group(over: Partial<AudiobookGroup> = {}): AudiobookGroup {
    return {
      files: [],
      by: "album",
      album: "Robinson Crusoe",
      authors: ["Daniel Defoe"],
      title: null,
      ...over,
    };
  }

  it("takes the album as the book and the artists as its authors", () => {
    expect(draftFromAudiobook(group())).toMatchObject({
      title: "Robinson Crusoe",
      author: "Daniel Defoe",
      isbn: "",
      notFound: true,
    });
  });

  it("joins every author with the separator the server splits on", () => {
    // A collection is one audiobook by ten writers, and the line has to round
    // trip through `backend/authors.py`, which splits on a comma and nothing
    // else.
    const many = group({ authors: ["Saki", "Mark Twain", "Kate Chopin"] });

    expect(draftFromAudiobook(many)?.author).toBe(
      "Saki, Mark Twain, Kate Chopin",
    );
  });

  it("falls back to the one file's own title when no album was named", () => {
    expect(
      draftFromAudiobook(group({ album: null, title: "Mort" }))?.title,
    ).toBe("Mort");
  });

  it("answers null when the files named no book at all", () => {
    // The caller then derives the same draft from the folder's name. A blank
    // title here would be a 422 in the middle of somebody's batch.
    expect(draftFromAudiobook(group({ album: null, title: null }))).toBeNull();
  });

  it("answers null for a title that is only whitespace", () => {
    expect(draftFromAudiobook(group({ album: "   ", title: null }))).toBeNull();
  });

  it("cuts a title the column could not hold rather than losing the book", () => {
    const long = draftFromAudiobook(group({ album: "x".repeat(600) }));

    expect(long?.title).toHaveLength(500);
  });

  it("cuts an author line the column could not hold", () => {
    // Cut rather than dropped, the same as every other path into `BookCreate`:
    // `author` is in `CUT_TO_FIT`, and a cut author line still names the first
    // of them.
    const long = draftFromAudiobook(group({ authors: ["y".repeat(600)] }));

    expect(long?.author).toHaveLength(500);
  });

  it("names no year, because an audio tag's year is the recording's", () => {
    // Measured: Defoe's Robinson Crusoe carries `TYER 2006`. `lib/audiobook.ts`
    // does not read one, and this is the other end of that decision.
    expect(draftFromAudiobook(group())).not.toHaveProperty("year");
  });
});

describe("this module names a File exactly once", () => {
  const SOURCE = import.meta.glob(
    ["../../../src/pages/ScanPage/types.ts", "../../lib/fileName.test.ts"],
    { query: "?raw", import: "default", eager: true },
  ) as Record<string, string>;

  /** The source with comments removed, so a rule cannot be satisfied by prose. */
  function withoutProse(source: string): string {
    return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");
  }

  function code(): string {
    const source = SOURCE["../../../src/pages/ScanPage/types.ts"] ?? "";
    // A glob that matched nothing would make the assertion below pass on an
    // empty string, which names no File at all.
    expect(source.length).toBeGreaterThan(1000);
    return withoutProse(source);
  }

  it("is reading the module it claims to", () => {
    expect(code()).toContain("export function draftFromName");
  });

  it("spells the refusal the way the name side guard spells it", () => {
    // **One literal, and the one file that does not import it.** This rule and
    // the house rule over every draft builder both import `CARRIES_A_BOOK`, so
    // holding it is using it. `tests/lib/fileName.test.ts` writes it out, and
    // that pair shipped one commit apart naming different sets, `File` here and
    // `File|Blob` there, until both critic seats found the gap: a `File` is a
    // `Blob`, so the narrower admitted a parameter taking a member's book with
    // no cast. Two spellings of one rule is the defect `backend/targets.py`
    // records shipping once already, so this asserts that file carries this
    // exact source text rather than trusting that somebody kept them level.
    const sibling = SOURCE["../../lib/fileName.test.ts"] ?? "";
    expect(sibling.length).toBeGreaterThan(1000);
    // **Stripped, like every other reading here.** Against the raw source the
    // sibling satisfies this with a comment: narrow its pattern and leave the
    // full literal in a trailing comment on the same line, and the check passes
    // while the guard is weaker. That is exactly what `withoutProse` exists for.
    expect(withoutProse(sibling)).toContain(CARRIES_A_BOOK.source);
  });

  it("names a file type on the cover line and nowhere else", () => {
    // Word bounded, so `draftFromFile` and `FileNaming` are not mentions of the
    // type. Asserted as the line rather than as a count, because a count that
    // stays right while the line moves is a guard that has stopped watching.
    const named = code()
      .split("\n")
      .filter((line) => CARRIES_A_BOOK.test(line))
      .map((line) => line.trim());

    expect(named).toEqual(["coverFile: File | null;"]);
  });
});
