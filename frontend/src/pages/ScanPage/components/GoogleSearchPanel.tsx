import type { FormEvent } from "react";

import type { GoogleBooksMatch } from "../../../api/generated/model";
import { HelpButton } from "../../../components";
import { errorText } from "../../../components/ErrorState";
import { useTranslation } from "../../../i18n";

interface GoogleSearchPanelProps {
  /** False when no API key is stored: the box is shown but inert. */
  isConfigured: boolean;
  onOpenHelp: () => void;
  query: string;
  matches: GoogleBooksMatch[];
  isSearching: boolean;
  isEmpty: boolean;
  error: unknown;
  onQueryChange: (query: string) => void;
  onSubmit: () => void;
  onChoose: (match: GoogleBooksMatch) => void;
}

/** A one-line description of an edition, skipping the parts it lacks. */
function summarise(match: GoogleBooksMatch): string {
  return [match.author, match.publisher, match.year]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Searching Google Books by title, for a book with no scannable barcode.
 *
 * Dumb: it renders the box and the results and reports what was picked. The
 * query, the request and the prefill all live in the page's hooks.
 */
export default function GoogleSearchPanel({
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
}: GoogleSearchPanelProps) {
  const { t } = useTranslation();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
      <div className="flex items-center justify-center gap-2 mb-3">
        <p className="text-sm text-gray-500 dark:text-gray-400">
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
          disabled={!isConfigured}
          className="flex-1 px-3 py-2.5 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-sky-400 text-sm disabled:bg-gray-50 disabled:text-gray-400 disabled:cursor-not-allowed dark:border-gray-700 dark:disabled:bg-gray-800"
        />
        <button
          type="submit"
          disabled={!isConfigured || isSearching || query.trim().length < 2}
          className="px-4 py-2.5 bg-sky-500 text-white rounded-lg text-sm font-medium hover:bg-sky-600 disabled:opacity-40 transition-colors"
        >
          {isSearching ? t("search.searching") : t("search.button")}
        </button>
      </form>

      {/* Shown rather than hiding the box entirely: a control that is visibly
          off and explains itself is better than a feature nobody knows exists. */}
      {!isConfigured && (
        <p className="text-xs text-gray-500 mt-2 dark:text-gray-400">
          {t("help.disabledSearch")}{" "}
          <button
            type="button"
            onClick={onOpenHelp}
            className="text-sky-600 hover:text-sky-700 underline dark:text-sky-400"
          >
            {t("help.title")}
          </button>
        </p>
      )}

      {error != null && (
        <p role="alert" className="text-sm text-red-600 mt-2 dark:text-red-400">
          {errorText(error, t("common.somethingWentWrong"))}
        </p>
      )}

      {isEmpty && (
        <p className="text-sm text-gray-500 text-center mt-4 dark:text-gray-400">
          {t("search.noResults")}
        </p>
      )}

      {matches.length > 0 && (
        <>
          <ul className="mt-4 space-y-2">
            {matches.map((match, index) => (
              // Google's volume id is the natural key, but it is optional in
              // the payload, so the index backs it up rather than risking a
              // duplicate key collapsing two results into one row.
              <li key={match.google_books_id ?? `match-${index}`}>
                <button
                  type="button"
                  onClick={() => onChoose(match)}
                  className="w-full flex gap-3 text-left p-2 rounded-xl border border-gray-200 hover:border-sky-300 hover:bg-sky-50 transition-colors dark:border-gray-700"
                >
                  {match.cover_url ? (
                    <img
                      src={match.cover_url}
                      alt=""
                      className="w-10 h-14 object-cover rounded shrink-0 bg-gray-100 dark:bg-gray-800"
                      onError={(event) => {
                        event.currentTarget.style.visibility = "hidden";
                      }}
                    />
                  ) : (
                    <div className="w-10 h-14 rounded shrink-0 bg-gray-100 flex items-center justify-center text-lg dark:bg-gray-800">
                      📖
                    </div>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-gray-900 truncate dark:text-gray-100">
                      {match.title}
                    </span>
                    {match.subtitle && (
                      <span className="block text-xs text-gray-500 truncate dark:text-gray-400">
                        {match.subtitle}
                      </span>
                    )}
                    <span className="block text-xs text-gray-400 truncate mt-0.5 dark:text-gray-500">
                      {summarise(match)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="text-xs text-gray-400 text-center mt-3 dark:text-gray-500">
            {t("search.pickHint")}
          </p>
        </>
      )}
    </div>
  );
}
