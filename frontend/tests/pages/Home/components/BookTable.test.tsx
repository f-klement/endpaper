/** Tests for src/pages/Home/components/BookTable.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BookCondition,
  BookFormat,
  BookSort,
  ClassificationScheme,
  LendingWillingness,
  ReadStatus,
} from "../../../../src/api/generated/model";
import BookTable from "../../../../src/pages/Home/components/BookTable";
import {
  AVAILABLE_COLUMNS,
  DEFAULT_COLUMNS,
} from "../../../../src/lib/libraryColumns";
import { makeBook, makeTag, makeUser, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

const DUNE = () =>
  makeBook({
    title: "Dune",
    author: "Frank Herbert",
    publisher: "Chilton",
    year: 1965,
    page_count: 412,
    language: "en",
    location: "Loft box 3",
    format: BookFormat.paperback,
    condition: BookCondition.good,
    my_status: ReadStatus.reading,
    my_rating: 4,
    series_name: "Dune",
    series_index: 1,
    added_by: makeUser({ username: "kim" }),
    tags: [makeTag({ name: "Science Fiction" })],
    purchase_price_minor: 1299,
    purchase_currency: "EUR",
    purchase_source: "The Oxfam on the high street",
    lending: LendingWillingness.happy,
    discuss_with: [makeUser({ username: "ana" })],
  });

function renderTable(props: Partial<Parameters<typeof BookTable>[0]> = {}) {
  return renderLocalised(
    <BookTable
      books={[DUNE()]}
      columns={DEFAULT_COLUMNS.household}
      sort={BookSort.title_asc}
      onSortChange={() => {}}
      isLoading={false}
      hasMore={false}
      isLoadingMore={false}
      onLoadMore={() => {}}
      {...props}
    />,
  );
}

describe("BookTable", () => {
  it("shows the metadata a grid of covers cannot", () => {
    renderTable();

    const row = screen.getAllByRole("row")[1]!;
    for (const value of [
      "Frank Herbert",
      "Chilton",
      "1965",
      "412",
      "Loft box 3",
      "Paperback",
      "Good",
      "Science Fiction",
      "kim",
      "12.99 EUR",
      "The Oxfam on the high street",
      "Happy to lend",
      // The names, not a tick: "ask about it" is only useful if it says whom.
      "ana",
    ]) {
      expect(within(row).getByText(value)).toBeInTheDocument();
    }
  });

  it("heads every column with a whole phrase", () => {
    renderTable();

    expect(
      screen.getByRole("columnheader", { name: /Year published/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /Page count/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /Reading status/ }),
    ).toBeInTheDocument();
  });

  it("links only the title", () => {
    // A whole row of links is one destination announced once per column, and
    // a reader copying a publisher out of a cell should not navigate.
    renderTable();

    const row = screen.getAllByRole("row")[1]!;
    expect(within(row).getAllByRole("link")).toHaveLength(1);
    expect(within(row).getByRole("link")).toHaveTextContent("Dune");
  });

  it("says which column is ordering the list", () => {
    renderTable({ sort: BookSort.title_asc });

    expect(screen.getByRole("columnheader", { name: /Title/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
  });

  it("asks the server for the other direction", async () => {
    const onSortChange = vi.fn();
    renderTable({ sort: BookSort.title_asc, onSortChange });

    await userEvent
      .setup()
      .click(
        within(screen.getByRole("columnheader", { name: /Title/ })).getByRole(
          "button",
        ),
      );

    expect(onSortChange).toHaveBeenCalledWith(BookSort.title_desc);
  });

  it("marks a sortable column before it is the active one", () => {
    // 6 of the 23 columns can be sorted. With the chevron shown only when
    // active, the only always-visible difference was a hover colour, so the
    // feature was there and nobody could find it.
    renderTable({ sort: BookSort.title_asc });

    const author = screen.getByRole("columnheader", { name: /Author/ });
    expect(author).toHaveAttribute("aria-sort", "none");
    expect(
      within(author).getByRole("button").querySelector("svg"),
    ).not.toBeNull();
  });

  it("does not offer to sort a column the server cannot order by", () => {
    // Sorting those in the browser would sort only the page that has been
    // loaded, silently.
    renderTable();

    const publisher = screen.getByRole("columnheader", { name: /Publisher/ });
    expect(within(publisher).queryByRole("button")).toBeNull();
    expect(publisher).not.toHaveAttribute("aria-sort");
  });

  it("leaves a cell empty rather than inventing a value", () => {
    renderTable({
      books: [makeBook({ title: "Bare", publisher: null, year: null })],
    });

    const row = screen.getAllByRole("row")[1]!;
    expect(within(row).getByRole("link")).toHaveTextContent("Bare");
  });

  it("scrolls inside its own container", () => {
    // The page body must never scroll sideways: it would take the navigation
    // and the header with it, which on a touch device loses the app.
    const { container } = renderTable();

    const table = container.querySelector("table");
    expect(table?.parentElement?.className).toContain("overflow-x-auto");
  });

  it("draws placeholders while the first page loads", () => {
    renderTable({ isLoading: true });

    expect(screen.getByTestId("book-table-skeletons")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("draws only the columns it is handed", () => {
    renderTable({ columns: ["title", "author"] });

    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
    expect(
      screen.queryByRole("columnheader", { name: /Publisher/ }),
    ).toBeNull();
  });

  it("draws them in the table's order whatever order they arrive in", () => {
    renderTable({ columns: ["publisher", "author", "title"] });

    expect(
      screen.getAllByRole("columnheader").map((cell) => cell.textContent),
    ).toEqual(["Title", "Author", "Publisher"]);
  });
});

/**
 * The two columns a cataloguer works from.
 *
 * Both read data that was already on the payload: `classifications`, which #19
 * shipped. Nothing here is derived and nothing new is stored, which is what
 * made this ticket an S.
 */
