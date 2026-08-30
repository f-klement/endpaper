import { Link } from "react-router-dom";

import {
  BookSort,
  ClassificationScheme,
  OwnershipStatus,
  ReadStatus,
  type BookOut,
  type ClassificationOut,
  type Locale,
} from "../../../api/generated/model";
import { Icon, Skeleton } from "../../../components";
import { tagName, useTranslation, type Translate } from "../../../i18n";
import { SCHEME_LABEL } from "../../../lib/classificationLabels";
import {
  COLUMN_KEYS,
  COLUMN_SPECS,
  type ColumnKey,
} from "../../../lib/libraryColumns";
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

/**
 * The two schemes that place a book on a shelf, against the two that say what
 * it is about.
 *
 * **Not a preference: `ClassificationScheme`'s own docstring draws this line.**
 * "GND is an authority file rather than a shelf order", LCC is a call number
 * (`BF575.S75 E64 2022`), and Dewey is the one that also sorts. So the call
 * number column holds notations and the classification column holds headings,
 * and neither is `location`, which is prose about a shelf in this house and
 * means nothing outside it.
 */
const CALL_NUMBER_SCHEMES: ClassificationScheme[] = [
  ClassificationScheme.ddc,
  ClassificationScheme.lcc,
];

function callNumbers(book: BookOut): ClassificationOut[] {
  return (book.classifications ?? []).filter((entry) =>
    CALL_NUMBER_SCHEMES.includes(entry.scheme),
  );
}

function subjectHeadings(book: BookOut): ClassificationOut[] {
  return (book.classifications ?? []).filter(
    (entry) => !CALL_NUMBER_SCHEMES.includes(entry.scheme),
  );
}

