/** Tests for src/pages/LoansPage. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fc from "fast-check";
import { beforeEach, describe, expect, it } from "vitest";

import LoansPage from "../../../src/pages/LoansPage";
import {
  endOfDay,
  makeBook,
  makeLoan,
  makeLoanPage,
  makeUser,
  resetIds,
} from "../../factories";
import {
  heldOpen,
  mockApi,
  renderWithProviders,
  type MockApi,
} from "../../utils";
import { answersOf } from "../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../property";
import { forget, overSchema } from "../../schemaPage";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
});

/** Query parameters of the most recent loans request. */
function lastQuery(): URLSearchParams {
  // **Matched on `/api/loans?`, not on `/api/loans`.** `lastCall` matches a
  // string by substring, and this page now also calls
  // `/api/loans/overdue/mine` for the nudge's count, which contains it: the
  // helper started reading the wrong request the moment that query was added,
  // and reported `active_only` as null. The list endpoint is the only one of
  // the three that carries query parameters, so the `?` is what separates
  // them.
  return new URL(api.lastCall(/\/api\/loans\?/)!.url, "http://localhost")
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
      // Named rather than taken by index. `getAllByRole("link")[0]` used to be
      // the cover, and stopped being it the moment the overdue nudge above the
      // list became a link to the overdue page (#102): the test then asserted
      // about a different element and failed for a reason that had nothing to
      // do with what it is named after.
      renderWithProviders(<LoansPage />);
      await screen.findByText("Dune");
      expect(screen.getAllByRole("link", { name: "Dune" })[0]).toHaveAttribute(
        "href",
        "/book/7",
      );
    });

    it("records a return", async () => {
      api.on("/api/loans/5/return", {
        body: makeLoan({ returned_at: "2026-03-01T12:00:00Z" }),
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

    it("takes a failed return's alert down once the return is pressed again", async () => {
      let presses = 0;
      api.on(
        "/api/loans/5/return",
        () =>
          ++presses === 1
            ? { status: 400, body: { detail: "Loan already returned" } }
            : { body: makeLoan({ returned_at: "2026-03-01T12:00:00Z" }) },
        "PUT",
      );
      renderWithProviders(<LoansPage />);
      const button = await screen.findByRole("button", {
        name: "Mark Returned",
      });
      const user = userEvent.setup();
      await user.click(button);
      await screen.findByRole("alert");

      await user.click(button);

      await waitFor(() => expect(presses).toBe(2));
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("asks for the list again once a return lands", async () => {
      // The returned loan leaves the active list, and only a refetch shows it.
      api.on(
        "/api/loans/5/return",
        { body: makeLoan({ returned_at: "2026-03-01T12:00:00Z" }) },
        "PUT",
      );
      renderWithProviders(<LoansPage />);
      const button = await screen.findByRole("button", {
        name: "Mark Returned",
      });
      const listReads = () =>
        api.calls.filter((call) => /\/api\/loans\?/.test(call.url)).length;
      const before = listReads();

      await userEvent.setup().click(button);

      await waitFor(() => expect(listReads()).toBeGreaterThan(before));
    });
  });

  describe("a loan mid return", () => {
    // The busy marker is a loan id, so a second row must stay pressable.
    it("marks the row being returned, and only that row", async () => {
      api.on("/api/loans", {
        body: makeLoanPage([
          makeLoan({ id: 5, book: makeBook({ title: "Dune" }) }),
          makeLoan({ id: 6, book: makeBook({ title: "Emma" }) }),
        ]),
      });
      const reply = heldOpen();
      api.on("/api/loans/5/return", reply.respond, "PUT");
      renderWithProviders(<LoansPage />);
      await screen.findByText("Emma");
      const [dune, emma] = screen.getAllByRole("button", {
        name: "Mark Returned",
      });

      await userEvent.setup().click(dune!);

      await waitFor(() => expect(dune).toBeDisabled());
      expect(emma).toBeEnabled();

      reply.release({ body: makeLoan({ id: 5 }) });
    });

    it("keeps each row marked until its own return answers, a failed one included", async () => {
      // A mutation remembers only its latest call, so reading the hook's own
      // variables would unmark the first row the moment the second was
      // pressed. And a write that has failed stays in the mutation cache, so
      // only reading the pending ones lets the reader retry it.
      api.on("/api/loans", {
        body: makeLoanPage([
          makeLoan({ id: 5, book: makeBook({ title: "Dune" }) }),
          makeLoan({ id: 6, book: makeBook({ title: "Emma" }) }),
        ]),
      });
      const first = heldOpen();
      const second = heldOpen();
      api.on("/api/loans/5/return", first.respond, "PUT");
      api.on("/api/loans/6/return", second.respond, "PUT");
      renderWithProviders(<LoansPage />);
      await screen.findByText("Emma");
      const [dune, emma] = screen.getAllByRole("button", {
        name: "Mark Returned",
      });
      const user = userEvent.setup();

      await user.click(dune!);
      await user.click(emma!);

      await waitFor(() =>
        expect(api.lastCall("/api/loans/6/return", "PUT")).toBeDefined(),
      );
      await waitFor(() => expect(emma).toBeDisabled());
      expect(dune).toBeDisabled();

      first.release({ status: 400, body: { detail: "Loan already returned" } });

      await waitFor(() => expect(dune).toBeEnabled());
      expect(emma).toBeDisabled();

      second.release({ body: makeLoan({ id: 6 }) });
    });

    it("reports a failed return when another row's return was pressed after it", async () => {
      // The hook's own `error` is its latest call's, Emma's here, so Dune's
      // failure would show nothing at all.
      api.on("/api/loans", {
        body: makeLoanPage([
          makeLoan({ id: 5, book: makeBook({ title: "Dune" }) }),
          makeLoan({ id: 6, book: makeBook({ title: "Emma" }) }),
        ]),
      });
      const first = heldOpen();
      const second = heldOpen();
      api.on("/api/loans/5/return", first.respond, "PUT");
      api.on("/api/loans/6/return", second.respond, "PUT");
      renderWithProviders(<LoansPage />);
      await screen.findByText("Emma");
      const [dune, emma] = screen.getAllByRole("button", {
        name: "Mark Returned",
      });
      const user = userEvent.setup();

      await user.click(dune!);
      await user.click(emma!);
      await waitFor(() =>
        expect(api.lastCall("/api/loans/6/return", "PUT")).toBeDefined(),
      );

      first.release({ status: 400, body: { detail: "Loan already returned" } });
      second.release({ body: makeLoan({ id: 6 }) });

      await waitFor(() => expect(emma).toBeEnabled());
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
            returned_at: "2026-03-01T12:00:00Z",
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
  /**
   * The list, and the count the nudge is drawn from.
   *
   * **Two endpoints, and that is the point (#102).** The nudge counts through
   * `GET /api/loans/overdue/mine`, which is the rule the page it links to
   * lists by; the list itself is `GET /api/loans`, which is wider. `wide` is
   * how many rows the "Overdue only" filter would show, and it is set higher
   * than `overdueTotal` in the tests below precisely so a nudge that went back
   * to reading the list would print a different number and fail.
   */
  function stubLoans(rows: unknown[], overdueTotal = 0, wide = overdueTotal) {
    api.on("/api/loans/overdue/mine", {
      body: { enabled: true, count: overdueTotal },
    });
    api.on(/\/api\/loans\?/, (url) =>
      url.includes("overdue_only=true")
        ? { body: { items: [], total: wide, page: 1, page_size: 50 } }
        : { body: { items: rows, total: rows.length, page: 1, page_size: 50 } },
    );
  }

  it("nudges when loans are overdue", async () => {
    stubLoans([makeLoan()], 2);
    renderWithProviders(<LoansPage />);

    expect(
      await screen.findByText("2 loans need chasing."),
    ).toBeInTheDocument();
  });

  it("counts what the page it links to lists, not what the filter shows", async () => {
    // The defect this replaced. The nudge read `overdue_only=true`, which is
    // the household's loans narrowed to the late ones, and linked to a page
    // that applies `overdue_for_viewer` on top. For a non admin member, which
    // is every member, the two are different sets: the nudge said 2 and the
    // page showed 1.
    stubLoans([makeLoan()], 1, 9);
    renderWithProviders(<LoansPage />);

    expect(
      await screen.findByText("1 loans need chasing."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/9 loans need chasing/)).not.toBeInTheDocument();
  });

  it("says nothing when the in app reminder is switched off", async () => {
    // The dead end. With the channel off the server empties the overdue page,
    // and the library banner hides itself, so a nudge still counting the
    // household's late loans was the only entrance to a page that could only
    // say "switched off".
    api.on("/api/loans/overdue/mine", { body: { enabled: false, count: 0 } });
    api.on(/\/api\/loans\?/, (url) =>
      url.includes("overdue_only=true")
        ? { body: { items: [], total: 4, page: 1, page_size: 50 } }
        : {
            body: {
              items: [makeLoan({ book: makeBook({ title: "Dune" }) })],
              total: 1,
              page: 1,
              page_size: 50,
            },
          },
    );
    renderWithProviders(<LoansPage />);

    await screen.findByText("Dune");
    expect(screen.queryByText(/loans are overdue/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Show them" }),
    ).not.toBeInTheDocument();
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
    await screen.findByText("2 loans need chasing.");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Overdue only" }));

    await waitFor(() =>
      expect(api.lastCall(/overdue_only=true.*page_size=50/)).toBeDefined(),
    );
  });

  it("sends the reader to the overdue page for the delivery status", async () => {
    // The nudge used to be a second spelling of the "Overdue only" button two
    // lines above it (#102). It is now the one route to the page that carries
    // the reminder channels' standing state, which the loans list does not
    // show and cannot.
    stubLoans([makeLoan()], 2);
    renderWithProviders(<LoansPage />);
    await screen.findByText("2 loans need chasing.");

    expect(screen.getByRole("link", { name: "Show them" })).toHaveAttribute(
      "href",
      "/loans/overdue",
    );
  });

  it("hides the nudge once already filtered to it", async () => {
    // It would be asking for something the reader is already looking at.
    stubLoans([makeLoan()], 2);
    renderWithProviders(<LoansPage />);
    await screen.findByText("2 loans need chasing.");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Overdue only" }));

    await waitFor(() =>
      expect(screen.queryByText(/loans are overdue/)).not.toBeInTheDocument(),
    );
  });

  it("marks an overdue row", async () => {
    stubLoans(
      [makeLoan({ is_overdue: true, due_at: endOfDay("2026-01-05") })],
      1,
    );
    renderWithProviders(<LoansPage />);

    expect(await screen.findByText(/Overdue since/)).toBeInTheDocument();
  });

  it("shows a future date without calling it overdue", async () => {
    stubLoans(
      [makeLoan({ is_overdue: false, due_at: endOfDay("2099-01-05") })],
      0,
    );
    renderWithProviders(<LoansPage />);

    expect(await screen.findByText(/^Due /)).toBeInTheDocument();
    // Scoped to the row: an unscoped /Overdue/ also matches the filter button.
    expect(screen.queryByText(/Overdue since/)).not.toBeInTheDocument();
  });
});

/** How many entries a page body holds, or -1 for one that is not a page. */
const entries = (body: unknown) =>
  (body as { items?: unknown[] } | undefined)?.items?.length ?? -1;

describe("LoansPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do.
  it("is drawn every shape of answer its main request declares", async () => {
    await witness(answersOf("list_loans"), {
      "is an error body": (answer) => answer.status === 422,
      "is an empty page": (answer) => entries(answer.body) === 0,
      "is a page with an entry": (answer) => entries(answer.body) > 0,
    });
  });

  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.gen(),
        async (answers) => {
          try {
            const rendered = await overSchema(<LoansPage />, answers);
            expect(rendered.problems).toEqual([]);
            return rendered;
          } finally {
            forget();
          }
        },
        {
          "showed a value an answer carried": (_, rendered) =>
            rendered.echoed > 0,
          "drew an alert": (_, rendered) => rendered.alerts.length > 0,
        },
      ),
    ).toBe(PROFILE.runs);
  });
});
