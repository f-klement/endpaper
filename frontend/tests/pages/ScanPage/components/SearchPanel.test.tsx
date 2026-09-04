/** Tests for src/pages/ScanPage/components/SearchPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  BookMatch,
  CatalogueSource,
} from "../../../../src/api/generated/model";
import SearchPanel from "../../../../src/pages/ScanPage/components/SearchPanel";
import { renderLocalised } from "../../../utils";

function match(overrides: Partial<BookMatch> = {}): BookMatch {
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
  overrides: Partial<Parameters<typeof SearchPanel>[0]> = {},
) {
  const props = {
    isConfigured: true,
    onOpenHelp: vi.fn(),
    query: "",
    matches: [] as BookMatch[],
    isSearching: false,
    isEmpty: false,
    error: null,
    onQueryChange: vi.fn(),
    onSubmit: vi.fn(),
    onChoose: vi.fn(),
    unasked: [] as CatalogueSource[],
    askedNothing: false,
    onSearchHarder: vi.fn(),
    isSearchingHarder: false,
    hasSearchedHarder: false,
    ...overrides,
  };
  renderLocalised(<SearchPanel {...props} />);
  return props;
}

describe("SearchPanel", () => {
  it("reports each keystroke upwards", async () => {
    const props = renderPanel();

    await userEvent
      .setup()
      .type(screen.getByLabelText("Search by title or author"), "d");

    expect(props.onQueryChange).toHaveBeenCalledWith("d");
  });

  it("submits on enter as well as on the button", async () => {
    const props = renderPanel({ query: "dune" });

    await userEvent
      .setup()
      .type(screen.getByLabelText("Search by title or author"), "{Enter}");

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
      // The label no longer swaps to "Searching...". The shared Button shows a
      // spinner and keeps its text, so the control does not change width
      // mid-click, and `aria-busy` carries the state to a screen reader, which
      // a changed label only did by accident.
      renderPanel({ query: "dune", isSearching: true });
      const button = screen.getByRole("button", { name: "Search" });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("aria-busy", "true");
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

describe("SearchPanel without a Google Books key", () => {
  it("stays usable, because Open Library needs no key", () => {
    // It used to grey itself out here, which left a library with no key
    // unable to add a book that has no barcode at all.
    renderPanel({ isConfigured: false, query: "dune" });

    expect(
      screen.getByLabelText("Search by title or author"),
    ).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Search" })).not.toBeDisabled();
  });

  it("says what a key would add rather than what is broken", () => {
    renderPanel({ isConfigured: false });
    expect(
      screen.getByText(/A Google Books key adds descriptions and genres/),
    ).toBeInTheDocument();
  });

  it("says nothing about a key once one is configured", () => {
    renderPanel({ isConfigured: true });
    expect(
      screen.queryByText(/A Google Books key adds/),
    ).not.toBeInTheDocument();
  });

  it("offers the explanation", async () => {
    const props = renderPanel({ isConfigured: false });

    await userEvent
      .setup()
      .click(
        screen.getByRole("button", { name: "About searching for a book" }),
      );

    expect(props.onOpenHelp).toHaveBeenCalledOnce();
  });

  it("keeps the help reachable even when configured", async () => {
    const props = renderPanel({ isConfigured: true });

    await userEvent
      .setup()
      .click(
        screen.getByRole("button", { name: "About searching for a book" }),
      );

    expect(props.onOpenHelp).toHaveBeenCalledOnce();
  });
});

describe("the offer to search harder", () => {
  it("is not made when every catalogue was already asked", () => {
    renderPanel({ matches: [match()] });

    expect(
      screen.queryByRole("button", { name: "Search harder" }),
    ).not.toBeInTheDocument();
  });

  it("names the catalogues it would add", () => {
    renderPanel({ matches: [match()], unasked: ["oenb", "nlg"] });

    expect(
      screen.getByText(
        "Austrian National Library and National Library of Greece are slower than a quick search waits for.",
      ),
    ).toBeInTheDocument();
  });

  it("is made when the search found nothing, which is when it is wanted most", () => {
    renderPanel({ matches: [], isEmpty: true, unasked: ["oenb"] });

    expect(
      screen.getByRole("button", { name: "Search harder" }),
    ).toBeInTheDocument();
  });

  it("asks upwards when pressed", async () => {
    const props = renderPanel({ unasked: ["oenb"] });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Search harder" }));

    expect(props.onSearchHarder).toHaveBeenCalledOnce();
  });

  it("says why the offer came back when the longer search was refused", () => {
    // Having asked harder and still having something unasked is the one shape
    // that means refused. Without this the reader presses, waits, and gets the
    // identical offer back with no reason.
    renderPanel({
      matches: [match()],
      unasked: ["oenb"],
      hasSearchedHarder: true,
    });

    expect(
      screen.getByText(
        "Only one long search runs at a time. Try again in a moment.",
      ),
    ).toBeInTheDocument();
    // Still offered, because the retry is the point of saying so.
    expect(
      screen.getByRole("button", { name: "Search harder" }),
    ).toBeInTheDocument();
  });

  it("does not call it busy before a longer search has been asked for", () => {
    renderPanel({ matches: [match()], unasked: ["oenb"] });

    expect(
      screen.queryByText(/Only one long search runs at a time/),
    ).not.toBeInTheDocument();
  });

  it("says everything was asked once the longer search has answered", () => {
    renderPanel({ matches: [match()], unasked: [], hasSearchedHarder: true });

    expect(screen.getByText("Every catalogue was asked.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Search harder" }),
    ).not.toBeInTheDocument();
    // **The other half of the busy condition, on the fixture that already has
    // it.** Busy is having asked harder **and** still having something unasked,
    // and only the first half was pinned: dropping the second survived the whole
    // gate, and under that mutant this fixture renders "only one long search
    // runs at a time" directly above "Every catalogue was asked."
    // Same two condition shape as `askedNothing`, one level along.
    expect(
      screen.queryByText(/Only one long search runs at a time/),
    ).not.toBeInTheDocument();
  });

  it("says nothing about the longer search before one has been run", () => {
    renderPanel({ matches: [match()], unasked: [], hasSearchedHarder: false });

    expect(
      screen.queryByText("Every catalogue was asked."),
    ).not.toBeInTheDocument();
  });

  it("distinguishes asking nothing from finding nothing", () => {
    renderPanel({ matches: [], askedNothing: true, unasked: ["oenb"] });

    expect(
      screen.getByText(
        "Nothing was searched. Every catalogue this library has switched on is a slow one.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/No matches\. Try fewer words/),
    ).not.toBeInTheDocument();
  });
});
