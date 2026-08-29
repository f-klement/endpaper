/**
 * Data for the authors page.
 *
 * Two queries, because the index and the suggestions answer different
 * questions and the second is worth nothing on a tidy shelf. Both are derived
 * from `books.author` on the server, so neither is cached beyond the default.
 *
 * A merge writes one row per spelling and never touches a book, so what it
 * invalidates is narrow: the two lists here, and the book listing, whose
 * `?author=` filter resolves through the rows that just changed. Nothing on a
 * book payload depends on an alias.
 *
 * The one non-obvious outcome is a merge landing somewhere other than the name
 * that was typed, which happens when that name is itself already folded into
 * somebody. It is correct, and it is silent without the toast below.
 */

import { useMemo } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../app/toast";
import { useSortedByName, useTranslation } from "../../i18n";

import {
  getListAuthorSuggestionsQueryKey,
  getListAuthorsQueryKey,
  useAuthorWikipedia,
  useListAuthorSuggestions,
  useListAuthors,
  useMergeAuthors,
  useUnmergeAuthor,
} from "../../api/generated/endpoints/books/books";
import {
  AuthorityScheme,
  type AuthorOut,
  type AuthorSuggestionOut,
  type AuthorWikipediaOut,
} from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";

/**
 * How long the outward links stay fresh.
 *
 * An hour, against the app-wide default of thirty seconds, because the question
 * this answers is "does a Wikipedia article about this person exist", and the
 * answer changes on the order of months. The default would put an outbound
 * request on every navigation back to this page.
 *
 * It matters more than an ordinary cache setting: every miss is a request the
 * server makes to Wikidata on this member's behalf, and it shares
 * `AUTHORITY_LIMIT` with confirming an identifier.
 */
const LINKS_STALE_MS = 60 * 60 * 1000;

export interface UseAuthorsResult {
  authors: AuthorOut[];
  suggestions: AuthorSuggestionOut[];
  /** Where to read about each author, by author key. Absent means no button. */
  wikipedia: Map<string, AuthorWikipediaOut>;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;

  merge: (keys: string[], keepName: string) => void;
  isMerging: boolean;
  mergeError: unknown;

  undo: (aliasId: number) => void;
  isUndoing: boolean;
  undoError: unknown;
}

export function useAuthors(): UseAuthorsResult {
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const toast = useToast();
  const { t, locale } = useTranslation();
  const authors = useListAuthors({ query: { retry: false } });
  const suggestions = useListAuthorSuggestions({ query: { retry: false } });

  // **Asked only when somebody on this page could carry a link, and only for
  // the locale the reader chose.** A library that has confirmed nobody makes no
  // request at all, which is most libraries: the server answers a row per
  // author with a confirmed authority identifier, and confirming one is a
  // deliberate act per person.
  //
  // **The gate is written twice on purpose, and the two are not equals.** The
  // server's is the one that decides: `GET /authors/wikipedia` returns a row
  // only for an author carrying a `wikidata` identifier the caller may see, and
  // `Authorship.listing()` is what applies `visible_to` to that. This one
  // decides only whether to make the request at all, so the worst it can do
  // wrong is spend a request that comes back empty, or skip one that would have
  // come back empty. It cannot show a button the server did not offer.
  //
  // It is duplicated rather than derived because the alternative is asking the
  // server whether it is worth asking the server. Removing it would put an
  // outbound call on every visit to this page by every library, including the
  // ones that have confirmed nobody.
  //
  // The locale is in the query key, so switching language refetches rather than
  // serving the previous language's links from cache.
  const identified = (authors.data ?? []).some((author) =>
    (author.identifiers ?? []).some(
      (row) => row.scheme === AuthorityScheme.wikidata,
    ),
  );
  const links = useAuthorWikipedia(
    { lang: locale },
    {
      query: {
        enabled: identified,
        staleTime: LINKS_STALE_MS,
        // A failure costs the second button and nothing else, so retrying it
        // would spend the shared authority budget to recover a link.
        retry: false,
      },
    },
  );

  const byKey = useMemo(
    () => new Map((links.data ?? []).map((row) => [row.key, row])),
    [links.data],
  );

  // `build_index` sorts on `name.casefold()`, which is a fold and not a
  // collation: it files Ä after Z. An index of people is the one list here a
  // reader scans alphabetically rather than searches. See `lib/nameOrder.ts`.
  const ordered = useSortedByName(authors.data);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListAuthorsQueryKey() });
    void queryClient.invalidateQueries({
      queryKey: getListAuthorSuggestionsQueryKey(),
    });
    // The library's author filter resolves a name through the alias rows, so a
    // merge changes which books it answers with. Nothing else about a book
    // changes, which is why the listings are dropped and the stats are not.
    // Through `invalidate` because the grid is an infinite query and a
    // hand-written `["/api/books"]` does not match it.
    invalidate.listings();
  };

  const merge = useMergeAuthors({
    mutation: {
      onSuccess: (author, variables) => {
        refresh();
        // A name that is itself already folded resolves to whoever it was
        // folded into, which is correct and invisible: the page refetches and
        // the author is simply filed under a name nobody typed. Said out loud
        // rather than left for the reader to notice, because the alternative
        // reads as the merge having gone somewhere at random.
        if (author.name !== variables.data.keep_name) {
          toast.show({
            message: t("authors.foldedInto", { name: author.name }),
          });
        }
      },
    },
  });
  const undo = useUnmergeAuthor({ mutation: { onSuccess: refresh } });

  return {
    authors: ordered,
    // A Map rather than the array, so the card is a lookup rather than a scan
    // per render: the page renders one card per author and `find` would make
    // that quadratic on a shelf with a few hundred identified people.
    //
    // Memoised for the reason `i18n`'s own `EMPTY` records: a fresh collection
    // every render is a new reference every render, and this one is handed to
    // every card.
    wikipedia: byKey,
    // A failure here costs the suggestions, not the page: the index is the
    // reason somebody opened it.
    suggestions: suggestions.data ?? [],
    isLoading: authors.isPending,
    error: authors.error,
    refetch: () => void authors.refetch(),

    // `mutate`, not `mutateAsync`: the latter rejects, leaving an unhandled
    // promise rejection on every failure. The error is read off the mutation.
    merge: (keys, keepName) =>
      merge.mutate({ data: { keys, keep_name: keepName } }),
    isMerging: merge.isPending,
    mergeError: merge.error,

    undo: (aliasId) => undo.mutate({ aliasId }),
    isUndoing: undo.isPending,
    undoError: undo.error,
  };
}
