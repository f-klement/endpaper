/** Tests for src/pages/ScanPage/components/GoogleSearchPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { GoogleBooksMatch } from "../../../../src/api/generated/model";
import GoogleSearchPanel from "../../../../src/pages/ScanPage/components/GoogleSearchPanel";
import { renderLocalised } from "../../../utils";

function match(overrides: Partial<GoogleBooksMatch> = {}): GoogleBooksMatch {
  return {
    google_books_id: "abc",
    title: "Dune",
    author: "Frank Herbert",
    publisher: "Chilton",
    year: 1965,
    ...overrides,
  };
}

function renderPanel(
  overrides: Partial<Parameters<typeof GoogleSearchPanel>[0]> = {},
) {
  const props = {
    isConfigured: true,
    onOpenHelp: vi.fn(),
    query: "",
    matches: [] as GoogleBooksMatch[],
    isSearching: false,
    isEmpty: false,
    error: null,
    onQueryChange: vi.fn(),
    onSubmit: vi.fn(),
    onChoose: vi.fn(),
    ...overrides,
  };
  renderLocalised(<GoogleSearchPanel {...props} />);
  return props;
}

describe("GoogleSearchPanel", () => {
  it("reports each keystroke upwards", async () => {
    const props = renderPanel();

    await userEvent
      .setup()
      .type(screen.getByLabelText("Search Google Books"), "d");

    expect(props.onQueryChange).toHaveBeenCalledWith("d");
  });

  it("submits on enter as well as on the button", async () => {
    const props = renderPanel({ query: "dune" });

    await userEvent
      .setup()
      .type(screen.getByLabelText("Search Google Books"), "{Enter}");

    expect(props.onSubmit).toHaveBeenCalledOnce();
  });

  describe("the submit button", () => {
    it("is disabled for a query too short to be worth a request", () => {
      // Each search spends somebody's Google Books quota, so a one-character
      // query is stopped here rather than at the server.
      renderPanel({ query: "d" });
      expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
    });

    it("is enabled once there is enough to go on", () => {
      renderPanel({ query: "du" });
      expect(screen.getByRole("button", { name: "Search" })).toBeEnabled();
    });

    it("is disabled while a search is running", () => {
      renderPanel({ query: "dune", isSearching: true });
      expect(
        screen.getByRole("button", { name: "Searching..." }),
      ).toBeDisabled();
    });
  });

  describe("results", () => {
    it("lists each candidate", () => {
      renderPanel({
        matches: [match({ title: "Dune" }), match({ title: "Dune Messiah" })],
      });
      expect(screen.getByText("Dune")).toBeInTheDocument();
      expect(screen.getByText("Dune Messiah")).toBeInTheDocument();
    });

    it("summarises an edition so two printings can be told apart", () => {
      renderPanel({ matches: [match({ publisher: "Ace", year: 1990 })] });
      expect(
        screen.getByText("Frank Herbert · Ace · 1990"),
      ).toBeInTheDocument();
    });

    it("leaves out the parts a record does not have", () => {
      renderPanel({ matches: [match({ publisher: null, year: null })] });
      expect(screen.getByText("Frank Herbert")).toBeInTheDocument();
    });

    it("hands the chosen record upwards", async () => {
      const chosen = match({ title: "Dune" });
      const props = renderPanel({ matches: [chosen] });

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: /Dune/ }));

      expect(props.onChoose).toHaveBeenCalledWith(chosen);
    });

    it("says that nothing is saved yet", () => {
      // The panel picks which book; the confirm step is what writes one.
      renderPanel({ matches: [match()] });
      expect(
        screen.getByText(/Nothing is saved until you confirm/),
      ).toBeInTheDocument();
    });

    it("renders results that share a missing id", () => {
      // The volume id is optional in the payload, and two undefined keys
      // would otherwise collapse into a single row.
      renderPanel({
        matches: [
          match({ google_books_id: null, title: "First" }),
          match({ google_books_id: null, title: "Second" }),
        ],
      });
      expect(screen.getByText("First")).toBeInTheDocument();
      expect(screen.getByText("Second")).toBeInTheDocument();
    });
  });

  it("says so when a search matched nothing", () => {
    renderPanel({ isEmpty: true });
    expect(screen.getByText(/No matches/)).toBeInTheDocument();
  });

  it("shows a failure", () => {
    renderPanel({ error: new Error("Google Books rejected the API key.") });
    expect(screen.getByRole("alert")).toHaveTextContent("rejected the API key");
  });

  it("shows neither results nor an empty message before the first search", () => {
    renderPanel();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    expect(screen.queryByText(/No matches/)).not.toBeInTheDocument();
  });
});

describe("GoogleSearchPanel without a key", () => {
  it("greys the box out rather than hiding it", () => {
    // A control that is visibly off and explains itself beats a feature nobody
    // knows exists.
    renderPanel({ isConfigured: false, query: "dune" });

    expect(screen.getByLabelText("Search Google Books")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
  });

  it("says why", () => {
    renderPanel({ isConfigured: false });
    expect(
      screen.getByText(/Search is off until an admin adds/),
    ).toBeInTheDocument();
  });

  it("offers the explanation", async () => {
    const props = renderPanel({ isConfigured: false });

    await userEvent
      .setup()
      .click(
        screen.getByRole("button", { name: "About searching Google Books" }),
      );

    expect(props.onOpenHelp).toHaveBeenCalledOnce();
  });

  it("keeps the help reachable even when configured", async () => {
    const props = renderPanel({ isConfigured: true });

    await userEvent
      .setup()
      .click(
        screen.getByRole("button", { name: "About searching Google Books" }),
      );

    expect(props.onOpenHelp).toHaveBeenCalledOnce();
  });
});
