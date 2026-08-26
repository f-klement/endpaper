/**
 * Tests for src/pages/Home/hooks.ts.
 *
 * Drives the real generated hooks against a stubbed network, so the request
 * shapes and pagination assertions here are the ones the app actually makes.
 */

import { act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  BookSort,
  LendingWillingness,
  OwnershipStatus,
  ReadStatus,
} from "../../../src/api/generated/model";
import {
  PAGE_SIZE,
  useBookSelection,
  useLibrary,
  useUnconfirmedCount,
} from "../../../src/pages/Home/hooks";
import {
  makeBook,
  makeBookPage,
  makeCollection,
  makeTagSet,
  resetIds,
} from "../../factories";
import { mockApi, renderHookWithProviders, type MockApi } from "../../utils";

function renderLibrary(route = "/") {
  return renderHookWithProviders(() => useLibrary(), { route });
}

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/api/books/tags", { body: makeTagSet() });
  api.on("/api/collections", { body: [] });
  api.on(/\/api\/books(\?|$)/, {
    body: makeBookPage([makeBook({ title: "Dune" })]),
  });
});

/** The query string of the most recent books listing request. */
function lastQuery(): URLSearchParams {
  const call = api.lastCall(/\/api\/books\?/) ?? api.lastCall("/api/books");
  return new URL(call!.url, "http://localhost").searchParams;
}

describe("useLibrary", () => {
  it("loads books and tags", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));
    expect(result.current.books[0]!.title).toBe("Dune");
    await waitFor(() => expect(result.current.tags).toHaveLength(3));
  });

  it("reports the filtered total, not the page length", async () => {
    api.on(/\/api\/books\?/, {
      body: makeBookPage([makeBook()], { total: 42 }),
    });
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.total).toBe(42));
  });

  it("requests a bounded page size rather than the whole library", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(lastQuery().get("page_size")).toBe(String(PAGE_SIZE));
  });

  it("surfaces a load failure", async () => {
    api.on(/\/api\/books\?/, { status: 500, body: { detail: "boom" } });
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.error).toBeTruthy());
  });

  it("still returns books when the tag fetch fails", async () => {
    // Losing tags costs the filter panel, not the grid.
    api.on("/api/books/tags", { status: 500, body: { detail: "boom" } });
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));
    expect(result.current.tags).toEqual([]);
  });

  describe("filters", () => {
    it("omits empty values from the query", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      const query = lastQuery();
      expect(query.get("q")).toBeNull();
      expect(query.get("status")).toBeNull();
      expect(query.get("tags")).toBeNull();
    });

    it("sends a search term", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.setQuery("dune"));

      await waitFor(() => expect(lastQuery().get("q")).toBe("dune"));
    });

    it("sends a status filter", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.setStatus(ReadStatus.read));

      await waitFor(() => expect(lastQuery().get("status")).toBe("read"));
    });

    it("sends the chosen sort", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.setSort(BookSort.year_desc));

      await waitFor(() => expect(lastQuery().get("sort")).toBe("year_desc"));
    });

    it("joins several tag ids with commas", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.toggleTag(1));
      act(() => result.current.toggleTag(2));

      await waitFor(() => expect(lastQuery().get("tags")).toBe("1,2"));
    });

    it("toggles a tag off when selected twice", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.toggleTag(1));
      await waitFor(() => expect(result.current.filters.tagIds).toEqual([1]));
      act(() => result.current.toggleTag(1));

      await waitFor(() => expect(result.current.filters.tagIds).toEqual([]));
    });

    it("clears every tag at once", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.toggleTag(1));
      act(() => result.current.toggleTag(2));
      act(() => result.current.clearTags());

      await waitFor(() => expect(result.current.filters.tagIds).toEqual([]));
    });
  });

  describe("pagination", () => {
    it("reports more pages while rows remain", async () => {
      api.on(/\/api\/books\?/, {
        body: makeBookPage([makeBook(), makeBook()], { total: 10 }),
      });
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.hasMore).toBe(true));
    });

    it("reports no more once every row is loaded", async () => {
      api.on(/\/api\/books\?/, {
        body: makeBookPage([makeBook()], { total: 1 }),
      });
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.hasMore).toBe(false);
    });

    it("appends the next page rather than replacing the first", async () => {
      let page = 0;
      api.on(/\/api\/books\?/, () => {
        page += 1;
        return {
          body: makeBookPage([makeBook({ title: `Book ${page}` })], {
            total: 2,
            page,
          }),
        };
      });

      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.books).toHaveLength(1));

      act(() => result.current.loadMore());

      await waitFor(() => expect(result.current.books).toHaveLength(2));
      expect(result.current.books.map((book) => book.title)).toEqual([
        "Book 1",
        "Book 2",
      ]);
    });

    it("asks for the next page number", async () => {
      api.on(/\/api\/books\?/, {
        body: makeBookPage([makeBook()], { total: 5 }),
      });
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.hasMore).toBe(true));

      act(() => result.current.loadMore());

      await waitFor(() => expect(lastQuery().get("page")).toBe("2"));
    });
  });
});

