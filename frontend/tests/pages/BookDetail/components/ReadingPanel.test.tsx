/** Tests for src/pages/BookDetail/components/ReadingPanel.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BookOut } from "../../../../src/api/generated/model";
import ReadingPanel from "../../../../src/pages/BookDetail/components/ReadingPanel";
import { makeBook } from "../../../factories";
import { renderLocalised } from "../../../utils";

function renderPanel(book: Partial<BookOut> = {}) {
  renderLocalised(<ReadingPanel book={makeBook(book)} onRate={vi.fn()} />);
}

describe("ReadingPanel", () => {
  it("offers the rating control", () => {
    renderPanel();
    expect(
      screen.getByRole("radiogroup", { name: "Your rating" }),
    ).toBeInTheDocument();
  });

  it("shows both dates when they exist", () => {
    renderPanel({
      my_started_at: "2026-01-02T10:00:00",
      my_finished_at: "2026-01-20T10:00:00",
    });

    expect(screen.getByText(/Started/)).toBeInTheDocument();
    expect(screen.getByText(/Finished/)).toBeInTheDocument();
  });

  it("shows only the start when that is all there is", () => {
    renderPanel({ my_started_at: "2026-01-02T10:00:00", my_finished_at: null });

    expect(screen.getByText(/Started/)).toBeInTheDocument();
    expect(screen.queryByText(/Finished/)).not.toBeInTheDocument();
  });

  it("shows no date line for a book nobody has opened", () => {
    renderPanel({ my_started_at: null, my_finished_at: null });
    expect(screen.queryByText(/Started/)).not.toBeInTheDocument();
  });
});
