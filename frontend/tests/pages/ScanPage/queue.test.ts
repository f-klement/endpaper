/**
 * Tests for src/pages/ScanPage/queue.ts: what each event makes of a row, and
 * what the queue adds up to, with no React and no request.
 *
 * The hook that feeds these events is `hooks.test.tsx`'s, which pins the
 * requests and the wiring; a rule here is pinned by naming its event.
 */

import { describe, expect, it } from "vitest";

import type { BookLookup } from "../../../src/api/generated/model";
import type { CalibreBook } from "../../../src/lib/calibre";
import {
  canBeAskedAgain,
  figuresOf,
  groupKey,
  isReading,
  isReady,
  needsALookup,
  queueAfter,
  type EntryIn,
  type QueueEvent,
  type ScannedEntry,
} from "../../../src/pages/ScanPage/queue";
import { blankDraft } from "../../../src/pages/ScanPage/types";

const DUNE: BookLookup = {
  isbn: "9780441013593",
  title: "Dune",
  author: "Frank Herbert",
  suggested_tag_ids: [],
};

/** A library's book `id`, with a title and nothing else. */
function calibreBook(id: number): CalibreBook {
  return {
    id,
    path: `Herbert/Dune (${id})`,
    uuid: null,
    title: "Dune",
    authors: [],
    authorsSeparated: true,
    identifiers: [],
    isbn: null,
    publisher: null,
    year: null,
    language: null,
    description: null,
    seriesName: null,
    seriesIndex: null,
    files: [],
  };
}

/** The facts `row` fills in where a test does not name them. */
type Defaulted = "key" | "label" | "isbn" | "format" | "draft";

/**
 * One arm of `ScannedEntry` at a time with the defaulted facts optional, so a
 * row is checked against the arm its state names.
 */
type Given<E = ScannedEntry> = E extends ScannedEntry
  ? Omit<E, Defaulted> & Partial<Pick<E, Defaulted>>
  : never;

/** A row carrying nothing it was not given. */
function row(given: Given): ScannedEntry {
  return {
    key: "k",
    label: "k",
    isbn: "",
    format: "",
    draft: null,
    ...given,
  };
}

/** The one row a single event leaves of a one row queue. */
function rowAfter(start: ScannedEntry, event: QueueEvent): ScannedEntry {
  const [only] = queueAfter([start], event);
  return only!;
}

describe("a barcode", () => {
  it("is queued as a row being looked up", () => {
    expect(queueAfter([], { kind: "captured", isbn: DUNE.isbn })).toEqual([
      row({
        state: "looking-up",
        key: `isbn:${DUNE.isbn}`,
        label: DUNE.isbn,
        isbn: DUNE.isbn,
      }),
    ]);
  });

  it("arriving again leaves the same queue, so nothing is asked twice", () => {
    const queue = queueAfter([], { kind: "captured", isbn: DUNE.isbn });
    expect(queueAfter(queue, { kind: "captured", isbn: DUNE.isbn })).toBe(
      queue,
    );
  });

  it("is found with the record a catalogue had", () => {
    const answered = rowAfter(row({ state: "looking-up", isbn: DUNE.isbn }), {
      kind: "isbn-answered",
      key: "k",
      lookup: DUNE,
    });
    expect([answered.state, answered.draft?.title]).toEqual(["found", "Dune"]);
  });

  it("nobody knows keeps a titleless draft the batch does not take", () => {
    const missed = rowAfter(row({ state: "looking-up", isbn: DUNE.isbn }), {
      kind: "not-answered",
      key: "k",
      asked: "looking-up",
      unknown: true,
    });
    expect([missed.state, missed.draft]).toEqual([
      "not-found",
      blankDraft(DUNE.isbn),
    ]);
    expect(isReady(missed)).toBe(false);
  });

  it("whose catalogues were not reached is offered to the lookup", () => {
    const missed = rowAfter(row({ state: "looking-up", isbn: DUNE.isbn }), {
      kind: "not-answered",
      key: "k",
      asked: "looking-up",
      unknown: false,
    });
    expect([missed.state, needsALookup(missed)]).toEqual(["not-reached", true]);
  });

  it("asked again during an outage stays not reached, not a kept name", () => {
    const asked = rowAfter(row({ state: "not-reached", isbn: DUNE.isbn }), {
      kind: "asked",
      key: "k",
    });
    const again = rowAfter(asked, {
      kind: "not-answered",
      key: "k",
      asked: "not-reached",
      unknown: false,
    });
    expect([again.state, again.reason]).toEqual(["not-reached", undefined]);
  });
});

