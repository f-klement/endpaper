import { Link } from "react-router-dom";

import { ReadStatus, type BookOut } from "../../../api/generated/model";
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
 * is here is exactly what a **grid card's face** carries (cover, title, author,
 * reading status) plus the two facts the card hides in its fold out that
 * somebody scanning a list is actually looking for: the series, which is what
 * says the next one is missing, and the year, which is what tells two printings
 * apart. Everything else stays in the table, which exists for reading metadata.
 *
 * **Lazy covers are not optional here.** A list fits roughly three times as
 * many rows on a screen as the grid fits cards, and a 200 row page would
 * otherwise fetch 200 images at once. `loading="lazy"` is on every one.
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
                {/* Plain muted text, not the coloured pill the card uses. One
                    pill among covers is a marker; thirty of them stacked is a
                    colour field with no signal, and that ramp's own contrast is
                    recorded as below the 4.5 floor on three palettes. The word
                    is the information either way. */}
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