describe("useLibrary ownership filter", () => {
  it("omits the filter by default", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));
    expect(lastQuery().has("ownership")).toBe(false);
  });

  it("sends the chosen ownership", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    act(() => result.current.setOwnership(OwnershipStatus.unknown));

    await waitFor(() => expect(lastQuery().get("ownership")).toBe("unknown"));
  });

  it("counts as an active filter", async () => {
    const { result } = renderLibrary();
    act(() => result.current.setOwnership(OwnershipStatus.owned));
    await waitFor(() =>
      expect(result.current.filters.ownership).toBe(OwnershipStatus.owned),
    );
  });

  describe("seeded from the URL", () => {
    it("starts filtered when the route asks for it", async () => {
      // The link the Goodreads import result offers, and the one the banner
      // uses. It has to survive a full page load, not just an in-app click.
      const { result } = renderLibrary("/?ownership=unknown");
      await waitFor(() =>
        expect(result.current.filters.ownership).toBe(OwnershipStatus.unknown),
      );
      await waitFor(() => expect(lastQuery().get("ownership")).toBe("unknown"));
    });

    it("ignores a value that is not an ownership state", async () => {
      const { result } = renderLibrary("/?ownership=maybe");
      await waitFor(() => expect(result.current.books).toHaveLength(1));
      expect(result.current.filters.ownership).toBeNull();
    });

    it("does not fight a later choice", async () => {
      // Read once as an initial value, not kept in sync: otherwise clicking
      // "Any" would be undone by the URL on the next render.
      const { result } = renderLibrary("/?ownership=unknown");
      await waitFor(() =>
        expect(result.current.filters.ownership).toBe(OwnershipStatus.unknown),
      );

      act(() => result.current.setOwnership(null));

      await waitFor(() => expect(result.current.filters.ownership).toBeNull());
    });
  });
});

describe("useLibrary collection filter", () => {
  it("omits the filter by default", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    expect(lastQuery().has("collection_id")).toBe(false);
    expect(lastQuery().has("unfiled")).toBe(false);
  });

  it("sends the chosen collection", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    act(() => result.current.setCollection(3));

    await waitFor(() => expect(lastQuery().get("collection_id")).toBe("3"));
  });

  it("asks for the unfiled books with their own parameter", async () => {
    // Never both: the API answers 422 to a request naming a collection and the
    // unfiled books at once, so one field has to produce one or the other.
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    act(() => result.current.setCollection("unfiled"));

    await waitFor(() => expect(lastQuery().get("unfiled")).toBe("true"));
    expect(lastQuery().has("collection_id")).toBe(false);
  });

  it("offers the library's collections to the filter", async () => {
    api.on("/api/collections", { body: [makeCollection({ name: "Ebooks" })] });
    const { result } = renderLibrary();

    await waitFor(() => expect(result.current.collections).toHaveLength(1));
  });

  describe("seeded from the URL", () => {
    it("starts on the collection the link names", async () => {
      const { result } = renderLibrary("/?collection=3");
      await waitFor(() => expect(result.current.books).toHaveLength(1));

      expect(lastQuery().get("collection_id")).toBe("3");
    });

    it("starts on the unfiled books", async () => {
      const { result } = renderLibrary("/?collection=unfiled");
      await waitFor(() => expect(result.current.books).toHaveLength(1));

      expect(lastQuery().get("unfiled")).toBe("true");
    });

    it("ignores a value that is neither", async () => {
      const { result } = renderLibrary("/?collection=everything");
      await waitFor(() => expect(result.current.books).toHaveLength(1));

      expect(lastQuery().has("collection_id")).toBe(false);
      expect(lastQuery().has("unfiled")).toBe(false);
    });
  });
});

