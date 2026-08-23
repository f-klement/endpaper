/** Tests for src/pages/QuotesPage/components/QuoteCard.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import QuoteCard from "../../../../src/pages/QuotesPage/components/QuoteCard";
import { makeQuoteWithBook, makeUser } from "../../../factories";
import { renderLocalised } from "../../../utils";

describe("QuoteCard", () => {
  it("puts the passage in a quotation, not in body text", () => {
    renderLocalised(
      <QuoteCard quote={makeQuoteWithBook({ text: "Call me Ishmael" })} />,
    );
    expect(screen.getByText("Call me Ishmael").tagName).toBe("BLOCKQUOTE");
  });

  it("names the book, its author, the page and who saved it", () => {
    renderLocalised(
      <QuoteCard
        quote={makeQuoteWithBook({
          book_title: "Dune",
          book_author: "Frank Herbert",
          page: 214,
          author: makeUser({ username: "kim" }),
        })}
      />,
    );

    expect(screen.getByText("Dune")).toBeInTheDocument();
    expect(
      screen.getByText("Frank Herbert · p. 214 · kim"),
    ).toBeInTheDocument();
  });

  it("leaves out the parts a quote does not have", () => {
    // A book with no author and a quote with no page: the separators must not
    // be left stranded, which is why the line is joined from what is present
    // rather than written out with dots between fixed slots.
    renderLocalised(
      <QuoteCard
        quote={makeQuoteWithBook({
          book_author: null,
          page: null,
          author: makeUser({ username: "kim" }),
        })}
      />,
    );

    expect(screen.getByText("kim")).toBeInTheDocument();
  });

  it("shows the remark when there is one", () => {
    renderLocalised(
      <QuoteCard quote={makeQuoteWithBook({ note: "Why this one" })} />,
    );
    expect(screen.getByText("Why this one")).toBeInTheDocument();
  });
});