describe("an ISBN a file or a name carried", () => {
  it("from a name takes the record whole", () => {
    const named = row({
      state: "searching",
      isbn: DUNE.isbn,
      isbnFromTheName: true,
      draft: { ...DUNE, title: "dune", year: 1999 },
    });
    expect(
      rowAfter(named, { kind: "isbn-answered", key: "k", lookup: DUNE }).draft,
    ).toEqual(DUNE);
  });

  it("from a file keeps the file's fields where the record has none", () => {
    const stated = row({
      state: "searching",
      isbn: DUNE.isbn,
      draft: { ...DUNE, publisher: "Ace" },
    });
    const found = rowAfter(stated, {
      kind: "isbn-answered",
      key: "k",
      lookup: DUNE,
    });
    expect([found.state, found.draft?.publisher]).toEqual(["found", "Ace"]);
  });

  it("from a file is held, not taken, when the titles cannot be one book", () => {
    const stated = row({
      state: "searching",
      isbn: DUNE.isbn,
      draft: { ...DUNE, title: "Hyperion" },
    });
    const held = rowAfter(stated, {
      kind: "isbn-answered",
      key: "k",
      lookup: DUNE,
    });
    expect([
      held.state,
      held.answered,
      held.reason,
      held.differentRecord,
    ]).toEqual(["stated", "records", { kind: "record-differs" }, DUNE]);
  });

  it("from a file goes back to the file's draft when no catalogue was reached", () => {
    const stated = row({ state: "searching", isbn: DUNE.isbn, draft: DUNE });
    const back = rowAfter(stated, {
      kind: "not-answered",
      key: "k",
      asked: "stated",
      unknown: false,
    });
    expect([back.state, back.answered, back.reason]).toEqual([
      "stated",
      undefined,
      { kind: "lookup-failed-as-stated" },
    ]);
  });

  it("the member takes once held is filed over the draft as it stands", () => {
    const held = row({
      state: "stated",
      draft: { ...DUNE, title: "Hyperion", categories: ["Kept"] },
      differentRecord: DUNE,
      reason: { kind: "record-differs" },
    });
    const taken = rowAfter(held, { kind: "record-taken", key: "k" });
    expect([taken.state, taken.draft?.title, taken.draft?.categories]).toEqual([
      "found",
      "Dune",
      ["Kept"],
    ]);
  });

  it("the member refuses once held leaves the file's draft and says so", () => {
    const held = row({
      state: "stated",
      draft: DUNE,
      reason: { kind: "record-differs" },
      differentRecord: DUNE,
    });
    const kept = rowAfter(held, { kind: "kept-the-file", key: "k" });
    expect([kept.state, kept.differentRecord, kept.reason]).toEqual([
      "stated",
      undefined,
      { kind: "kept-the-file" },
    ]);
  });
});

