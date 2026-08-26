/** Tests for src/pages/Home/Home.tsx: composition and states. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import Home from "../../../src/pages/Home";
import { makeBook, makeBookPage, makeTagSet, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/api/books/tags", { body: makeTagSet() });
});

describe("Home", () => {
  it("shows skeletons while the first page loads", () => {
    api.on(/\/api\/books\?/, { body: makeBookPage([]) });
    renderWithProviders(<Home />);
    expect(screen.getByTestId("book-skeletons")).toBeInTheDocument();
  });

  it("renders the books it receives", async () => {
    api.on(/\/api\/books\?/, {
      body: makeBookPage([
        makeBook({ title: "Dune" }),
        makeBook({ title: "Neuromancer" }),
      ]),
    });
    renderWithProviders(<Home />);

    expect(await screen.findByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("Neuromancer")).toBeInTheDocument();
  });

  it("shows the total alongside the heading", async () => {
    api.on(/\/api\/books\?/, {
      body: makeBookPage([makeBook()], { total: 137 }),
    });
    renderWithProviders(<Home />);
    expect(await screen.findByText("137")).toBeInTheDocument();
  });

  it("prompts a first-time member to scan something", async () => {
    api.on(/\/api\/books\?/, { body: makeBookPage([]) });
    renderWithProviders(<Home />);

    expect(await screen.findByText("No books found")).toBeInTheDocument();
    expect(
      screen.getByText("Scan a barcode to add your first book"),
    ).toBeInTheDocument();
  });

  it("suggests loosening filters when a filtered search is empty", async () => {
    api.on(/\/api\/books\?/, { body: makeBookPage([]) });
    renderWithProviders(<Home />);
    await screen.findByText("No books found");

    await userEvent.setup().click(screen.getByRole("button", { name: "Read" }));

    expect(
      await screen.findByText("Try adjusting your filters"),
    ).toBeInTheDocument();
  });

  it("reports a load failure with a retry", async () => {
    api.on(/\/api\/books\?/, {
      status: 500,
      body: { detail: "Server exploded" },
    });
    renderWithProviders(<Home />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Server exploded",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("links to the scan page", async () => {
    api.on(/\/api\/books\?/, { body: makeBookPage([]) });
    renderWithProviders(<Home />);
    expect(await screen.findByRole("link", { name: "+ Scan" })).toHaveAttribute(
      "href",
      "/scan",
    );
  });

  it("opens the tag panel on demand", async () => {
    api.on(/\/api\/books\?/, { body: makeBookPage([]) });
    renderWithProviders(<Home />);
    await screen.findByText("No books found");

    // Collapsed to begin with, so the grid is not pushed off screen.
    expect(
      screen.queryByRole("button", { name: "Fantasy" }),
    ).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Tags/ }));

    // Two steps now: the panel, then the category. The curated vocabulary is
    // 105 tags, so the categories inside the panel start closed too.
    await user.click(await screen.findByRole("button", { name: /Genre/ }));

    expect(
      await screen.findByRole("button", { name: "Fantasy" }),
    ).toBeInTheDocument();
  });

  it("offers Load more only while pages remain", async () => {
    api.on(/\/api\/books\?/, {
      body: makeBookPage([makeBook()], { total: 5 }),
    });
    renderWithProviders(<Home />);
    expect(
      await screen.findByRole("button", { name: "Load more" }),
    ).toBeInTheDocument();
  });

  it("hides Load more once everything is shown", async () => {
    api.on(/\/api\/books\?/, {
      body: makeBookPage([makeBook()], { total: 1 }),
    });
    renderWithProviders(<Home />);
    await screen.findByText("Dune");
    expect(
      screen.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();
  });

  it("appends the next page when Load more is clicked", async () => {
    let page = 0;
    api.on(/\/api\/books\?/, (url) => {
      // Home also asks how many books are unconfirmed, and that request hits
      // the same path. Counting it here would hand the grid page 3 while the
      // test waited for page 2.
      if (url.includes("ownership=unknown")) {
        return { body: makeBookPage([], { total: 0 }) };
      }
      page += 1;
      return {
        body: makeBookPage([makeBook({ title: `Book ${page}` })], {
          total: 2,
          page,
        }),
      };
    });
    renderWithProviders(<Home />);
    await screen.findByText("Book 1");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => expect(screen.getByText("Book 2")).toBeInTheDocument());
    // The first page is still on screen: appended, not replaced.
    expect(screen.getByText("Book 1")).toBeInTheDocument();
  });
});

describe("Home's view toggle", () => {
  beforeEach(() => {
    localStorage.clear();
    api.on(/\/api\/books\?/, {
      body: makeBookPage([makeBook({ title: "Dune", publisher: "Chilton" })]),
    });
  });

  it("starts on the covers", async () => {
    renderWithProviders(<Home />);

    expect(await screen.findByText("Dune")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("switches the grid for a table", async () => {
    renderWithProviders(<Home />);
    await screen.findByText("Dune");

    await userEvent.setup().click(screen.getByRole("button", { name: "Table" }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Chilton")).toBeInTheDocument();
  });

  it("remembers the choice in this browser", async () => {
    // Local first, like the saved views: a habit rather than library data,
    // and it needs no endpoint and no migration to be useful.
    renderWithProviders(<Home />);
    await screen.findByText("Dune");

    await userEvent.setup().click(screen.getByRole("button", { name: "Table" }));

    expect(localStorage.getItem("libraryView")).toBe("table");
  });

  it("switches the grid for dense rows", async () => {
    renderWithProviders(<Home />);
    await screen.findByText("Dune");

    await userEvent.setup().click(screen.getByRole("button", { name: "List" }));

    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(localStorage.getItem("libraryView")).toBe("list");
  });

  it("shows the covers again while selecting", async () => {
    // The checkbox lives on a card, so a selection offered from a table would
    // be a selection that does nothing.
    localStorage.setItem("libraryView", "table");
    renderWithProviders(<Home />);
    await screen.findByRole("table");

    await userEvent.setup().click(screen.getByRole("button", { name: "Select" }));

    expect(screen.queryByRole("table")).toBeNull();
  });

  it("shows the covers again while selecting from the list", async () => {
    // The same rule, and the reason the selection is tested before the view
    // rather than beside it: a third view must not reintroduce a selection
    // with nothing to tick.
    localStorage.setItem("libraryView", "list");
    renderWithProviders(<Home />);
    await screen.findByRole("list");

    await userEvent.setup().click(screen.getByRole("button", { name: "Select" }));

    expect(screen.getAllByRole("checkbox").length).toBeGreaterThan(0);
  });
});

describe("Home as the wishlist", () => {
  // The wishlist is a saved view rather than a page, and it used to look like
  // one: headed "Library", and telling a reader whose wishlist was empty to go
  // and scan a barcode, which is the opposite of what an empty wishlist means.
  const WISHLIST = "/?status=want_to_read&ownership=not_owned";

  it("is headed as the wishlist, not the library", async () => {
    api.on(/\/api\/books\?/, { body: makeBookPage([makeBook()]) });
    renderWithProviders(<Home />, { route: WISHLIST });

    expect(await screen.findByText("Wishlist")).toBeInTheDocument();
  });

  it("says nothing is missing rather than nothing is here", async () => {
    api.on(/\/api\/books\?/, { body: makeBookPage([]) });
    renderWithProviders(<Home />, { route: WISHLIST });

    expect(await screen.findByText("Nothing on the wishlist")).toBeInTheDocument();
    expect(
      screen.queryByText("Scan a barcode to add your first book"),
    ).not.toBeInTheDocument();
  });

  it("stays the wishlist when a search is typed into it", async () => {
    // Only the two fields that define the view are compared, so narrowing it
    // does not throw you back to the library.
    api.on(/\/api\/books\?/, { body: makeBookPage([makeBook()]) });
    renderWithProviders(<Home />, { route: `${WISHLIST}&query=dune` });

    expect(await screen.findByText("Wishlist")).toBeInTheDocument();
  });
});

describe("Home selection mode", () => {
  beforeEach(() => {
    api.on(/\/api\/books\?/, (url) =>
      url.includes("ownership=unknown")
        ? { body: makeBookPage([], { total: 0 }) }
        : {
            body: makeBookPage([
              makeBook({ title: "Dune" }),
              makeBook({ title: "Neuromancer" }),
            ]),
          },
    );
  });

  it("is off to begin with, so a tap opens the book", async () => {
    renderWithProviders(<Home />);
    await screen.findByText("Dune");
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
  });

  it("starts when asked", async () => {
    renderWithProviders(<Home />);
    await screen.findByText("Dune");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Select" }));

    expect(screen.getByText("0 selected")).toBeInTheDocument();
  });

  it("counts what has been ticked", async () => {
    renderWithProviders(<Home />);
    await screen.findByText("Dune");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Select" }));

    await user.click(screen.getByRole("checkbox", { name: "Dune" }));

    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });

  it("selects only the books actually loaded", async () => {
    // "Select all" cannot honestly mean rows the reader has not paged in.
    renderWithProviders(<Home />);
    await screen.findByText("Dune");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Select" }));

    await user.click(screen.getByRole("button", { name: "Select all" }));

    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("marks the selection as being on the shelf", async () => {
    api.on("/api/books/bulk", {
      body: { updated: 2, unchanged: 0, skipped: 0 },
    });
    renderWithProviders(<Home />);
    await screen.findByText("Dune");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Select" }));
    await user.click(screen.getByRole("button", { name: "Select all" }));

    await user.click(
      screen.getByRole("button", { name: "Mark as on the shelf" }),
    );

    await waitFor(() =>
      expect(api.lastCall("/books/bulk", "POST")?.body).toMatchObject({
        action: "set_ownership",
        value: "owned",
      }),
    );
  });

  it("ends when done, and the cards become links again", async () => {
    renderWithProviders(<Home />);
    await screen.findByText("Dune");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Select" }));

    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("link").length).toBeGreaterThan(0);
  });

  it("offers no way in when the shelf is empty", async () => {
    api.on(/\/api\/books\?/, { body: makeBookPage([]) });
    renderWithProviders(<Home />);
    await screen.findByText("No books found");
    expect(
      screen.queryByRole("button", { name: "Select" }),
    ).not.toBeInTheDocument();
  });
});

describe("Home unconfirmed banner", () => {
  function stubCounts(unconfirmed: number) {
    api.on(/\/api\/books\?/, (url) =>
      url.includes("ownership=unknown")
        ? { body: makeBookPage([], { total: unconfirmed }) }
        : { body: makeBookPage([makeBook({ title: "Dune" })]) },
    );
  }

  it("appears when books are waiting to be confirmed", async () => {
    stubCounts(9);
    renderWithProviders(<Home />);
    expect(
      await screen.findByText(/9 books have not been confirmed/),
    ).toBeInTheDocument();
  });

  it("stays away when there are none", async () => {
    stubCounts(0);
    renderWithProviders(<Home />);
    await screen.findByText("Dune");
    expect(
      screen.queryByText(/have not been confirmed/),
    ).not.toBeInTheDocument();
  });

  it("filters to them and starts selecting in one step", async () => {
    stubCounts(9);
    renderWithProviders(<Home />);
    await screen.findByText(/9 books have not been confirmed/);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Review them" }));

    expect(screen.getByText("0 selected")).toBeInTheDocument();
    await waitFor(() =>
      expect(api.lastCall(/ownership=unknown&/)).toBeDefined(),
    );
  });

  it("steps aside while selecting, since the nudge is already being acted on", async () => {
    stubCounts(9);
    renderWithProviders(<Home />);
    await screen.findByText(/9 books have not been confirmed/);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Review them" }));

    expect(
      screen.queryByText(/have not been confirmed/),
    ).not.toBeInTheDocument();
  });
});
