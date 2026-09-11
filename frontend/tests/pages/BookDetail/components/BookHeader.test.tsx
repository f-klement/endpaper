/** Tests for src/pages/BookDetail/components/BookHeader. */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  BookIdentifierScheme,
  Locale,
} from "../../../../src/api/generated/model";
import BookHeader from "../../../../src/pages/BookDetail/components/BookHeader";
import { makeBook } from "../../../factories";
import { renderLocalised } from "../../../utils";

function renderHeader(book = makeBook(), locale: Locale = Locale.en) {
  return renderLocalised(
    <BookHeader
      book={book}
      isRefreshing={false}
      refreshError={null}
      showGoodreadsLink={false}
      onBack={vi.fn()}
      onUploadCover={vi.fn()}
      onRefreshMetadata={vi.fn()}
      onRemoveIdentifier={vi.fn()}
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