describe("useLibrary author filter", () => {
  it("omits it until a link asks for one", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    expect(lastQuery().has("author")).toBe(false);
  });

  it("starts on the author a link names", async () => {
    // The key, not the display name: a merge changes what an author is called
    // and a saved link naming the old spelling would show an empty shelf.
    const { result } = renderLibrary("/?author=ursula%20k%20le%20guin");
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    expect(lastQuery().get("author")).toBe("ursula k le guin");
  });

  it("clears back to the whole library", async () => {
    const { result } = renderLibrary("/?author=ursula%20k%20le%20guin");
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    act(() => result.current.setAuthor(null));

    await waitFor(() => expect(lastQuery().has("author")).toBe(false));
  });
});

describe("useLibrary lending and discussion filters", () => {
  it("omits both by default", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));
    expect(lastQuery().has("lending")).toBe(false);
    expect(lastQuery().has("discuss")).toBe(false);
  });

  it("sends the chosen willingness", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    act(() => result.current.setLending(LendingWillingness.happy));

    await waitFor(() => expect(lastQuery().get("lending")).toBe("happy"));
  });

  it("sends the discussion filter only when it is on", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    act(() => result.current.setDiscuss(true));
    await waitFor(() => expect(lastQuery().get("discuss")).toBe("true"));

    act(() => result.current.setDiscuss(false));
    await waitFor(() => expect(lastQuery().has("discuss")).toBe(false));
  });

  describe("seeded from the URL", () => {
    it("starts on a willingness the route asks for", async () => {
      const { result } = renderLibrary("/?lending=never");
      await waitFor(() =>
        expect(result.current.filters.lending).toBe(LendingWillingness.never),
      );
    });

    it("ignores a willingness that is not one of the three", async () => {
      const { result } = renderLibrary("/?lending=sometimes");
      await waitFor(() => expect(result.current.books).toHaveLength(1));
      expect(result.current.filters.lending).toBeNull();
    });

    it("treats a bare ?discuss as on", async () => {
      // What a link somebody typed looks like. Reading it as off would make
      // the link silently do nothing.
      const { result } = renderLibrary("/?discuss");
      await waitFor(() => expect(result.current.filters.discuss).toBe(true));
    });

    it("treats ?discuss=false as off", async () => {
      const { result } = renderLibrary("/?discuss=false");
      await waitFor(() => expect(result.current.books).toHaveLength(1));
      expect(result.current.filters.discuss).toBe(false);
    });
  });
});

