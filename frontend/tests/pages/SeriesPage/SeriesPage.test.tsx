/** Tests for src/pages/SeriesPage. */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import SeriesPage from "../../../src/pages/SeriesPage";
import { resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
});

describe("SeriesPage", () => {
  it("lists the series", async () => {
    api.on("/api/books/series", {
      body: [{ name: "Dune", book_count: 3, missing_indexes: [2] }],
    });
    renderWithProviders(<SeriesPage />);

    expect(await screen.findByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("Missing: 2")).toBeInTheDocument();
  });

  it("says when there are none", async () => {
    api.on("/api/books/series", { body: [] });
    renderWithProviders(<SeriesPage />);

    expect(await screen.findByText("No series yet")).toBeInTheDocument();
  });

  it("surfaces a failure", async () => {
    api.on("/api/books/series", { status: 500, body: { detail: "Nope" } });
    renderWithProviders(<SeriesPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});
