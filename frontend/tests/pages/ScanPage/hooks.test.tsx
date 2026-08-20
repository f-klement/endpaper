/**
 * Tests for src/pages/ScanPage/hooks.ts: the Google Books search path.
 *
 * The scan-and-lookup path is covered through the page in `ScanPage.test.tsx`.
 * These are the parts that are easier to pin at the hook: when a request is
 * made at all, and what a chosen result does to the draft.
 */

import { act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

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
  api.on("/api/books/search", { body: [match()] });
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

    await waitFor(() => expect(api.lastCall("/api/books/search")).toBeDefined());

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
    api.on("/api/books/search", { body: [] });
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
});

describe("useScanFlow.chooseMatch", () => {
  function renderFlow() {
    return renderHookWithProviders(() => useScanFlow(() => {}));
  }

  it("prefills the draft from the chosen record", () => {
    const { result } = renderFlow();

    act(() => result.current.chooseMatch(match()));

    expect(result.current.draft).toMatchObject({
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
    expect(result.current.selectedTagIds).toEqual([7]);
  });

  it("shows the summary rather than the manual-entry fields", () => {
    // The fields came from a real record, so this is a confirmation, not a
    // blank form to fill in.
    const { result } = renderFlow();
    act(() => result.current.chooseMatch(match()));
    expect(result.current.draft?.notFound).toBeUndefined();
  });

  it("accepts a record with no ISBN", () => {
    // A book found by title genuinely may not have one, and the server reads
    // a blank ISBN as absent rather than as invalid.
    const { result } = renderFlow();
    act(() => result.current.chooseMatch(match({ isbn13: null })));
    expect(result.current.draft?.isbn).toBe("");
  });

  it("does not start an ISBN lookup that would overwrite the draft", async () => {
    // Setting the ISBN would re-run the Open Library lookup and replace the
    // record the reader just picked.
    const { result } = renderFlow();

    act(() => result.current.chooseMatch(match()));

    await waitFor(() => expect(result.current.draft).not.toBeNull());
    expect(api.lastCall("/api/books/lookup")).toBeUndefined();
    expect(result.current.isLookingUp).toBe(false);
  });

  it("is undone by reset", () => {
    const { result } = renderFlow();
    act(() => result.current.chooseMatch(match()));

    act(() => result.current.reset());

    expect(result.current.draft).toBeNull();
    expect(result.current.selectedTagIds).toEqual([]);
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
    await waitFor(() => expect(result.current.location).toBe("Loft box 2"));
  });

  it("sends the shelf with the book", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", { body: makeBook() });
    const { result } = renderHookWithProviders(() => useScanFlow(() => {}));

    act(() => result.current.lookup("9780441013593"));
    await waitFor(() => expect(result.current.draft).not.toBeNull());
    act(() => result.current.setLocation("Kitchen"));
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
    await waitFor(() => expect(result.current.draft).not.toBeNull());
    act(() => result.current.setLocation("Kitchen"));
    act(() => result.current.confirm());

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(localStorage.getItem("lastLocation")).toBeNull();
  });

  it("keeps the shelf across a cancel, which is the whole point", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    const { result } = renderHookWithProviders(() => useScanFlow(() => {}));

    act(() => result.current.setLocation("Kitchen"));
    act(() => result.current.reset());

    await waitFor(() => expect(result.current.location).toBe("Kitchen"));
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
