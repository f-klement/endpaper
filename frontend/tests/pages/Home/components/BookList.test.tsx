/** Tests for src/pages/Home/components/BookList.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  OwnershipStatus,
  ReadStatus,
} from "../../../../src/api/generated/model";
import BookList from "../../../../src/pages/Home/components/BookList";
import { makeBook, makeLoan, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

const DUNE = () =>
  makeBook({
    title: "Dune",
    author: "Frank Herbert",
    year: 1965,
    series_name: "Dune",
    series_index: 1,
    my_status: ReadStatus.reading,
    cover_url: "https://covers.example/dune.jpg",
  });

function renderList(props: Partial<Parameters<typeof BookList>[0]> = {}) {
  return renderLocalised(
    <BookList
      books={[DUNE()]}
      isLoading={false}
      hasMore={false}
      isLoadingMore={false}
      onLoadMore={() => {}}
      {...props}
    />,
  );
}

describe("BookList", () => {
  it("shows what identifies a book at a glance", () => {
    renderList();

    const row = screen.getByRole("listitem");
    expect(within(row).getByText("Dune")).toBeInTheDocument();
    expect(within(row).getByText(/Frank Herbert/)).toBeInTheDocument();
    expect(within(row).getByText(/1965/)).toBeInTheDocument();
    expect(within(row).getByText("Reading")).toBeInTheDocument();
  });

  it("says when a book is out on loan", () => {
    /** The list is for somebody looking for a book they know they have, and
     * "it is lent out" is one of the two answers to why it is not there. */
    renderList({
      books: [makeBook({ title: "Dune", active_loan: makeLoan() })],
    });

    expect(screen.getByText("Loaned")).toBeInTheDocument();
  });

  it("says when nobody has confirmed the library holds it", () => {
    renderList({
      books: [makeBook({ title: "Dune", ownership: OwnershipStatus.unknown })],
    });

    expect(screen.getByText("Not confirmed")).toBeInTheDocument();
  });

  it("marks neither on an ordinary book", () => {
    /** Both are the minority of a shelf, which is what makes them a signal
     * rather than a colour field. */
    renderList({
      books: [
        makeBook({ ownership: OwnershipStatus.owned, active_loan: null }),
      ],
    });

    expect(screen.queryByText("Loaned")).not.toBeInTheDocument();
    expect(screen.queryByText("Not confirmed")).not.toBeInTheDocument();
  });

  it("names the series and the number in it", () => {
    renderList();

    expect(screen.getByText(/Dune, book 1/)).toBeInTheDocument();
  });

  it("closes up around a fact the book does not have", () => {
    /** A row with holes reads as missing data rather than as data a book
     * does not have. */
    renderList({
      books: [
        makeBook({
          title: "Untitled",
          author: null,
          year: null,
          series_name: null,
        }),
      ],
    });

    const row = screen.getByRole("listitem");
    expect(within(row).queryByText("·")).not.toBeInTheDocument();
  });

  it("loads every cover lazily", () => {
    /** A list fits roughly three times as many rows on a screen as the grid
     * fits cards, so a page of them would otherwise fetch every image at once. */
    const { container } = renderList({
      books: [
        DUNE(),
        makeBook({ cover_url: "https://covers.example/other.jpg" }),
      ],
    });

    const covers = container.querySelectorAll("img");
    expect(covers).toHaveLength(2);
    for (const cover of covers) {
      expect(cover).toHaveAttribute("loading", "lazy");
    }
  });

  it("gives the cover no accessible name of its own", () => {
    /** The title sits beside it inside the same link, and a duplicate label is
     * noise in a screen reader's control list. An empty `alt` also takes the
     * image out of the accessibility tree entirely, which is why it cannot be
     * found by role here. */
    const { container } = renderList();

    expect(container.querySelector("img")).toHaveAttribute("alt", "");
    expect(screen.queryAllByRole("img")).toHaveLength(0);
    expect(screen.getByRole("link", { name: /Dune/ })).toBeInTheDocument();
  });

  it("makes the whole row one link to the book", () => {
    renderList();

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/book/1");
  });

  it("draws placeholders while the first page loads", () => {
    renderList({ isLoading: true, books: [] });

    expect(screen.getByTestId("book-list-skeletons")).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("offers the next page only when there is one", async () => {
    const onLoadMore = vi.fn();
    const { rerender } = renderList({ hasMore: false, onLoadMore });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(
      <BookList
        books={[DUNE()]}
        isLoading={false}
        hasMore
        isLoadingMore={false}
        onLoadMore={onLoadMore}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Load more/i }));

    expect(onLoadMore).toHaveBeenCalledOnce();
  });
});
