import { useState } from "react";

import { EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import { Page, PageCount, PageHeader } from "../components";
import QuoteCard from "./components/QuoteCard";
import { useAllQuotes } from "./hooks";

/**
 * Every passage the member can see, newest first.
 *
 * Its own page rather than a section of the library grid: a quote is read, not
 * scanned, so it wants a column rather than a card grid, and mixing the two
 * would give the grid a row whose height depends on how much somebody typed.
 *
 * **This is a second book listing.** It shows a title, an author and a cover
 * for every row, so the endpoint behind it applies `visible_to()` on both the
 * rows and the count. Nothing here can filter what the API already decided.
 */
export default function QuotesPage() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const quotes = useAllQuotes(page);

  if (quotes.isLoading) return <Spinner label={t("common.loading")} />;

  return (
    <Page width="narrow">
      <PageHeader
        icon="bookmark"
        title={t("quotes.title")}
        badge={quotes.total > 0 && <PageCount>{quotes.total}</PageCount>}
      />

      {quotes.error != null ? (
        <ErrorState
          error={quotes.error}
          fallback={t("quotes.couldNotLoad")}
          onRetry={quotes.refetch}
        />
      ) : quotes.quotes.length === 0 ? (
        <EmptyState
          icon="bookmark"
          title={t("quotes.empty")}
          hint={t("quotes.emptyHint")}
        />
      ) : (
        <>
          <div className="space-y-3">
            {quotes.quotes.map((quote) => (
              <QuoteCard key={quote.id} quote={quote} />
            ))}
          </div>

          {quotes.pageCount > 1 && (
            <nav
              aria-label={t("quotes.pagination")}
              className="flex items-center justify-between gap-3 mt-6"
            >
              <button
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1}
                className="px-3 py-1.5 rounded-lg border border-paper-200 text-sm text-paper-700 disabled:opacity-40 hover:bg-paper-100 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
              >
                {t("quotes.previous")}
              </button>
              <span className="text-xs text-paper-600 tabular-nums dark:text-paper-400">
                {t("quotes.pageOf", { page, of: quotes.pageCount })}
              </span>
              <button
                onClick={() =>
                  setPage((current) => Math.min(quotes.pageCount, current + 1))
                }
                disabled={page >= quotes.pageCount}
                className="px-3 py-1.5 rounded-lg border border-paper-200 text-sm text-paper-700 disabled:opacity-40 hover:bg-paper-100 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
              >
                {t("quotes.next")}
              </button>
            </nav>
          )}
        </>
      )}
    </Page>
  );
}
