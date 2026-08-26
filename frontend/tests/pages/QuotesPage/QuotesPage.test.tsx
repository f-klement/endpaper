/** Tests for src/pages/QuotesPage. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import QuotesPage from "../../../src/pages/QuotesPage";
import { makeQuoteWithBook, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

function page(items: unknown[], total = items.length, pageNumber = 1) {
  return { items, total, page: pageNumber, page_size: 50 };
}

beforeEach(() => {
  resetIds();
  api = mockApi();
});

describe("QuotesPage", () => {
  it("lists a passage with the book it came from", async () => {
    api.on("/api/books/quotes", {
      body: page([
        makeQuoteWithBook({ text: "Fear is the mind-killer", book_title: "Dune" }),
      ]),
    });
    renderWithProviders(<QuotesPage />);

    expect(
      await screen.findByText("Fear is the mind-killer"),
    ).toBeInTheDocument();
    expect(screen.getByText("Dune")).toBeInTheDocument();
  });

  it("links each row to the book it came from", async () => {
    api.on("/api/books/quotes", {
      body: page([makeQuoteWithBook({ book_id: 12 })]),
    });
    renderWithProviders(<QuotesPage />);

    const link = await screen.findByRole("link", { name: /Dune/ });
    expect(link).toHaveAttribute("href", "/book/12");
  });

  it("says when there are none", async () => {
    api.on("/api/books/quotes", { body: page([]) });
    renderWithProviders(<QuotesPage />);

    expect(await screen.findByText("No quotes saved yet")).toBeInTheDocument();
  });

  it("asks for the first page with a bounded page size", async () => {
    // The API caps `page_size` at 200 and answers 422 above it. Asking for
    // more than it allows would make the whole page an error state.
    api.on("/api/books/quotes", { body: page([]) });
    renderWithProviders(<QuotesPage />);
    await screen.findByText("No quotes saved yet");

    expect(api.calls[0]!.url).toContain("page=1");
    expect(api.calls[0]!.url).toContain("page_size=50");
  });

  it("offers no paging when everything fits on one page", async () => {
    api.on("/api/books/quotes", { body: page([makeQuoteWithBook()]) });
    renderWithProviders(<QuotesPage />);
    await screen.findByRole("link", { name: /Dune/ });

    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });

  it("asks for the next page when the reader moves on", async () => {
    api.on("/api/books/quotes", { body: page([makeQuoteWithBook()], 120) });
    renderWithProviders(<QuotesPage />);
    await screen.findByRole("link", { name: /Dune/ });

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(api.calls.at(-1)!.url).toContain("page=2");
  });

  it("keeps the list on screen while the next page loads", async () => {
    // The page number is in the query key, so without `placeholderData` the
    // whole page drops back to a spinner on every click and the heading goes
    // with it.
    api.on("/api/books/quotes", { body: page([makeQuoteWithBook()], 120) });
    renderWithProviders(<QuotesPage />);
    await screen.findByRole("link", { name: /Dune/ });

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(screen.getByRole("link", { name: /Dune/ })).toBeInTheDocument();
  });

  it("reports a failure rather than an empty shelf", async () => {
    // The distinction is the point: an empty state here would claim the
    // library has saved nothing, which is a different and wrong statement
    // from "this request failed".
    api.on("/api/books/quotes", { status: 500, body: {} });
    renderWithProviders(<QuotesPage />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("No quotes saved yet")).not.toBeInTheDocument();
  });
});
