/**
 * Tests for src/pages/PublicCataloguePage/PublicBookPage.tsx.
 *
 * One published record. The interesting half is the record it cannot draw: the
 * payload carries no member, no loan, no reading status and no price, so this
 * file asserts the shape of what arrives rather than trying to prove a negative
 * about the component. What proves the negative is
 * `backend/tests/schemas/test_public.py`, on the model that decides.
 */

import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { PublicBookPage } from "../../../src/pages/PublicCataloguePage";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

const RECORD = {
  id: 12,
  title: "Dune",
  subtitle: null,
  author: "Frank Herbert",
  authors: ["Frank Herbert"],
  publisher: "Chilton",
  year: 1965,
  isbn: "9780441013593",
  language: "en",
  page_count: 412,
  format: "paperback",
  series_name: "Dune",
  series_index: 1,
  description: "A desert planet.",
  cover_url: null,
  tags: [],
  categories: [],
  classifications: [
    { scheme: "ddc", number: "813.54", label: "American fiction" },
  ],
};

beforeEach(() => {
  localStorage.clear();
  api = mockApi();
  api.on(/\/api\/public\/books\/12/, { body: RECORD });
});

function render() {
  // Through a `<Routes>`, because the page reads the id with `useParams` and a
  // component rendered outside a matched route sees no params at all.
  return renderWithProviders(
    <Routes>
      <Route path="/catalogue/:id" element={<PublicBookPage />} />
    </Routes>,
    { route: "/catalogue/12" },
  );
}

describe("PublicBookPage", () => {
  it("shows the record", async () => {
    render();
    expect(
      await screen.findByRole("heading", { name: "Dune" }),
    ).toBeInTheDocument();
  });

  it("reads the bibliographic facts as pairs", async () => {
    // A `<dl>`, so a screen reader says "ISBN, 978..." rather than two
    // unrelated strings. Asserted through the term, which only exists in one.
    render();
    expect(await screen.findByText("ISBN")).toBeInTheDocument();
    expect(screen.getByText("9780441013593")).toBeInTheDocument();
  });

  it("shows the classification, which is what library mode is for", async () => {
    render();
    expect(await screen.findByText("813.54")).toBeInTheDocument();
    expect(screen.getByText("American fiction")).toBeInTheDocument();
  });

  it("answers a book that is not published with the same not found", async () => {
    // The server answers 404 for a book that never existed, one in the trash
    // and one marked private alike, so that a stranger cannot count through
    // ids. A client that told them apart would give back what was withheld.
    api.on(/\/api\/public\/books\/12/, {
      status: 404,
      body: { detail: "Book not found" },
    });
    render();

    expect(await screen.findByText("Book not found.")).toBeInTheDocument();
  });

  it("offers a way back to the catalogue from a missing record", async () => {
    api.on(/\/api\/public\/books\/12/, {
      status: 404,
      body: { detail: "Book not found" },
    });
    render();

    expect(
      await screen.findByRole("link", { name: "Back to the catalogue" }),
    ).toHaveAttribute("href", "/catalogue");
  });
});
