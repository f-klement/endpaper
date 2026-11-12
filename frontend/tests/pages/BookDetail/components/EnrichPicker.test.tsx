/** Tests for src/pages/BookDetail/components/EnrichPicker.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { BookMatch } from "../../../../src/api/generated/model";
import EnrichPicker from "../../../../src/pages/BookDetail/components/EnrichPicker";
import { renderLocalised } from "../../../utils";

const DUNE: BookMatch = {
  title: "Dune",
  subtitle: "Deluxe Edition",
  publisher: "Chilton",
  year: 1965,
  language: "en",
  page_count: 412,
  source: "open_library+google_books",
  isbn13: "9780441013593",
  classifications: [
    { scheme: "ddc", number: "813.54", label: "American fiction" },
    { scheme: "lcc", number: "PS3558.E63" },
  ],
};

const BARE: BookMatch = { title: "Untitled" };

type Props = Parameters<typeof EnrichPicker>[0];

function renderPicker(overrides: Partial<Props> = {}) {
  const props = {
    candidates: [DUNE],
    isSearching: false,
    isWorking: false,
    isConfigured: true,
    error: null,
    onChoose: vi.fn<Props["onChoose"]>(),
    onClose: vi.fn<Props["onClose"]>(),
    ...overrides,
  };
  renderLocalised(<EnrichPicker {...props} />);
  return props;
}

function row(title: string): HTMLElement {
  return screen.getByRole("button", { name: new RegExp(`^${title}`) });
}

describe("EnrichPicker", () => {
  describe("while there is no list", () => {
    it("shows a spinner and no verdict while it searches", () => {
      renderPicker({ candidates: [], isSearching: true });

      expect(
        screen.getByRole("status", { name: "Searching..." }),
      ).toBeVisible();
      expect(screen.queryByText(/does not have a record/)).toBeNull();
    });

    it("says the catalogue has no record once an empty search ends", () => {
      renderPicker({ candidates: [] });

      expect(screen.getByText(/does not have a record/)).toBeVisible();
    });

    it("shows the error in place of the empty verdict", () => {
      renderPicker({ candidates: [], error: new Error("Quota exceeded") });

      expect(screen.getByRole("alert")).toHaveTextContent("Quota exceeded");
      expect(screen.queryByText(/does not have a record/)).toBeNull();
    });

    it("falls back to a general sentence for an error that carries none", () => {
      renderPicker({ candidates: [], error: {} });

      expect(screen.getByRole("alert")).toHaveTextContent(
        "Something went wrong.",
      );
    });
  });

  describe("one edition", () => {
    it("names it, its subtitle, its imprint and what it would add", () => {
      renderPicker();

      const button = row("Dune");
      expect(button).toHaveTextContent("Deluxe Edition");
      expect(button).toHaveTextContent("Chilton · 1965 · EN");
      expect(button).toHaveTextContent(
        "412 pages · open_library, google_books",
      );
    });

    it("lists each classification it would post back", () => {
      renderPicker();

      const button = row("Dune");
      expect(button).toHaveTextContent("DDC 813.54: American fiction");
      expect(button).toHaveTextContent("LCC PS3558.E63");
      expect(button).not.toHaveTextContent("No classifications proposed.");
    });

    it("says so when it carries no classification", () => {
      renderPicker({ candidates: [BARE] });

      expect(row("Untitled")).toHaveTextContent("No classifications proposed.");
    });

    it("leaves out the details it does not carry", () => {
      renderPicker({ candidates: [BARE] });

      const button = row("Untitled");
      expect(button).not.toHaveTextContent("pages");
      expect(button).not.toHaveTextContent("·");
    });

    it("hands the chosen edition back", async () => {
      const props = renderPicker({ candidates: [BARE, DUNE] });

      await userEvent.setup().click(row("Dune"));

      expect(props.onChoose).toHaveBeenCalledExactlyOnceWith(DUNE);
    });

    it("cannot be chosen while a choice is being written", () => {
      renderPicker({ isWorking: true });

      expect(row("Dune")).toBeDisabled();
    });
  });

  describe("the note on a missing key", () => {
    it("is shown beside results found without a Google Books key", () => {
      renderPicker({ isConfigured: false });

      expect(screen.getByText(/Searching Open Library/)).toBeVisible();
    });

    it("is not shown with a key", () => {
      renderPicker();

      expect(screen.queryByText(/Searching Open Library/)).toBeNull();
    });

    it("is not shown when there are no results to qualify", () => {
      renderPicker({ candidates: [], isConfigured: false });

      expect(screen.queryByText(/Searching Open Library/)).toBeNull();
    });
  });
});
