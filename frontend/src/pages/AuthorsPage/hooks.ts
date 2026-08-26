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

import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../app/toast";
import { useSortedByName, useTranslation } from "../../i18n";

import {
  getListAuthorSuggestionsQueryKey,
  getListAuthorsQueryKey,
  useListAuthorSuggestions,
  useListAuthors,
  useMergeAuthors,
  useUnmergeAuthor,
} from "../../api/generated/endpoints/books/books";
import type { AuthorOut, AuthorSuggestionOut } from "../../api/generated/model";

export interface UseAuthorsResult {
  authors: AuthorOut[];
  suggestions: AuthorSuggestionOut[];
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
  const toast = useToast();
  const { t } = useTranslation();
  const authors = useListAuthors({ query: { retry: false } });
  const suggestions = useListAuthorSuggestions({ query: { retry: false } });

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
    // changes, which is why the book caches are dropped and the stats are not.
    void queryClient.invalidateQueries({ queryKey: ["/api/books"] });
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
