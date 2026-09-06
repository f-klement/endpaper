import { useMemo, useState } from "react";

import type { AuthorSuggestionOut } from "../../api/generated/model";
import { EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import AuthorCard from "./components/AuthorCard";
import BatchBar from "./components/BatchBar";
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
  // Which proposed groups are **not** in the batch, rather than which are.
  // Everything the server offered is ticked to begin with, and the list is
  // refetched after every write, so holding the included set would mean
  // deciding what a group that has just appeared should default to.
  const [dropped, setDropped] = useState<string[]>([]);
  // The names a reader has taken out of a group, by group. **Here rather than
  // inside the card, because both the card's own button and the batch have to
  // honour them**: while this lived in the card, unticking a name left it out
  // of that group's merge and the batch folded it anyway.
  const [excluded, setExcluded] = useState<Record<string, string[]>>({});

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

  const groupId = (group: AuthorSuggestionOut) => group.keys.join("|");
  const excludedIn = (group: AuthorSuggestionOut) =>
    excluded[groupId(group)] ?? [];
  const includedIn = (group: AuthorSuggestionOut) =>
    group.keys.filter((key) => !excludedIn(group).includes(key));

  // The key of the name the server proposed keeping. Names are unique inside a
  // group, because a key is derived from a name, so the index is unambiguous.
  const keptKey = (group: AuthorSuggestionOut) =>
    group.keep_name == null
      ? undefined
      : group.keys[group.names.indexOf(group.keep_name)];

  // **One predicate decides both the checkbox and the bar**, so a checkbox can
  // never appear with nothing on the page to act on it. A group the server held
  // back carries no name to fold into and is not offered either way.
  const isOfferable = (group: AuthorSuggestionOut) => group.keep_name != null;
  const offerable = authors.suggestions.filter(isOfferable);
  const heldBack = authors.suggestions.length - offerable.length;

  // Ticked **and** still sendable. A reader who unticks the proposed name, or
  // narrows a group below two, has withdrawn it: the server keeps one of the
  // group's own names and needs two of them, so sending it would be a 422.
  const isTicked = (group: AuthorSuggestionOut) => {
    if (!isOfferable(group) || dropped.includes(groupId(group))) return false;
    const kept = keptKey(group);
    const included = includedIn(group);
    return kept !== undefined && included.includes(kept) && included.length > 1;
  };
  const ticked = authors.suggestions.filter(isTicked);
  // Offered by the server, not deliberately unticked, and still not sendable:
  // the reader has narrowed it past what the batch can take. Counted apart from
  // the held back ones, because the two have different reasons and only one of
  // them is the reader's own doing.
  const withdrawn = authors.suggestions.filter(
    (group) =>
      isOfferable(group) &&
      !dropped.includes(groupId(group)) &&
      !isTicked(group),
  ).length;

  // **One click, one visible change.** `checked` reads three things and this
  // used to write only `dropped`, so a reader who had unticked the proposed name
  // saw the box untick itself and then clicked twice more with nothing moving.
  // Putting a group back therefore puts its names back too: that is what the
  // batch needs to take it, and it is visible in the name checkboxes rather than
  // in a variable nobody can see.
  function toggleBatch(group: AuthorSuggestionOut) {
    const id = groupId(group);
    if (isTicked(group)) {
      setDropped((current) => [...current, id]);
      return;
    }
    setDropped((current) => current.filter((other) => other !== id));
    setExcluded((current) => ({ ...current, [id]: [] }));
  }

  function toggleName(group: AuthorSuggestionOut, key: string) {
    const id = groupId(group);
    setExcluded((current) => {
      const before = current[id] ?? [];
      return {
        ...current,
        [id]: before.includes(key)
          ? before.filter((other) => other !== key)
          : [...before, key],
      };
    });
  }

  // **The request, built once and used for both the counts and the write.**
  // The bar counted whole groups while this sent only the names still ticked,
  // so unticking a name inside a ticked group left the sentence and the
  // confirmation overstating what would be written. One source removes the
  // class rather than the instance.
  //
  // `keys` is the names still ticked, not every name the rule grouped: the
  // grouping is transitive, so that is the difference between folding two
  // people together and not. `keep_name` is non-null by construction, since
  // `isTicked` requires it; written out rather than asserted so a group that
  // lost its name between render and click is dropped instead of sent empty.
  const payload = ticked.map((group) => ({
    keys: includedIn(group),
    keep_name: group.keep_name ?? "",
  }));

  function foldBatch() {
    authors.mergeBatch(payload);
    setDropped([]);
    setExcluded({});
  }

  if (authors.isLoading) return <Spinner label={t("common.loading")} />;

  const writeError =
    authors.mergeError ?? authors.undoError ?? authors.batchError;
  const isBusy =
    authors.isMerging || authors.isUndoing || authors.isMergingBatch;

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
              {offerable.length > 0 && (
                <BatchBar
                  payload={payload}
                  heldBack={heldBack}
                  withdrawn={withdrawn}
                  isMerging={authors.isMergingBatch}
                  onFold={foldBatch}
                />
              )}
              {authors.suggestions.map((group) => (
                <SuggestionCard
                  key={groupId(group)}
                  group={group}
                  isMerging={isBusy}
                  onMerge={authors.merge}
                  isBatched={isTicked(group)}
                  onToggleBatch={() => toggleBatch(group)}
                  excluded={excludedIn(group)}
                  onToggleName={(key) => toggleName(group, key)}
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
