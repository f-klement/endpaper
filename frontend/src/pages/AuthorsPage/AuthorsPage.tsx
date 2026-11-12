import { useMemo, useState } from "react";

import type {
  AuthorMergeGroup,
  AuthorOut,
  AuthorSuggestionOut,
} from "../../api/generated/model";
import { EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import AuthorCard from "./components/AuthorCard";
import BatchBar from "./components/BatchBar";
import MergeBar from "./components/MergeBar";
import SuggestionCard from "./components/SuggestionCard";
import { useAuthors, type UseAuthorsResult } from "./hooks";
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
  //
  // **A `Map`, never a plain object.** A group's id is its keys joined, and a
  // key is the server's; read from an object, an id such as `toString` finds
  // the member every object has rather than nothing, and the page throws.
  const [excluded, setExcluded] = useState<Excluded>(() => new Map());

  const matching = useMemo(
    () => matchingAuthors(authors.authors, search),
    [authors.authors, search],
  );

  // Taken from the whole list rather than from `matching`, so a selection
  // survives the search box. That is not a nicety: two spellings of one name
  // often do not match one search term, and folding them together means
  // finding them one at a time.
  const chosen = authors.authors.filter((author) =>
    selected.includes(author.key),
  );

  function merge(keys: string[], keepName: string) {
    authors.merge(keys, keepName);
    setSelected([]);
  }

  const batch = batchOf(authors.suggestions, dropped, excluded);

  // **One click, one visible change.** `checked` reads three things and this
  // used to write only `dropped`, so a reader who had unticked the proposed name
  // saw the box untick itself and then clicked twice more with nothing moving.
  // Putting a group back therefore puts its names back too: that is what the
  // batch needs to take it, and it is visible in the name checkboxes rather than
  // in a variable nobody can see.
  function toggleBatch(group: AuthorSuggestionOut) {
    const id = groupId(group);
    if (batch.ticked.has(id)) {
      setDropped((current) => [...current, id]);
      return;
    }
    setDropped((current) => current.filter((other) => other !== id));
    setExcluded((current) => new Map(current).set(id, []));
  }

  function toggleName(group: AuthorSuggestionOut, key: string) {
    setExcluded((current) =>
      new Map(current).set(
        groupId(group),
        toggled(excludedIn(group, current), key),
      ),
    );
  }

  function foldBatch() {
    authors.mergeBatch(batch.payload);
    setDropped([]);
    setExcluded(new Map());
  }

  if (authors.isLoading) return <Spinner label={t("common.loading")} />;

  const { writeError, isBusy } = writeStatus(authors);

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
          <Suggestions
            suggestions={authors.suggestions}
            batch={batch}
            excluded={excluded}
            isBusy={isBusy}
            isMergingBatch={authors.isMergingBatch}
            onFold={foldBatch}
            onMerge={authors.merge}
            onToggleBatch={toggleBatch}
            onToggleName={toggleName}
          />

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
                  onToggleSelect={(picked) =>
                    setSelected((current) => toggled(current, picked.key))
                  }
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

/** The names a reader has taken out of each group, by the group's id. */
type Excluded = ReadonlyMap<string, string[]>;

interface SuggestionsProps {
  suggestions: AuthorSuggestionOut[];
  batch: Batch;
  excluded: Excluded;
  isBusy: boolean;
  isMergingBatch: boolean;
  onFold: () => void;
  onMerge: UseAuthorsResult["merge"];
  onToggleBatch: (group: AuthorSuggestionOut) => void;
  onToggleName: (group: AuthorSuggestionOut, key: string) => void;
}

/** The groups a rule proposes folding together, and the bar that folds them. */
function Suggestions({
  suggestions,
  batch,
  excluded,
  isBusy,
  isMergingBatch,
  onFold,
  onMerge,
  onToggleBatch,
  onToggleName,
}: SuggestionsProps) {
  const { t } = useTranslation();
  if (suggestions.length === 0) return null;
  return (
    <section className="mb-6 space-y-3">
      <h2 className="font-semibold text-paper-900 dark:text-paper-100">
        {t("authors.suggestionsTitle")}
      </h2>
      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("authors.suggestionsExplain")}
      </p>
      {batch.offerable > 0 && (
        <BatchBar
          payload={batch.payload}
          heldBack={batch.heldBack}
          withdrawn={batch.withdrawn}
          isMerging={isMergingBatch}
          onFold={onFold}
        />
      )}
      {suggestions.map((group) => (
        <SuggestionCard
          key={groupId(group)}
          group={group}
          isMerging={isBusy}
          onMerge={onMerge}
          isBatched={batch.ticked.has(groupId(group))}
          onToggleBatch={() => onToggleBatch(group)}
          excluded={excludedIn(group, excluded)}
          onToggleName={(key) => onToggleName(group, key)}
        />
      ))}
    </section>
  );
}

