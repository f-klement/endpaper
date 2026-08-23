/** Tests for src/pages/AuthorsPage. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuthorsPage from "../../../src/pages/AuthorsPage";
import { ToastProvider } from "../../../src/app/toast";
import { resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

function author(overrides: Record<string, unknown> = {}) {
  return {
    key: "frank herbert",
    name: "Frank Herbert",
    book_count: 3,
    spellings: ["Frank Herbert"],
    merged: [],
    ...overrides,
  };
}

/** The suggestions request is made on every render, so every test answers it.
 *
 * Registered second, and that is load bearing: a matcher is a substring and
 * the later registration wins, so the shorter path first would answer the
 * suggestions request with the author list. */
function stub(authors: unknown[], suggestions: unknown[] = []) {
  api.on("/api/books/authors", { body: authors });
  api.on("/api/books/authors/suggestions", { body: suggestions });
}

describe("AuthorsPage", () => {
  it("lists everybody with the count the caller can see", async () => {
    stub([author()]);
    renderWithProviders(<AuthorsPage />);

    expect(await screen.findByText("Frank Herbert")).toBeInTheDocument();
    expect(screen.getByText("3 books")).toBeInTheDocument();
  });

  it("says when the shelf credits nobody", async () => {
    stub([]);
    renderWithProviders(<AuthorsPage />);

    expect(await screen.findByText("No authors yet")).toBeInTheDocument();
  });

  it("surfaces a failure", async () => {
    api.on("/api/books/authors", { status: 500, body: { detail: "Nope" } });
    api.on("/api/books/authors/suggestions", { body: [] });
    renderWithProviders(<AuthorsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });

  it("filters in the browser rather than through another request", async () => {
    stub([author(), author({ key: "zadie smith", name: "Zadie Smith" })]);
    renderWithProviders(<AuthorsPage />);
    await screen.findByText("Frank Herbert");
    const before = api.calls.length;

    await userEvent
      .setup()
      .type(screen.getByLabelText("Search authors"), "zadie");

    expect(screen.queryByText("Frank Herbert")).not.toBeInTheDocument();
    expect(screen.getByText("Zadie Smith")).toBeInTheDocument();
    expect(api.calls.length).toBe(before);
  });

  it("matches a spelling that is not the displayed name", async () => {
    stub([
      author({
        name: "Ursula K. Le Guin",
        key: "ursula k le guin",
        spellings: ["Ursula K. Le Guin", "U. K. Le Guin"],
      }),
    ]);
    renderWithProviders(<AuthorsPage />);
    await screen.findByText("Ursula K. Le Guin");

    await userEvent
      .setup()
      .type(screen.getByLabelText("Search authors"), "U. K.");

    expect(screen.getByText("Ursula K. Le Guin")).toBeInTheDocument();
  });

  it("says when nothing matches the search", async () => {
    stub([author()]);
    renderWithProviders(<AuthorsPage />);
    await screen.findByText("Frank Herbert");

    await userEvent
      .setup()
      .type(screen.getByLabelText("Search authors"), "zzz");

    expect(screen.getByText("No author matches that")).toBeInTheDocument();
  });

  it("offers no suggestions section on a tidy shelf", async () => {
    stub([author()]);
    renderWithProviders(<AuthorsPage />);
    await screen.findByText("Frank Herbert");

    expect(
      screen.queryByText("Probably the same person"),
    ).not.toBeInTheDocument();
  });

  it("merges a suggested group into the chosen name", async () => {
    stub(
      [
        author({ key: "u k le guin", name: "U. K. Le Guin" }),
        author({ key: "ursula k le guin", name: "Ursula K. Le Guin" }),
      ],
      [
        {
          keys: ["u k le guin", "ursula k le guin"],
          names: ["U. K. Le Guin", "Ursula K. Le Guin"],
          reasons: ["initials"],
        },
      ],
    );
    api.on("/api/books/authors/merge", { body: author() });
    renderWithProviders(<AuthorsPage />);

    const [, second] = await screen.findAllByRole("button", {
      name: "Keep this name",
    });
    await userEvent.setup().click(second!);

    await waitFor(() =>
      expect(api.lastCall("/api/books/authors/merge", "POST")?.body).toEqual({
        keys: ["u k le guin", "ursula k le guin"],
        keep_name: "Ursula K. Le Guin",
      }),
    );
  });

  it("merges two names that no rule would ever suggest", async () => {
    // A misspelling: no shared word, no initial pattern, no squashed key, so
    // `/suggestions` returns nothing and this is the only path to the merge
    // the endpoint has always accepted.
    stub([
      author({ key: "tolkein", name: "Tolkein", book_count: 1 }),
      author({ key: "tolkien", name: "Tolkien", book_count: 4 }),
    ]);
    api.on("/api/books/authors/merge", { body: author() });
    renderWithProviders(<AuthorsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText("Select Tolkein"));
    await user.click(screen.getByLabelText("Select Tolkien"));
    await user.click(screen.getByRole("button", { name: "Keep Tolkien" }));

    await waitFor(() =>
      expect(api.lastCall("/api/books/authors/merge", "POST")?.body).toEqual({
        keys: ["tolkein", "tolkien"],
        keep_name: "Tolkien",
      }),
    );
  });

  it("keeps the merge bar away until something is selected", async () => {
    stub([author()]);
    renderWithProviders(<AuthorsPage />);
    await screen.findByText("Frank Herbert");

    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
  });

  it("says so when the merge lands under a name nobody typed", async () => {
    // Typing a name that is itself already folded resolves to whoever it was
    // folded into. Correct, and silent: the page just refetches and the author
    // is filed under a third name.
    stub([author({ key: "tolkein", name: "Tolkein" })]);
    api.on("/api/books/authors/merge", {
      body: author({ key: "j r r tolkien", name: "J. R. R. Tolkien" }),
    });
    renderWithProviders(
      <ToastProvider>
        <AuthorsPage />
      </ToastProvider>,
    );
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText("Select Tolkein"));
    await user.type(screen.getByLabelText("A name to use instead"), "Tolkien");
    await user.click(screen.getByRole("button", { name: "Rename" }));

    expect(
      await screen.findByText(
        'That name is already "J. R. R. Tolkien", so they went there.',
      ),
    ).toBeInTheDocument();
  });

  it("stays quiet when the merge went exactly where it was asked", async () => {
    // The false positive: the server collapses internal whitespace before
    // storing, so a typed "Ursula K.  Le Guin" comes back spelled with one
    // space. Sending the raw string made that read as a redirect.
    stub([author({ key: "le guin", name: "Le Guin" })]);
    api.on("/api/books/authors/merge", {
      body: author({ key: "ursula k le guin", name: "Ursula K. Le Guin" }),
    });
    renderWithProviders(
      <ToastProvider>
        <AuthorsPage />
      </ToastProvider>,
    );
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText("Select Le Guin"));
    await user.type(
      screen.getByLabelText("A name to use instead"),
      "Ursula K.  Le Guin",
    );
    await user.click(screen.getByRole("button", { name: "Rename" }));

    await waitFor(() =>
      expect(api.lastCall("/api/books/authors/merge", "POST")?.body).toEqual({
        keys: ["le guin"],
        keep_name: "Ursula K. Le Guin",
      }),
    );
    expect(screen.queryByText(/so they went there/)).not.toBeInTheDocument();
  });

  it("undoes one merge from the author it was folded into", async () => {
    stub([
      author({
        merged: [{ alias_id: 7, spelling: "U. K. Le Guin" }],
      }),
    ]);
    api.on("/api/books/authors/aliases/7", { status: 204 });
    renderWithProviders(<AuthorsPage />);

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Undo this merge" }));

    await waitFor(() =>
      expect(
        api.lastCall("/api/books/authors/aliases/7", "DELETE"),
      ).toBeDefined(),
    );
  });
});
