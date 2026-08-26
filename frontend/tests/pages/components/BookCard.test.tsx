/** Tests for src/pages/components/BookCard.tsx. */

import { fireEvent, screen } from "@testing-library/react";
import { renderLocalised } from "../../utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  LendingWillingness,
  OwnershipStatus,
  ReadStatus,
  type BookOut,
} from "../../../src/api/generated/model";
import BookCard from "../../../src/pages/components/BookCard";
import { makeBook, makeLoan, makeTag, makeUser, resetIds } from "../../factories";

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
      const { container } = renderCard(makeBook({ cover_url: null }));
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
      // A drawn icon now, not an emoji. It is decorative, so it is found by
      // shape rather than by an accessible name it deliberately does not have.
      expect(container.querySelector("svg")).toBeInTheDocument();
    });

    it("loads lazily", () => {
      renderCard(makeBook({ title: "Dune", cover_url: "/covers/1.png" }));
      expect(screen.getByRole("img", { name: "Dune" })).toHaveAttribute(
        "loading",
        "lazy",
      );
    });

    it("shows the placeholder when an image fails to load", () => {
      // Open Library cover URLs 404 often; a broken-image icon reads as a bug
      // in our app rather than a gap in their catalogue. The placeholder is
      // the same size as the cover, so the grid does not reflow around it.
      renderCard(
        makeBook({ title: "Dune", cover_url: "https://example.com/gone.jpg" }),
      );

      fireEvent.error(screen.getByRole("img", { name: "Dune" }));

      expect(screen.queryByRole("img")).not.toBeInTheDocument();
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
    it("shows the first three", () => {
      renderCard(
        makeBook({
          tags: [
            makeTag({ name: "Fantasy", category: "genre" }),
            makeTag({ name: "Adult", category: "age" }),
            makeTag({ name: "Fiction", category: "type" }),
          ],
        }),
      );
      expect(screen.getByText("Fantasy")).toBeInTheDocument();
      expect(screen.getByText("Adult")).toBeInTheDocument();
      expect(screen.getByText("Fiction")).toBeInTheDocument();
    });

    it("prefers a genre tag to whatever the API listed first", () => {
      // What a book *is* is the thing somebody scanning a shelf matches on. An
      // age band arriving first used to push the genre off the card entirely.
      renderCard(
        makeBook({
          tags: [
            makeTag({ name: "Adult", category: "age" }),
            makeTag({ name: "Fiction", category: "type" }),
            makeTag({ name: "Reference", category: "custom" }),
            makeTag({ name: "Fantasy", category: "genre" }),
          ],
        }),
      );
      expect(screen.getByText("Fantasy")).toBeInTheDocument();
      expect(screen.queryByText("Reference")).not.toBeInTheDocument();
    });

    it("truncates beyond three so the card keeps its height", () => {
      renderCard(
        makeBook({
          tags: [
            makeTag({ name: "Fantasy", category: "genre" }),
            makeTag({ name: "Adult", category: "age" }),
            makeTag({ name: "Fiction", category: "type" }),
            makeTag({ name: "Reference", category: "custom" }),
          ],
        }),
      );
      expect(screen.queryByText("Reference")).not.toBeInTheDocument();
    });

    it("handles a book with no tags", () => {
      renderCard(makeBook({ tags: [] }));
      expect(screen.getByText("Unread")).toBeInTheDocument();
    });
  });
});

