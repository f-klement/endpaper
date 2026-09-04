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
  useBookSearch,
  useRapidIntake,
  useScanFlow,
} from "../../../src/pages/ScanPage/hooks";
import { makeBook, resetIds } from "../../factories";
import { mockApi, renderHookWithProviders, type MockApi } from "../../utils";

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
      expect(result.current.result).toEqual({ added: 0, failed: 1 }),
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

    act(() => result.current.remove("9780441013593"));

    expect(result.current.entries.map((e) => e.isbn)).toEqual([
      "9780262033848",
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