describe("a name", () => {
  const derived = row({ state: "derived", query: "dune herbert", draft: DUNE });

  it("being asked about drops the answer and the note it carried", () => {
    const kept = row({
      state: "derived",
      query: "dune herbert",
      draft: DUNE,
      answered: "records-for-now",
      reason: { kind: "kept-for-now" },
    });
    const asked = rowAfter(kept, { kind: "asked", key: "k" });
    expect([asked.state, asked.answered, asked.reason]).toEqual([
      "searching",
      undefined,
      undefined,
    ]);
  });

  it("no catalogue has a record of stays under the name, answered", () => {
    const empty = rowAfter(derived, {
      kind: "search-answered",
      key: "k",
      matches: [],
    });
    expect([
      empty.state,
      empty.answered,
      needsALookup(empty),
      canBeAskedAgain(empty),
    ]).toEqual(["derived", "nothing", false, false]);
  });

  it("with records offered is decided before the batch takes it", () => {
    const choosing = rowAfter(derived, {
      kind: "search-answered",
      key: "k",
      matches: [{ title: "Dune" }],
    });
    expect([
      choosing.state,
      isReady(choosing),
      figuresOf([choosing]).deciding,
    ]).toEqual(["choosing", false, 1]);
  });

  it("takes a chosen record and forgets the name gave its ISBN", () => {
    const choosing = row({
      state: "choosing",
      draft: DUNE,
      isbnFromTheName: true,
      matches: [],
    });
    const chosen = rowAfter(choosing, {
      kind: "chosen",
      key: "k",
      match: { title: "Dune", isbn13: DUNE.isbn },
    });
    expect([
      chosen.state,
      chosen.isbn,
      chosen.matches,
      chosen.isbnFromTheName,
    ]).toEqual(["found", DUNE.isbn, undefined, undefined]);
  });

  it("kept one row at a time is not offered again", () => {
    const kept = rowAfter(
      row({ state: "choosing", query: "q", draft: DUNE, matches: [] }),
      {
        kind: "kept-the-name",
        key: "k",
      },
    );
    expect([needsALookup(kept), canBeAskedAgain(kept)]).toEqual([false, false]);
  });

  it("kept in bulk is offered again, and only by its own press", () => {
    const [kept] = queueAfter(
      [row({ state: "choosing", query: "q", draft: DUNE, matches: [] })],
      {
        kind: "kept-every-name-for-now",
      },
    );
    expect([
      kept!.answered,
      needsALookup(kept!),
      canBeAskedAgain(kept!),
    ]).toEqual(["records-for-now", false, true]);
  });

  it("whose file the library already holds asks no catalogue", () => {
    expect(needsALookup({ ...derived, heldBy: null })).toBe(true);
    const held = queueAfter([derived], {
      kind: "holders-answered",
      held: new Map([["k", { bookId: 7, lands: true }]]),
    });
    expect(needsALookup(held[0]!)).toBe(false);
  });
});

