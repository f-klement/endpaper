/**
 * Tests for src/pages/ScanPage/queue.ts: what each event makes of a row, and
 * what the queue adds up to, with no React and no request.
 *
 * The hook that feeds these events is `hooks.test.tsx`'s, which pins the
 * requests and the wiring; a rule here is pinned by naming its event.
 */

import { describe, expect, it } from "vitest";

import type { BookLookup } from "../../../src/api/generated/model";
import {
  canBeAskedAgain,
  figuresOf,
  groupKey,
  isReading,
  isReady,
  needsALookup,
  queueAfter,
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

/** A row in `state`, carrying nothing it was not given. */
function row(
  state: ScannedEntry["state"],
  more: Partial<ScannedEntry> = {},
): ScannedEntry {
  return {
    key: "k",
    label: "k",
    isbn: "",
    format: "",
    state,
    draft: null,
    ...more,
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
      row("looking-up", {
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
    const answered = rowAfter(row("looking-up", { isbn: DUNE.isbn }), {
      kind: "isbn-answered",
      key: "k",
      lookup: DUNE,
    });
    expect([answered.state, answered.draft?.title]).toEqual(["found", "Dune"]);
  });

  it("nobody knows keeps a titleless draft the batch does not take", () => {
    const missed = rowAfter(row("looking-up", { isbn: DUNE.isbn }), {
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
    const missed = rowAfter(row("looking-up", { isbn: DUNE.isbn }), {
      kind: "not-answered",
      key: "k",
      asked: "looking-up",
      unknown: false,
    });
    expect([missed.state, needsALookup(missed)]).toEqual(["not-reached", true]);
  });

  it("asked again during an outage stays not reached, not a kept name", () => {
    const asked = rowAfter(row("not-reached", { isbn: DUNE.isbn }), {
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
    const named = row("searching", {
      isbn: DUNE.isbn,
      isbnFromTheName: true,
      draft: { ...DUNE, title: "dune", year: 1999 },
    });
    expect(
      rowAfter(named, { kind: "isbn-answered", key: "k", lookup: DUNE }).draft,
    ).toEqual(DUNE);
  });

  it("from a file keeps the file's fields where the record has none", () => {
    const stated = row("searching", {
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
    const stated = row("searching", {
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
    const stated = row("searching", { isbn: DUNE.isbn, draft: DUNE });
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
    const held = row("stated", {
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
    const held = row("stated", { draft: DUNE, differentRecord: DUNE });
    const kept = rowAfter(held, { kind: "kept-the-file", key: "k" });
    expect([kept.state, kept.differentRecord, kept.reason]).toEqual([
      "stated",
      undefined,
      { kind: "kept-the-file" },
    ]);
  });
});

describe("a name", () => {
  const derived = row("derived", { query: "dune herbert", draft: DUNE });

  it("being asked about drops the answer and the note it carried", () => {
    const kept = {
      ...derived,
      answered: "records-for-now" as const,
      reason: { kind: "kept-for-now" as const },
    };
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
    const choosing = row("choosing", {
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
    const kept = rowAfter(row("choosing", { query: "q", draft: DUNE }), {
      kind: "kept-the-name",
      key: "k",
    });
    expect([needsALookup(kept), canBeAskedAgain(kept)]).toEqual([false, false]);
  });

  it("kept in bulk is offered again, and only by its own press", () => {
    const [kept] = queueAfter([row("choosing", { query: "q", draft: DUNE })], {
      kind: "kept-every-name-for-now",
    });
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
  const reading = row("reading", { key: "file:dune.epub" });
  const naming = { name: "Dune.epub", folders: [] };

  it("stands as reading until it has been read", () => {
    const queue = queueAfter([], {
      kind: "picked",
      rows: [{ key: "file:dune.epub", label: "dune", format: "" }],
    });
    expect([queue[0]!.state, isReading(queue)]).toEqual(["reading", true]);
  });

  it("the queue already claims is not queued again beside a new one", () => {
    const audio = row("reading", {
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
    const queued = row("reading", { key: "file:a.mp3" });
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

  it("picked again while queued leaves the same queue, so nothing is read twice", () => {
    const queue = [row("reading", { key: "calibre:L" })];
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
    const tagged = row("found", {
      draft: { ...DUNE, categories: ["Fiction", "Spam"] },
    });
    expect(
      rowAfter(tagged, { kind: "subject-dropped", key: "k", subject: "Spam" })
        .draft?.categories,
    ).toEqual(["Fiction"]);
  });

  it("from a library gives way to its books, queueing none twice", () => {
    const book = row("found", { key: "calibre:L:1", draft: DUNE });
    const queue = queueAfter([book, row("reading", { key: "calibre:L" })], {
      kind: "library-read",
      pendingKey: "calibre:L",
      rows: [book, { ...book, key: "calibre:L:2" }],
    });
    expect(queue.map((one) => one.key)).toEqual(["calibre:L:1", "calibre:L:2"]);
  });
});

describe("an audiobook", () => {
  it("is keyed by its smallest file key and its count, in any order", () => {
    expect(groupKey(["file:b.mp3", "file:a.mp3"])).toBe("audio:file:a.mp3:2");
  });
});

describe("the batch", () => {
  const found = (key: string) => row("found", { key, draft: DUNE });

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
    const notFound = row("not-found", {
      key: "isbn:2",
      draft: blankDraft("2"),
    });
    expect(
      figuresOf([row("found", { key: "isbn:1", draft: DUNE }), notFound]).ready,
    ).toBe(1);
  });

  it("quote a run's pace in minutes, at least one", () => {
    const waiting = (count: number) =>
      Array.from({ length: count }, (_, index) =>
        row("derived", { key: `${index}`, query: "q", draft: DUNE }),
      );
    expect(figuresOf([]).paceMinutes).toBe(1);
    expect(figuresOf(waiting(31)).paceMinutes).toBe(2);
  });
});