describe("BookCard fold out", () => {
  const detailed = () =>
    makeBook({
      title: "Dune",
      publisher: "Chilton",
      year: 1965,
      location: "Loft box 3",
      page_count: 412,
      purchase_source: "The Oxfam on the high street",
    });

  it("starts closed", () => {
    renderCard(detailed());
    expect(screen.getByRole("button", { name: /Details for Dune/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("Chilton")).not.toBeInTheDocument();
  });

  it("opens without leaving the grid", async () => {
    renderCard(detailed());

    await userEvent.setup().click(
      screen.getByRole("button", { name: /Details for Dune/ }),
    );

    expect(screen.getByText("Chilton")).toBeInTheDocument();
    expect(screen.getByText("Loft box 3")).toBeInTheDocument();
    expect(screen.getByText("The Oxfam on the high street")).toBeInTheDocument();
  });

  it("says it is open, without pointing at an id that is not there", async () => {
    // The panel renders only when open, so `aria-controls` would dangle on
    // every closed card. ARIA requires the reference to resolve; `aria-expanded`
    // plus DOM adjacency says the same thing and is always true.
    renderCard(detailed());
    const toggle = screen.getByRole("button", { name: /Details for Dune/ });
    expect(toggle).not.toHaveAttribute("aria-controls");

    await userEvent.setup().click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps the toggle out of the link", () => {
    // A button inside an anchor is invalid, and browsers resolve the ambiguity
    // differently: some navigate, some fire the button.
    renderCard(detailed());

    const toggle = screen.getByRole("button", { name: /Details for Dune/ });

    expect(toggle.closest("a")).toBeNull();
  });

  it("offers nothing to open on a book with no other facts", () => {
    renderCard(makeBook({ title: "Bare", publisher: null, year: null }));

    expect(screen.queryByRole("button", { name: /Details for Bare/ })).toBeNull();
  });

  it("shows the tags the face of the card left out", async () => {
    renderCard(
      makeBook({
        title: "Dune",
        tags: [
          makeTag({ name: "Fantasy", category: "genre" }),
          makeTag({ name: "Adult", category: "age" }),
          makeTag({ name: "Fiction", category: "type" }),
          makeTag({ name: "Reference", category: "custom" }),
        ],
      }),
    );

    await userEvent.setup().click(
      screen.getByRole("button", { name: /Details for Dune/ }),
    );

    expect(screen.getByText("Reference")).toBeInTheDocument();
  });

  it("has no fold out while selecting", () => {
    // A button inside a button is invalid for the same reason, and somebody
    // ticking twenty boxes is not reading page counts.
    renderSelectable(detailed());

    expect(screen.queryByRole("button", { name: /Details for Dune/ })).toBeNull();
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

describe("BookCard talk-about-it marker", () => {
  it("is on the face of the card, not behind the fold out", () => {
    // The offer exists to be noticed by somebody browsing. A marker that
    // needs a click to find is one only the person who set it ever sees.
    renderCard(makeBook({ discuss_with: [makeUser({ username: "ana" })] }));
    expect(screen.getByText("Talk about it")).toBeInTheDocument();
  });

  it("appears for somebody else's offer, not only the reader's own", () => {
    renderCard(
      makeBook({
        my_wants_to_discuss: false,
        discuss_with: [makeUser({ username: "ana" })],
      }),
    );
    expect(screen.getByText("Talk about it")).toBeInTheDocument();
  });

  it("says nothing when nobody has offered", () => {
    renderCard(makeBook());
    expect(screen.queryByText("Talk about it")).not.toBeInTheDocument();
  });

  it("names who to ask in the fold out", async () => {
    renderCard(
      makeBook({
        title: "Dune",
        discuss_with: [
          makeUser({ username: "ana" }),
          makeUser({ username: "ben" }),
        ],
      }),
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Details for Dune/ }));

    expect(screen.getByText("ana, ben")).toBeInTheDocument();
  });
});

describe("BookCard lending willingness", () => {
  it("is in the fold out, in the reader's own words", async () => {
    renderCard(makeBook({ title: "Dune", lending: LendingWillingness.never }));

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Details for Dune/ }));

    expect(screen.getByText("Never lent")).toBeInTheDocument();
  });

  it("is left out of a book nobody has been asked about", async () => {
    renderCard(makeBook({ title: "Dune", publisher: "Chilton" }));

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Details for Dune/ }));

    expect(screen.queryByText("Lending")).not.toBeInTheDocument();
  });
});

describe("BookCard and multiple copies", () => {
  it("says so when the library holds more than one", () => {
    // Two copies are two rows and the grid draws both, so without this the
    // shelf looks like a catalogue that has double-added something.
    renderCard(makeBook({ title: "Dune", copy_count: 2 }));

    expect(screen.getByText("2 copies")).toBeInTheDocument();
  });

  it("says nothing about a book with one copy", () => {
    renderCard(makeBook({ title: "Dune", copy_count: 1 }));

    expect(screen.queryByText(/copies/)).not.toBeInTheDocument();
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