describe("BookTable, the cataloguer's columns", () => {
  const CATALOGUED = () =>
    makeBook({
      title: "Emotion and stress",
      author: "E. Ochsner",
      publisher: "Chilton",
      year: 2022,
      location: "Reading room, case 2",
      classifications: [
        { scheme: ClassificationScheme.ddc, number: "155.9042", label: null },
        {
          scheme: ClassificationScheme.lcc,
          number: "BF575.S75 E64 2022",
          label: null,
        },
        { scheme: ClassificationScheme.lcsh, number: "Stress management" },
        {
          scheme: ClassificationScheme.gnd,
          number: "4203576-4",
          label: "Stressbewältigung",
        },
      ],
    });

  function cell(name: RegExp): HTMLElement {
    const headers = screen.getAllByRole("columnheader");
    const index = headers.findIndex((header) => name.test(header.textContent!));
    expect(index).toBeGreaterThanOrEqual(0);
    return within(screen.getAllByRole("row")[1]!).getAllByRole("cell")[index]!;
  }

  it("names the scheme on every call number", () => {
    // `ClassificationPanel`'s reason, and it is the same one: `004` is
    // computing in Dewey and is not a Library of Congress call number at all.
    renderTable({
      books: [CATALOGUED()],
      columns: ["title", "callNumber"],
    });

    expect(cell(/Call number/)).toHaveTextContent(
      "Dewey 155.9042 · Library of Congress BF575.S75 E64 2022",
    );
  });

  it("keeps the subjects out of the call number", () => {
    // The split is `ClassificationScheme`'s own: GND is an authority file
    // rather than a shelf order, and an LCSH heading is a phrase.
    renderTable({
      books: [CATALOGUED()],
      columns: ["title", "callNumber", "classification"],
    });

    expect(cell(/Call number/)).not.toHaveTextContent("Stress management");
    expect(cell(/Subjects/)).toHaveTextContent(
      "Stress management, Stressbewältigung",
    );
    expect(cell(/Subjects/)).not.toHaveTextContent("155.9042");
  });

  it("shows the GND heading rather than its identifier", () => {
    // Its `number` is an opaque id and its `label` is the heading. LCSH is the
    // other way round, which is why the fallback goes label first.
    renderTable({
      books: [CATALOGUED()],
      columns: ["title", "classification"],
    });

    expect(cell(/Subjects/)).not.toHaveTextContent("4203576-4");
  });

  it("does not read the shelf note as a call number", () => {
    // The obvious shortcut and the mistake. `location` is prose about where a
    // book stands in this house; it sorts against nothing and means nothing
    // outside it.
    renderTable({
      books: [makeBook({ location: "Reading room, case 2" })],
      columns: ["title", "callNumber", "location"],
    });

    expect(cell(/Call number/).textContent).toBe("");
    expect(cell(/Where it is/)).toHaveTextContent("Reading room, case 2");
  });

  it("asks the server for the Dewey order, not for the cell's text", async () => {
    // The cell reads "Dewey 155.9042": a scheme name in the reader's language
    // followed by a notation, and a second notation from a different shelf
    // order after that. Ordering the library by that string would order it by
    // the word "Dewey". `BookSort.ddc` is
    // `min(classifications.number) where scheme = ddc`, in SQL, over the whole
    // table rather than over the page that has been loaded.
    const onSortChange = vi.fn();
    renderTable({
      books: [CATALOGUED()],
      columns: ["title", "callNumber"],
      onSortChange,
    });

    const header = screen.getByRole("columnheader", { name: /Call number/ });
    await userEvent.setup().click(within(header).getByRole("button"));

    expect(onSortChange).toHaveBeenCalledWith(BookSort.ddc);
    expect(onSortChange).toHaveBeenCalledTimes(1);
  });

  it("draws the rows in the order it was given them", () => {
    // The other half of the same property: nothing here reorders anything, so
    // no rendered string can be the sort key even by accident. These two are
    // in the reverse of their Dewey order on purpose.
    renderTable({
      books: [
        makeBook({
          title: "Later on the shelf",
          classifications: [
            { scheme: ClassificationScheme.ddc, number: "823.912" },
          ],
        }),
        makeBook({
          title: "Earlier on the shelf",
          classifications: [
            { scheme: ClassificationScheme.ddc, number: "004" },
          ],
        }),
      ],
      columns: ["title", "callNumber"],
      sort: BookSort.ddc,
    });

    expect(
      screen
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.textContent),
    ).toEqual([
      expect.stringContaining("Later on the shelf"),
      expect.stringContaining("Earlier on the shelf"),
    ]);
  });

  it("draws both when a cataloguer opens the table", () => {
    renderTable({
      books: [CATALOGUED()],
      columns: DEFAULT_COLUMNS.cataloguer,
    });

    for (const name of [/Call number/, /Subjects/]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    // And the household's own columns are away, which is user story 2.
    expect(
      screen.queryByRole("columnheader", { name: /Ownership/ }),
    ).toBeNull();
    expect(
      screen.queryByRole("columnheader", { name: /Reading status/ }),
    ).toBeNull();
  });

  it("can still draw every column a cataloguer is offered", () => {
    renderTable({
      books: [CATALOGUED()],
      columns: AVAILABLE_COLUMNS.cataloguer,
    });

    expect(screen.getAllByRole("columnheader")).toHaveLength(
      AVAILABLE_COLUMNS.cataloguer.length,
    );
  });
});

describe("BookTable, paging", () => {
  it("offers the next page when there is one", async () => {
    const onLoadMore = vi.fn();
    renderTable({ hasMore: true, onLoadMore });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Load more/ }));

    expect(onLoadMore).toHaveBeenCalledOnce();
  });
});
