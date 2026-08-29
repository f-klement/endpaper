import { useState } from "react";

import { Button, EmptyState, ErrorState } from "../../components";
import { useTranslation } from "../../i18n";
import { Page, PageCount, PageHeader, SearchBar } from "../components";
import PublicBookCard from "./components/PublicBookCard";
import PublicShell from "./components/PublicShell";
import { usePublicCatalogue } from "./hooks";

/**
 * The published catalogue, searched by somebody with no account.
 *
 * **Accessibility is the point of this screen rather than a finish applied to
 * it.** A public catalogue is the surface in this application most likely to be
 * read by a screen reader, on an old browser, on a library's public terminal,
 * and every choice here follows from that:
 *
 * * the results are a real `<ul>` of `<li>`, so a screen reader announces how
 *   many there are and where in them the reader is;
 * * the count sits in an `aria-live="polite"` region, because a search that
 *   changes the list silently changes nothing a non sighted reader can tell;
 * * more results arrive behind a **button**, never by scrolling, so nothing
 *   appends itself under a reader who is still reading, and the button stays
 *   mounted **and focusable** while the next page is on its way rather than
 *   vanishing or going dead under the hand that pressed it. It took two rounds
 *   to keep that promise: the first version unmounted it, and the second
 *   disabled it, which drops focus just as surely;
 * * every card is one link with one accessible name.
 *
 * **A closed catalogue is not an error.** The server answers 404 when nothing
 * is published, which is deliberate (a 403 would confirm that this deployment
 * holds a catalogue it is withholding), so this screen says there is nothing
 * here rather than that something went wrong.
 */
export default function PublicCataloguePage() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const catalogue = usePublicCatalogue(query);

  if (catalogue.isClosed) {
    return (
      <PublicShell>
        <Page width="narrow">
          <EmptyState
            icon="library"
            title={t("public.closedTitle")}
            hint={t("public.closedHint")}
          />
        </Page>
      </PublicShell>
    );
  }

  return (
    <PublicShell>
      <Page width="wide">
        <PageHeader
          icon="library"
          title={t("public.title")}
          badge={
            catalogue.total > 0 ? (
              <PageCount>{catalogue.total}</PageCount>
            ) : undefined
          }
        />

        <div className="mb-5">
          <SearchBar
            onSearch={setQuery}
            placeholder={t("public.search")}
            label={t("public.searchLabel")}
          />
        </div>

        {/* Announced rather than only drawn. A search that silently swaps the
            list underneath tells a screen reader nothing at all, and the count
            is the one fact that says the search did something. */}
        <p
          aria-live="polite"
          className="text-sm text-paper-600 dark:text-paper-400 mb-4"
        >
          {catalogue.isLoading
            ? t("common.loading")
            : t(
                catalogue.total === 1
                  ? "public.resultCountOne"
                  : "public.resultCount",
                { count: catalogue.total },
              )}
        </p>

        {catalogue.error && !catalogue.isClosed ? (
          <ErrorState error={catalogue.error} />
        ) : catalogue.books.length === 0 && !catalogue.isLoading ? (
          <EmptyState
            icon="search"
            title={t("public.noResults")}
            hint={query ? t("public.noResultsHint") : t("public.emptyHint")}
          />
        ) : (
          <>
            {/* `role="list"` beside `list-none`, which is not belt and braces:
                Safari and VoiceOver drop list semantics from a `ul` whose
                `list-style` is none, so without it a screen reader stops
                announcing how many records there are and where in them the
                reader is. That is the whole reason the results are a list. */}
            <ul
              role="list"
              className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 list-none p-0"
            >
              {catalogue.books.map((book) => (
                <PublicBookCard key={book.id} book={book} />
              ))}
            </ul>

            {/* A button, not a scroll listener. See the note at the top: this
                is the difference between a reader choosing to load more and
                content arriving under them while they read. */}
            {catalogue.hasMore && (
              <div className="mt-6 flex justify-center">
                {/* **`aria-disabled`, never `disabled`, and that is the whole
                    point of this control.** `Button` puts a real `disabled`
                    attribute on a real `<button>`, and a disabled element is
                    not focusable, so the browser blurs to `<body>` the instant
                    the next page starts loading. That is the same focus drop
                    the unmounting version caused, arrived at by a different
                    mechanism: the reader who pressed this loses their place
                    either way. `aria-disabled` says "not actionable" while
                    leaving it focusable, and the handler declines the second
                    press rather than the DOM declining it. */}
                <Button
                  variant="secondary"
                  aria-disabled={catalogue.isLoadingMore || undefined}
                  aria-busy={catalogue.isLoadingMore || undefined}
                  onClick={() => {
                    if (catalogue.isLoadingMore) return;
                    catalogue.loadMore();
                  }}
                >
                  {catalogue.isLoadingMore
                    ? t("common.loading")
                    : t("public.loadMore")}
                </Button>
              </div>
            )}
          </>
        )}
      </Page>
    </PublicShell>
  );
}
