/** Tests for src/pages/BookDetail/components/BookHeader. */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../src/api/mutator";

import {
  type BookIdentifierOut,
  BookIdentifierScheme,
  Locale,
} from "../../../../src/api/generated/model";
import BookHeader from "../../../../src/pages/BookDetail/components/BookHeader";
import { makeBook } from "../../../factories";
import { renderLocalised } from "../../../utils";

type HeaderProps = ComponentProps<typeof BookHeader>;

function renderHeader(
  book = makeBook(),
  locale: Locale = Locale.en,
  props: Partial<Omit<HeaderProps, "book">> = {},
) {
  return renderLocalised(
    <BookHeader
      book={book}
      isRefreshing={false}
      refreshError={null}
      showGoodreadsLink={false}
      onBack={vi.fn<() => void>()}
      onUploadCover={vi.fn<(file: File) => void>()}
      onRefreshMetadata={vi.fn<() => void>()}
      onRemoveIdentifier={vi.fn<(identifier: BookIdentifierOut) => void>()}
      {...props}
    />,
    { locale },
  );
}

describe("the credit line", () => {
  it("links each name to that person's shelf", () => {
    renderHeader(makeBook({ author: "Terry Pratchett, Neil Gaiman" }));

    expect(
      screen.getByRole("link", { name: "Terry Pratchett" }),
    ).toHaveAttribute("href", "/?author=Terry%20Pratchett");
    expect(screen.getByRole("link", { name: "Neil Gaiman" })).toHaveAttribute(
      "href",
      "/?author=Neil%20Gaiman",
    );
  });

  it("reads as one sentence, not as fragments", () => {
    const { container } = renderHeader(
      makeBook({ author: "Terry Pratchett, Neil Gaiman" }),
    );

    expect(container.textContent).toContain("by Terry Pratchett, Neil Gaiman");
  });

  it("keeps the translated phrase whole in German", () => {
    // The name is located inside the translated sentence rather than the
    // sentence being assembled from pieces, so a language that puts the
    // placeholder somewhere else still reads correctly.
    const { container } = renderHeader(
      makeBook({ author: "Frank Herbert" }),
      Locale.de,
    );

    expect(container.textContent).toContain("von Frank Herbert");
  });

  it("falls back to the credit line when the payload predates the split", () => {
    // A response cached before `authors` existed still has to show who wrote
    // the book, as one link rather than as none.
    renderHeader(makeBook({ author: "Frank Herbert", authors: undefined }));

    expect(
      screen.getByRole("link", { name: "Frank Herbert" }),
    ).toBeInTheDocument();
  });

  it("says nothing at all when nobody is credited", () => {
    renderHeader(makeBook({ author: null }));

    expect(screen.queryByRole("link", { name: /Herbert/ })).toBeNull();
  });
});

describe("the chip row", () => {
  it("puts what a store calls the book after the ISBN, never before it", () => {
    // Order is the whole of this test. The reason is at the call site.
    const { container } = renderHeader(
      makeBook({
        isbn: "9780441013593",
        identifiers: [
          { id: 1, scheme: BookIdentifierScheme.asin, value: "B00J4YQKHY" },
        ],
      }),
    );

    const text = container.textContent ?? "";
    expect(text).toContain("ISBN: 9780441013593");
    expect(text.indexOf("ISBN: 9780441013593")).toBeLessThan(
      text.indexOf("Amazon reference: B00J4YQKHY"),
    );
  });

  it("says nothing about stores for a book no import named", () => {
    const { container } = renderHeader(makeBook({ identifiers: [] }));

    expect(container.textContent).not.toContain("reference:");
  });
});

describe("the lines under the title", () => {
  it("shows the subtitle a book has", () => {
    renderHeader(makeBook({ subtitle: "A Novel" }));

    expect(screen.getByText("A Novel")).toBeInTheDocument();
  });

  it("links a numbered series to its shelf in reading order", () => {
    renderHeader(makeBook({ series_name: "Dune Chronicles", series_index: 1 }));

    expect(
      screen.getByRole("link", { name: "Dune Chronicles, book 1" }),
    ).toHaveAttribute("href", "/?series=Dune%20Chronicles&sort=series");
  });

  it("names an unnumbered series without inventing a position", () => {
    renderHeader(makeBook({ series_name: "Discworld", series_index: null }));

    expect(
      screen.getByRole("link", { name: "Part of Discworld" }),
    ).toHaveAttribute("href", "/?series=Discworld&sort=series");
  });

  it("numbers a series whose index is zero", () => {
    // Zero is a position, which is why the guard is `!= null` and not
    // truthiness: a truthy test would call book 0 unnumbered.
    renderHeader(makeBook({ series_name: "Prequels", series_index: 0 }));

    expect(
      screen.getByRole("link", { name: "Prequels, book 0" }),
    ).toBeInTheDocument();
  });

  it("says nothing about a series for a book in none", () => {
    renderHeader(makeBook({ series_name: null }));

    expect(screen.queryByRole("link", { name: /Part of|, book / })).toBeNull();
  });
});

