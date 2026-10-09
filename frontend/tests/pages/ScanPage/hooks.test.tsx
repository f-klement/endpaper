/**
 * Tests for src/pages/ScanPage/hooks.ts: the Google Books search path.
 *
 * The scan-and-lookup path is covered through the page in `ScanPage.test.tsx`.
 * These are the parts that are easier to pin at the hook: when a request is
 * made at all, and what a chosen result does to the draft.
 */

import { act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BookMatch } from "../../../src/api/generated/model";
import {
  FALLBACK_INTERVAL_MS,
  FALLBACK_STARTS_PER_MINUTE,
  useBookSearch,
  useRapidIntake,
  useScanFlow,
} from "../../../src/pages/ScanPage/hooks";
import { makeBook, resetIds } from "../../factories";
import { epubFile, packageDocument } from "../../zipFixtures";
import { id3v2, mp3, plainFrame } from "../../audioFixtures";
import { mockApi, renderHookWithProviders, type MockApi } from "../../utils";

/**
 * One chapter of an audiobook, tagged the way the measured LibriVox files are.
 *
 * `TALB` is the book, `TPE1` the author and `TIT2` this chapter, and the file
 * sits in a folder named after the book, which is how one is on disk.
 */
function chapterFile(index: number, album: string) {
  const file = new File(
    [
      mp3({
        head: id3v2({
          frames: [
            plainFrame("TALB", album),
            plainFrame("TPE1", "Daniel Defoe"),
            plainFrame("TIT2", `Chapter ${index}`),
          ],
        }),
      }),
    ],
    `chapter ${index}.mp3`,
  );
  Object.defineProperty(file, "webkitRelativePath", {
    value: `${album}/chapter ${index}.mp3`,
  });
  return file;
}

let api: MockApi;

function match(overrides: Partial<BookMatch> = {}): BookMatch {
  return {
    google_books_id: "abc",
    title: "Dune",
    subtitle: "A Novel",
    author: "Frank Herbert",
    publisher: "Chilton",
    year: 1965,
    description: "Desert planet politics.",
    isbn13: "9780441013593",
    cover_url: "https://books.google.com/thumb.jpg",
    suggested_tag_ids: [7],
    ...overrides,
  };
}

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/api/books/tags", { body: [] });
  api.on("/api/settings/features", {
    body: {
      google_books_enabled: true,
      google_books_ready: true,
      goodreads_lookup_enabled: false,
      default_locale: "en",
    },
  });
  api.on("/api/books/search", {
    body: { matches: [match()], asked: ["open_library"], unasked: [] },
  });
  api.on("/api/books/locations", {
    body: [{ name: "Living room shelf 3", book_count: 40 }],
  });
  localStorage.clear();
});

describe("useBookSearch", () => {
  it("searches with no Google Books key configured", async () => {
    // The regression this endpoint exists for. Search used to be hidden
    // entirely without a key, which left no way to add a book that has no
    // barcode or predates ISBNs.
    api.on("/api/settings/features", {
      body: {
        google_books_enabled: false,
        google_books_ready: false,
        goodreads_lookup_enabled: false,
        default_locale: "en",
      },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());

    await waitFor(() => expect(result.current.matches).toHaveLength(1));
  });

  it("reports whether a key is configured, for the panel's note", async () => {
    const { result } = renderHookWithProviders(() => useBookSearch());
    await waitFor(() => expect(result.current.isConfigured).toBe(true));
  });

  it("makes no request while the query is only being typed", async () => {
    // Deliberately not debounced: every search is a billed call, and typing
    // "the hobbit" would spend ten of them to answer one question.
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));

    await waitFor(() => expect(result.current.isConfigured).toBe(true));
    expect(api.lastCall("/api/books/search")).toBeUndefined();
  });

  it("searches once submitted", async () => {
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));

    act(() => result.current.submit());

    await waitFor(() => expect(result.current.matches).toHaveLength(1));
    expect(api.lastCall("/api/books/search")).toBeDefined();
  });

  it("asks for the reader's own language, to order the editions", async () => {
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("zauberberg"));
    act(() => result.current.submit());

    await waitFor(() =>
      expect(api.lastCall("/api/books/search")).toBeDefined(),
    );
    const query = new URL(
      api.lastCall("/api/books/search")!.url,
      "http://localhost",
    ).searchParams;
    // The render helpers force English, so that is what should be sent.
    expect(query.get("lang")).toBe("en");
  });

  it("sends the trimmed query and a bounded limit", async () => {
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("  dune  "));
    act(() => result.current.submit());

    await waitFor(() =>
      expect(api.lastCall("/api/books/search")).toBeDefined(),
    );

    const query = new URL(
      api.lastCall("/api/books/search")!.url,
      "http://localhost",
    ).searchParams;
    expect(query.get("q")).toBe("dune");
    expect(query.get("limit")).toBe("10");
  });

  it("does not search for a query too short to be useful", async () => {
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("d"));
    act(() => result.current.submit());

    await waitFor(() => expect(result.current.isConfigured).toBe(true));
    expect(api.lastCall("/api/books/search")).toBeUndefined();
  });

  it("reports an empty result as empty rather than as a failure", async () => {
    api.on("/api/books/search", {
      body: { matches: [], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("zzzz"));
    act(() => result.current.submit());

    await waitFor(() => expect(result.current.isEmpty).toBe(true));
    expect(result.current.error).toBeNull();
  });

  it("surfaces an upstream failure", async () => {
    api.on("/api/books/search", {
      status: 502,
      body: { detail: "Google Books rejected the API key." },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());

    await waitFor(() => expect(result.current.error).toBeTruthy());
  });

  it("clears the box and the results", async () => {
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.matches).toHaveLength(1));

    act(() => result.current.clear());

    await waitFor(() => expect(result.current.matches).toEqual([]));
    expect(result.current.query).toBe("");
  });

  it("reports what the answer says was left unasked", async () => {
    api.on("/api/books/search", {
      body: { matches: [match()], asked: ["open_library"], unasked: ["oenb"] },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());

    await waitFor(() => expect(result.current.unasked).toEqual(["oenb"]));
    // **The other half of `askedNothing`, on the fixture that already has it.**
    // It is `asked` empty **and** something left to ask, and only the second
    // half was pinned: dropping the first survived the whole gate, and under
    // that mutant this very fixture, one catalogue asked and one left, reports
    // that nothing was searched above a full page of results. Same lie as the
    // one the field exists to prevent, from the other direction.
    expect(result.current.askedNothing).toBe(false);
  });

  it("asks again for the slow catalogues when told to", async () => {
    api.on("/api/books/search", {
      body: { matches: [match()], asked: ["open_library"], unasked: ["oenb"] },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.unasked).toEqual(["oenb"]));

    api.on("/api/books/search", {
      body: {
        matches: [match()],
        asked: ["open_library", "oenb"],
        unasked: [],
      },
    });
    act(() => result.current.searchHarder());

    await waitFor(() =>
      expect(
        new URL(
          api.lastCall("/api/books/search")!.url,
          "http://localhost",
        ).searchParams.get("harder"),
      ).toBe("true"),
    );
    await waitFor(() => expect(result.current.hasSearchedHarder).toBe(true));
    expect(result.current.unasked).toEqual([]);
  });

  it("does not ask harder for a query that has not been asked at all", async () => {
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.matches).toHaveLength(1));

    act(() => result.current.searchHarder());
    act(() => result.current.setQuery("zauberberg"));
    act(() => result.current.submit());

    await waitFor(() =>
      expect(
        new URL(
          api.lastCall("/api/books/search")!.url,
          "http://localhost",
        ).searchParams.get("q"),
      ).toBe("zauberberg"),
    );
    const query = new URL(
      api.lastCall("/api/books/search")!.url,
      "http://localhost",
    ).searchParams;
    // A new question has not been asked harder yet, whatever the last one was.
    expect(query.get("harder")).toBe("false");
    expect(result.current.hasSearchedHarder).toBe(false);
  });

  it("keeps the rows on screen while the longer search runs", async () => {
    // Otherwise the list blanks for the whole of the longer deadline and takes
    // with it the candidate the reader was about to click.
    api.on("/api/books/search", {
      body: { matches: [match()], asked: ["open_library"], unasked: ["oenb"] },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.matches).toHaveLength(1));

    act(() => result.current.searchHarder());

    expect(result.current.isSearchingHarder).toBe(true);
    expect(result.current.matches).toHaveLength(1);
  });

  const searchCalls = () =>
    api.calls.filter((call) => call.url.includes("/api/books/search")).length;

  it("retries a harder search that was refused its slot", async () => {
    // The server allows one long fan out at a time and answers the rest as
    // ordinary searches, so a refused answer comes back cached under
    // `harder: true` with `unasked` still populated and the offer still on
    // screen. Pressing it again sets a state that is already set, which React
    // bails out of, and `staleTime` then suppresses the request: without a
    // refetch the button is dead for five minutes, and the server's whole
    // fallback rests on the client being able to try again.
    api.on("/api/books/search", {
      body: { matches: [match()], asked: ["open_library"], unasked: ["oenb"] },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.unasked).toEqual(["oenb"]));

    act(() => result.current.searchHarder());
    await waitFor(() => expect(result.current.hasSearchedHarder).toBe(true));
    // Refused: an ordinary answer under a harder key, so the offer stands.
    expect(result.current.unasked).toEqual(["oenb"]);
    const refused = searchCalls();

    api.on("/api/books/search", {
      body: {
        matches: [match()],
        asked: ["open_library", "oenb"],
        unasked: [],
      },
    });
    act(() => result.current.searchHarder());

    await waitFor(() => expect(result.current.unasked).toEqual([]));
    expect(searchCalls()).toBeGreaterThan(refused);
  });

  it("does not blame the catalogues for a query with nothing in it", async () => {
    // A query reducing to no usable terms asks nothing too, and "and" survives
    // the minimum length. Reading `asked` alone would tell that reader every
    // catalogue their library runs is a slow one.
    api.on("/api/books/search", {
      body: { matches: [], asked: [], unasked: [] },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("and"));
    act(() => result.current.submit());

    await waitFor(() => expect(result.current.isEmpty).toBe(true));
    expect(result.current.askedNothing).toBe(false);
  });

  it("separates asking nothing from finding nothing", async () => {
    // Every catalogue this library has switched on is a slow one, so the
    // ordinary "no matches" line would report a fact nothing checked.
    api.on("/api/books/search", {
      body: { matches: [], asked: [], unasked: ["oenb", "nlg"] },
    });
    const { result } = renderHookWithProviders(() => useBookSearch());
    act(() => result.current.setQuery("dune"));
    act(() => result.current.submit());

    await waitFor(() => expect(result.current.askedNothing).toBe(true));
    expect(result.current.isEmpty).toBe(false);
  });
});

