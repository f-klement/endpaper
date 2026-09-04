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

type SortDirection = "ascending" | "descending";

/**
 * One order a column offers.
 *
 * **`scheme` is set only where a column offers more than one**, and the call
 * number column is the only one that does. It draws Dewey and Library of
 * Congress notations side by side, and the two file by different rules, so
 * "sorted by call number" is not a complete statement: the header has to say
 * which shelf it is reading. See `backend/filing.py`.
 */
interface SortOption {
  sort: BookSort;
  direction: SortDirection;
  scheme?: ClassificationScheme;
}

interface Column {
  /**
   * The orders this column offers, in the order pressing it cycles them.
   * Empty where the API cannot order by it.
   *
   * **Deliberately not client side.** Sorting the rows in the browser would
   * sort only the page that has been loaded, silently, and a table headed
   * "Publisher, ascending" showing the first 25 books by title is worse than a
   * header that does nothing. So a column the backend cannot order by is plain
   * text.
   */
  sort: readonly SortOption[];
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
    sort: [
      { sort: BookSort.title_asc, direction: "ascending" },
      { sort: BookSort.title_desc, direction: "descending" },
    ],
    render: (book) => book.title,
  },
  author: {
    // One direction only: the API sorts by author ascending and has no
    // descending counterpart, and offering a toggle that silently reverses
    // nothing would be the client side sort this table refuses to do.
    sort: [{ sort: BookSort.author, direction: "ascending" }],
    render: (book) => book.author ?? "",
  },
  series: {
    sort: [{ sort: BookSort.series, direction: "ascending" }],
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
    sort: [
      { sort: BookSort.year_asc, direction: "ascending" },
      { sort: BookSort.year_desc, direction: "descending" },
    ],
    numeric: true,
    render: (book) => number(book.year),
  },
  publisher: {
    sort: [],
    render: (book) => book.publisher ?? "",
  },
  callNumber: {
    // **The only column offering two orders, and the only one that has to.**
    // It draws both schemes that place a book on a shelf, and the two file by
    // different rules: `filing.DeweyFiling` sorts a notation as its own text
    // and `filing.LccFiling` pads the class number, because `BF75` stands
    // before `BF575` on a shelf and after it in a string comparison. One order
    // over both would be a Dewey rule applied to LCC numbers, which is what
    // this replaced.
    //
    // Neither is the string this cell draws, which carries a scheme name in
    // the reader's language and both notations at once, and would therefore
    // sort by neither shelf. The API orders in SQL over the whole table: see
    // `_shelf_order` in `backend/shelf.py`.
    //
    // Ascending only, in both, because that is the one direction the API
    // offers. Pressing the header cycles Dewey, then Library of Congress, and
    // the header names whichever is running.
    sort: [
      {
        sort: BookSort.ddc,
        direction: "ascending",
        scheme: ClassificationScheme.ddc,
      },
      {
        sort: BookSort.lcc,
        direction: "ascending",
        scheme: ClassificationScheme.lcc,
      },
    ],
    // Every notation names its scheme, for the reason `ClassificationPanel`
    // gives: `004` is computing in Dewey and is not a Library of Congress call
    // number at all, so a notation shown without its scheme cannot be read.
    render: (book, t) =>
      callNumbers(book)
        .map((entry) => `${t(SCHEME_LABEL[entry.scheme])} ${entry.number}`)
        .join(" · "),
  },
  classification: {
    sort: [],
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
    sort: [],
    render: (book, t) => (book.format ? t(FORMAT_LABELS[book.format]) : ""),
  },
  condition: {
    sort: [],
    render: (book, t) =>
      book.condition ? t(CONDITION_LABELS[book.condition]) : "",
  },
  lending: {
    sort: [],
    render: (book, t) => (book.lending ? t(LENDING_LABELS[book.lending]) : ""),
  },
  discuss: {
    sort: [],
    // The names, not a tick. "Ask about it" is only useful if it says whom.
    render: (book) =>
      (book.discuss_with ?? []).map((member) => member.username).join(", "),
  },
  location: {
    sort: [],
    render: (book) => book.location ?? "",
  },
  pageCount: {
    sort: [],
    numeric: true,
    render: (book) => number(book.page_count),
  },
  language: {
    sort: [],
    render: (book) => book.language ?? "",
  },
  status: {
    sort: [],
    render: (book, t) => t(STATUS_LABELS[book.my_status ?? ReadStatus.unread]),
  },
  rating: {
    sort: [],
    numeric: true,
    render: (book) => number(book.my_rating),
  },
  tags: {
    sort: [],
    render: (book, _t, locale) =>
      (book.tags ?? []).map((tag) => tagName(tag, locale)).join(", "),
  },
  ownership: {
    sort: [],
    render: (book, t) =>
      t(OWNERSHIP_LABELS[book.ownership ?? OwnershipStatus.unknown]),
  },
  addedBy: {
    sort: [],
    render: (book) => book.added_by?.username ?? "",
  },
  addedAt: {
    // Newest first is the only order the API offers for this, so the column
    // sorts one way and says so through `aria-sort` rather than pretending to
    // toggle.
    sort: [{ sort: BookSort.newest, direction: "descending" }],
    render: (book, _t, locale) => date(book.added_at, locale),
  },
  price: {
    sort: [],
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
    sort: [],
    render: (book, _t, locale) => date(book.purchased_at, locale),
  },
  purchaseSource: {
    sort: [],
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

/** The order this column is running, or undefined when it is not the one. */
function activeOption(column: Column, sort: BookSort): SortOption | undefined {
  return column.sort.find((option) => option.sort === sort);
}

/** Which way this column is currently ordering, for `aria-sort`. */
function direction(column: Column, sort: BookSort): SortDirection | "none" {
  return activeOption(column, sort)?.direction ?? "none";
}

/**
 * The sort pressing this header should ask for next.
 *
 * `findIndex` answers -1 when this column is not the one ordering the list,
 * which the modulo turns into the first option. So a column offering one order
 * asks for that one again rather than turning itself off, which is what it did
 * before there was a list here.
 */
function nextSort(column: Column, sort: BookSort): BookSort | null {
  if (column.sort.length === 0) return null;
  const at = column.sort.findIndex((option) => option.sort === sort);
  return column.sort[(at + 1) % column.sort.length]!.sort;
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
                const active = activeOption(column, sort);
                return (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={column.sort.length > 0 ? way : undefined}
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
                        {/* Which shelf is being read, where the column offers
                            more than one. Only the call number column does,
                            and without this the reader cannot tell a Dewey
                            order from a Library of Congress one: the rows
                            simply come back differently. Inside the button, so
                            a screen reader gets it with the name rather than
                            after the sort direction. */}
                        {active?.scheme !== undefined && (
                          <span className="font-normal text-paper-600 dark:text-paper-400">
                            {t(SCHEME_LABEL[active.scheme])}
                          </span>
                        )}
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
