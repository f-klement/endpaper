/** Tests for src/pages/Home/components/BookTable.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BookCondition,
  BookFormat,
  BookSort,
  ReadStatus,
} from "../../../../src/api/generated/model";
import BookTable from "../../../../src/pages/Home/components/BookTable";
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
  });

function renderTable(
  props: Partial<Parameters<typeof BookTable>[0]> = {},
) {
  return renderLocalised(
    <BookTable
      books={[DUNE()]}
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
    // A whole row of links is one destination announced nineteen times, and a
    // reader copying a publisher out of a cell should not navigate.
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
      .click(within(screen.getByRole("columnheader", { name: /Title/ })).getByRole("button"));

    expect(onSortChange).toHaveBeenCalledWith(BookSort.title_desc);
  });

  it("marks a sortable column before it is the active one", () => {
    // 5 of the 19 columns can be sorted. With the chevron shown only when
    // active, the only always-visible difference was a hover colour, so the
    // feature was there and nobody could find it.
    renderTable({ sort: BookSort.title_asc });

    const author = screen.getByRole("columnheader", { name: /Author/ });
    expect(author).toHaveAttribute("aria-sort", "none");
    expect(within(author).getByRole("button").querySelector("svg")).not.toBeNull();
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
    renderTable({ books: [makeBook({ title: "Bare", publisher: null, year: null })] });

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

  it("offers the next page when there is one", async () => {
    const onLoadMore = vi.fn();
    renderTable({ hasMore: true, onLoadMore });

    await userEvent.setup().click(screen.getByRole("button", { name: /Load more/ }));

    expect(onLoadMore).toHaveBeenCalledOnce();
  });
});