describe("a picked file", () => {
  const reading = row({ state: "reading", key: "file:dune.epub" });
  const naming = { name: "Dune.epub", folders: [] };

  it("stands as reading until it has been read", () => {
    const queue = queueAfter([], {
      kind: "picked",
      rows: [{ key: "file:dune.epub", label: "dune", format: "" }],
    });
    expect([queue[0]!.state, isReading(queue)]).toEqual(["reading", true]);
  });

  it("the queue already claims is not queued again beside a new one", () => {
    const audio = row({
      state: "reading",
      key: "audio:file:a.mp3:1",
      claims: ["file:a.mp3"],
    });
    const queue = queueAfter([audio], {
      kind: "picked",
      rows: [
        { key: "file:a.mp3", label: "a", format: "" },
        { key: "file:b.epub", label: "b", format: "" },
      ],
    });
    expect(queue.map((one) => one.key)).toEqual([
      "audio:file:a.mp3:1",
      "file:b.epub",
    ]);
  });

  it("an audio row whose claims overlap a queued file does not claim it again", () => {
    const queued = row({ state: "reading", key: "file:a.mp3" });
    const queue = queueAfter([queued], {
      kind: "picked",
      rows: [
        {
          key: "audio:file:a.mp3:2",
          label: "book",
          format: "",
          claims: ["file:a.mp3", "file:b.mp3"],
        },
      ],
    });
    expect(queue.map((one) => one.key)).toEqual(["file:a.mp3"]);
  });

  it("carries onto its reading row only the fields a reading row is made from", () => {
    // Held in a variable, so no excess check refuses the extra fields: the
    // shape a row built in a `map` callback or spread from another arrives in.
    const carrying = {
      key: "file:dune.epub",
      label: "dune",
      format: "" as const,
      copyOf: 42,
      heldBy: { bookId: 42, lands: true },
    };
    const [queued] = queueAfter([], { kind: "picked", rows: [carrying] });
    expect([queued!.copyOf, queued!.heldBy]).toEqual([undefined, undefined]);
  });

  it("picked again while queued leaves the same queue, so nothing is read twice", () => {
    const queue = [row({ state: "reading", key: "calibre:L" })];
    expect(
      queueAfter(queue, {
        kind: "picked",
        rows: [{ key: "calibre:L", label: "L", format: "" }],
      }),
    ).toBe(queue);
  });

  it("that states its ISBN is offered the lookup rather than sent to it", () => {
    const read = rowAfter(reading, {
      kind: "file-read",
      key: reading.key,
      naming,
      reference: undefined,
      said: DUNE,
      note: undefined,
    });
    expect([read.state, needsALookup(read)]).toEqual(["stated", true]);
  });

  it("that opened and named no title falls to its name, saying so", () => {
    const read = rowAfter(reading, {
      kind: "file-read",
      key: reading.key,
      naming,
      reference: undefined,
      said: { ...DUNE, title: "" },
      note: undefined,
    });
    expect([read.state, read.draft?.title, read.reason]).toEqual([
      "derived",
      "Dune",
      { kind: "no-title" },
    ]);
  });

  it("whose name says nothing either fails with what the file said", () => {
    const read = rowAfter(reading, {
      kind: "file-read",
      key: reading.key,
      naming: { name: ".pdf", folders: [] },
      reference: undefined,
      said: undefined,
      note: { kind: "unreadable" },
    });
    expect([read.state, read.reason]).toEqual([
      "failed",
      { kind: "unreadable" },
    ]);
  });

  it("loses one subject by its value, before anything is written", () => {
    const tagged = row({
      state: "found",
      draft: { ...DUNE, categories: ["Fiction", "Spam"] },
    });
    expect(
      rowAfter(tagged, { kind: "subject-dropped", key: "k", subject: "Spam" })
        .draft?.categories,
    ).toEqual(["Fiction"]);
  });

  it("from a library gives way to its books, queueing none twice", () => {
    const book = row({ state: "found", key: "calibre:L:1", draft: DUNE });
    const queue = queueAfter(
      [book, row({ state: "reading", key: "calibre:L" })],
      {
        kind: "library-read",
        pendingKey: "calibre:L",
        books: [
          { book: calibreBook(1), files: [] },
          { book: calibreBook(2), files: [] },
        ],
      },
    );
    expect(queue.map((one) => one.key)).toEqual(["calibre:L:1", "calibre:L:2"]);
  });
});

