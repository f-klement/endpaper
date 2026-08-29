import { useMemo, useState } from "react";

import { EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import AuthorCard from "./components/AuthorCard";
import MergeBar from "./components/MergeBar";
import SuggestionCard from "./components/SuggestionCard";
import { useAuthors } from "./hooks";
import { Page, PageHeader } from "../components";

/**
 * Everybody credited on the shelf, and the tools to say which of them are the
 * same person.
 *
 * **The index is the page; there is no page per author.** Following a name
 * goes to the library filtered to it, which is the shape the series page
 * already has: "everything by this person" is a filtered library, and the
 * library is what renders one well. A second grid here would be a second grid
 * to keep in step with the first.
 *
 * Filtering happens in the browser rather than through a query parameter. The
 * whole list arrives in one request (one entry per name, a string and a
 * number), so a request per keystroke would buy latency and nothing else.
 *
 * Two ways to fold names together, and both are needed. The suggestion cards
 * cover what a rule can propose; selecting names here covers what no rule can,
 * which is a misspelling (`Tolkein` shares no word, initial or squashed key
 * with `Tolkien`) and a plain rename. Leaving only the first would make
 * deduplication reachable exactly where a guess had already been made for you.
 */
export default function AuthorsPage() {
  const { t } = useTranslation();
  const authors = useAuthors();
  const [search, setSearch] = useState("");
  // Keys rather than whole rows: the list is refetched after every merge, so a
  // held row would be a copy of something that has just changed.
  const [selected, setSelected] = useState<string[]>([]);

  const matching = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    if (!needle) return authors.authors;
    return authors.authors.filter((author) =>
      [author.name, ...(author.spellings ?? [])].some((spelling) =>
        spelling.toLocaleLowerCase().includes(needle),
      ),
    );
  }, [authors.authors, search]);

  // Taken from the whole list rather than from `matching`, so a selection
  // survives the search box. That is not a nicety: two spellings of one name
  // often do not match one search term, and folding them together means
  // finding them one at a time.
  const chosen = authors.authors.filter((author) =>
    selected.includes(author.key),
  );

  function toggle(key: string) {
    setSelected((current) =>
      current.includes(key)
        ? current.filter((other) => other !== key)
        : [...current, key],
    );
  }

  function merge(keys: string[], keepName: string) {
    authors.merge(keys, keepName);
    setSelected([]);
  }

  if (authors.isLoading) return <Spinner label={t("common.loading")} />;

  const writeError = authors.mergeError ?? authors.undoError;
  const isBusy = authors.isMerging || authors.isUndoing;

  return (
    <Page width="narrow">
      <PageHeader icon="library" title={t("authors.title")} />

      <p className="text-sm text-paper-600 mb-4 dark:text-paper-400">
        {t("authors.explain")}
      </p>

      {writeError != null && (
        <div className="mb-4">
          <ErrorState
            error={writeError}
            fallback={t("common.somethingWentWrong")}
          />
        </div>
      )}

      {authors.error != null ? (
        <ErrorState
          error={authors.error}
          fallback={t("authors.couldNotLoad")}
          onRetry={authors.refetch}
        />
      ) : authors.authors.length === 0 ? (
        <EmptyState
          icon="library"
          title={t("authors.none")}
          hint={t("authors.noneHint")}
        />
      ) : (
        <>
          {authors.suggestions.length > 0 && (
            <section className="mb-6 space-y-3">
              <h2 className="font-semibold text-paper-900 dark:text-paper-100">
                {t("authors.suggestionsTitle")}
              </h2>
              <p className="text-sm text-paper-600 dark:text-paper-400">
                {t("authors.suggestionsExplain")}
              </p>
              {authors.suggestions.map((group) => (
                <SuggestionCard
                  key={group.keys.join("|")}
                  group={group}
                  isMerging={authors.isMerging}
                  onMerge={authors.merge}
                />
              ))}
            </section>
          )}

          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("authors.searchPlaceholder")}
            aria-label={t("authors.search")}
            className="w-full px-3 py-2 mb-4 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          />

          {matching.length === 0 ? (
            <EmptyState icon="search" title={t("authors.noMatches")} />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {matching.map((author) => (
                <AuthorCard
                  key={author.key}
                  author={author}
                  isBusy={isBusy}
                  isSelected={selected.includes(author.key)}
                  onToggleSelect={(picked) => toggle(picked.key)}
                  onUndo={authors.undo}
                  wikipedia={authors.wikipedia.get(author.key)}
                />
              ))}
            </div>
          )}

          {/* Below the list rather than above it, and only while something is
              selected: the bar is the answer to a selection, not a control
              that waits for one. */}
          {chosen.length > 0 && (
            <MergeBar
              selected={chosen}
              isMerging={authors.isMerging}
              onMerge={merge}
              onClear={() => setSelected([])}
            />
          )}
        </>
      )}
    </Page>
  );
}