/** Every author whose name, or any spelling folded into it, holds `search`. */
function matchingAuthors(authors: AuthorOut[], search: string): AuthorOut[] {
  const needle = search.trim().toLocaleLowerCase();
  if (!needle) return authors;
  return authors.filter((author) =>
    [author.name, ...(author.spellings ?? [])].some((spelling) =>
      spelling.toLocaleLowerCase().includes(needle),
    ),
  );
}

/** `keys` with `key` taken out when it is there and added when it is not. */
function toggled(keys: string[], key: string): string[] {
  return keys.includes(key)
    ? keys.filter((other) => other !== key)
    : [...keys, key];
}

/** The error of the last failed write, and whether any write is in flight. */
function writeStatus(authors: UseAuthorsResult) {
  return {
    writeError: authors.mergeError ?? authors.undoError ?? authors.batchError,
    isBusy: authors.isMerging || authors.isUndoing || authors.isMergingBatch,
  };
}

function groupId(group: AuthorSuggestionOut): string {
  return group.keys.join("|");
}

function excludedIn(group: AuthorSuggestionOut, excluded: Excluded): string[] {
  return excluded.get(groupId(group)) ?? [];
}

function includedIn(group: AuthorSuggestionOut, excluded: Excluded): string[] {
  const out = excludedIn(group, excluded);
  return group.keys.filter((key) => !out.includes(key));
}

// The key of the name the server proposed keeping. Names are unique inside a
// group, because a key is derived from a name, so the index is unambiguous.
function keptKey(group: AuthorSuggestionOut): string | undefined {
  return group.keep_name == null
    ? undefined
    : group.keys[group.names.indexOf(group.keep_name)];
}

// **One predicate decides both the checkbox and the bar**, so a checkbox can
// never appear with nothing on the page to act on it. A group the server held
// back carries no name to fold into and is not offered either way.
function isOfferable(group: AuthorSuggestionOut): boolean {
  return group.keep_name != null;
}

/** Offered by the server and not deliberately unticked by the reader. */
function isStillOffered(
  group: AuthorSuggestionOut,
  dropped: string[],
): boolean {
  return isOfferable(group) && !dropped.includes(groupId(group));
}

// Ticked **and** still sendable. A reader who unticks the proposed name, or
// narrows a group below two, has withdrawn it: the server keeps one of the
// group's own names and needs two of them, so sending it would be a 422.
function isTicked(
  group: AuthorSuggestionOut,
  dropped: string[],
  excluded: Excluded,
): boolean {
  if (!isStillOffered(group, dropped)) return false;
  const kept = keptKey(group);
  const included = includedIn(group, excluded);
  return kept !== undefined && included.includes(kept) && included.length > 1;
}

/** What the batch bar counts and what its button would send. */
interface Batch {
  offerable: number;
  heldBack: number;
  withdrawn: number;
  /** The ids of the groups `payload` carries, which each card's tick shows. */
  ticked: ReadonlySet<string>;
  payload: AuthorMergeGroup[];
}

function batchOf(
  suggestions: AuthorSuggestionOut[],
  dropped: string[],
  excluded: Excluded,
): Batch {
  const offerable = suggestions.filter(isOfferable).length;
  const ticked = suggestions.filter((group) =>
    isTicked(group, dropped, excluded),
  );
  // Still offered and still not sendable: the reader has narrowed it past what
  // the batch can take. Counted apart from the held back ones, because the two
  // have different reasons and only one of them is the reader's own doing.
  const withdrawn = suggestions.filter(
    (group) => isStillOffered(group, dropped) && !ticked.includes(group),
  ).length;
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
    keys: includedIn(group, excluded),
    keep_name: group.keep_name ?? "",
  }));
  return {
    offerable,
    heldBack: suggestions.length - offerable,
    withdrawn,
    ticked: new Set(ticked.map(groupId)),
    payload,
  };
}
