/** Tests for src/pages/PatronsPage: the staff page over the patron register. */

import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Locale, type PatronOut } from "../../../src/api/generated/model";
import PatronsPage from "../../../src/pages/PatronsPage";
import { DEBOUNCE_MS } from "../../../src/pages/components/SearchBar";
import {
  createTestQueryClient,
  expectRequest,
  mockApi,
  renderWithProviders,
  type MockApi,
} from "../../utils";

let api: MockApi;

beforeEach(() => {
  api = mockApi();
});

function makePatron(overrides: Partial<PatronOut> = {}): PatronOut {
  return {
    id: 7,
    card_number: "A-1001",
    name: "Ada Lovelace",
    email: "ada@example.org",
    phone: null,
    street: "Hauptstraße",
    house_number: "3",
    postcode: "1010",
    city: "Wien",
    expires_on: "2099-12-31",
    enrolled_at: "2026-01-01T12:00:00Z",
    ...overrides,
  };
}

/**
 * Type a term and let the search box's debounce run out on a clock of the
 * step's own. Real timers are back before the request runs.
 */
function searchFor(term: string, name = "Search patrons") {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  try {
    fireEvent.change(screen.getByRole("searchbox", { name }), {
      target: { value: term },
    });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_MS);
    });
  } finally {
    vi.useRealTimers();
  }
}

const SEARCH = "/api/patrons/search";

const patronRequests = () =>
  api.calls.filter((call) => call.url.includes("/api/patrons"));

