import type { FormEvent } from "react";

import type { BookMatch } from "../../../api/generated/model";
import { Button, HelpButton } from "../../../components";
import { errorText } from "../../../components/ErrorState";
import { useTranslation } from "../../../i18n";
import { CoverImage } from "../../components";

interface SearchPanelProps {
  /**
   * Whether Google Books is configured. It is not required: Open Library
   * answers without a key. It adds the blurb and the categories, so the panel
   * says what a key would buy rather than switching itself off.
   */
  isConfigured: boolean;
  onOpenHelp: () => void;
  query: string;
  matches: BookMatch[];
  isSearching: boolean;
  isEmpty: boolean;
  error: unknown;
  onQueryChange: (query: string) => void;
  onSubmit: () => void;
  onChoose: (match: BookMatch) => void;
}

/** A one-line description of an edition, skipping the parts it lacks. */
function summarise(match: BookMatch): string {
  return [match.author, match.publisher, match.year]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Searching by title, for a book with no scannable barcode.
 *
 * This used to be a Google Books panel, hidden entirely from anyone without an
 * API key, which left them no way at all to add a book that has no barcode or
 * predates ISBNs. Open Library answers without a key, so the box is always
 * live and Google is an upgrade rather than a prerequisite.
 *
 * Dumb: it renders the box and the results and reports what was picked. The
 * query, the request and the prefill all live in the page's hooks.
 */
export default function SearchPanel({
  isConfigured,
  onOpenHelp,
  query,
  matches,
  isSearching,
  isEmpty,
  error,
  onQueryChange,
  onSubmit,
  onChoose,
}: SearchPanelProps) {
  const { t } = useTranslation();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <div className="mt-6 pt-5 border-t border-paper-200 dark:border-paper-700">
      <div className="flex items-center justify-center gap-2 mb-3">
        <p className="text-sm text-paper-600 dark:text-paper-400">
          {t("search.orSearchByTitle")}
        </p>
        <HelpButton label={t("help.aboutSearch")} onClick={onOpenHelp} />
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={t("search.placeholder")}
          aria-label={t("search.label")}
          className="field flex-1"
        />
        <Button
          type="submit"
          isLoading={isSearching}
          disabled={query.trim().length < 2}
        >
          {t("search.button")}
        </Button>
      </form>

      {/* Not a disabled state: search works. This says what a key adds, so an
          admin knows the option exists without anyone else being blocked. */}
      {!isConfigured && (
        <p className="text-xs text-paper-600 mt-2 dark:text-paper-400">
          {t("search.withoutKey")}{" "}
          <button
            type="button"
            onClick={onOpenHelp}
            className="text-accent-700 hover:text-accent-800 underline dark:text-accent-400 dark:hover:text-accent-300"
          >
            {t("help.title")}
          </button>
        </p>
      )}

      {error != null && (
        <p
          role="alert"
          className="text-sm text-danger-600 mt-2 dark:text-danger-300"
        >
          {errorText(error, t("common.somethingWentWrong"), t)}
        </p>
      )}

      {isEmpty && (
        <p className="text-sm text-paper-600 text-center mt-4 dark:text-paper-400">
          {t("search.noResults")}
        </p>
      )}

      {matches.length > 0 && (
        <>
          <ul className="mt-4 space-y-2">
            {matches.map((match, index) => (
              // No result carries a stable id across both sources: Open
              // Library rows have no volume id at all. Two printings of one
              // book differ only by year, so the index is the only key that
              // cannot collapse two rows into one.
              <li
                key={`${match.google_books_id ?? match.isbn13 ?? ""}-${index}`}
              >
                <button
                  type="button"
                  onClick={() => onChoose(match)}
                  className="w-full flex gap-3 text-left p-2.5 rounded-xl border border-paper-200 hover:border-accent-300 hover:bg-accent-50 transition-colors dark:border-paper-800 dark:hover:border-accent-700 dark:hover:bg-accent-500/10"
                >
                  <CoverImage
                    src={match.cover_url}
                    alt=""
                    iconClassName="w-5 h-5"
                    className="w-10 h-14 object-cover rounded shrink-0 bg-paper-100 dark:bg-paper-800"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-paper-900 truncate dark:text-paper-100">
                      {match.title}
                    </span>
                    {match.subtitle && (
                      <span className="block text-xs text-paper-600 truncate dark:text-paper-400">
                        {match.subtitle}
                      </span>
                    )}
                    <span className="block text-xs text-paper-600 truncate mt-0.5 dark:text-paper-400">
                      {summarise(match)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="text-xs text-paper-600 text-center mt-3 dark:text-paper-400">
            {t("search.pickHint")}
          </p>
        </>
      )}
    </div>
  );
}
