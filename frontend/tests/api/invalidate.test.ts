/**
 * @vitest-environment node
 *
 * Tests for src/api/invalidate.ts: which cached queries a write drops.
 *
 * No DOM: every assertion is about a `QueryClient` and a set of keys, so this
 * file skips the 2s jsdom build the suite otherwise pays per file.
 */

import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import * as auth from "../../src/api/generated/endpoints/auth/auth";
import * as backup from "../../src/api/generated/endpoints/backup/backup";
import * as books from "../../src/api/generated/endpoints/books/books";
import * as collections from "../../src/api/generated/endpoints/collections/collections";
import * as covers from "../../src/api/generated/endpoints/covers/covers";
import * as loans from "../../src/api/generated/endpoints/loans/loans";
import * as settings from "../../src/api/generated/endpoints/settings/settings";
import * as stats from "../../src/api/generated/endpoints/stats/stats";
import * as system from "../../src/api/generated/endpoints/system/system";
import * as users from "../../src/api/generated/endpoints/users/users";
import { invalidateWith, isCatalogueQuery } from "../../src/api/invalidate";

/**
 * Every generated endpoint module, found rather than listed.
 *
 * A hand-written list of modules cannot see a new module, and new modules are
 * how endpoints have actually arrived here: five of the eleven modules
 * (`collections`, `system`, `backup`, `covers`, `imports`) were added after the
 * initial commit. A twelfth would have appeared in neither side of the
 * inventory assertion, so the equality would still have held and nobody would
 * have been made to place its keys. `catalogue()` is an allowlist, so they
 * would have defaulted to excluded: a new library-wide list going stale under
 * every write, silently.
 *
 * The named imports above stay, because building `KEYS` needs the getters
 * themselves and a glob gives back `unknown`.
 */
const MODULES = import.meta.glob("../../src/api/generated/endpoints/**/*.ts", {
  eager: true,
}) as Record<string, Record<string, unknown>>;

/** A key for every query the app can hold, named by the getter that built it. */
const KEYS: Record<string, readonly unknown[]> = {
  listBooks: books.getListBooksQueryKey(),
  listBooksInfinite: books.getListBooksInfiniteQueryKey(),
  getBook: books.getGetBookQueryKey(7),
  listCopies: books.getListCopiesQueryKey(7),
  getNotes: books.getGetNotesQueryKey(7),
  getCustomFields: books.getGetCustomFieldsQueryKey(7),
  listCustomFields: books.getListCustomFieldsQueryKey(),
  getQuotes: books.getGetQuotesQueryKey(7),
  listProgress: books.getListProgressQueryKey(7),
  enrichmentCandidates: books.getEnrichmentCandidatesQueryKey(7),
  listAuthors: books.getListAuthorsQueryKey(),
  listAuthorSuggestions: books.getListAuthorSuggestionsQueryKey(),
  listSeries: books.getListSeriesQueryKey(),
  listLocations: books.getListLocationsQueryKey(),
  listDuplicates: books.getListDuplicatesQueryKey(),
  listTags: books.getListTagsQueryKey(),
  listTrash: books.getListTrashQueryKey(),
  listQuotes: books.getListQuotesQueryKey(),
  exportBooks: books.getExportBooksQueryKey(),
  lookupIsbn: books.getLookupIsbnQueryKey({ isbn: "9780441013593" }),
  searchBooks: books.getSearchBooksQueryKey({ q: "dune" }),
  listCollections: collections.getListCollectionsQueryKey(),
  listLoans: loans.getListLoansQueryKey(),
  getStats: stats.getGetStatsQueryKey(),
  getSettings: settings.getGetSettingsQueryKey(),
  getFeatureFlags: settings.getGetFeatureFlagsQueryKey(),
  getLoginImage: settings.getGetLoginImageQueryKey(),
  listUsers: users.getListUsersQueryKey(),
  getMyAppearance: users.getGetMyAppearanceQueryKey(),
  listTestAccounts: users.getListTestAccountsQueryKey(),
  authConfig: auth.getAuthConfigQueryKey(),
  me: auth.getMeQueryKey(),
  downloadBackup: backup.getDownloadBackupQueryKey(),
  getCover: covers.getGetCoverQueryKey(7, "jpg"),
  getLoginBackground: covers.getGetLoginBackgroundQueryKey("jpg"),
  healthz: system.getHealthzQueryKey(),
};

/**
 * A client holding one entry per key above.
 *
 * `setQueryData` rather than a fetch: what is under test is which entries a
 * filter selects, and an entry with data in it is selected the same way a
 * fetched one is.
 */
function populated(): QueryClient {
  const client = new QueryClient();
  for (const key of Object.values(KEYS)) client.setQueryData(key, {});
  return client;
}

let client: QueryClient;
beforeEach(() => {
  client = new QueryClient();
});

/** Wrap one key as the `Query` object the predicate is handed. */
function query(key: readonly unknown[]) {
  client.setQueryData(key, {});
  return client.getQueryCache().find({ queryKey: key, exact: true })!;
}

/** Which of the named keys a filter selected, as names rather than keys. */
function invalidatedBy(action: (client: QueryClient) => void): string[] {
  const client = populated();
  action(client);
  const stale = new Set(
    client
      .getQueryCache()
      .getAll()
      .filter((query) => query.state.isInvalidated)
      .map((query) => JSON.stringify(query.queryKey)),
  );
  return Object.entries(KEYS)
    .filter(([, key]) => stale.has(JSON.stringify(key)))
    .map(([name]) => name)
    .sort();
}

