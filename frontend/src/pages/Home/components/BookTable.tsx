import { Link } from "react-router-dom";

import {
  BookSort,
  OwnershipStatus,
  ReadStatus,
  type BookOut,
  type Locale,
} from "../../../api/generated/model";
import { Icon, Skeleton } from "../../../components";
import {
  tagName,
  useTranslation,
  type MessageKey,
  type Translate,
} from "../../../i18n";
import { formatMinor } from "../../../lib/money";
import {
  CONDITION_LABELS,
  FORMAT_LABELS,
  LENDING_LABELS,
  OWNERSHIP_LABELS,
  STATUS_LABELS,
} from "../../types";

const SKELETON_ROWS = 8;

/**
 * Which sorts a column offers, or null where the API cannot order by it.
 *
 * **Deliberately not client side.** Sorting the rows in the browser would sort
 * only the page that has been loaded, silently, and a table headed "Publisher,
 * ascending" showing the first 25 books by title is worse than a header that
 * does nothing. So a column the backend cannot order by is plain text.
 */
interface ColumnSort {
  asc: BookSort | null;
  desc: BookSort | null;
}

interface Column {
  key: string;
  label: MessageKey;
  sort: ColumnSort | null;
  /** Right aligned, for the columns that hold a number. */
  numeric?: boolean;
  render: (book: BookOut, t: Translate, locale: Locale) => string;
}

function date(iso: string | null | undefined, locale: string): string {
  return iso ? new Date(iso).toLocaleDateString(locale) : "";
}