describe("a row's state", () => {
  it("cannot carry the records of the state it left", () => {
    const choosing: EntryIn<"choosing"> = {
      key: "k",
      label: "k",
      isbn: "",
      format: "",
      state: "choosing",
      draft: DUNE,
      matches: [],
    };
    // @ts-expect-error: `matches` belongs to `choosing`, so a spread carrying
    // it into another state is refused.
    const found: ScannedEntry = { ...choosing, state: "found" };
    expect(found.state).toBe("found");
  });

  it("holds a record only under the reason that names it", () => {
    // @ts-expect-error: a held record beside any other reason is refused.
    const kept: EntryIn<"stated"> = {
      key: "k",
      label: "k",
      isbn: "",
      format: "",
      state: "stated",
      draft: DUNE,
      reason: { kind: "kept-the-file" },
      differentRecord: DUNE,
    };
    expect(kept.state).toBe("stated");
  });

  it("names a differing record only while it holds one", () => {
    // @ts-expect-error: the reason naming a held record, with none held, is refused.
    const naming: EntryIn<"stated"> = {
      key: "k",
      label: "k",
      isbn: "",
      format: "",
      state: "stated",
      draft: DUNE,
      reason: { kind: "record-differs" },
    };
    expect(naming.state).toBe("stated");
  });

  it("holds a differing record under the reason that names it", () => {
    // The two refusals above share this literal less one field or one reason.
    // Without it a new required field on the arm would satisfy both
    // directives and refuse nothing they were written for.
    const holding: EntryIn<"stated"> = {
      key: "k",
      label: "k",
      isbn: "",
      format: "",
      state: "stated",
      draft: DUNE,
      reason: { kind: "record-differs" },
      differentRecord: DUNE,
    };
    expect(holding.state).toBe("stated");
  });
});

describe("an audiobook", () => {
  it("is keyed by its smallest file key and its count, in any order", () => {
    expect(groupKey(["file:b.mp3", "file:a.mp3"])).toBe("audio:file:a.mp3:2");
  });
});

describe("the batch", () => {
  const found = (key: string) => row({ state: "found", key, draft: DUNE });

  it("leaves the rows it landed and keeps every other, failures with their reason", () => {
    const queue = queueAfter([found("a"), found("b"), found("c")], {
      kind: "batch-ran",
      walked: ["a", "b"],
      failures: [{ row: found("b"), reason: { kind: "unreachable" } }],
    });
    expect(queue.map((one) => [one.key, one.state, one.reason])).toEqual([
      ["b", "failed", { kind: "unreachable" }],
      ["c", "found", undefined],
    ]);
  });

  it("stops offering a record held for a row it fails", () => {
    const held = row({
      state: "stated",
      key: "a",
      draft: { ...DUNE, title: "Hyperion" },
      answered: "records",
      reason: { kind: "record-differs" },
      differentRecord: DUNE,
    });
    const [failed] = queueAfter([held], {
      kind: "batch-ran",
      walked: ["a"],
      failures: [{ row: held, reason: { kind: "unreachable" } }],
    });
    expect([failed!.state, failed!.differentRecord, failed!.answered]).toEqual([
      "failed",
      undefined,
      "records",
    ]);
  });

  it("offers a copy only on a row held in another format", () => {
    const [held] = queueAfter([found("a")], {
      kind: "batch-ran",
      walked: ["a"],
      failures: [{ row: found("a"), heldInAnotherFormat: 9 }],
    });
    expect([held!.reason, held!.copyOf]).toEqual([
      { kind: "held-in-another-format" },
      9,
    ]);
    const [refused] = queueAfter([held!], {
      kind: "batch-ran",
      walked: ["a"],
      failures: [{ row: held!, reason: { kind: "unreachable" } }],
    });
    expect(refused!.copyOf).toBeUndefined();
  });
});

describe("the queue's figures", () => {
  it("count a queue with one addable row as ready to add one", () => {
    // The count Add all is held on: zero here is a button nobody can press.
    const notFound = row({
      state: "not-found",
      key: "isbn:2",
      draft: blankDraft("2"),
    });
    expect(
      figuresOf([row({ state: "found", key: "isbn:1", draft: DUNE }), notFound])
        .ready,
    ).toBe(1);
  });

  it("quote a run's pace in minutes, at least one", () => {
    const waiting = (count: number) =>
      Array.from({ length: count }, (_, index) =>
        row({ state: "derived", key: `${index}`, query: "q", draft: DUNE }),
      );
    expect(figuresOf([]).paceMinutes).toBe(1);
    expect(figuresOf(waiting(31)).paceMinutes).toBe(2);
  });
});
