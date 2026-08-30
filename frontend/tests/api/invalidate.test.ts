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
import * as publicCatalogue from "../../src/api/generated/endpoints/public/public";
import * as settings from "../../src/api/generated/endpoints/settings/settings";
import * as stats from "../../src/api/generated/endpoints/stats/stats";
import * as system from "../../src/api/generated/endpoints/system/system";
import * as users from "../../src/api/generated/endpoints/users/users";
import { Locale } from "../../src/api/generated/model";
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
  listClassifications: books.getListClassificationsQueryKey(),
  listTrash: books.getListTrashQueryKey(),
  listQuotes: books.getListQuotesQueryKey(),
  exportBooks: books.getExportBooksQueryKey(),
  lookupIsbn: books.getLookupIsbnQueryKey({ isbn: "9780441013593" }),
  searchBooks: books.getSearchBooksQueryKey({ q: "dune" }),
  authorAuthority: books.getAuthorAuthorityQueryKey({
    author: "Ursula K. Le Guin",
  }),
  authorWikipedia: books.getAuthorWikipediaQueryKey({ lang: Locale.en }),
  listCollections: collections.getListCollectionsQueryKey(),
  // The published catalogue, and the **first three keys in this file with no
  // session behind them**. They are deliberately not part of any write: see
  // "leaves the published catalogue to its own staleness rule" below.
  listPublicBooks: publicCatalogue.getListPublicBooksQueryKey(),
  listPublicBooksInfinite: publicCatalogue.getListPublicBooksInfiniteQueryKey(),
  getPublicBook: publicCatalogue.getGetPublicBookQueryKey(7),
  listLoans: loans.getListLoansQueryKey(),
  listOverdue: loans.getListOverdueQueryKey(),
  myOverdue: loans.getMyOverdueQueryKey(),
  getStats: stats.getGetStatsQueryKey(),
  getSettings: settings.getGetSettingsQueryKey(),
  getFeatureFlags: settings.getGetFeatureFlagsQueryKey(),
  getLoginImage: settings.getGetLoginImageQueryKey(),
  getSenderHealth: settings.getGetSenderHealthQueryKey(),
  listUsers: users.getListUsersQueryKey(),
  getMyAppearance: users.getGetMyAppearanceQueryKey(),
  getMyEmail: users.getGetMyEmailQueryKey(),
  listEmails: users.getListEmailsQueryKey(),
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
    // ever, by comparing an empty list against an empty list. Recounted
    // 2026-08-28 after four features landed together: 12 modules, 45 getters.
    // The count moves whenever an endpoint is added, and that is the point: it
    // is the second half of the tripwire, so a glob that quietly stopped
    // matching cannot hide behind a KEYS list that also stopped growing.
    //
    // Six arrived and five were anticipated, which is the useful part. Every
    // seat that wave derived the target as 44, from 39 plus an address pair, a
    // public pair and one author lookup. It is 45, because adding
    // `list_public_books` to orval's `operations` generates an INFINITE query
    // getter beside the plain one: a config line meant to fix a paging bug
    // produced a sixth key nobody had counted. Derive this number from the
    // tree rather than from an expected delta.
    //
    // 47 on 2026-08-30, counted the way that sentence asks rather than as 46
    // plus one: `grep -rhoE "export const get[A-Za-z]+QueryKey"
    // src/api/generated/endpoints/ | sort -u | wc -l`. The classification facet
    // list is the arrival, and it generated exactly one getter, which is the
    // case the paragraph above warns is not guaranteed.
    expect(Object.keys(MODULES).length).toBeGreaterThan(5);
    expect(Object.keys(KEYS).length).toBe(47);
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
      // Every facet carries a book_count, and enrichment can add a heading the
      // library has never held, so a write moves this list the way it moves the
      // tag list beside it.
      "listClassifications",
      "listCollections",
      "listCopies",
      "listDuplicates",
      "listLoans",
      "listLocations",
      // The overdue page's list (#102), beside the count it is the detail of.
      "listOverdue",
      "listQuotes",
      "listSeries",
      "listTags",
      "listTrash",
      // The in app overdue banner. A count over loans and books, so trashing a
      // book or returning a loan moves it, and it is drawn above the grid: the
      // one entry here whose staleness a reader meets before any list.
      "myOverdue",
    ]);
  });

  it("leaves the three outward lookups alone", () => {
    // The point of the whole module. `searchBooks` is a billed Google Books
    // call carrying `staleTime: 5 * 60_000` precisely so that going back to
    // edit a draft does not re-spend the quota, and an invalidate ignores
    // staleTime. Adding a book used to refetch it.
    //
    // `authorAuthority` is the third, and it arrived the way the docstring on
    // `isCatalogueQuery` said one would: the inventory assertion above failed
    // on it rather than letting it default into every write. It asks lobid and
    // Wikidata, so it is not derived from the books table and no write to the
    // library can make it stale. It is also rate limited at 10 a minute
    // against lobid's published 30, which an invalidate would spend.
    //
    // `authorWikipedia` is the fourth, and it arrived the same way. It asks
    // Wikidata for which language editions hold an article about an author, so
    // no write to the library can make it stale either, and it shares
    // `authorAuthority`'s counter: an invalidate would spend a confirmation's
    // budget on a page render. It is the one of the four whose cost is paid on
    // navigation rather than on a deliberate act, which is why joining every
    // write would be the most expensive of the four mistakes.
    expect(isCatalogueQuery(query(KEYS.lookupIsbn!))).toBe(false);
    expect(isCatalogueQuery(query(KEYS.searchBooks!))).toBe(false);
    expect(isCatalogueQuery(query(KEYS.authorAuthority!))).toBe(false);
    expect(isCatalogueQuery(query(KEYS.authorWikipedia!))).toBe(false);
  });

  it("leaves the published catalogue to its own staleness rule", () => {
    // **Excluded by decision, and the decision is not the one the four outward
    // lookups get.** Those four are excluded because no write can make them
    // stale. These three can: editing a book does change what a visitor sees.
    //
    // What decides it is who pays. The public queries are the only ones in
    // this file with no session behind them, and they are answered under a
    // rate limit keyed on the **source address**, which behind a reverse proxy
    // is close to a global cap shared with every real visitor. Joining the
    // catalogue group would make a signed-in member's writes spend that budget:
    // a bulk import would fire a public request per write and could 429 the
    // catalogue for the people it was published for. That is the same shape as
    // `searchBooks` spending a billed quota, arrived at from the other side.
    //
    // What is given up is small and bounded. A signed-out reader never calls
    // any of this, because a session with no writes never invalidates
    // anything; the only client holding both is an admin previewing through
    // "See what a visitor sees", and both public hooks carry
    // `staleTime: 60_000`, so that preview is at most a minute behind.
    //
    // Measured rather than read off the regex: `/api/public/books` is not in
    // `LIBRARY_WIDE`, and `BOOK_RECORD` is anchored at `^/api/books/`, so
    // `/api/public/books/7` misses it. The infinite spelling resolves to the
    // same path, because `pathOf` steps over orval's marker.
    for (const name of [
      "listPublicBooks",
      "listPublicBooksInfinite",
      "getPublicBook",
    ]) {
      expect(isCatalogueQuery(query(KEYS[name]!)), name).toBe(false);
    }
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
      // A measurement of the reminder channels rather than anything derived
      // from the books table, and admin only: no write to the library can make
      // it stale, and a member's copy of it does not exist.
      "getSenderHealth",
      "getFeatureFlags",
      "listUsers",
      "getMyAppearance",
      // A member's own address and, for an admin, every member's. Per member
      // data on `/api/users`, so no write to the books table can make either
      // stale, and the only writes that can are their own two routes, which
      // invalidate their own keys. Named here rather than left to the count:
      // the grouping is decided by the query's **path**, so a key joins or
      // misses a group by its URL rather than by anything about its name.
      "getMyEmail",
      "listEmails",
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

describe("loans covers the lending views and the list that draws one", () => {
  it("takes the loans list, the overdue list, the count and the listings", () => {
    // The reason it is a group at all: the loans page and the overdue page
    // perform the same write, and the loans page's hand-assembled version was
    // missing the overdue list.
    expect(invalidatedBy((client) => invalidateWith(client).loans())).toEqual([
      "listBooks",
      "listBooksInfinite",
      "listLoans",
      "listOverdue",
      "myOverdue",
    ]);
  });

  it("leaves a book's own record alone", () => {
    // Narrower than `book()` on purpose: returning a loan from a list has no
    // book id to hand, and dropping every cached record to avoid naming one
    // is what this module exists to stop.
    const client = populated();
    invalidateWith(client).loans();
    expect(client.getQueryState(KEYS.getBook!)?.isInvalidated).toBe(false);
    expect(client.getQueryState(KEYS.getStats!)?.isInvalidated).toBe(false);
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
      "listOverdue",
      "myOverdue",
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