describe("useScanFlow.chooseMatch", () => {
  function renderFlow() {
    return renderHookWithProviders(() => useScanFlow(() => {}));
  }

  it("prefills the draft from the chosen record", () => {
    const { result } = renderFlow();

    act(() => result.current.chooseMatch(match()));

    expect(result.current.pending.draft).toMatchObject({
      title: "Dune",
      subtitle: "A Novel",
      author: "Frank Herbert",
      publisher: "Chilton",
      year: 1965,
      description: "Desert planet politics.",
      isbn: "9780441013593",
    });
  });

  it("preselects the suggested tags", () => {
    const { result } = renderFlow();
    act(() => result.current.chooseMatch(match()));
    expect(result.current.pending.tagIds).toEqual([7]);
  });

  it("shows the summary rather than the manual-entry fields", () => {
    // The fields came from a real record, so this is a confirmation, not a
    // blank form to fill in.
    const { result } = renderFlow();
    act(() => result.current.chooseMatch(match()));
    expect(result.current.pending.draft?.notFound).toBeUndefined();
  });

  it("accepts a record with no ISBN", () => {
    // A book found by title genuinely may not have one, and the server reads
    // a blank ISBN as absent rather than as invalid.
    const { result } = renderFlow();
    act(() => result.current.chooseMatch(match({ isbn13: null })));
    expect(result.current.pending.draft?.isbn).toBe("");
  });

  it("does not start an ISBN lookup that would overwrite the draft", async () => {
    // Setting the ISBN would re-run the Open Library lookup and replace the
    // record the reader just picked.
    const { result } = renderFlow();

    act(() => result.current.chooseMatch(match()));

    await waitFor(() => expect(result.current.pending.draft).not.toBeNull());
    expect(api.lastCall("/api/books/lookup")).toBeUndefined();
    expect(result.current.isLookingUp).toBe(false);
  });

  it("carries the catalogue headings into the draft", () => {
    // The number is the half of a heading that survives a language, and the
    // confirm step is what posts it back. Dropping it here would store a
    // heading for a scanned book and none for one found by title.
    const { result } = renderFlow();

    act(() =>
      result.current.chooseMatch(
        match({
          classifications: [
            { scheme: "ddc", number: "004", label: "Informatik" },
          ],
        }),
      ),
    );

    expect(result.current.pending.draft?.classifications).toEqual([
      { scheme: "ddc", number: "004", label: "Informatik" },
    ]);
  });

  it("is undone by reset", () => {
    const { result } = renderFlow();
    act(() => result.current.chooseMatch(match()));

    act(() => result.current.reset());

    expect(result.current.pending.draft).toBeNull();
    expect(result.current.pending.tagIds).toEqual([]);
  });
});

describe("useRapidIntake", () => {
  function renderRapid() {
    return renderHookWithProviders(() => useRapidIntake());
  }

  const LOOKUP = {
    isbn: "9780441013593",
    title: "Dune",
    author: "Frank Herbert",
    suggested_tag_ids: [],
  };

  it("starts inactive", () => {
    const { result } = renderRapid();
    expect(result.current.isActive).toBe(false);
    expect(result.current.entries).toEqual([]);
  });

  it("queues a scanned book and looks it up", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    const { result } = renderRapid();

    act(() => result.current.capture("9780441013593"));

    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));
    expect(result.current.entries[0]?.draft?.title).toBe("Dune");
  });

  it("ignores the same barcode arriving again", async () => {
    // The camera fires continuously while a barcode is in frame, so without
    // this the queue fills up with one book.
    api.on("/api/books/lookup", { body: LOOKUP });
    const { result } = renderRapid();

    act(() => result.current.capture("9780441013593"));
    act(() => result.current.capture("9780441013593"));

    await waitFor(() => expect(result.current.entries).toHaveLength(1));
  });

  it("keeps a book neither source knew, rather than dropping it", async () => {
    // It is still a book on the shelf. Silently discarding it is how a
    // catalogue ends up quietly incomplete.
    api.on("/api/books/lookup", {
      status: 404,
      body: { detail: "Book not found" },
    });
    const { result } = renderRapid();

    act(() => result.current.capture("9780441013593"));

    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("not-found"),
    );
    expect(result.current.entries[0]?.draft).not.toBeNull();
  });

  it("writes nothing until the batch is confirmed", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    const { result } = renderRapid();

    act(() => result.current.capture("9780441013593"));
    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));

    expect(api.lastCall("/api/books/scan")).toBeUndefined();
  });

  it("adds the whole queue on confirm", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();
    act(() => result.current.capture("9780441013593"));
    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));

    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(api.lastCall("/api/books/scan", "POST")).toBeDefined();
  });

  it("counts a book that could not be added rather than failing the batch", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", {
      status: 409,
      body: { detail: "Already exists" },
    });
    const { result } = renderRapid();
    act(() => result.current.capture("9780441013593"));
    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));

    act(() => result.current.addAll());

    await waitFor(() =>
      expect(result.current.result).toEqual({
        added: 0,
        failed: 1,
        unreferenced: 0,
      }),
    );
  });

  it("empties the queue once added", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();
    act(() => result.current.capture("9780441013593"));
    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));

    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.entries).toEqual([]));
  });

  it("drops one entry without touching the rest", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    const { result } = renderRapid();
    act(() => result.current.capture("9780441013593"));
    act(() => result.current.capture("9780262033848"));
    await waitFor(() => expect(result.current.entries).toHaveLength(2));

    act(() => result.current.remove("isbn:9780441013593"));

    expect(result.current.entries.map((e) => e.isbn)).toEqual([
      "9780262033848",
    ]);
  });

  it("keeps a barcode whose lookup was still in flight when the batch ran", async () => {
    // It has no draft, so it is not in the batch. It used to be dropped from
    // the queue anyway: press Add all one second early and that book is gone
    // between the shelf and the catalogue, with nothing on screen saying so.
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    api.on("/api/books/lookup", async (url) => {
      if (url.includes("9780262033848")) await held;
      return { body: LOOKUP };
    });
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();

    act(() => result.current.capture("9780441013593"));
    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));
    act(() => result.current.capture("9780262033848"));
    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(result.current.entries.map((entry) => entry.isbn)).toEqual([
      "9780262033848",
    ]);
    release();
  });
});