function number(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

const COLUMNS: Column[] = [
  {
    key: "title",
    label: "field.title",
    sort: { asc: BookSort.title_asc, desc: BookSort.title_desc },
    render: (book) => book.title,
  },
  {
    key: "author",
    label: "field.author",
    // One direction only: the API sorts by author ascending and has no
    // descending counterpart, and offering a toggle that silently reverses
    // nothing would be the client side sort this table refuses to do.
    sort: { asc: BookSort.author, desc: null },
    render: (book) => book.author ?? "",
  },
  {
    key: "series",
    label: "series.label",
    sort: { asc: BookSort.series, desc: null },
    render: (book, t) =>
      book.series_name
        ? book.series_index === null || book.series_index === undefined
          ? t("series.partOfUnnumbered", { name: book.series_name })
          : t("series.partOf", {
              name: book.series_name,
              index: book.series_index,
            })
        : "",
  },
  {
    key: "year",
    label: "field.year",
    sort: { asc: BookSort.year_asc, desc: BookSort.year_desc },
    numeric: true,
    render: (book) => number(book.year),
  },
  {
    key: "publisher",
    label: "field.publisher",
    sort: null,
    render: (book) => book.publisher ?? "",
  },
  {
    key: "format",
    label: "copy.format",
    sort: null,
    render: (book, t) => (book.format ? t(FORMAT_LABELS[book.format]) : ""),
  },
  {
    key: "condition",
    label: "copy.condition",
    sort: null,
    render: (book, t) =>
      book.condition ? t(CONDITION_LABELS[book.condition]) : "",
  },
  {
    key: "lending",
    label: "lending.label",
    sort: null,
    render: (book, t) => (book.lending ? t(LENDING_LABELS[book.lending]) : ""),
  },
  {
    key: "discuss",
    label: "discuss.label",
    sort: null,
    // The names, not a tick. "Ask about it" is only useful if it says whom.
    render: (book) =>
      (book.discuss_with ?? []).map((member) => member.username).join(", "),
  },
  {
    key: "location",
    label: "location.label",
    sort: null,
    render: (book) => book.location ?? "",
  },
  {
    key: "pageCount",
    label: "field.pageCount",
    sort: null,
    numeric: true,
    render: (book) => number(book.page_count),
  },
  {
    key: "language",
    label: "field.language",
    sort: null,
    render: (book) => book.language ?? "",
  },
  {
    key: "status",
    label: "field.readingStatus",
    sort: null,
    render: (book, t) => t(STATUS_LABELS[book.my_status ?? ReadStatus.unread]),
  },
  {
    key: "rating",
    label: "field.rating",
    sort: null,
    numeric: true,
    render: (book) => number(book.my_rating),
  },
  {
    key: "tags",
    label: "library.tags",
    sort: null,
    render: (book, _t, locale) =>
      (book.tags ?? []).map((tag) => tagName(tag, locale)).join(", "),
  },
  {
    key: "ownership",
    label: "field.ownership",
    sort: null,
    render: (book, t) =>
      t(OWNERSHIP_LABELS[book.ownership ?? OwnershipStatus.unknown]),
  },
  {
    key: "addedBy",
    label: "field.addedBy",
    sort: null,
    render: (book) => book.added_by?.username ?? "",
  },
  {
    key: "addedAt",
    label: "field.addedAt",
    // Newest first is the only order the API offers for this, so the column
    // sorts one way and says so through `aria-sort` rather than pretending to
    // toggle.
    sort: { asc: null, desc: BookSort.newest },
    render: (book, _t, locale) => date(book.added_at, locale),
  },
  {
    key: "price",
    label: "copy.price",
    sort: null,
    numeric: true,
    render: (book) => {
      const amount = formatMinor(book.purchase_price_minor);
      if (!amount) return "";
      return book.purchase_currency
        ? `${amount} ${book.purchase_currency}`
        : amount;
    },
  },
  {
    key: "purchasedAt",
    label: "copy.purchasedAt",
    sort: null,
    render: (book, _t, locale) => date(book.purchased_at, locale),
  },
  {
    key: "purchaseSource",
    label: "copy.purchaseSource",
    sort: null,
    render: (book) => book.purchase_source ?? "",
  },
];

/** Which way this column is currently ordering, for `aria-sort`. */
function direction(
  column: Column,
  sort: BookSort,
): "ascending" | "descending" | "none" {
  if (column.sort?.asc === sort) return "ascending";
  if (column.sort?.desc === sort) return "descending";
  return "none";
}

/** The sort pressing this header should ask for next. */
function nextSort(column: Column, sort: BookSort): BookSort | null {
  if (!column.sort) return null;
  const { asc, desc } = column.sort;
  if (asc !== null && sort !== asc) return asc;
  if (desc !== null && sort !== desc) return desc;
  return asc ?? desc;
}

interface BookTableProps {
  books: BookOut[];
  sort: BookSort;
  onSortChange: (sort: BookSort) => void;
  isLoading: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
}

/**
 * The library as a table, for reading the metadata rather than the covers.
 *
 * Twenty one columns will not fit a phone and are not meant to: **the table
 * scrolls inside its own container**, so the page body never scrolls sideways.
 * A body that scrolls horizontally takes the navigation and the header with it,
 * which on a touch device is how a reader loses the app.
 *
 * The same list query and the same paging as the grid. A table view that
 * fetched its own rows would be a second definition of what the library
 * currently is, and the two would disagree the first time a filter changed.
 */
export default function BookTable({
  books,
  sort,
  onSortChange,
  isLoading,
  hasMore,
  isLoadingMore,
  onLoadMore,
}: BookTableProps) {
  const { t, locale } = useTranslation();

  if (isLoading) {
    return (
      <div className="space-y-2" data-testid="book-table-skeletons">
        {Array.from({ length: SKELETON_ROWS }).map((_, index) => (
          <Skeleton key={index} className="h-8 w-full" />
        ))}
      </div>
    );
  }

  return (
    <>
      <div className="card overflow-x-auto">
        <table className="w-full min-w-max border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-paper-200 dark:border-paper-800">
              {COLUMNS.map((column) => {
                const way = direction(column, sort);
                const next = nextSort(column, sort);
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={column.sort ? way : undefined}
                    className={`whitespace-nowrap px-3 py-2 text-xs font-semibold text-paper-700 dark:text-paper-200 ${
                      column.numeric ? "text-right" : ""
                    }`}
                  >
                    {next === null ? (
                      t(column.label)
                    ) : (
                      <button
                        type="button"
                        onClick={() => onSortChange(next)}
                        className="inline-flex items-center gap-1 hover:text-accent-700 dark:hover:text-accent-300"
                      >
                        {t(column.label)}
                        {/* Always drawn, dimmed until this column is the one
                            ordering the list. Only 5 of the 21 columns can be
                            sorted, and with the chevron shown only when active
                            the sole always-visible difference was a hover
                            colour: the feature was there and undiscoverable.
                            `aria-hidden` because `aria-sort` on the header
                            already says this, in words. */}
                        <Icon
                          name="chevron"
                          aria-hidden="true"
                          className={`h-3 w-3 transition-opacity ${
                            way === "none"
                              ? "rotate-90 opacity-30"
                              : way === "ascending"
                                ? "-rotate-90"
                                : "rotate-90"
                          }`}
                        />
                      </button>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {books.map((book) => (
              <tr
                key={book.id}
                className="border-b border-paper-100 last:border-0 hover:bg-paper-50 dark:border-paper-800 dark:hover:bg-paper-800/50"
              >
                {COLUMNS.map((column) => (
                  <td
                    key={column.key}
                    className={`whitespace-nowrap px-3 py-1.5 text-paper-700 dark:text-paper-300 ${
                      column.numeric ? "text-right tabular-nums" : ""
                    }`}
                  >
                    {/* Only the title links. A whole row of links is one
                        destination announced twenty one times, and a reader
                        copying a publisher out of a cell should not navigate. */}
                    {column.key === "title" ? (
                      <Link
                        to={`/book/${book.id}`}
                        className="font-medium text-accent-700 hover:underline dark:text-accent-300"
                      >
                        {book.title}
                      </Link>
                    ) : (
                      column.render(book, t, locale)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