describe("useBookSelection", () => {
  function renderSelection() {
    return renderHookWithProviders(() => useBookSelection());
  }

  it("starts inactive, so a tap navigates as usual", () => {
    const { result } = renderSelection();
    expect(result.current.isSelecting).toBe(false);
    expect(result.current.selectedIds).toEqual([]);
  });

  it("toggles a book in and out", () => {
    const { result } = renderSelection();

    act(() => result.current.toggle(3));
    expect(result.current.selectedIds).toEqual([3]);
    expect(result.current.isSelected(3)).toBe(true);

    act(() => result.current.toggle(3));
    expect(result.current.selectedIds).toEqual([]);
  });

  it("never selects the same book twice", () => {
    const { result } = renderSelection();
    act(() => result.current.selectAll([1, 2, 1, 2]));
    expect(result.current.selectedIds).toEqual([1, 2]);
  });

  it("clears without leaving selection mode", () => {
    const { result } = renderSelection();
    act(() => result.current.start());
    act(() => result.current.toggle(1));

    act(() => result.current.clear());

    expect(result.current.selectedIds).toEqual([]);
    expect(result.current.isSelecting).toBe(true);
  });

  it("drops the selection when selection mode ends", () => {
    const { result } = renderSelection();
    act(() => result.current.start());
    act(() => result.current.toggle(1));

    act(() => result.current.stop());

    expect(result.current.isSelecting).toBe(false);
    expect(result.current.selectedIds).toEqual([]);
  });

  describe("applying", () => {
    it("sends the selected ids and the chosen state", async () => {
      api.on("/api/books/bulk", {
        body: { updated: 2, unchanged: 0, skipped: 0 },
      });
      const { result } = renderSelection();
      act(() => result.current.toggle(4));
      act(() => result.current.toggle(9));

      act(() => result.current.apply(OwnershipStatus.owned));

      await waitFor(() =>
        // The same verb as every other bulk action now, not a second endpoint
        // with an identical body.
        expect(api.lastCall("/books/bulk", "POST")?.body).toEqual({
          book_ids: [4, 9],
          action: "set_ownership",
          value: "owned",
        }),
      );
    });

    it("sends nothing when nothing is selected", () => {
      const { result } = renderSelection();
      act(() => result.current.apply(OwnershipStatus.owned));
      expect(api.lastCall("/books/bulk")).toBeUndefined();
    });

    it("empties the selection once the update lands", async () => {
      api.on("/api/books/bulk", {
        body: { updated: 1, unchanged: 0, skipped: 0 },
      });
      const { result } = renderSelection();
      act(() => result.current.toggle(4));

      act(() => result.current.apply(OwnershipStatus.owned));

      await waitFor(() => expect(result.current.selectedIds).toEqual([]));
    });

    it("reports what happened", async () => {
      api.on("/api/books/bulk", {
        body: { updated: 1, unchanged: 2, skipped: 3 },
      });
      const { result } = renderSelection();
      act(() => result.current.toggle(4));

      act(() => result.current.apply(OwnershipStatus.owned));

      await waitFor(() =>
        expect(result.current.result).toEqual({
          updated: 1,
          unchanged: 2,
          skipped: 3,
        }),
      );
    });

    it("keeps the selection when the update fails", async () => {
      // Clearing it would make the reader tick every book again.
      api.on("/api/books/bulk", {
        status: 422,
        body: { detail: "Too many" },
      });
      const { result } = renderSelection();
      act(() => result.current.toggle(4));

      act(() => result.current.apply(OwnershipStatus.owned));

      await waitFor(() => expect(result.current.error).toBeTruthy());
      expect(result.current.selectedIds).toEqual([4]);
    });
  });
});

describe("useUnconfirmedCount", () => {
  it("asks only for the total, not for the books", async () => {
    api.on(/ownership=unknown/, { body: makeBookPage([], { total: 41 }) });
    const { result } = renderHookWithProviders(() => useUnconfirmedCount());

    await waitFor(() => expect(result.current).toBe(41));

    const query = new URL(
      api.lastCall(/ownership=unknown/)!.url,
      "http://localhost",
    ).searchParams;
    expect(query.get("page_size")).toBe("1");
  });

  it("reports zero before the answer arrives", () => {
    api.on(/ownership=unknown/, { body: makeBookPage([], { total: 5 }) });
    const { result } = renderHookWithProviders(() => useUnconfirmedCount());
    // Zero rather than undefined, so the banner is simply absent rather than
    // flashing on with a blank number.
    expect(result.current).toBe(0);
  });
});