describe("useRapidIntake and a picked file", () => {
  function renderRapid() {
    return renderHookWithProviders(() => useRapidIntake());
  }

  /** The queue, once nothing in it is still being read. */
  async function settled(result: { current: { isReading: boolean } }) {
    await waitFor(() => expect(result.current.isReading).toBe(false));
  }

  it("reads an EPUB into the queue without sending anything", async () => {
    const { result } = renderRapid();
    const file = await epubFile("dune.epub");

    act(() => result.current.pickFiles([file]));
    await settled(result);

    expect(result.current.entries[0]?.state).toBe("found");
    expect(result.current.entries[0]?.draft?.title).toBe("Dune");
    // The decision behind this path, asserted rather than commented: reading a
    // file creates no request at all, so nothing here is a route by which the
    // application comes to hold somebody's book.
    expect(api.calls).toEqual(
      api.calls.filter((call) => call.method === "GET"),
    );
  });

  it("labels the entry with the file's name, since most files have no ISBN", async () => {
    // Measured over 79 real EPUBs: 4 carried an ISBN. A queue labelled by ISBN
    // would show seventy five blanks.
    const { result } = renderRapid();

    const file = await epubFile("dune.epub");

    act(() => result.current.pickFiles([file]));
    await settled(result);

    expect(result.current.entries[0]?.label).toBe("dune.epub");
    expect(result.current.entries[0]?.isbn).toBe("");
  });

  it("keeps a file it could not read as a candidate under its own name", async () => {
    // It was a dead end until the filename fallback shipped. The file is still
    // a book, its name is still a signal, and what the file itself could not
    // say becomes a note beside it rather than the end of it.
    const { result } = renderRapid();
    const broken = new File(["not an epub at all"], "broken.epub");

    act(() => result.current.pickFiles([broken]));
    await settled(result);

    expect(result.current.entries[0]).toMatchObject({
      state: "derived",
      label: "broken.epub",
      draft: { title: "broken" },
    });
    expect(result.current.entries[0]?.reason).toBe("Not an EPUB file.");
  });

  it("reads the rest of a batch after one file fails", async () => {
    const { result } = renderRapid();

    const good = await epubFile("dune.epub");

    act(() =>
      result.current.pickFiles([new File(["nope"], "broken.epub"), good]),
    );
    await settled(result);

    expect(result.current.entries.map((entry) => entry.state)).toEqual([
      "derived",
      "found",
    ]);
  });

  it("fails a file only when its name says nothing either", async () => {
    // A title is the one field the API requires, and both instruments have to
    // come up empty before a picked file is a failure now: the file opened and
    // named no title, and the name reduces to nothing once its extension is
    // taken off.
    const { result } = renderRapid();
    const untitled = await epubFile(".epub", {
      opf: packageDocument(`<dc:creator>Frank Herbert</dc:creator>`),
    });

    act(() => result.current.pickFiles([untitled]));
    await settled(result);

    expect(result.current.entries[0]?.state).toBe("failed");
    expect(result.current.entries[0]?.reason).toBe(
      "This file carries no title.",
    );
  });

  it("ignores the same file picked twice", async () => {
    const { result } = renderRapid();
    const file = await epubFile("dune.epub");

    act(() => result.current.pickFiles([file]));
    await settled(result);
    act(() => result.current.pickFiles([file]));
    await settled(result);

    expect(result.current.entries).toHaveLength(1);
  });

  it("adds what the file said when the batch is confirmed", async () => {
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();
    const file = await epubFile("dune.epub");
    act(() => result.current.pickFiles([file]));
    await settled(result);

    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
      title: "Dune",
      author: "Frank Herbert",
      language: "en",
      // The container answers this. `format` is nullable precisely so nothing
      // guesses it, and a file whose own type is EPUB is not a guess.
      format: "ebook",
    });
  });

  it("leaves the format blank for a barcode, which answers nothing about it", async () => {
    api.on("/api/books/lookup", {
      body: {
        isbn: "9780441013593",
        title: "Dune",
        author: "Frank Herbert",
        suggested_tag_ids: [],
      },
    });
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();
    act(() => result.current.capture("9780441013593"));
    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));

    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
      format: null,
    });
  });

  it("keeps an unreadable file in the queue after the batch runs", async () => {
    // It has no draft, so it was never offered to the batch, and it is exactly
    // what still needs a decision.
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();
    const good = await epubFile("dune.epub");
    act(() => result.current.pickFiles([new File(["nope"], ".epub"), good]));
    await settled(result);

    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(result.current.entries.map((entry) => entry.label)).toEqual([
      ".epub",
    ]);
  });
});

describe("useScanFlow and a book already on the shelf", () => {
  const LOOKUP = {
    isbn: "9780441013593",
    title: "Dune",
    author: "Frank Herbert",
    suggested_tag_ids: [],
  };

  const CONFLICT = {
    status: 409,
    body: {
      detail: { message: "Book with this ISBN already in catalog", book_id: 7 },
    },
  };

  async function scanADuplicate(onAdded: (bookId: number) => void = () => {}) {
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", CONFLICT);
    const rendered = renderHookWithProviders(() => useScanFlow(onAdded));

    act(() => rendered.result.current.lookup("9780441013593"));
    await waitFor(() =>
      expect(rendered.result.current.pending.draft).not.toBeNull(),
    );
    act(() => rendered.result.current.confirm());
    await waitFor(() => expect(rendered.result.current.error).not.toBeNull());
    return rendered;
  }

  it("does nothing when there was no conflict to copy from", async () => {
    // The id comes off the 409, so with no 409 there is no book to copy.
    const { result } = renderHookWithProviders(() => useScanFlow(() => {}));

    act(() => result.current.addCopy());

    await waitFor(() => expect(result.current.isAddingCopy).toBe(false));
    expect(api.lastCall("/copies", "POST")).toBeUndefined();
  });

  it("adds a copy of the book that already holds the ISBN", async () => {
    // The deliberate half of the collision. The mis-scan keeps its own answer,
    // which is the link to the book already here.
    const { result } = await scanADuplicate();
    act(() => result.current.update({ location: "Loft" }));
    api.on("/api/books/7/copies", { body: makeBook({ id: 99 }) }, "POST");

    act(() => result.current.addCopy());

    await waitFor(() =>
      expect(api.lastCall("/api/books/7/copies", "POST")).toBeDefined(),
    );
    expect(api.lastCall("/api/books/7/copies", "POST")?.body).toMatchObject({
      location: "Loft",
    });
  });

  it("opens the new copy once it exists", async () => {
    const onAdded = vi.fn();
    const { result } = await scanADuplicate(onAdded);
    api.on("/api/books/7/copies", { body: makeBook({ id: 99 }) }, "POST");

    act(() => result.current.addCopy());

    await waitFor(() => expect(onAdded).toHaveBeenCalledWith(99));
  });

  it("sends nothing about the work, only about the copy", async () => {
    // A payload that can restate the title is a payload that can disagree with
    // it, and two rows claiming to be copies of each other while naming
    // different books is a state nothing can render.
    const { result } = await scanADuplicate();
    api.on("/api/books/7/copies", { body: makeBook({ id: 99 }) }, "POST");

    act(() => result.current.addCopy());

    await waitFor(() =>
      expect(api.lastCall("/api/books/7/copies", "POST")).toBeDefined(),
    );
    const sent = api.lastCall("/api/books/7/copies", "POST")?.body as object;
    expect(sent).not.toHaveProperty("title");
    expect(sent).not.toHaveProperty("isbn");
    expect(sent).not.toHaveProperty("is_private");
  });
});

