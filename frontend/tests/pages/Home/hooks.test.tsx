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
  useColumnChoice,
  useLibrary,
  useUnconfirmedCount,
  useViewChoice,
} from "../../../src/pages/Home/hooks";
import {
  DEFAULT_COLUMNS,
  libraryColumnsPreference,
} from "../../../src/lib/libraryColumns";
import { libraryViewPreference } from "../../../src/lib/libraryView";
import {
  makeBook,
  makeBookPage,
  makeCollection,
  makeTagSet,
  resetIds,
} from "../../factories";
import {
  mockApi,
  renderHookWithProviders,
  type MockApi,
  type StubResponse,
} from "../../utils";

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

const HOOKS_PATH = "../../../src/pages/Home/hooks.ts";
const HOOKS_SOURCE = import.meta.glob("../../../src/pages/Home/hooks.ts", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

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

      act(() => result.current.update({ query: "dune" }));

      await waitFor(() => expect(lastQuery().get("q")).toBe("dune"));
    });

    it("sends a status filter", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.update({ status: ReadStatus.read }));

      await waitFor(() => expect(lastQuery().get("status")).toBe("read"));
    });

    it("sends the chosen sort", async () => {
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.update({ sort: BookSort.year_desc }));

      await waitFor(() => expect(lastQuery().get("sort")).toBe("year_desc"));
    });

    it("joins several tag ids with commas", async () => {
      // Which ids a click puts in the list is `toggledFilter`'s, tested
      // without a query client in `tests/lib/bookFilters.test.ts`. What this
      // covers is the rest of the pipe: state, parameters, request.
      const { result } = renderLibrary();
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => result.current.update({ tagIds: [1, 2] }));

      await waitFor(() => expect(lastQuery().get("tags")).toBe("1,2"));
    });
  });

  /**
   * The filter set has one writer, and the door is offered rather than used.
   *
   * Five writers once grew back around `update`, one per facet: 32 members
   * against the 27 here without them. Every one of them worked, so no test saw
   * them. A second door is a spelling rather than a behaviour, which is why
   * this reads the source.
   *
   * **Two assertions on the writing, because a member that writes through
   * `update` regrows
   * this interface exactly as those five did** and leaves the setter count at
   * one. What such a member cannot do is write without naming the door.
   *
   * Its blind spots, stated rather than left to be discovered: three spellings
   * in one file. A second filter set is caught where it is written
   * `useState<BookFilters>` and not where the annotation is left off, and a
   * setter or a door passed on under another name is caught by none of them:
   * measured, `const door = update;` behind a member passes all three.
   *
   * **All three read the raw source, comments included**, so a docstring in
   * that file may not spell `setFilters(` or `update(`, which is the spelling
   * its own door goes by elsewhere. Stripping comments first was refused: a
   * stripper that took code for a comment would drop a real call and weaken a
   * count in silence, where this fails loudly and says which arm.
   */
  describe("the filter set has one writer", () => {
    function source(): string {
      const raw = HOOKS_SOURCE[HOOKS_PATH] ?? "";
      // A glob that matched nothing would make both assertions pass forever.
      expect(raw.length).toBeGreaterThan(1000);
      return raw;
    }

    it("holds the filters in one piece of state", () => {
      expect(source().split("useState<BookFilters>").length - 1).toBe(1);
    });

    it("writes them in one place, which is update", () => {
      expect(source().split("setFilters(").length - 1).toBe(1);
    });

    it("offers that door rather than calling it from inside", () => {
      // `result.updated` in the bulk verbs is the only other `update` in the
      // file, and the `(` excludes it. A member spelled
      // `clearTags: () => update({ tagIds: [] })` is what this catches and the
      // assertion above does not.
      expect(source().split(/\bupdate\(/).length - 1).toBe(0);
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

    act(() => result.current.update({ ownership: OwnershipStatus.unknown }));

    await waitFor(() => expect(lastQuery().get("ownership")).toBe("unknown"));
  });

  it("counts as an active filter", async () => {
    const { result } = renderLibrary();
    act(() => result.current.update({ ownership: OwnershipStatus.owned }));
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

      act(() => result.current.update({ ownership: null }));

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

    act(() => result.current.update({ collection: 3 }));

    await waitFor(() => expect(lastQuery().get("collection_id")).toBe("3"));
  });

  it("asks for the unfiled books with their own parameter", async () => {
    // Never both: the API answers 400 to a request naming a collection and the
    // unfiled books at once, so one field has to produce one or the other.
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    act(() => result.current.update({ collection: "unfiled" }));

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

    act(() => result.current.update({ author: null }));

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

    act(() => result.current.update({ lending: LendingWillingness.happy }));

    await waitFor(() => expect(lastQuery().get("lending")).toBe("happy"));
  });

  it("sends the discussion filter only when it is on", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    act(() => result.current.update({ discuss: true }));
    await waitFor(() => expect(lastQuery().get("discuss")).toBe("true"));

    act(() => result.current.update({ discuss: false }));
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

const BASE_FLAGS = {
  google_books_ready: false,
  goodreads_lookup_enabled: false,
  default_locale: "en",
};

function inLibraryMode(on: boolean) {
  api.on("/api/settings/features", {
    body: { ...BASE_FLAGS, library_mode: on },
  });
}

/**
 * Hold the flags request open, and return the function that answers it.
 *
 * The window between the first paint and that answer is the one where the mode
 * is unknown, and it is the only way to reach it: every other test here has
 * the flags answering as fast as the books do.
 */
function heldFlags(): (libraryMode: boolean) => void {
  let release!: (libraryMode: boolean) => void;
  const answered = new Promise<StubResponse>((resolve) => {
    release = (libraryMode) =>
      resolve({ body: { ...BASE_FLAGS, library_mode: libraryMode } });
  });
  api.on("/api/settings/features", () => answered);
  return release;
}
/**
 * The remembered choices, which are no longer members of the library hook.
 *
 * The mode comes from `library_mode` on the feature flags, which is fetched, so
 * every assertion here waits for it rather than reading the first render.
 *
 * **What a test waits on is the cataloguer's own column, not a mode.** There is
 * no `mode` member to wait on any more and there should not be: it had no reader
 * in the application at all, only the assertions in this file that used it as a
 * way to know the flags had landed. `available` containing a call number is that
 * signal and is strictly better, because household reads the same before the
 * flags answer and after they answer false, so waiting for `"household"` passed
 * on the first render and landed inside the window where a write is refused.
 * Only an answer produces the cataloguer's set.
 *
 * **The keys are named through the preference rather than spelled again.** A
 * test at a distance from the module that owns a key used to restate the string,
 * so renaming one turned the assertions green while every browser holding it
 * reset. The literals live in `tests/lib/preference.test.ts`, which exists to say
 * they are a promise to browsers that already hold them.
 */
const HOUSEHOLD_VIEW_KEY = libraryViewPreference.keyFor("household");
const CATALOGUER_VIEW_KEY = libraryViewPreference.keyFor("cataloguer");
const HOUSEHOLD_COLUMNS_KEY = libraryColumnsPreference.keyFor("household");
const CATALOGUER_COLUMNS_KEY = libraryColumnsPreference.keyFor("cataloguer");

/** Both choices at once, so one render can watch the view and the column set. */
function renderChoices() {
  return renderHookWithProviders(() => ({
    view: useViewChoice(),
    columns: useColumnChoice(),
  }));
}

describe("useColumnChoice", () => {
  it("gives a household its own table and none of the cataloguer's columns", async () => {
    inLibraryMode(false);
    const { result } = renderChoices();

    await waitFor(() => expect(result.current.columns.canChange).toBe(true));
    expect(result.current.columns.columns).toEqual([
      ...DEFAULT_COLUMNS.household,
    ]);
    expect(result.current.columns.available).not.toContain("callNumber");
  });

  it("offers the cataloguer's set in library mode", async () => {
    inLibraryMode(true);
    const { result } = renderChoices();

    await waitFor(() =>
      expect(result.current.columns.available).toContain("callNumber"),
    );
    expect(result.current.columns.columns).toEqual([
      ...DEFAULT_COLUMNS.cataloguer,
    ]);
    expect(result.current.columns.available).toContain("classification");
  });

  it("falls back to the household set when the flags never answer", async () => {
    // The flags query is `retry: false` and the shell renders regardless, so a
    // failure here has to mean the table every existing library already has.
    // Asserted on the set a reader sees rather than on a mode: this test used
    // to assert the mode and nothing else, so it was the one arm here with no
    // observable a reader shares.
    api.on("/api/settings/features", { status: 500, body: {} });
    const { result } = renderChoices();

    await waitFor(() => expect(result.current.columns.canChange).toBe(true));
    expect(result.current.columns.columns).toEqual([
      ...DEFAULT_COLUMNS.household,
    ]);
    expect(result.current.columns.available).not.toContain("callNumber");
  });

  it("keeps a household's choice through a mode switch in both directions", async () => {
    // Two storage keys, so neither mode's choice is ever a merge of the other's.
    inLibraryMode(false);
    const household = renderChoices();
    await waitFor(() =>
      expect(household.result.current.columns.canChange).toBe(true),
    );

    act(() => household.result.current.columns.toggle("price"));
    const chosen = [...household.result.current.columns.columns];
    expect(chosen).not.toContain("price");
    household.unmount();

    inLibraryMode(true);
    const cataloguer = renderChoices();
    await waitFor(() =>
      expect(cataloguer.result.current.columns.available).toContain(
        "callNumber",
      ),
    );
    expect(cataloguer.result.current.columns.columns).toEqual([
      ...DEFAULT_COLUMNS.cataloguer,
    ]);
    act(() => cataloguer.result.current.columns.toggle("classification"));
    cataloguer.unmount();

    inLibraryMode(false);
    const back = renderChoices();
    await waitFor(() =>
      expect(back.result.current.columns.canChange).toBe(true),
    );
    expect(back.result.current.columns.columns).toEqual(chosen);
  });

  it("hands the choice back and takes it away again", async () => {
    inLibraryMode(false);
    const { result } = renderChoices();
    await waitFor(() => expect(result.current.columns.canChange).toBe(true));

    expect(result.current.columns.isDefault).toBe(true);
    act(() => result.current.columns.toggle("price"));
    expect(result.current.columns.isDefault).toBe(false);

    act(() => result.current.columns.reset());
    expect(result.current.columns.columns).toEqual([
      ...DEFAULT_COLUMNS.household,
    ]);
    expect(result.current.columns.isDefault).toBe(true);
  });

  it("resets by writing the default, which is what clears the key", async () => {
    // Resetting and writing the set the mode starts with were two exported
    // names for one operation, because the column preference clears its key on
    // the default. This is the arm that says they are still the same thing.
    inLibraryMode(false);
    const { result } = renderChoices();
    await waitFor(() => expect(result.current.columns.canChange).toBe(true));

    act(() => result.current.columns.toggle("price"));
    expect(localStorage.getItem(HOUSEHOLD_COLUMNS_KEY)).not.toBeNull();

    act(() => result.current.columns.reset());
    expect(localStorage.getItem(HOUSEHOLD_COLUMNS_KEY)).toBeNull();
  });
});

/**
 * The view, per mode.
 *
 * Same shape as the column set above and for the same reason: the mode comes
 * from a fetched flag, so every assertion waits for it rather than reading the
 * first render. A `useState` initialiser would read storage before the flag
 * arrives and hand a cataloguer the household's view for the session.
 */
describe("useViewChoice", () => {
  it("opens a household on the covers", async () => {
    inLibraryMode(false);
    const { result } = renderChoices();

    await waitFor(() => expect(result.current.view.canSet).toBe(true));
    expect(result.current.view.value).toBe("grid");
  });

  it("opens library mode on the dense rows", async () => {
    // The first user story: a counter sees records without setting anything.
    inLibraryMode(true);
    const { result } = renderChoices();

    await waitFor(() =>
      expect(result.current.columns.available).toContain("callNumber"),
    );
    expect(result.current.view.value).toBe("list");
  });

  it("opens library mode on the dense rows despite the household's choice", async () => {
    // The flag arrives late, so the household's key is the one already read
    // when the mode flips. Reading it once into state is how a cataloguer ends
    // up on a table somebody else picked.
    localStorage.setItem(HOUSEHOLD_VIEW_KEY, "table");
    inLibraryMode(true);
    const { result } = renderChoices();

    await waitFor(() =>
      expect(result.current.columns.available).toContain("callNumber"),
    );
    expect(result.current.view.value).toBe("list");
  });

  it("remembers a change made in library mode", async () => {
    // The second user story. A fresh render is the reload: nothing carries
    // between them but storage.
    inLibraryMode(true);
    const first = renderChoices();
    await waitFor(() =>
      expect(first.result.current.columns.available).toContain("callNumber"),
    );

    act(() => first.result.current.view.set("table"));
    expect(first.result.current.view.value).toBe("table");
    first.unmount();

    const second = renderChoices();
    await waitFor(() =>
      expect(second.result.current.columns.available).toContain("callNumber"),
    );
    expect(second.result.current.view.value).toBe("table");
  });

  it("keeps a household's view through a mode switch in both directions", async () => {
    // The property this item exists to protect. Two storage keys, so neither
    // mode's choice is ever a merge of the other's.
    inLibraryMode(false);
    const household = renderChoices();
    await waitFor(() =>
      expect(household.result.current.view.canSet).toBe(true),
    );

    act(() => household.result.current.view.set("table"));
    expect(household.result.current.view.value).toBe("table");
    household.unmount();

    inLibraryMode(true);
    const cataloguer = renderChoices();
    await waitFor(() =>
      expect(cataloguer.result.current.columns.available).toContain(
        "callNumber",
      ),
    );
    expect(cataloguer.result.current.view.value).toBe("list");
    act(() => cataloguer.result.current.view.set("grid"));
    cataloguer.unmount();

    inLibraryMode(false);
    const back = renderChoices();
    await waitFor(() => expect(back.result.current.view.canSet).toBe(true));
    expect(back.result.current.view.value).toBe("table");
  });

  it("falls back to the household's view when the flags never answer", async () => {
    // A failure is a settled answer, and the documented one.
    localStorage.setItem(HOUSEHOLD_VIEW_KEY, "table");
    api.on("/api/settings/features", { status: 500, body: {} });
    const { result } = renderChoices();

    await waitFor(() => expect(result.current.view.canSet).toBe(true));
    expect(result.current.view.value).toBe("table");
    expect(result.current.columns.available).not.toContain("callNumber");
  });
});

/**
 * Writing a preference before the mode is known.
 *
 * `catalogueMode(undefined)` is household, which is the right answer for
 * reading and is not an answer at all for writing: a cataloguer's pick would
 * be filed under the household's key, overwriting the choice the two keys
 * exist to protect and leaving the cataloguer's key empty. A wrong read costs
 * one paint. This is permanent and silent, so it is refused.
 *
 * **The refusal is the scope being absent, not a flag beside it.** The gate
 * used to be a wrapper inside the library hook that closed over its own
 * settledness; it is now `useScopedPreference` being handed `undefined`, so a
 * fourth preference keyed on the mode is refused in that window by
 * construction rather than by remembering.
 */
describe("before the mode is known", () => {
  it("refuses a view chosen in the window, and keeps the household's", async () => {
    localStorage.setItem(HOUSEHOLD_VIEW_KEY, "table");
    const release = heldFlags();
    const { result } = renderChoices();
    await waitFor(() => expect(result.current.view.value).toBe("table"));
    expect(result.current.view.canSet).toBe(false);

    // "grid" rather than "list", so the assertion after the release can tell a
    // refused pick from the cataloguer's default arriving.
    act(() => result.current.view.set("grid"));
    expect(localStorage.getItem(HOUSEHOLD_VIEW_KEY)).toBe("table");

    await act(async () => release(true));
    await waitFor(() =>
      expect(result.current.columns.available).toContain("callNumber"),
    );

    expect(localStorage.getItem(HOUSEHOLD_VIEW_KEY)).toBe("table");
    expect(localStorage.getItem(CATALOGUER_VIEW_KEY)).toBeNull();
    expect(result.current.view.value).toBe("list");
  });

  it("refuses a column toggled in the window", async () => {
    // The same hole through the same scope, and it shipped before the view had
    // it. One gate covers both.
    const release = heldFlags();
    const { result } = renderChoices();
    await waitFor(() => expect(result.current.columns.canChange).toBe(false));

    act(() => result.current.columns.toggle("price"));
    expect(localStorage.getItem(HOUSEHOLD_COLUMNS_KEY)).toBeNull();

    await act(async () => release(true));
    await waitFor(() =>
      expect(result.current.columns.available).toContain("callNumber"),
    );
    expect(localStorage.getItem(HOUSEHOLD_COLUMNS_KEY)).toBeNull();
    expect(localStorage.getItem(CATALOGUER_COLUMNS_KEY)).toBeNull();
  });

  it("refuses a reset in the window, which would clear the wrong key", async () => {
    // Of the writers this is the one whose damage needs no second step: it
    // deletes a set somebody chose.
    localStorage.setItem(HOUSEHOLD_COLUMNS_KEY, "title,author");
    const release = heldFlags();
    const { result } = renderChoices();
    await waitFor(() => expect(result.current.columns.canChange).toBe(false));

    act(() => result.current.columns.reset());
    expect(localStorage.getItem(HOUSEHOLD_COLUMNS_KEY)).toBe("title,author");

    await act(async () => release(false));
    await waitFor(() => expect(result.current.columns.canChange).toBe(true));
    expect(localStorage.getItem(HOUSEHOLD_COLUMNS_KEY)).toBe("title,author");
  });

  it("opens the gate the moment the flags answer, in either mode", async () => {
    const release = heldFlags();
    const { result } = renderChoices();
    await waitFor(() => expect(result.current.view.canSet).toBe(false));

    await act(async () => release(true));
    await waitFor(() => expect(result.current.view.canSet).toBe(true));

    act(() => result.current.view.set("grid"));
    expect(localStorage.getItem(CATALOGUER_VIEW_KEY)).toBe("grid");
  });

  it("opens the gate on a failure too, rather than locking the controls", async () => {
    // **What the gate must not refuse.** A failure is a settled answer and the
    // documented one: household, the mode every existing library already had.
    // Reading "no flags" as "not ready" would leave a library whose flags
    // endpoint is down unable to change its view at all, for the whole
    // session, with the controls greyed and nothing saying why.
    api.on("/api/settings/features", { status: 500, body: {} });
    const { result } = renderChoices();

    await waitFor(() => expect(result.current.view.canSet).toBe(true));

    act(() => result.current.view.set("list"));
    expect(localStorage.getItem(HOUSEHOLD_VIEW_KEY)).toBe("list");
  });
});

/**
 * What the counter used to buy, asserted as a property rather than a mechanism.
 *
 * A write did not tell a reader, so the library hook held a counter it bumped
 * after every write to make its own next render read storage again. That only
 * ever worked inside one hook instance: a second reader of the same preference
 * elsewhere on the page went on drawing the old value until something else
 * redrew it. These are the two arms the counter could not pass.
 */
describe("a write reaches every reader", () => {
  it("reaches a reader that did not make it", async () => {
    inLibraryMode(false);
    const writer = renderChoices();
    const reader = renderChoices();
    await waitFor(() => expect(writer.result.current.view.canSet).toBe(true));
    await waitFor(() => expect(reader.result.current.view.value).toBe("grid"));

    act(() => writer.result.current.view.set("table"));

    expect(reader.result.current.view.value).toBe("table");
  });

  it("leaves an untouched preference at the value it already held", async () => {
    // One listener set for every preference, so a write to the view wakes the
    // column reader too. That is free only because a snapshot is the same value
    // until its own stored string changes, which is what this asserts: the
    // identity, not the contents.
    inLibraryMode(false);
    const { result } = renderChoices();
    await waitFor(() => expect(result.current.view.canSet).toBe(true));

    const before = result.current.columns.columns;
    act(() => result.current.view.set("table"));

    expect(result.current.columns.columns).toBe(before);
  });
});

/**
 * The library hook returns the library and nothing a browser remembered.
 *
 * **Pinned as a set rather than counted**, so a member added to it fails by
 * name and whoever reads the failure is told which one arrived. Every name here
 * is a request or something derived from one. A remembered choice does not
 * belong in this interface however convenient it is: ten of them grew here
 * once, the page and two panels paid a prop each, and every one of them worked,
 * so no other test saw them. They live behind `useViewChoice`,
 * `useColumnChoice` and `useSavedSearches`, which is where a sixth goes too.
 */
describe("useLibrary returns the library and nothing a browser remembered", () => {
  it("offers exactly the members that are requests or derived from one", async () => {
    const { result } = renderLibrary();
    await waitFor(() => expect(result.current.books).toHaveLength(1));

    expect(Object.keys(result.current).sort()).toEqual([
      "books",
      "classifications",
      "collections",
      "error",
      "filters",
      "hasMore",
      "isLoading",
      "isLoadingMore",
      "isStale",
      "loadMore",
      "locations",
      "refetch",
      "tags",
      "total",
      "update",
    ]);
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
        status: 400,
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