describe("PatronsPage", () => {
  it("asks for no patron before a term is typed", () => {
    renderWithProviders(<PatronsPage />);

    expect(
      screen.getByText(
        "Search by name, email or card number to find a patron.",
      ),
    ).toBeInTheDocument();
    expect(patronRequests()).toEqual([]);
  });

  it("searches by the typed term and lists each match with its card and contact", async () => {
    api.on(SEARCH, { body: [makePatron()] }, "POST");
    renderWithProviders(<PatronsPage />);

    searchFor("ada");

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Card A-1001")).toBeInTheDocument();
    expect(screen.getByText("ada@example.org")).toBeInTheDocument();
    expect(screen.getByText("Hauptstraße 3, 1010 Wien")).toBeInTheDocument();
    expect(expectRequest(api, SEARCH, "POST").body).toEqual({
      q: "ada",
      limit: 50,
    });
  });

  it("lists the books a patron has out, each linked to its book", async () => {
    const loan = {
      id: 3,
      book_id: 42,
      title: "Dune",
      loaned_at: "2026-03-01T10:00:00Z",
      due_at: null,
    };
    api.on(SEARCH, { body: [makePatron({ open_loans: [loan] })] }, "POST");
    renderWithProviders(<PatronsPage />);

    searchFor("ada");

    expect(await screen.findByRole("link", { name: "Dune" })).toHaveAttribute(
      "href",
      "/book/42",
    );
    expect(screen.getByText(/^Out since /)).toBeInTheDocument();
  });

  it("puts the term in no URL, where a request log would keep it", async () => {
    api.on(SEARCH, { body: [makePatron()] }, "POST");
    renderWithProviders(<PatronsPage />);

    searchFor("ada");

    await screen.findByText("Ada Lovelace");
    expect(patronRequests().map((call) => call.url)).toEqual([
      expect.not.stringContaining("ada"),
    ]);
  });

  it("says when no patron matches", async () => {
    api.on(SEARCH, { body: [] }, "POST");
    renderWithProviders(<PatronsPage />);

    searchFor("zzz");

    expect(
      await screen.findByText("No patron matches that search."),
    ).toBeInTheDocument();
  });

  it("marks a lapsed registration as expired in words", async () => {
    api.on(
      SEARCH,
      {
        body: [
          makePatron({ id: 1, name: "Lapsed", expires_on: "2001-02-03" }),
          makePatron({ id: 2, name: "Current", expires_on: "2099-12-31" }),
        ],
      },
      "POST",
    );
    renderWithProviders(<PatronsPage />);

    searchFor("la");

    const lapsed = (await screen.findByText("Lapsed")).closest("li")!;
    const current = screen.getByText("Current").closest("li")!;
    expect(
      within(lapsed).getByText(/^Registration expired on/),
    ).toBeInTheDocument();
    expect(within(current).queryByText(/expired/)).toBeNull();
    expect(within(current).getByText(/^Registered until/)).toBeInTheDocument();
  });

  it("shows the server's refusal in the form and keeps it open", async () => {
    api.on(
      "/api/patrons",
      {
        status: 409,
        body: { detail: "Another patron already carries this card number." },
      },
      "POST",
    );
    renderWithProviders(<PatronsPage />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "New patron" }));
    await user.type(screen.getByLabelText("Name"), "Ada");
    await user.type(screen.getByLabelText(/^Card number/), "A-1001");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(
      await screen.findByText(
        "Another patron already carries this card number.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Ada");
  });

  it("sends an emptied field as null on an edit, so the record loses it", async () => {
    api.on(SEARCH, { body: [makePatron()] }, "POST");
    api.on("/api/patrons/7", { body: makePatron({ email: null }) }, "PATCH");
    renderWithProviders(<PatronsPage />);
    const user = userEvent.setup();
    searchFor("ada");

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.clear(screen.getByLabelText("Email"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(expectRequest(api, "/api/patrons/7", "PATCH").body).toMatchObject({
      name: "Ada Lovelace",
      card_number: "A-1001",
      email: null,
      city: "Wien",
      expires_on: "2099-12-31",
    });
  });

  it("deletes only after a confirmation saying what the erasure costs", async () => {
    api.on(SEARCH, { body: [makePatron()] }, "POST");
    api.on("/api/patrons/7", { status: 204 }, "DELETE");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<PatronsPage />);
    const user = userEvent.setup();
    searchFor("ada");

    await user.click(await screen.findByRole("button", { name: "Delete" }));

    const asked = String(confirm.mock.calls[0]?.[0]);
    expect(asked).toContain("Ada Lovelace");
    expect(asked).toContain("cannot be undone");
    expect(asked).toContain("keep the dates each book went out and came back");
    expect(asked).toContain(
      "A book still out with them stays recorded as out, with no borrower",
    );
    expect(api.lastCall("/api/patrons/7", "DELETE")).toBeDefined();
  });

  it("takes an erased patron off the list once the delete is done", async () => {
    api.on(SEARCH, { body: [makePatron()] }, "POST");
    api.on("/api/patrons/7", { status: 204 }, "DELETE");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<PatronsPage />);
    const user = userEvent.setup();
    searchFor("ada");
    const remove = await screen.findByRole("button", { name: "Delete" });
    // The search asked again after the erasure answers without them.
    api.on(SEARCH, { body: [] }, "POST");

    await user.click(remove);

    expect(
      await screen.findByText("No patron matches that search."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ada Lovelace")).toBeNull();
  });

  it("forgets the cached loans that named an erased patron", async () => {
    const loan = {
      id: 3,
      book_id: 42,
      title: "Dune",
      loaned_at: "2026-03-01T10:00:00Z",
      due_at: null,
    };
    api.on(SEARCH, { body: [makePatron({ open_loans: [loan] })] }, "POST");
    api.on("/api/patrons/7", { status: 204 }, "DELETE");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const queryClient = createTestQueryClient();
    // Kept with no observer, which the test client would otherwise collect.
    for (const key of [["/api/books/42"], ["/api/loans"]]) {
      queryClient.setQueryDefaults(key, { gcTime: Infinity });
      queryClient.setQueryData(key, {});
    }
    renderWithProviders(<PatronsPage />, { queryClient });
    const user = userEvent.setup();
    searchFor("ada");

    await user.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(
        [["/api/books/42"], ["/api/loans"]].map(
          (key) => queryClient.getQueryState(key)?.isInvalidated,
        ),
      ).toEqual([true, true]);
    });
  });

  it("sends no delete when the confirmation is declined", async () => {
    api.on(SEARCH, { body: [makePatron()] }, "POST");
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithProviders(<PatronsPage />);
    const user = userEvent.setup();
    searchFor("ada");

    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(api.lastCall("/api/patrons/7", "DELETE")).toBeUndefined();
  });

  it("speaks of a Benutzer:in and a Neuanmeldung in German", () => {
    renderWithProviders(<PatronsPage />, { locale: Locale.de });

    expect(
      screen.getByRole("heading", { name: "Benutzer:innen" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Neuanmeldung" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("searchbox", { name: "Benutzerkonto suchen" }),
    ).toBeInTheDocument();
  });
});