describe("the facts in the chip row", () => {
  it("shows every fact the book carries", () => {
    renderHeader(
      makeBook({
        publisher: "Chilton",
        year: 1965,
        page_count: 412,
        language: "en",
        location: "Hall shelf",
      }),
    );

    for (const fact of ["Chilton", "1965", "412 pages", "en", "Hall shelf"]) {
      expect(screen.getByText(fact)).toBeInTheDocument();
    }
  });

  it("counts a page count of zero rather than hiding it", () => {
    renderHeader(makeBook({ page_count: 0 }));

    expect(screen.getByText("0 pages")).toBeInTheDocument();
  });

  it("shows no chip for a fact the book does not carry", () => {
    // Counted rather than read: a guard taken off renders an empty chip,
    // which no text query can see.
    const { container } = renderHeader(
      makeBook({
        isbn: null,
        publisher: null,
        year: null,
        page_count: null,
        language: null,
        location: null,
        identifiers: [],
      }),
    );

    expect(container.querySelectorAll("span.rounded")).toHaveLength(0);
  });
});

describe("the cover control", () => {
  it("hands over the picked image and forgets it, so the same file can be picked again", async () => {
    const onUploadCover = vi.fn<(file: File) => void>();
    renderHeader(makeBook(), Locale.en, { onUploadCover });
    const input = screen.getByLabelText<HTMLInputElement>("Upload Cover");
    const file = new File(["cover"], "cover.png", { type: "image/png" });

    await userEvent.setup().upload(input, file);

    expect(onUploadCover).toHaveBeenCalledWith(file);
    expect(input.value).toBe("");
  });

  it("does nothing when the picker is closed without a file", () => {
    const onUploadCover = vi.fn<(file: File) => void>();
    renderHeader(makeBook(), Locale.en, { onUploadCover });

    fireEvent.change(screen.getByLabelText("Upload Cover"), {
      target: { files: [] },
    });

    expect(onUploadCover).not.toHaveBeenCalled();
  });

  it("opens the file picker from the visible button", async () => {
    renderHeader();
    const input = screen.getByLabelText<HTMLInputElement>("Upload Cover");
    const opened = vi.fn<() => void>();
    input.addEventListener("click", opened);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Upload Cover" }));

    expect(opened).toHaveBeenCalledOnce();
  });

  it("goes back from the back button", async () => {
    const onBack = vi.fn<() => void>();
    renderHeader(makeBook(), Locale.en, { onBack });

    await userEvent.setup().click(screen.getByRole("button", { name: "Back" }));

    expect(onBack).toHaveBeenCalledOnce();
  });
});

describe("refreshing the metadata", () => {
  it("offers a refresh for a book with an ISBN", async () => {
    const onRefreshMetadata = vi.fn<() => void>();
    renderHeader(makeBook({ isbn: "9780441013593" }), Locale.en, {
      onRefreshMetadata,
    });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Refresh Metadata" }));

    expect(onRefreshMetadata).toHaveBeenCalledOnce();
  });

  it("offers no refresh without an ISBN, which is what it looks up", () => {
    renderHeader(makeBook({ isbn: null }));

    expect(
      screen.queryByRole("button", { name: "Refresh Metadata" }),
    ).toBeNull();
  });

  it("cannot be pressed twice while one is running", () => {
    renderHeader(makeBook(), Locale.en, { isRefreshing: true });

    expect(
      screen.getByRole("button", { name: "Refreshing..." }),
    ).toBeDisabled();
  });

  it("says what the server said when a refresh failed", () => {
    renderHeader(makeBook(), Locale.en, {
      refreshError: new ApiError("No catalogue knows this ISBN.", 404),
    });

    expect(
      screen.getByText("No catalogue knows this ISBN."),
    ).toBeInTheDocument();
  });

  it("falls back to a general sentence for a failure that carries none", () => {
    renderHeader(makeBook(), Locale.en, { refreshError: {} });

    expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
  });
});

describe("the Goodreads link", () => {
  it("searches by ISBN in a new tab that is not told where it came from", () => {
    renderHeader(makeBook({ isbn: "9780441013593" }), Locale.en, {
      showGoodreadsLink: true,
    });

    const link = screen.getByRole("link", { name: "Look up on Goodreads" });
    expect(link).toHaveAttribute(
      "href",
      "https://www.goodreads.com/search?q=9780441013593",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("is still offered for a book with no ISBN, searching by title", () => {
    // Refreshing needs an ISBN and searching does not, so the two are gated
    // apart: this is the arm where they disagree.
    renderHeader(makeBook({ isbn: null, title: "Dune" }), Locale.en, {
      showGoodreadsLink: true,
    });

    expect(
      screen.getByRole("link", { name: "Look up on Goodreads" }),
    ).toHaveAttribute("href", "https://www.goodreads.com/search?q=Dune");
  });

  it("is absent while an admin has it switched off", () => {
    renderHeader(makeBook(), Locale.en, { showGoodreadsLink: false });

    expect(
      screen.queryByRole("link", { name: "Look up on Goodreads" }),
    ).toBeNull();
  });
});
