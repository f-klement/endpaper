/**
 * Tests for src/pages/BookDetail/components/PatronPicker.tsx: the loan form's
 * two doors to the patron register, finding somebody and registering somebody.
 */

import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Locale } from "../../../../src/api/generated/model";
import PatronPicker, {
  type PickedPatron,
} from "../../../../src/pages/BookDetail/components/PatronPicker";
import { DEBOUNCE_MS } from "../../../../src/pages/components/SearchBar";
import { makePatron, resetIds } from "../../../factories";
import {
  expectRequest,
  mockApi,
  renderWithProviders,
  type MockApi,
} from "../../../utils";

const SEARCH = "/api/patrons/search";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
});

function renderPicker(
  picked: PickedPatron | null = null,
  locale: Locale = Locale.en,
) {
  const onPick = vi.fn<(picked: PickedPatron | null) => void>();
  renderWithProviders(<PatronPicker picked={picked} onPick={onPick} />, {
    locale,
  });
  return { onPick };
}

/**
 * Type a term and let the search box's debounce run out on a clock of the
 * step's own. `fireEvent`, because `user-event` schedules its own async work
 * and deadlocks against fake timers. Real timers are back before the request
 * runs.
 */
function searchFor(term: string) {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  try {
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search patrons" }),
      {
        target: { value: term },
      },
    );
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_MS);
    });
  } finally {
    vi.useRealTimers();
  }
}

async function openFind() {
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Existing patron" }));
}

describe("PatronPicker", () => {
  it("offers two doors: somebody registered, and somebody new", () => {
    renderPicker();

    expect(
      screen.getByRole("button", { name: "Existing patron" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "New patron" }),
    ).toBeInTheDocument();
  });

  it("asks the register nothing until a term is typed", async () => {
    renderPicker();

    await openFind();

    expect(
      screen.getByText(
        "Search by name, email or card number to find a patron.",
      ),
    ).toBeInTheDocument();
    expect(api.calls).toEqual([]);
  });

  it("sends what was typed in one field, in the body and capped", async () => {
    api.on(SEARCH, { body: [makePatron()] }, "POST");
    renderPicker();
    await openFind();

    searchFor("ada");

    await screen.findByText("Ada Lovelace");
    expect(expectRequest(api, SEARCH, "POST")).toEqual({
      url: expect.not.stringContaining("ada"),
      method: "POST",
      body: { q: "ada", limit: 50 },
    });
  });

  it("picks the patron a search found", async () => {
    const found = makePatron({ name: "Kim Ode" });
    api.on(SEARCH, { body: [found] }, "POST");
    const { onPick } = renderPicker();
    await openFind();
    searchFor("kim");

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: /Kim Ode/ }));

    expect(onPick).toHaveBeenCalledWith({
      patron: found,
      today: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
  });

  it("says no patron matches rather than showing an empty box", async () => {
    api.on(SEARCH, { body: [] }, "POST");
    renderPicker();
    await openFind();

    searchFor("zzz");

    expect(
      await screen.findByText("No patron matches that search."),
    ).toBeInTheDocument();
  });

  it("says a match's registration has lapsed, in words", async () => {
    api.on(
      SEARCH,
      { body: [makePatron({ expires_on: "2001-02-03" })] },
      "POST",
    );
    renderPicker();
    await openFind();

    searchFor("ada");

    expect(
      await screen.findByText(/^Registration expired on/),
    ).toBeInTheDocument();
  });

  it("registers a new patron and picks the record the server stored", async () => {
    const stored = makePatron({ id: 41, name: "Pat Lee", card_number: "C1" });
    api.on("/api/patrons", { status: 201, body: stored }, "POST");
    const { onPick } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "New patron" }));
    await user.type(screen.getByLabelText("Name"), "Pat Lee");
    await user.type(screen.getByLabelText(/^Card number/), "C1");
    await user.click(screen.getByRole("button", { name: "Register" }));

    await vi.waitFor(() =>
      expect(onPick).toHaveBeenCalledWith({
        patron: stored,
        today: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      }),
    );
  });

  it("keeps the form open on the server's refusal and picks nobody", async () => {
    api.on(
      "/api/patrons",
      {
        status: 409,
        body: { detail: "Another patron already carries this card number." },
      },
      "POST",
    );
    const { onPick } = renderPicker();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "New patron" }));
    await user.type(screen.getByLabelText("Name"), "Pat Lee");
    await user.type(screen.getByLabelText(/^Card number/), "C1");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(
      await screen.findByText(
        "Another patron already carries this card number.",
      ),
    ).toBeInTheDocument();
    expect(onPick).not.toHaveBeenCalled();
  });

  it("shows the picked patron with their card and offers another choice", async () => {
    const { onPick } = renderPicker({
      patron: makePatron({ name: "Kim Ode", card_number: "K7" }),
      today: "2026-11-20",
    });

    expect(screen.getByText("Kim Ode")).toBeInTheDocument();
    expect(screen.getByText("Card K7")).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Choose another" }));
    expect(onPick).toHaveBeenCalledWith(null);
  });

  it("says the picked patron's registration has lapsed, judged on the day it was picked", () => {
    renderPicker({
      patron: makePatron({ expires_on: "2026-11-19" }),
      today: "2026-11-20",
    });

    expect(
      screen.getByText("Registration expired on 11/19/2026"),
    ).toBeInTheDocument();
  });

  it("offers the two doors in formal German", () => {
    renderPicker(null, Locale.de);

    expect(
      screen.getByRole("button", { name: "Bereits angemeldet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Neuanmeldung" }),
    ).toBeInTheDocument();
  });
});
