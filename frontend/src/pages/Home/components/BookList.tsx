import { Link } from "react-router-dom";

import {
  OwnershipStatus,
  ReadStatus,
  type BookOut,
} from "../../../api/generated/model";
import { Skeleton } from "../../../components";
import { useTranslation, type Translate } from "../../../i18n";
import CoverImage from "../../components/CoverImage";
import { STATUS_LABELS } from "../../types";

/** Placeholder rows while the first page loads. More than the grid: they fit. */
const SKELETON_ROWS = 12;

/**
 * The second line of a row: author, series, year, in that order.
 *
 * **Joined into one line rather than laid out in columns**, because a column
 * grid with three optional values leaves holes on most rows, and a row with
 * holes reads as missing data rather than as data a book does not have. Every
 * absent value simply closes up.
 */
function subtitleOf(book: BookOut, t: Translate): string {
  const series = book.series_name
    ? book.series_index === null || book.series_index === undefined
      ? t("series.partOfUnnumbered", { name: book.series_name })
      : t("series.partOf", { name: book.series_name, index: book.series_index })
    : null;
  return [book.author, series, book.year]
    .filter((part) => part !== null && part !== undefined && part !== "")
    .join(" · ");
}

interface BookListProps {
  books: BookOut[];
  isLoading: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
}

/**
 * The library as dense rows: a tiny cover, and what identifies a book at a glance.
 *
 * **What the row holds is the design, and the answer is not everything the
 * table has.** A dense row repeating twenty one columns is a worse table. What
 * is here is what a **grid card's face** carries, minus the two badges that are
 * about a card rather than a book (the copies count and the discussion offer),
 * plus the two facts the card hides in its fold out that somebody scanning a
 * list is actually looking for: the series, which is what says the next one is
 * missing, and the year, which tells two printings apart. Everything else stays
 * in the table, which exists for reading metadata.
 *
 * **The loan and the unconfirmed marker are on the row, and that is not
 * decoration.** This view is for somebody looking for a book they know they
 * have, and the two answers to "why is it not on the shelf" are that it is out
 * on loan and that nobody ever confirmed we own it. The grid shows both
 * deliberately; the table shows neither (its `lending` column is the policy,
 * not a live loan), so a list without them is the only view that answers the
 * question it exists for by saying nothing.
 *
 * **Lazy covers are not optional here.** A page holds up to 200 books, so
 * without `loading="lazy"` a full one fetches 200 images at once. It is on
 * every cover. The reason is the page size rather than the viewport: a row is
 * about 65px against a grid card's 400px, which is 3x more rows on a 390px
 * phone and about the same number on a 1200px desktop, and the grid's covers
 * are lazy for the same reason.
 *
 * **The cover carries no accessible name.** The title sits beside it in the
 * same link, and a duplicate label is noise in a screen reader's control list:
 * the book page had exactly this defect twice.
 *
 * The same list query and the same paging as the grid and the table. A view
 * that fetched its own rows would be a second definition of what the library
 * currently is.
 */
export default function BookList({
  books,
  isLoading,
  hasMore,
  isLoadingMore,
  onLoadMore,
}: BookListProps) {
  const { t } = useTranslation();

  if (isLoading) {
    return (
      <div className="card divide-y divide-paper-100 dark:divide-paper-800" data-testid="book-list-skeletons">
        {Array.from({ length: SKELETON_ROWS }).map((_, index) => (
          <div key={index} className="flex items-center gap-3 px-3 py-2">
            <Skeleton className="h-12 w-8 shrink-0 rounded" />
            <div className="min-w-0 flex-1 space-y-1.5">
              <Skeleton className="h-3 w-1/2" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <>
      <ul className="card divide-y divide-paper-100 dark:divide-paper-800">
        {books.map((book) => {
          const status = book.my_status ?? ReadStatus.unread;
          const line = subtitleOf(book, t);
          return (
            <li key={book.id}>
              {/* One link for the whole row rather than a link on the title.
                  The table links the title alone because a reader copying a
                  publisher out of a cell should not navigate; a row here holds
                  nothing to copy and is a single target, which is also what
                  makes it usable on a phone. */}
              <Link
                to={`/book/${book.id}`}
                className="flex items-center gap-3 px-3 py-2 transition-colors hover:bg-paper-50 dark:hover:bg-paper-800/50"
              >
                <CoverImage
                  src={book.cover_url}
                  alt=""
                  loading="lazy"
                  className="h-12 w-8 shrink-0 rounded bg-paper-100 object-cover dark:bg-paper-800"
                  iconClassName="w-4 h-4 opacity-40"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-paper-900 dark:text-paper-100">
                    {book.title}
                  </p>
                  {line && (
                    <p className="truncate text-xs text-paper-600 dark:text-paper-400">
                      {line}
                    </p>
                  )}
                </div>
                {/* The two exceptions to the muted rule below, and they earn
                    it by being rare: a loan and an unconfirmed book are the
                    minority of a shelf, so a coloured marker on one is a signal
                    rather than a field. The grid uses the same two colours for
                    the same two facts. */}
                {book.active_loan && (
                  <span className="shrink-0 rounded-full bg-orange-500 px-1.5 py-0.5 text-xs font-medium text-white">
                    {t("library.loaned")}
                  </span>
                )}
                {book.ownership === OwnershipStatus.unknown && (
                  <span className="shrink-0 rounded-full bg-amber-500/90 px-1.5 py-0.5 text-xs font-medium text-white">
                    {t("ownership.unknown")}
                  </span>
                )}
                {/* Plain muted text, not the coloured pill the card uses. One
                    pill among covers is a marker; thirty of them stacked is a
                    colour field with no signal, and that ramp's own contrast is
                    recorded as below the 4.5 floor on three palettes. Measured
                    as drawn here: paper-600 on paper-0 is 5.03:1 at worst
                    across the seven palettes, and paper-400 on paper-900 is
                    6.00:1, against the pill's 3.97:1. The word is the
                    information either way. */}
                <span className="shrink-0 text-xs text-paper-600 dark:text-paper-400">
                  {t(STATUS_LABELS[status])}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>

      {hasMore && (
        <div className="mt-6 flex justify-center">
          <button
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="rounded-lg border border-paper-200 bg-paper-0 px-4 py-2 text-sm font-medium text-paper-700 transition-colors hover:border-accent-300 disabled:opacity-50 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-200"
          >
            {isLoadingMore ? t("common.loading") : t("library.loadMore")}
          </button>
        </div>
      )}
    </>
  );
}