const COLUMNS: Record<ColumnKey, Column> = {
  title: {
    sort: { asc: BookSort.title_asc, desc: BookSort.title_desc },
    render: (book) => book.title,
  },
  author: {
    // One direction only: the API sorts by author ascending and has no
    // descending counterpart, and offering a toggle that silently reverses
    // nothing would be the client side sort this table refuses to do.
    sort: { asc: BookSort.author, desc: null },
    render: (book) => book.author ?? "",
  },
  series: {
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
  year: {
    sort: { asc: BookSort.year_asc, desc: BookSort.year_desc },
    numeric: true,
    render: (book) => number(book.year),
  },
  publisher: {
    sort: null,
    render: (book) => book.publisher ?? "",
  },
  callNumber: {
    // **The only sort here that is not on a column of its own.** The API
    // orders by `min(classifications.number) where scheme = ddc`, in SQL, over
    // the table: see `_DDC_ORDER` in `backend/shelf.py`. It is deliberately
    // not the string this cell draws, which carries a scheme name in the
    // reader's language and can hold a Library of Congress notation as well,
    // and would therefore sort by neither shelf's order. Ascending only,
    // because that is the one direction the API offers.
    sort: { asc: BookSort.ddc, desc: null },
    // Every notation names its scheme, for the reason `ClassificationPanel`
    // gives: `004` is computing in Dewey and is not a Library of Congress call
    // number at all, so a notation shown without its scheme cannot be read.
    render: (book, t) =>
      callNumbers(book)
        .map((entry) => `${t(SCHEME_LABEL[entry.scheme])} ${entry.number}`)
        .join(" · "),
  },
  classification: {
    sort: null,
    // The caption where there is one, the identifier where there is not, and
    // no scheme name: a subject heading is words rather than a notation, so
    // the argument for prefixing the call number does not reach it. GND is
    // why the fallback is that way round: its `number` is an opaque id
    // (`4203576-4`) and its `label` is the heading, while LCSH carries the
    // heading in `number` and no label at all.
    render: (book) =>
      subjectHeadings(book)
        .map((entry) => entry.label ?? entry.number)
        .join(", "),
  },
  format: {
    sort: null,
    render: (book, t) => (book.format ? t(FORMAT_LABELS[book.format]) : ""),
  },
  condition: {
    sort: null,
    render: (book, t) =>
      book.condition ? t(CONDITION_LABELS[book.condition]) : "",
  },
  lending: {
    sort: null,
    render: (book, t) => (book.lending ? t(LENDING_LABELS[book.lending]) : ""),
  },
  discuss: {
    sort: null,
    // The names, not a tick. "Ask about it" is only useful if it says whom.
    render: (book) =>
      (book.discuss_with ?? []).map((member) => member.username).join(", "),
  },
  location: {
    sort: null,
    render: (book) => book.location ?? "",
  },
  pageCount: {
    sort: null,
    numeric: true,
    render: (book) => number(book.page_count),
  },
  language: {
    sort: null,
    render: (book) => book.language ?? "",
  },
  status: {
    sort: null,
    render: (book, t) => t(STATUS_LABELS[book.my_status ?? ReadStatus.unread]),
  },
  rating: {
    sort: null,
    numeric: true,
    render: (book) => number(book.my_rating),
  },
  tags: {
    sort: null,
    render: (book, _t, locale) =>
      (book.tags ?? []).map((tag) => tagName(tag, locale)).join(", "),
  },
  ownership: {
    sort: null,
    render: (book, t) =>
      t(OWNERSHIP_LABELS[book.ownership ?? OwnershipStatus.unknown]),
  },
  addedBy: {
    sort: null,
    render: (book) => book.added_by?.username ?? "",
  },
  addedAt: {
    // Newest first is the only order the API offers for this, so the column
    // sorts one way and says so through `aria-sort` rather than pretending to
    // toggle.
    sort: { asc: null, desc: BookSort.newest },
    render: (book, _t, locale) => date(book.added_at, locale),
  },
  price: {
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
  purchasedAt: {
    sort: null,
    render: (book, _t, locale) => date(book.purchased_at, locale),
  },
  purchaseSource: {
    sort: null,
    render: (book) => book.purchase_source ?? "",
  },
};

/**
 * The columns to draw, in the canonical order, whatever order they arrive in.
 *
 * The stored set is already normalised, so this is belt and braces for one
 * property worth having structurally: the table's column order is
 * `COLUMN_KEYS` and nothing else can decide it. Reordering columns is a
 * feature this does not have, and this is where it would have to start.
 */
function drawn(columns: readonly ColumnKey[]): ColumnKey[] {
  const wanted = new Set<ColumnKey>(columns);
  return COLUMN_KEYS.filter((key) => wanted.has(key));
}

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
  /**
   * Which columns to draw. `lib/libraryColumns.ts` decides what may be in it.
   *
   * A prop rather than storage read here, so this component stays a function
   * of what it is handed and a test can draw one column without a browser.
   */
  columns: readonly ColumnKey[];
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
 * Twenty three columns exist and no phone will fit them, which is not meant to
 * be fixed by drawing fewer: **the table scrolls inside its own container**,
 * so the page body never scrolls sideways. A body that scrolls horizontally
 * takes the navigation and the header with it, which on a touch device is how
 * a reader loses the app.
 *
 * **Which of the twenty three are drawn is not this component's decision.** It
 * draws what `columns` names, in `COLUMN_KEYS` order. Where those come from,
 * and why a household and a cataloguer get different ones, is
 * `lib/libraryColumns.ts`.
 *
 * The same list query and the same paging as the grid. A table view that
 * fetched its own rows would be a second definition of what the library
 * currently is, and the two would disagree the first time a filter changed.
 */
export default function BookTable({
  books,
  columns,
  sort,
  onSortChange,
  isLoading,
  hasMore,
  isLoadingMore,
  onLoadMore,
}: BookTableProps) {
  const { t, locale } = useTranslation();
  const keys = drawn(columns);

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
              {keys.map((key) => {
                const column = COLUMNS[key];
                const way = direction(column, sort);
                const next = nextSort(column, sort);
                return (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={column.sort ? way : undefined}
                    className={`whitespace-nowrap px-3 py-2 text-xs font-semibold text-paper-700 dark:text-paper-200 ${
                      column.numeric ? "text-right" : ""
                    }`}
                  >
                    {next === null ? (
                      t(COLUMN_SPECS[key].label)
                    ) : (
                      <button
                        type="button"
                        onClick={() => onSortChange(next)}
                        className="inline-flex items-center gap-1 hover:text-accent-700 dark:hover:text-accent-300"
                      >
                        {t(COLUMN_SPECS[key].label)}
                        {/* Always drawn, dimmed until this column is the one
                            ordering the list. Only 6 of the 23 columns can be
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
                {keys.map((key) => (
                  <td
                    key={key}
                    className={`whitespace-nowrap px-3 py-1.5 text-paper-700 dark:text-paper-300 ${
                      COLUMNS[key].numeric ? "text-right tabular-nums" : ""
                    }`}
                  >
                    {/* Only the title links. A whole row of links is one
                        destination announced once per column, and a reader
                        copying a publisher out of a cell should not navigate. */}
                    {key === "title" ? (
                      <Link
                        to={`/book/${book.id}`}
                        className="font-medium text-accent-700 hover:underline dark:text-accent-300"
                      >
                        {book.title}
                      </Link>
                    ) : (
                      COLUMNS[key].render(book, t, locale)
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
