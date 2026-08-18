/** Tests for src/pages/Home/components/BookCard.tsx. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../../../utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  OwnershipStatus,
  ReadStatus,
  type BookOut,
} from "../../../../src/api/generated/model";
import BookCard from "../../../../src/pages/Home/components/BookCard";
import { makeBook, makeLoan, makeTag, resetIds } from "../../../factories";

beforeEach(resetIds);

function renderCard(book: BookOut) {
  return renderLocalised(<BookCard book={book} />);
}

function renderSelectable(book: BookOut, isSelected = false) {
  const onToggleSelect = vi.fn();
  renderLocalised(
    <BookCard
      book={book}
      isSelecting
      isSelected={isSelected}
      onToggleSelect={onToggleSelect}
    />,
  );
  return onToggleSelect;
}

describe("BookCard", () => {
  it("shows the title and author", () => {
    renderCard(makeBook({ title: "Dune", author: "Frank Herbert" }));
    expect(screen.getByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("Frank Herbert")).toBeInTheDocument();
  });

  it("omits the author line when there is none", () => {
    renderCard(makeBook({ title: "Anonymous", author: null }));
    expect(screen.getByText("Anonymous")).toBeInTheDocument();
    expect(screen.queryByText("Frank Herbert")).not.toBeInTheDocument();
  });

  it("links to the detail page", () => {
    renderCard(makeBook({ id: 42 }));
    expect(screen.getByRole("link")).toHaveAttribute("href", "/book/42");
  });

  describe("cover", () => {
    it("renders the image when there is one", () => {
      renderCard(makeBook({ title: "Dune", cover_url: "/covers/1.png" }));
      expect(screen.getByRole("img", { name: "Dune" })).toHaveAttribute(
        "src",
        "/covers/1.png",
      );
    });

    it("falls back to a placeholder when there is none", () => {
      renderCard(makeBook({ cover_url: null }));
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
      expect(screen.getByText("📖")).toBeInTheDocument();
    });

    it("loads lazily", () => {
      renderCard(makeBook({ title: "Dune", cover_url: "/covers/1.png" }));
      expect(screen.getByRole("img", { name: "Dune" })).toHaveAttribute(
        "loading",
        "lazy",
      );
    });

    it("hides an image that fails to load", () => {
      // Open Library cover URLs 404 often; a broken-image icon reads as a bug
      // in our app rather than a gap in their catalogue.
      renderCard(
        makeBook({ title: "Dune", cover_url: "https://example.com/gone.jpg" }),
      );
      const image = screen.getByRole("img", { name: "Dune" });
      image.dispatchEvent(new Event("error", { bubbles: true }));
      expect(image).toHaveStyle({ display: "none" });
    });
  });

  describe("reading status", () => {
    it.each([
      [ReadStatus.unread, "Unread"],
      [ReadStatus.reading, "Reading"],
      [ReadStatus.read, "Read"],
    ])("labels %s as %s", (status, label) => {
      renderCard(makeBook({ my_status: status }));
      expect(screen.getByText(label)).toBeInTheDocument();
    });

    it("treats a missing status as unread", () => {
      renderCard(makeBook({ my_status: undefined }));
      expect(screen.getByText("Unread")).toBeInTheDocument();
    });
  });

  describe("loan indicator", () => {
    it("marks a book that is out", () => {
      renderCard(makeBook({ active_loan: makeLoan() }));
      expect(screen.getByText("Loaned")).toBeInTheDocument();
    });

    it("shows nothing when the book is on the shelf", () => {
      renderCard(makeBook({ active_loan: null }));
      expect(screen.queryByText("Loaned")).not.toBeInTheDocument();
    });
  });

  describe("tags", () => {
    it("shows the first two", () => {
      renderCard(
        makeBook({
          tags: [
            makeTag({ name: "Fantasy" }),
            makeTag({ name: "Adult", category: "age" }),
          ],
        }),
      );
      expect(screen.getByText("Fantasy")).toBeInTheDocument();
      expect(screen.getByText("Adult")).toBeInTheDocument();
    });

    it("truncates beyond two so the card keeps its height", () => {
      renderCard(
        makeBook({
          tags: [
            makeTag({ name: "Fantasy" }),
            makeTag({ name: "Adult", category: "age" }),
            makeTag({ name: "Fiction", category: "type" }),
          ],
        }),
      );
      expect(screen.queryByText("Fiction")).not.toBeInTheDocument();
    });

    it("handles a book with no tags", () => {
      renderCard(makeBook({ tags: [] }));
      expect(screen.getByText("Unread")).toBeInTheDocument();
    });
  });
});

describe("BookCard ownership", () => {
  it("flags a book nobody has confirmed", () => {
    renderCard(makeBook({ ownership: OwnershipStatus.unknown }));
    expect(screen.getByText("Not confirmed")).toBeInTheDocument();
  });

  it("says nothing about a book that is simply here", () => {
    // A badge on every owned book would be noise across the whole grid.
    renderCard(makeBook({ ownership: OwnershipStatus.owned }));
    expect(screen.queryByText("Not confirmed")).not.toBeInTheDocument();
  });

  it("says nothing about a book marked as not owned", () => {
    renderCard(makeBook({ ownership: OwnershipStatus.not_owned }));
    expect(screen.queryByText("Not confirmed")).not.toBeInTheDocument();
  });
});

describe("BookCard while selecting", () => {
  it("becomes a checkbox rather than a link", () => {
    // A link whose navigation is suppressed announces as a link and behaves
    // like a dud. While selecting, the card genuinely is a checkbox.
    renderSelectable(makeBook({ title: "Dune" }));

    expect(screen.getByRole("checkbox", { name: "Dune" })).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("reports its checked state", () => {
    renderSelectable(makeBook({ title: "Dune" }), true);
    expect(screen.getByRole("checkbox", { name: "Dune" })).toBeChecked();
  });

  it("reports a tap upwards", async () => {
    const book = makeBook({ title: "Dune" });
    const onToggleSelect = renderSelectable(book);

    await userEvent
      .setup()
      .click(screen.getByRole("checkbox", { name: "Dune" }));

    expect(onToggleSelect).toHaveBeenCalledWith(book.id);
  });

  it("goes back to being a link when selection ends", () => {
    renderCard(makeBook({ title: "Dune" }));
    expect(screen.getByRole("link")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
