/** Tests for src/pages/LoansPage. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import LoansPage from "../../../src/pages/LoansPage";
import {
  makeBook,
  makeLoan,
  makeLoanPage,
  makeUser,
  resetIds,
} from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
});

/** Query parameters of the most recent loans request. */
function lastQuery(): URLSearchParams {
  return new URL(api.lastCall("/api/loans")!.url, "http://localhost")
    .searchParams;
}

describe("LoansPage", () => {
  it("shows skeletons while loading", () => {
    api.on("/api/loans", { body: makeLoanPage([]) });
    renderWithProviders(<LoansPage />);
    expect(screen.getByTestId("loan-skeletons")).toBeInTheDocument();
  });

  it("reassures when nothing is out", async () => {
    api.on("/api/loans", { body: makeLoanPage([]) });
    renderWithProviders(<LoansPage />);
    expect(await screen.findByText("No active loans")).toBeInTheDocument();
  });

  it("asks for active loans only by default", async () => {
    api.on("/api/loans", { body: makeLoanPage([]) });
    renderWithProviders(<LoansPage />);
    await screen.findByText("No active loans");
    expect(lastQuery().get("active_only")).toBe("true");
  });

  it("reports a load failure", async () => {
    api.on("/api/loans", { status: 500, body: { detail: "Server exploded" } });
    renderWithProviders(<LoansPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Server exploded",
    );
  });

  describe("a listed loan", () => {
    beforeEach(() => {
      api.on("/api/loans", {
        body: makeLoanPage([
          makeLoan({
            id: 5,
            book_id: 7,
            book: makeBook({ id: 7, title: "Dune", author: "Frank Herbert" }),
            loaned_to: makeUser({ username: "kim" }),
            loaned_by: makeUser({ username: "sam" }),
          }),
        ]),
      });
    });

    it("names the book", async () => {
      renderWithProviders(<LoansPage />);
      expect(await screen.findByText("Dune")).toBeInTheDocument();
    });

    it("names the borrower and the lender", async () => {
      renderWithProviders(<LoansPage />);
      await screen.findByText("Dune");
      // One sentence now rather than a name wrapped in <strong>, because
      // "Loaned to X by Y" does not keep its word order across languages.
      expect(screen.getByText("Loaned to kim by sam")).toBeInTheDocument();
    });

    it("names a borrower who has no account", async () => {
      // A whole phrase of its own rather than the member sentence with a name
      // dropped in: it says the borrower is not a member, which is the thing
      // somebody reading this list needs to know.
      api.on("/api/loans", {
        body: makeLoanPage([
          makeLoan({
            id: 6,
            book_id: 7,
            book: makeBook({ id: 7, title: "Dune" }),
            loaned_to: null,
            loaned_to_user_id: null,
            loaned_to_name: "the neighbour",
            loaned_by: makeUser({ username: "sam" }),
          }),
        ]),
      });
      renderWithProviders(<LoansPage />);
      await screen.findByText("Dune");

      expect(
        screen.getByText("Loaned to the neighbour (no account) by sam"),
      ).toBeInTheDocument();
    });

    it("links through to the book", async () => {
      renderWithProviders(<LoansPage />);
      await screen.findByText("Dune");
      expect(screen.getAllByRole("link")[0]).toHaveAttribute("href", "/book/7");
    });

    it("records a return", async () => {
      api.on("/api/loans/5/return", {
        body: makeLoan({ returned_at: "2026-03-01T00:00:00" }),
      });
      renderWithProviders(<LoansPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Mark Returned" }));

      await waitFor(() =>
        expect(api.lastCall("/api/loans/5/return", "PUT")).toBeDefined(),
      );
    });

    it("reports a failed return", async () => {
      api.on("/api/loans/5/return", {
        status: 400,
        body: { detail: "Loan already returned" },
      });
      renderWithProviders(<LoansPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Mark Returned" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Loan already returned",
      );
    });
  });

  describe("history toggle", () => {
    beforeEach(() => {
      api.on("/api/loans", { body: makeLoanPage([]) });
    });

    it("asks for every loan when switched", async () => {
      renderWithProviders(<LoansPage />);
      await screen.findByText("No active loans");

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Show all" }));

      await waitFor(() => expect(lastQuery().get("active_only")).toBe("false"));
    });

    it("changes the empty-state wording", async () => {
      renderWithProviders(<LoansPage />);
      await screen.findByText("No active loans");

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Show all" }));

      expect(await screen.findByText("No loans")).toBeInTheDocument();
    });

    it("offers no return action on an already-returned loan", async () => {
      api.on("/api/loans", {
        body: makeLoanPage([
          makeLoan({
            book: makeBook({ title: "Dune" }),
            returned_at: "2026-03-01T00:00:00",
          }),
        ]),
      });
      renderWithProviders(<LoansPage />);

      await screen.findByText("Dune");
      expect(
        screen.queryByRole("button", { name: "Mark Returned" }),
      ).not.toBeInTheDocument();
      expect(screen.getByText(/Returned/)).toBeInTheDocument();
    });
  });
});

describe("LoansPage overdue handling", () => {
  function stubLoans(rows: unknown[], overdueTotal = 0) {
    api.on(/\/api\/loans\?/, (url) =>
      url.includes("overdue_only=true") && url.includes("page_size=1")
        ? { body: { items: [], total: overdueTotal, page: 1, page_size: 1 } }
        : { body: { items: rows, total: rows.length, page: 1, page_size: 50 } },
    );
  }

  it("nudges when loans are overdue", async () => {
    stubLoans([makeLoan()], 2);
    renderWithProviders(<LoansPage />);

    expect(await screen.findByText("2 loans are overdue.")).toBeInTheDocument();
  });

  it("stays quiet when nothing is overdue", async () => {
    stubLoans([makeLoan({ book: makeBook({ title: "Dune" }) })], 0);
    renderWithProviders(<LoansPage />);

    await screen.findByText("Dune");
    expect(screen.queryByText(/loans are overdue/)).not.toBeInTheDocument();
  });

  it("filters to the overdue ones", async () => {
    stubLoans([makeLoan()], 2);
    renderWithProviders(<LoansPage />);
    await screen.findByText("2 loans are overdue.");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Show them" }));

    await waitFor(() =>
      expect(api.lastCall(/overdue_only=true.*page_size=50/)).toBeDefined(),
    );
  });

  it("hides the nudge once already filtered to it", async () => {
    // It would be asking for something the reader is already looking at.
    stubLoans([makeLoan()], 2);
    renderWithProviders(<LoansPage />);
    await screen.findByText("2 loans are overdue.");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Show them" }));

    await waitFor(() =>
      expect(screen.queryByText(/loans are overdue/)).not.toBeInTheDocument(),
    );
  });

  it("marks an overdue row", async () => {
    stubLoans(
      [makeLoan({ is_overdue: true, due_at: "2026-01-05T23:59:59" })],
      1,
    );
    renderWithProviders(<LoansPage />);

    expect(await screen.findByText(/Overdue since/)).toBeInTheDocument();
  });

  it("shows a future date without calling it overdue", async () => {
    stubLoans(
      [makeLoan({ is_overdue: false, due_at: "2099-01-05T23:59:59" })],
      0,
    );
    renderWithProviders(<LoansPage />);

    expect(await screen.findByText(/^Due /)).toBeInTheDocument();
    // Scoped to the row: an unscoped /Overdue/ also matches the filter button.
    expect(screen.queryByText(/Overdue since/)).not.toBeInTheDocument();
  });
});