describe("the inventory is complete", () => {
  it("names every query key the generated client can build", () => {
    // A new endpoint arriving unclassified is the failure this exists for.
    // `catalogue()` is written as "everything under /api/books except two
    // outward lookups", so a third outward lookup would silently join every
    // write in the app and start re-spending somebody's quota. The only way
    // that is caught is by someone being made to place it.
    const generated = Object.values(MODULES).flatMap((module) =>
      Object.keys(module).filter(
        (name) => name.startsWith("get") && name.endsWith("QueryKey"),
      ),
    );

    const named = Object.keys(KEYS).map(
      (name) => `get${name[0]!.toUpperCase()}${name.slice(1)}QueryKey`,
    );

    expect(generated.sort()).toEqual(named.sort());
  });

  it("is reading the generated tree at all", () => {
    // A glob that matched nothing would make the assertion above pass for
    // ever, by comparing an empty list against an empty list. Measured
    // 2026-08-27: 11 modules, 36 getters.
    expect(Object.keys(MODULES).length).toBeGreaterThan(5);
    expect(Object.keys(KEYS).length).toBe(36);
  });
});

describe("the catalogue is everything derived from the books table", () => {
  it("holds the library-wide lists and every book's own record", () => {
    expect(
      invalidatedBy((client) => invalidateWith(client).catalogue()),
    ).toEqual([
      "getBook",
      "getStats",
      "listAuthorSuggestions",
      "listAuthors",
      "listBooks",
      "listBooksInfinite",
      "listCollections",
      "listCopies",
      "listDuplicates",
      "listLoans",
      "listLocations",
      "listQuotes",
      "listSeries",
      "listTags",
      "listTrash",
    ]);
  });

  it("leaves the two outward lookups alone", () => {
    // The point of the whole module. `searchBooks` is a billed Google Books
    // call carrying `staleTime: 5 * 60_000` precisely so that going back to
    // edit a draft does not re-spend the quota, and an invalidate ignores
    // staleTime. Adding a book used to refetch it.
    expect(isCatalogueQuery(query(KEYS.lookupIsbn!))).toBe(false);
    expect(isCatalogueQuery(query(KEYS.searchBooks!))).toBe(false);
  });

  it("leaves a book's children to the hooks that write them", () => {
    // Notes, quotes, progress, enrichment candidates and the custom field
    // values change only through their own mutations, each of which
    // invalidates its own key.
    for (const name of [
      "getNotes",
      "getQuotes",
      "listProgress",
      "enrichmentCandidates",
      "getCustomFields",
    ]) {
      expect(isCatalogueQuery(query(KEYS[name]!)), name).toBe(false);
    }
  });

  it("leaves the custom field definitions alone", () => {
    // The one library-wide list under `/api/books` that is **not** derived
    // from the books table. Adding, deleting or editing a book changes nothing
    // about which fields the household has defined, so it does not belong to
    // any catalogue write; it changes only when a definition is written, and
    // `useCustomFields` invalidates it there. `TagOut` is the contrast and is
    // in `LIBRARY_WIDE` precisely because it carries a `book_count`, which
    // `CustomFieldOut` deliberately does not.
    expect(isCatalogueQuery(query(KEYS["listCustomFields"]!))).toBe(false);
  });

  it("leaves the accounts and the settings alone", () => {
    for (const name of [
      "getSettings",
      "getFeatureFlags",
      "listUsers",
      "getMyAppearance",
      "listTestAccounts",
      "authConfig",
      "me",
      "healthz",
    ]) {
      expect(isCatalogueQuery(query(KEYS[name]!)), name).toBe(false);
    }
  });
});

describe("listings covers both spellings of the library list", () => {
  it("matches the grid as well as the paginated list", () => {
    // The defect this module was built for. The grid is `useListBooksInfinite`,
    // whose key is `["infinite", "/api/books", params]`, and react-query
    // matches element by element, so the hand-written `["/api/books"]` at four
    // call sites compared "/api/books" against "infinite" and missed it.
    expect(
      invalidatedBy((client) => invalidateWith(client).listings()),
    ).toEqual(["listBooks", "listBooksInfinite"]);
  });

  it("is what a hand-written key would have missed", () => {
    // Stated as an assertion rather than as prose, so nobody re-introduces the
    // shorter spelling believing it equivalent.
    const missed = invalidatedBy((client) =>
      client.invalidateQueries({ queryKey: ["/api/books"] }),
    );
    expect(missed).toEqual(["listBooks"]);
  });
});

describe("book covers one book and the lists that show it", () => {
  it("takes the record, its copies, the listings, the loans and the stats", () => {
    expect(invalidatedBy((client) => invalidateWith(client).book(7))).toEqual([
      "getBook",
      "getStats",
      "listBooks",
      "listBooksInfinite",
      "listCopies",
      "listLoans",
    ]);
  });

  it("leaves another book's record alone", () => {
    const client = populated();
    const other = books.getGetBookQueryKey(8);
    client.setQueryData(other, {});
    invalidateWith(client).book(7);
    expect(client.getQueryState(other)?.isInvalidated).toBe(false);
  });
});

describe("everything is the whole cache", () => {
  it("spares nothing, including the session", () => {
    expect(
      invalidatedBy((client) => invalidateWith(client).everything()),
    ).toEqual(Object.keys(KEYS).sort());
  });
});