describe("the shelf location carries over", () => {
  const LOOKUP = {
    isbn: "9780441013593",
    title: "Dune",
    author: "Frank Herbert",
    suggested_tag_ids: [],
  };

  it("starts a scan from the shelf last used", async () => {
    localStorage.setItem("lastLocation", "Loft box 2");
    const { result } = renderHookWithProviders(() => useScanFlow(() => {}));
    await waitFor(() =>
      expect(result.current.pending.location).toBe("Loft box 2"),
    );
  });

  it("sends the shelf with the book", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderHookWithProviders(() => useScanFlow(() => {}));

    act(() => result.current.lookup("9780441013593"));
    await waitFor(() => expect(result.current.pending.draft).not.toBeNull());
    act(() => result.current.update({ location: "Kitchen" }));
    act(() => result.current.confirm());

    await waitFor(() =>
      expect(api.lastCall("/api/books/scan", "POST")).toBeDefined(),
    );
    expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
      location: "Kitchen",
    });
  });

  it("remembers the shelf only once the book is actually written", async () => {
    // A duplicate ISBN is rejected. Remembering the shelf anyway would carry
    // over a value nothing was ever filed at.
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", {
      status: 409,
      body: { detail: "Book with this ISBN already in catalog" },
    });
    const { result } = renderHookWithProviders(() => useScanFlow(() => {}));

    act(() => result.current.lookup("9780441013593"));
    await waitFor(() => expect(result.current.pending.draft).not.toBeNull());
    act(() => result.current.update({ location: "Kitchen" }));
    act(() => result.current.confirm());

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(localStorage.getItem("lastLocation")).toBeNull();
  });

  it("keeps the shelf across a cancel, which is the whole point", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    const { result } = renderHookWithProviders(() => useScanFlow(() => {}));

    act(() => result.current.update({ location: "Kitchen" }));
    act(() => result.current.reset());

    await waitFor(() =>
      expect(result.current.pending.location).toBe("Kitchen"),
    );
  });

  it("sends one shelf for every book in a rapid run", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderHookWithProviders(() => useRapidIntake());

    act(() => result.current.setLocation("Loft box 2"));
    act(() => result.current.capture("9780441013593"));
    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));
    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
      location: "Loft box 2",
    });
    expect(localStorage.getItem("lastLocation")).toBe("Loft box 2");
  });

  it("offers the shelves already in use", async () => {
    const { result } = renderHookWithProviders(() => useRapidIntake());
    await waitFor(() =>
      expect(result.current.locations[0]?.name).toBe("Living room shelf 3"),
    );
  });
});

/**
 * The filename and folder fallback.
 *
 * The floor under every format reader: what happens to a file whose own bytes
 * said nothing, or that no reader here opens at all.
 */
describe("useRapidIntake and a file with no usable metadata", () => {
  function renderRapid() {
    return renderHookWithProviders(() => useRapidIntake());
  }

  async function settled(result: { current: { isReading: boolean } }) {
    await waitFor(() => expect(result.current.isReading).toBe(false));
  }

  /** A file picked out of a folder, which is the only way a path arrives. */
  function inFolder(name: string, path: string): File {
    const file = new File(["%PDF-1.4"], name);
    Object.defineProperty(file, "webkitRelativePath", { value: path });
    return file;
  }

  const MATCH = {
    google_books_id: "abc",
    title: "The Dispossessed",
    author: "Ursula K. Le Guin",
    year: 1974,
    isbn13: "9780060512750",
    suggested_tag_ids: [],
  };

  function searchCalls(): number {
    return api.calls.filter((call) => call.url.includes("/api/books/search"))
      .length;
  }

  it("queues a format no reader here opens, from its name", async () => {
    // The whole point of the path: without it a PDF is a dead end, and for a
    // PDF an unusable metadata block is the common case rather than the
    // exception.
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([new File(["%PDF-1.4"], "Dune (1965).pdf")]),
    );
    await settled(result);

    expect(result.current.entries[0]).toMatchObject({
      state: "derived",
      draft: { title: "Dune", year: 1965 },
    });
  });

  it("says where a file picked out of a folder is, once the book exists", async () => {
    // The sentence the whole feature opens with: the page reads a file, adds
    // the book, and used to forget which file it came from. No byte of the file
    // is sent; a root the member picked and the path beneath it are.
    api.on("/api/books/scan", { body: makeBook({ id: 42 }) });
    api.on("/api/books/42/digital-references", { body: {} });
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        inFolder("Dune.pdf", "Books/Frank Herbert/Dune.pdf"),
      ]),
    );
    await settled(result);
    act(() => result.current.addAll());
    await waitFor(() => expect(result.current.result?.added).toBe(1));

    expect(
      api.lastCall("/api/books/42/digital-references", "POST")?.body,
    ).toMatchObject({
      // **The picked folder's own name is the root and never the head of the
      // path.** The server cannot enforce it, and two clients disagreeing
      // write two rows for one file.
      root_label: "Books",
      relative_path: "Frank Herbert/Dune.pdf",
      root_confirmed: true,
    });
  });

  it("sends no location for a file picked one at a time", async () => {
    // A bare pick gives a name and no path, so there is no root to name and no
    // screen in which a member names one. Nothing is sent rather than a guess
    // being sent with `root_confirmed` false.
    api.on("/api/books/scan", { body: makeBook({ id: 43 }) });
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([new File(["%PDF-1.4"], "Dune (1965).pdf")]),
    );
    await settled(result);
    act(() => result.current.addAll());
    await waitFor(() => expect(result.current.result?.added).toBe(1));

    expect(
      api.calls.some((call) => call.url.includes("digital-references")),
    ).toBe(false);
  });

  it("sends no location for an audiobook, which is not one file", async () => {
    // The format's own inversion again: a row standing for three chapter files
    // has no one file to point at, and a book holds sixteen references at the
    // most, so a folder of forty would spend the ceiling on one book.
    api.on("/api/books/scan", { body: makeBook({ id: 44 }) });
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        chapterFile(0, "Robinson Crusoe"),
        chapterFile(1, "Robinson Crusoe"),
      ]),
    );
    await settled(result);
    act(() => result.current.addAll());
    await waitFor(() => expect(result.current.result?.added).toBe(1));

    expect(
      api.calls.some((call) => call.url.includes("digital-references")),
    ).toBe(false);
  });

  it("counts a book whose location was refused, and still counts it added", async () => {
    // **The book exists by the time this runs.** Reporting it as failed would
    // put a created book back in the queue with a reason, and a member reading
    // that adds it again into a duplicate. What was lost is the answer to
    // "where is the file", which is its own count and its own sentence.
    api.on("/api/books/scan", { body: makeBook({ id: 45 }) });
    api.on("/api/books/45/digital-references", { status: 500, body: {} });
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([inFolder("Dune.pdf", "Books/Dune.pdf")]),
    );
    await settled(result);
    act(() => result.current.addAll());
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(result.current.result).toEqual({
      added: 1,
      failed: 0,
      unreferenced: 1,
    });
    expect(result.current.entries).toHaveLength(0);
  });

  const DUPLICATE = {
    status: 409,
    body: {
      detail: {
        message: "Book with this ISBN already in catalog",
        book_id: 77,
      },
    },
  };

  it("records the location on the book a duplicate turned out to be", async () => {
    // **The case the sighting was made idempotent for.** Re importing a folder
    // somebody imported last month answers 409 on every book in it, so a
    // reference sent only after a successful create is sent on exactly the
    // pick that needs it least.
    //
    // An EPUB rather than a PDF, and that is the arm below's subject: this file
    // states its own identifier, so the book the 409 names is a book this row
    // has evidence about.
    api.on("/api/books/scan", DUPLICATE);
    api.on("/api/books/77/digital-references", { body: {} });
    const file = await epubFile("dune.epub");
    Object.defineProperty(file, "webkitRelativePath", {
      value: "Books/dune.epub",
    });
    const { result } = renderRapid();

    act(() => result.current.pickFiles([file]));
    await settled(result);
    expect(result.current.entries[0]?.state).toBe("found");
    act(() => result.current.addAll());
    await waitFor(() => expect(result.current.result?.failed).toBe(1));

    expect(
      api.lastCall("/api/books/77/digital-references", "POST")?.body,
    ).toMatchObject({ root_label: "Books", relative_path: "dune.epub" });
    // The row is still a failure and still says why, which is what the member
    // acts on. The location is not a second reason.
    expect(result.current.result?.unreferenced).toBe(0);
  });

  it("writes no location onto a stranger's book on an ISBN read out of a name", async () => {
    // **A duplicate 409 names a book this member did not add.** A row standing
    // under its file name has whatever `fileName.isbnIn` found in that name,
    // and a ten digit run passes modulus 11 about one time in eleven, so
    // following it would write this member's own folder names onto somebody
    // else's book and spend one of its sixteen references, on a row the screen
    // calls failed.
    api.on("/api/books/scan", DUPLICATE);
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        inFolder("Dune 9780441013593.pdf", "Books/Dune 9780441013593.pdf"),
      ]),
    );
    await settled(result);
    // The row does carry the ISBN, which is what makes this a refusal rather
    // than a case that could not arise.
    expect(result.current.entries[0]).toMatchObject({
      state: "derived",
      isbn: "9780441013593",
    });

    act(() => result.current.addAll());
    await waitFor(() => expect(result.current.result?.failed).toBe(1));

    expect(
      api.calls.some((call) => call.url.includes("digital-references")),
    ).toBe(false);
  });

  it("writes none either once the catalogue has answered about that name", async () => {
    // **The case the first draft of this gate did not refuse.** A name carrying
    // a ten digit token that passes modulus 11 takes the route a barcode takes,
    // and a successful lookup promotes the row to `found`, so a gate reading the
    // state saw a file that had stated its own identifier. It had not: the
    // lookup answered about the ISBN and says nothing about where the ISBN came
    // from.
    api.on("/api/books/lookup", {
      body: {
        isbn: "9780441013593",
        title: "Dune",
        author: "Frank Herbert",
        suggested_tag_ids: [],
      },
    });
    api.on("/api/books/scan", DUPLICATE);
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        inFolder("Dune 9780441013593.pdf", "Books/Dune 9780441013593.pdf"),
      ]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));

    act(() => result.current.addAll());
    await waitFor(() => expect(result.current.result?.failed).toBe(1));

    expect(
      api.calls.some((call) => call.url.includes("digital-references")),
    ).toBe(false);
  });

  it("records the location once a member has taken a catalogue record", async () => {
    // The other side of the same rule, so the gate is a refusal of one
    // provenance rather than of every row that ever stood under its own name.
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    api.on("/api/books/scan", DUPLICATE);
    api.on("/api/books/77/digital-references", { body: {} });
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([inFolder("Dune.pdf", "Books/Dune.pdf")]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );
    act(() => result.current.chooseFor(result.current.entries[0]!.key, MATCH));
    act(() => result.current.addAll());
    await waitFor(() => expect(result.current.result?.failed).toBe(1));

    expect(
      api.lastCall("/api/books/77/digital-references", "POST")?.body,
    ).toMatchObject({ root_label: "Books", relative_path: "Dune.pdf" });
  });

  it("asks no catalogue while reading, because the lookup is offered", async () => {
    // Several hundred files is several hundred fan outs, and a page may not
    // spend somebody's rate limit because they pointed at a folder.
    const { result } = renderRapid();

    act(() => result.current.pickFiles([new File(["%PDF"], "Dune.pdf")]));
    await settled(result);

    expect(searchCalls()).toBe(0);
    expect(result.current.waiting).toBe(1);
  });

  it("counts what the walk passed over rather than ignoring it", async () => {
    // A member who points at a folder of CBR files and sees nothing appear
    // deserves to know why.
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        new File(["a"], "one.cbr"),
        new File(["b"], "two.djvu"),
        new File(["c"], "three.pdf"),
      ]),
    );
    await settled(result);

    expect(result.current.skipped).toBe(2);
    expect(result.current.entries).toHaveLength(1);
  });

  it("counts what the last pick passed over, not every pick ever made", async () => {
    // A running total has no way down, and this notice sits beside the picker
    // rather than the queue precisely so it can be shown when nothing was
    // queued at all: a member who picks a folder of comics and nothing else
    // would otherwise carry the number for the rest of the session.
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        new File(["a"], "one.cbr"),
        new File(["b"], "two.cbr"),
      ]),
    );
    await settled(result);
    expect(result.current.skipped).toBe(2);

    act(() => result.current.pickFiles([new File(["c"], "three.djvu")]));
    await settled(result);

    expect(result.current.skipped).toBe(1);
  });

  it("strips a picked name before printing it, as it does every title", async () => {
    // A bidirectional override renders as nothing and reverses what a reader
    // sees after it. The label is printed beside a title that was cleaned, and
    // it is what a removal is announced by.
    const { result } = renderRapid();

    act(() => result.current.pickFiles([new File(["%PDF"], "Du\u202ene.pdf")]));
    await settled(result);

    expect(result.current.entries[0]?.label).toBe("Dune.pdf");
  });

  it("reads the author off the folder when the name repeats it", async () => {
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        inFolder(
          "Le Guin - The Dispossessed.pdf",
          "Le Guin/The Dispossessed/Le Guin - The Dispossessed.pdf",
        ),
      ]),
    );
    await settled(result);

    expect(result.current.entries[0]?.draft).toMatchObject({
      author: "Le Guin",
      title: "The Dispossessed",
    });
  });

  it("falls back to the name when a file it can open says nothing", async () => {
    // It used to be a dead end. The file is still a book and its name is still
    // a signal, so what the file could not say becomes a note beside it.
    const { result } = renderRapid();
    const untitled = await epubFile("Dune (1965).epub", {
      opf: packageDocument(`<dc:creator>Frank Herbert</dc:creator>`),
    });

    act(() => result.current.pickFiles([untitled]));
    await settled(result);

    expect(result.current.entries[0]).toMatchObject({
      state: "derived",
      reason: "This file carries no title.",
      draft: { title: "Dune" },
    });
  });

  it("falls back to the name for a file that would not open at all", async () => {
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([new File(["nope"], "The Dispossessed.epub")]),
    );
    await settled(result);

    expect(result.current.entries[0]).toMatchObject({
      state: "derived",
      reason: "Not an EPUB file.",
      draft: { title: "The Dispossessed" },
    });
  });

  it("still fails a file whose name reduces to nothing", async () => {
    // A title is the one field the API requires, and this is the only way a
    // picked file arrives without one now.
    const { result } = renderRapid();

    act(() => result.current.pickFiles([new File(["%PDF"], ".pdf")]));
    await settled(result);

    expect(result.current.entries[0]?.state).toBe("failed");
  });

  it("adds what the name said when nothing else did", async () => {
    // Created rather than skipped, which is the same call the OPDS sync makes
    // for a holding with no description.
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();
    act(() => result.current.pickFiles([new File(["%PDF"], "Dune.pdf")]));
    await settled(result);

    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
      title: "Dune",
      format: "ebook",
    });
  });

  it("files an M4B as an audiobook and a CBZ as a comic", async () => {
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        new File(["a"], "Dune.m4b"),
        new File(["b"], "Watchmen.cbz"),
      ]),
    );
    await settled(result);

    // The audio row is queued first and filled in once the pick has been read,
    // because which audio files are one book is not known until then.
    expect(result.current.entries.map((entry) => entry.format)).toEqual([
      "audiobook",
      "comic",
    ]);
  });

  it("searches by the derived name once it is asked to", async () => {
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "The Dispossessed.pdf")]),
    );
    await settled(result);

    act(() => result.current.lookUpTheNames());

    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );
    const query = new URL(
      api.lastCall("/api/books/search")!.url,
      "http://localhost",
    ).searchParams;
    expect(query.get("q")).toBe("The Dispossessed");
    expect(result.current.entries[0]?.matches).toHaveLength(1);
  });

  it("makes one row of a folder of chapter files, not one each", async () => {
    // The whole ticket. Thirty seven rows from one audiobook is a mess
    // proportional to the size of a library.
    const chapters = Array.from({ length: 37 }, (_, index) =>
      chapterFile(index, "Robinson Crusoe"),
    );
    const { result } = renderRapid();

    act(() => result.current.pickFiles(chapters));
    await settled(result);

    expect(result.current.entries).toHaveLength(1);
    expect(result.current.entries[0]).toMatchObject({
      format: "audiobook",
      state: "derived",
      draft: { title: "Robinson Crusoe", author: "Daniel Defoe" },
    });
  });

  it("says how many files the row was made of, before anything is added", async () => {
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        chapterFile(0, "Robinson Crusoe"),
        chapterFile(1, "Robinson Crusoe"),
      ]),
    );
    await settled(result);

    expect(result.current.entries[0]?.group?.files).toHaveLength(2);
  });

  it("files the parts as separate books when the member says so", async () => {
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        chapterFile(0, "Mixed"),
        chapterFile(1, "Mixed"),
      ]),
    );
    await settled(result);
    const key = result.current.entries[0]!.key;

    act(() => result.current.splitApart(key));
    await waitFor(() => expect(result.current.entries).toHaveLength(2));

    // The album they shared is gone with the grouping the member rejected, so
    // each is named after its own chapter.
    expect(result.current.entries.map((entry) => entry.draft?.title)).toEqual([
      "Chapter 0",
      "Chapter 1",
    ]);
  });

  it("queues nothing twice when the same folder is picked again", async () => {
    const chapters = [chapterFile(0, "Dune"), chapterFile(1, "Dune")];
    const { result } = renderRapid();

    act(() => result.current.pickFiles(chapters));
    await settled(result);
    act(() => result.current.pickFiles(chapters));
    await settled(result);

    expect(result.current.entries).toHaveLength(1);
  });

  it("shows the picker as busy while a pick is being read", async () => {
    // A folder of chapter files has nothing to show until it has been grouped,
    // and a picker that shows nothing meanwhile reads as one that is broken.
    const { result } = renderRapid();

    act(() => result.current.pickFiles([chapterFile(0, "Dune")]));

    expect(result.current.isReading).toBe(true);
    await settled(result);
  });

  it("falls back to the folder's name when the files carry no tags", async () => {
    // The ordinary case for anything somebody ripped themselves.
    const { result } = renderRapid();
    const files = [0, 1].map((index) => {
      const file = new File([mp3()], `${index}.mp3`);
      Object.defineProperty(file, "webkitRelativePath", {
        value: `The Hobbit/${index}.mp3`,
      });
      return file;
    });

    act(() => result.current.pickFiles(files));
    await settled(result);

    expect(result.current.entries).toHaveLength(1);
    expect(result.current.entries[0]?.draft?.title).toBe("The Hobbit");
  });

  it("adds one audiobook rather than one book per chapter", async () => {
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();

    act(() =>
      result.current.pickFiles([
        chapterFile(0, "Robinson Crusoe"),
        chapterFile(1, "Robinson Crusoe"),
        chapterFile(2, "Robinson Crusoe"),
      ]),
    );
    await settled(result);

    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
      title: "Robinson Crusoe",
      author: "Daniel Defoe",
      format: "audiobook",
    });
  });

  it("takes an ISBN in the name to the lookup, never to the fan out", async () => {
    // An ISBN is an identifier rather than a guess, and one call per file is
    // what makes the pace's arithmetic true.
    api.on("/api/books/lookup", {
      body: {
        isbn: "9780441013593",
        title: "Dune",
        author: "Frank Herbert",
        suggested_tag_ids: [],
      },
    });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "Dune 9780441013593.pdf")]),
    );
    await settled(result);

    act(() => result.current.lookUpTheNames());

    await waitFor(() => expect(result.current.entries[0]?.state).toBe("found"));
    expect(result.current.entries[0]?.draft?.author).toBe("Frank Herbert");
    expect(searchCalls()).toBe(0);
  });

  it("keeps the book when the catalogues have never heard of it", async () => {
    // Six of the eight sources a title search reaches refuse a record that says
    // it is electronic, so this is the ordinary outcome for a born digital
    // title rather than a failure.
    api.on("/api/books/search", {
      body: { matches: [], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() => result.current.pickFiles([new File(["%PDF"], "Dune.pdf")]));
    await settled(result);

    act(() => result.current.lookUpTheNames());

    await waitFor(() =>
      expect(result.current.entries[0]?.reason).toBe(
        "Not in the catalogues, kept under its file name.",
      ),
    );
    expect(result.current.entries[0]).toMatchObject({
      state: "derived",
      draft: { title: "Dune" },
    });
  });

  it("does not offer to look that one up again", async () => {
    // The catalogue answered. Offering the same call a second time would spend
    // the same budget to be told the same thing.
    api.on("/api/books/search", {
      body: { matches: [], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() => result.current.pickFiles([new File(["%PDF"], "Dune.pdf")]));
    await settled(result);

    act(() => result.current.lookUpTheNames());

    await waitFor(() => expect(result.current.waiting).toBe(0));
  });

  it("takes a 404 from the ISBN lookup as an answer, not as a failure", async () => {
    // The books router splits the two deliberately: a 404 is nobody knowing the
    // ISBN and a 503 is no source having been reachable. Reading them as one
    // offered the retry that buys nothing and withheld the one that does.
    api.on("/api/books/lookup", { status: 404, body: { detail: "unknown" } });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "Dune 9780441013593.pdf")]),
    );
    await settled(result);

    act(() => result.current.lookUpTheNames());

    await waitFor(() =>
      expect(result.current.entries[0]?.reason).toBe(
        "Not in the catalogues, kept under its file name.",
      ),
    );
    expect(result.current.waiting).toBe(0);
  });

  it("offers a lookup again when the catalogues could not be reached", async () => {
    api.on("/api/books/lookup", { status: 503, body: { detail: "down" } });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "Dune 9780441013593.pdf")]),
    );
    await settled(result);

    act(() => result.current.lookUpTheNames());

    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("derived"),
    );
    expect(result.current.waiting).toBe(1);
  });

  it(
    "leaves a file still being decided out of the batch",
    async () => {
      // Adding it would file it under its file name and throw away every record
      // the catalogue found for it, with nothing said on screen. It stays queued,
      // for the reason an entry with no draft stays queued.
      //
      // **Two files, and the second one is what makes this a test.** With one the
      // batch has nothing to add, returns before it writes anything, and every
      // assertion about what was written passes whether the row was excluded or
      // not. Measured: the mutation that drops the exclusion was not caught until
      // a row that does get added was put beside it.
      api.on("/api/books/search", (url) =>
        url.includes("dispossessed")
          ? { body: { matches: [MATCH], asked: ["open_library"], unasked: [] } }
          : { body: { matches: [], asked: ["open_library"], unasked: [] } },
      );
      api.on("/api/books/scan", { body: makeBook() });
      const { result } = renderRapid();
      act(() =>
        result.current.pickFiles([
          new File(["%PDF"], "dispossessed.pdf"),
          new File(["%PDF"], "Dune.pdf"),
        ]),
      );
      await settled(result);
      // **Both ends, because one value pins no function.** Asserted only where
      // it is 1, a constant 1 passes; asserted only where it is 0, a constant 0
      // does. The diagonal is what makes this a measurement of the predicate
      // rather than of the moment it was read.
      expect(result.current.deciding).toBe(0);

      act(() => result.current.lookUpTheNames());
      await waitFor(
        () => expect(result.current.entries[1]?.answered).toBe("nothing"),
        { timeout: FALLBACK_INTERVAL_MS * 2 },
      );

      // The number the queue says this out of, taken from the predicate the
      // batch excludes rather than from a second one spelled the same way.
      expect(result.current.deciding).toBe(1);

      act(() => result.current.addAll());

      await waitFor(() => expect(result.current.result?.added).toBe(1));
      expect(result.current.entries).toHaveLength(1);
      expect(result.current.entries[0]?.state).toBe("choosing");
      expect(result.current.deciding).toBe(1);
    },
    FALLBACK_INTERVAL_MS * 4,
  );

  it("offers it again when nothing could be reached", async () => {
    // Nothing was learned, so the file is still worth asking about.
    api.on("/api/books/search", { status: 503, body: { detail: "down" } });
    const { result } = renderRapid();
    act(() => result.current.pickFiles([new File(["%PDF"], "Dune.pdf")]));
    await settled(result);

    act(() => result.current.lookUpTheNames());

    await waitFor(() =>
      expect(result.current.entries[0]?.reason).toBe(
        "The catalogues could not be reached, kept under its file name.",
      ),
    );
    expect(result.current.waiting).toBe(1);
  });

  it("takes the record a member chooses over the name", async () => {
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "dispossessed.pdf")]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );

    const entry = result.current.entries[0]!;
    act(() => result.current.chooseFor(entry.key, entry.matches![0]!));

    expect(result.current.entries[0]).toMatchObject({
      state: "found",
      isbn: "9780060512750",
      draft: { title: "The Dispossessed", author: "Ursula K. Le Guin" },
    });
  });

  it("keeps the name when a member rejects every record offered", async () => {
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "dispossessed.pdf")]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );

    act(() => result.current.keepTheName(result.current.entries[0]!.key));

    expect(result.current.entries[0]).toMatchObject({
      state: "derived",
      draft: { title: "dispossessed" },
    });
    expect(result.current.waiting).toBe(0);
  });

  it("does not offer a lookup again for a name kept one row at a time", async () => {
    // The member answered about this book. Asking again would spend the budget
    // to be told what they have already refused, and would put a decision they
    // made back on the screen. **This is the direction the bulk keep must not
    // quietly weaken**: it is the half of the pair that stays answered.
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "dispossessed.pdf")]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );

    act(() => result.current.keepTheName(result.current.entries[0]!.key));

    expect(result.current.entries[0]?.answered).toBe("records");
    expect(result.current.waiting).toBe(0);
  });

  it(
    "clears every row still being decided in one press",
    async () => {
      // The cost the owner's decision was taken against: a folder of 300 files
      // that matches 250 is 250 presses. **Two rows, because one pins nothing**:
      // a press that cleared only the row it was given would pass with one.
      api.on("/api/books/search", {
        body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
      });
      const { result } = renderRapid();
      act(() =>
        result.current.pickFiles([
          new File(["%PDF"], "dispossessed.pdf"),
          new File(["%PDF"], "Dune.pdf"),
        ]),
      );
      await settled(result);
      act(() => result.current.lookUpTheNames());
      await waitFor(() => expect(result.current.deciding).toBe(2), {
        timeout: FALLBACK_INTERVAL_MS * 2,
      });

      act(() => result.current.keepEveryNameForNow());

      expect(result.current.deciding).toBe(0);
      expect(result.current.entries.map((entry) => entry.state)).toEqual([
        "derived",
        "derived",
      ]);
    },
    FALLBACK_INTERVAL_MS * 4,
  );

  it("offers a lookup again for a name kept in bulk", async () => {
    // **What makes the press recoverable**, and the whole of the owner's
    // decision of 2026-09-10: the records leave the screen and the row goes
    // back into the set the lookup offers, so nothing is spent to get them
    // back except the search itself.
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "dispossessed.pdf")]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );

    act(() => result.current.keepEveryNameForNow());

    expect(result.current.entries[0]).toMatchObject({
      state: "derived",
      answered: "records-for-now",
      draft: { title: "dispossessed" },
      reason: "Kept under its file name for now, and can be looked up again.",
    });
    expect(result.current.entries[0]?.matches).toBeUndefined();
    // **Both counts, because either alone passes on a constant.** The row is
    // offered again by a press that names it, and not by the press that looks
    // up files nobody has asked about.
    expect(result.current.keptForNow).toBe(1);
    expect(result.current.waiting).toBe(0);
  });

  it("does not offer a second pass for a name the catalogues answered nothing about", async () => {
    // **The arm of the map the other tests never walk.** A catalogue with no
    // record is the ordinary outcome for a folder of ebooks, so an answer
    // treated as reopenable would offer a second pass over all three hundred
    // rows, under a control that says the member kept them.
    api.on("/api/books/search", {
      body: { matches: [], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() => result.current.pickFiles([new File(["%PDF"], "Dune.pdf")]));
    await settled(result);

    act(() => result.current.lookUpTheNames());

    await waitFor(() =>
      expect(result.current.entries[0]?.answered).toBe("nothing"),
    );
    expect(result.current.keptForNow).toBe(0);
  });

  it("does not put a name kept in bulk back into the ordinary lookup", async () => {
    // **The invariant the bulk keep was not allowed to cost.** Ten more files
    // picked after a queue of two hundred and fifty was cleared must be a press
    // that looks up ten: without this the generic button drags every kept row
    // back into the wall the member had just pressed their way out of.
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "dispossessed.pdf")]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );
    act(() => result.current.keepEveryNameForNow());

    act(() => result.current.lookUpTheNames());

    expect(result.current.entries[0]?.state).toBe("derived");
    expect(searchCalls()).toBe(1);
  });

  it(
    "leaves a row answered by hand where it is when the rest are kept in bulk",
    async () => {
      // The diagonal the two kinds of kept row have to pass: one press, two rows,
      // and only one of them moves. Asserted on both, because a press that
      // touched every derived row would pass on the row it was meant to touch.
      api.on("/api/books/search", {
        body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
      });
      const { result } = renderRapid();
      act(() =>
        result.current.pickFiles([
          new File(["%PDF"], "dispossessed.pdf"),
          new File(["%PDF"], "Dune.pdf"),
        ]),
      );
      await settled(result);
      act(() => result.current.lookUpTheNames());
      await waitFor(() => expect(result.current.deciding).toBe(2), {
        timeout: FALLBACK_INTERVAL_MS * 2,
      });
      act(() => result.current.keepTheName(result.current.entries[0]!.key));

      act(() => result.current.keepEveryNameForNow());

      expect(result.current.entries[0]).toMatchObject({
        answered: "records",
        reason: "Kept under its file name.",
      });
      expect(result.current.entries[1]?.answered).toBe("records-for-now");
      // One of the two, which is the count that says which row came back.
      expect(result.current.keptForNow).toBe(1);
    },
    FALLBACK_INTERVAL_MS * 4,
  );

  it("takes a name kept in bulk into the batch", async () => {
    // The press is a member clearing a queue so that Add all can run, so a row
    // it cleared has to be one the batch adds. Without this the control moves a
    // row out of one excluded set and into another.
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "dispossessed.pdf")]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );
    act(() => result.current.keepEveryNameForNow());

    act(() => result.current.addAll());

    await waitFor(() => expect(result.current.result?.added).toBe(1));
    expect(result.current.entries).toHaveLength(0);
  });

  it(
    "asks only the kept names on the second pass",
    async () => {
      // **A kept row and a waiting row on screen at once**, which is the state no
      // other test here produces and the one the second press could quietly widen
      // in: a button that says two and starts a run over everything on the queue
      // spends a budget priced for one run, under a figure that is not what it
      // does.
      api.on("/api/books/search", {
        body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
      });
      const { result } = renderRapid();
      act(() =>
        result.current.pickFiles([new File(["%PDF"], "dispossessed.pdf")]),
      );
      await settled(result);
      act(() => result.current.lookUpTheNames());
      await waitFor(() =>
        expect(result.current.entries[0]?.state).toBe("choosing"),
      );
      act(() => result.current.keepEveryNameForNow());
      act(() => result.current.pickFiles([new File(["%PDF"], "Dune.pdf")]));
      await settled(result);
      expect(result.current.waiting).toBe(1);
      expect(result.current.keptForNow).toBe(1);

      act(() => result.current.lookUpTheKeptNames());

      // Run to the end rather than to the first answer: a run that had taken the
      // second row as well would still be between two calls at that point, and
      // the count it had not yet spent would read as the count it never spends.
      await waitFor(() => expect(result.current.isLookingUp).toBe(false), {
        timeout: FALLBACK_INTERVAL_MS * 2,
      });
      expect(searchCalls()).toBe(2);
      expect(result.current.entries[1]).toMatchObject({ state: "derived" });
      expect(result.current.entries[1]?.answered).toBeUndefined();
    },
    FALLBACK_INTERVAL_MS * 4,
  );

  it("takes the kept note off a row it is asking about again", async () => {
    // A row being asked about has no answer and is not standing under its name
    // for a reason it can still state. Left behind, the note "kept under its
    // file name for now" renders above the list of records the second pass just
    // brought back, and the row is still counted as one of the kept.
    api.on("/api/books/search", {
      body: { matches: [MATCH], asked: ["open_library"], unasked: [] },
    });
    const { result } = renderRapid();
    act(() =>
      result.current.pickFiles([new File(["%PDF"], "dispossessed.pdf")]),
    );
    await settled(result);
    act(() => result.current.lookUpTheNames());
    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );
    act(() => result.current.keepEveryNameForNow());

    act(() => result.current.lookUpTheKeptNames());

    await waitFor(() =>
      expect(result.current.entries[0]?.state).toBe("choosing"),
    );
    expect(result.current.entries[0]?.reason).toBeUndefined();
    expect(result.current.entries[0]?.answered).toBeUndefined();
    expect(result.current.keptForNow).toBe(0);
  });

  it(
    "paces the run rather than asking about every file at once",
    async () => {
      // The decision this ticket had to answer. Without a pace the second call
      // follows the first within a microtask, and three hundred files would
      // answer 429 to the member's own next barcode.
      api.on("/api/books/search", {
        body: { matches: [], asked: ["open_library"], unasked: [] },
      });
      const { result } = renderRapid();
      act(() =>
        result.current.pickFiles([
          new File(["a"], "Dune.pdf"),
          new File(["b"], "Neuromancer.pdf"),
        ]),
      );
      await settled(result);

      act(() => result.current.lookUpTheNames());
      await waitFor(() => expect(searchCalls()).toBe(1));
      await new Promise((resolve) => {
        setTimeout(resolve, 100);
      });
      // A tenth of the interval in, the first has long since answered.
      expect(searchCalls()).toBe(1);

      // And it is a pace rather than a stop.
      await waitFor(() => expect(searchCalls()).toBe(2), {
        timeout: FALLBACK_INTERVAL_MS * 2,
      });
    },
    FALLBACK_INTERVAL_MS * 4,
  );

  it(
    "stops the run inside the wait rather than at the end of it",
    async () => {
      // **Both halves in one assertion, and neither had a test before.** The
      // loop reads the flag at its top, so without the flag the run carries on
      // and a second call lands; without the wait being woken the flag is not
      // read for a further two seconds, which is longer than a member waits
      // before pressing again. The timeout below is half an interval, so a stop
      // that only lands when the gap ends fails it.
      api.on("/api/books/search", {
        body: { matches: [], asked: ["open_library"], unasked: [] },
      });
      const { result } = renderRapid();
      act(() =>
        result.current.pickFiles([
          new File(["a"], "Dune.pdf"),
          new File(["b"], "Neuromancer.pdf"),
          new File(["c"], "Solaris.pdf"),
        ]),
      );
      await settled(result);

      act(() => result.current.lookUpTheNames());
      await waitFor(() => expect(searchCalls()).toBe(1));
      act(() => result.current.stopLookingUp());

      await waitFor(() => expect(result.current.isLookingUp).toBe(false), {
        timeout: FALLBACK_INTERVAL_MS / 2,
      });
      expect(searchCalls()).toBe(1);
      // The two it never reached are still there to be asked about.
      expect(result.current.waiting).toBe(2);
    },
    FALLBACK_INTERVAL_MS * 4,
  );

  it("says how long the run it is offering would take", async () => {
    const { result } = renderRapid();
    const files = Array.from(
      { length: 45 },
      (_unused, index) => new File(["a"], `Book number ${index}.pdf`),
    );

    act(() => result.current.pickFiles(files));
    await settled(result);

    // 45 files at one start per two seconds is 90 seconds.
    expect(result.current.waiting).toBe(45);
    expect(result.current.paceMinutes).toBe(2);
    // **The diagonal, and the only count where the two figures can differ.**
    // A minute is the floor, so at any count under thirty one both figures read
    // the same and a second pass quoting the first run's wait passes unseen.
    expect(result.current.keptForNow).toBe(0);
    expect(result.current.keptPaceMinutes).toBe(1);
  });
});

/**
 * The pace, against the budget it was priced on.
 *
 * @see backend/ratelimit.py
 */
describe("the fallback's share of the metadata budget", () => {
  const LIMITER = import.meta.glob("../../../../backend/ratelimit.py", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  it("is half of it, recomputed from the limiter rather than restated", () => {
    // **A number, once written down, stops being re-derived and starts being
    // copied.** The limiter is shared with the ISBN lookup behind every scanned
    // barcode and with the search box, so a fallback taking all of it would
    // answer 429 to the page it runs on. Half is the choice; that it is half of
    // *this* number is what this recomputes.
    const source = LIMITER["../../../../backend/ratelimit.py"] ?? "";
    expect(source.length).toBeGreaterThan(1000);
    const declared = source.match(
      /METADATA_LIMIT = RateLimit\(max_attempts=(\d+), window_seconds=(\d+)\)/,
    );
    expect(declared).not.toBeNull();

    const perMinute = (Number(declared![1]) * 60) / Number(declared![2]);
    expect(FALLBACK_STARTS_PER_MINUTE).toBe(perMinute / 2);
    expect(FALLBACK_INTERVAL_MS).toBe(60_000 / (perMinute / 2));
  });
});
