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

/** Two proposed groups, each carrying the name a batch would keep. */
const TOLKIEN = {
  keys: ["jrr tolkien", "j r r tolkien"],
  names: ["JRR Tolkien", "J. R. R. Tolkien"],
  reasons: ["spelling"],
  keep_name: "J. R. R. Tolkien",
};

const SMITHS = {
  keys: ["j smith", "james smith", "john smith"],
  names: ["J. Smith", "James Smith", "John Smith"],
  reasons: ["initials"],
  keep_name: "J. Smith",
};

const LE_GUIN = {
  keys: ["le guin", "ursula k", "ursula k le guin"],
  names: ["Le Guin", "Ursula K.", "Ursula K. Le Guin"],
  reasons: ["fragment"],
  keep_name: "Ursula K. Le Guin",
};

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

  it("folds every ticked group in one request", async () => {
    stub([author()], [TOLKIEN, LE_GUIN]);
    // Registered after `/merge`, because a matcher is a substring and the later
    // registration wins: the shorter path first would answer this one.
    api.on("/api/books/authors/merge", { body: author() });
    api.on("/api/books/authors/merge/batch", { body: { merged: [author()] } });
    renderWithProviders(<AuthorsPage />);

    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", { name: "Fold the ticked groups" }),
      );

    await waitFor(() =>
      expect(
        api.lastCall("/api/books/authors/merge/batch", "POST")?.body,
      ).toEqual({
        groups: [
          { keys: TOLKIEN.keys, keep_name: "J. R. R. Tolkien" },
          { keys: LE_GUIN.keys, keep_name: "Ursula K. Le Guin" },
        ],
      }),
    );
  });

  it("leaves out a group that was unticked", async () => {
    stub([author()], [TOLKIEN, LE_GUIN]);
    api.on("/api/books/authors/merge", { body: author() });
    api.on("/api/books/authors/merge/batch", { body: { merged: [author()] } });
    renderWithProviders(<AuthorsPage />);
    const user = userEvent.setup();

    await user.click(
      await screen.findByLabelText("Fold into J. R. R. Tolkien"),
    );
    await user.click(
      screen.getByRole("button", { name: "Fold the ticked groups" }),
    );

    await waitFor(() =>
      expect(
        api.lastCall("/api/books/authors/merge/batch", "POST")?.body,
      ).toEqual({
        groups: [{ keys: LE_GUIN.keys, keep_name: "Ursula K. Le Guin" }],
      }),
    );
  });

  it("leaves out a name the reader unticked inside a group", async () => {
    // The control the card exists for: the grouping is transitive, so a name
    // taken out of a group has to stay out of the batch as well as out of that
    // group's own merge. While the checkbox was the card's own state, the batch
    // folded the unticked name anyway.
    stub([author()], [SMITHS, TOLKIEN]);
    api.on("/api/books/authors/merge", { body: author() });
    api.on("/api/books/authors/merge/batch", { body: { merged: [author()] } });
    renderWithProviders(<AuthorsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText("Include James Smith"));
    await user.click(
      screen.getByRole("button", { name: "Fold the ticked groups" }),
    );

    await waitFor(() =>
      expect(
        api.lastCall("/api/books/authors/merge/batch", "POST")?.body,
      ).toEqual({
        groups: [
          { keys: ["j smith", "john smith"], keep_name: "J. Smith" },
          { keys: TOLKIEN.keys, keep_name: "J. R. R. Tolkien" },
        ],
      }),
    );
  });

  it("withdraws a group whose kept name the reader unticked", async () => {
    // The server keeps one of the group's own names, so a group without it is
    // a 422 rather than a merge. It leaves the batch instead of being sent.
    stub([author()], [SMITHS, TOLKIEN]);
    api.on("/api/books/authors/merge", { body: author() });
    api.on("/api/books/authors/merge/batch", { body: { merged: [author()] } });
    renderWithProviders(<AuthorsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText("Include J. Smith"));

    expect(screen.getByText(/1 groups ticked/)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Fold the ticked groups" }),
    );
    await waitFor(() =>
      expect(
        api.lastCall("/api/books/authors/merge/batch", "POST")?.body,
      ).toEqual({
        groups: [{ keys: TOLKIEN.keys, keep_name: "J. R. R. Tolkien" }],
      }),
    );
  });

  it("counts what it would send, not the groups it came from", async () => {
    // The last checkable fact before a write. While the bar counted whole
    // groups and the request sent only the names still ticked, unticking one
    // name left both the sentence and the confirmation overstating the write.
    stub([author()], [SMITHS, TOLKIEN]);
    api.on("/api/books/authors/merge", { body: author() });
    api.on("/api/books/authors/merge/batch", { body: { merged: [author()] } });
    renderWithProviders(<AuthorsPage />);
    const user = userEvent.setup();

    expect(
      await screen.findByText(/2 groups ticked, 5 spellings in all/),
    ).toBeInTheDocument();

    // James Smith is not the kept name, so the group stays ticked and the
    // request loses exactly one key.
    await user.click(screen.getByLabelText("Include James Smith"));

    expect(
      screen.getByText(/2 groups ticked, 4 spellings in all/),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Fold the ticked groups" }),
    );

    expect(window.confirm).toHaveBeenCalledWith(
      "Fold 2 groups, 4 spellings in all?",
    );
    // The body itself rather than a sum of it: four keys, which is the number
    // the sentence and the confirmation both just claimed.
    await waitFor(() =>
      expect(
        api.lastCall("/api/books/authors/merge/batch", "POST")?.body,
      ).toEqual({
        groups: [
          { keys: ["j smith", "john smith"], keep_name: "J. Smith" },
          { keys: TOLKIEN.keys, keep_name: "J. R. R. Tolkien" },
        ],
      }),
    );
  });

  it("puts a narrowed group back when its tick is clicked again", async () => {
    // One click, one visible change. While `checked` read the narrowing and
    // `onChange` wrote only the tick, this click moved nothing on screen and
    // flipped a variable the reader could not see.
    stub([author()], [SMITHS, TOLKIEN]);
    api.on("/api/books/authors/merge", { body: author() });
    api.on("/api/books/authors/merge/batch", { body: { merged: [author()] } });
    renderWithProviders(<AuthorsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText("Include J. Smith"));
    expect(screen.getByText(/1 groups ticked/)).toBeInTheDocument();

    await user.click(screen.getByLabelText("Fold into J. Smith"));

    expect(screen.getByText(/2 groups ticked/)).toBeInTheDocument();
    // The names it needs came back with it, which is what makes the click
    // visible rather than merely effective.
    expect(screen.getByLabelText("Include J. Smith")).toBeChecked();
    expect(screen.getByLabelText("Fold into J. Smith")).toBeChecked();
  });

  it("says a narrowed group is out for the reader's own reason", async () => {
    stub([author()], [SMITHS, TOLKIEN]);
    renderWithProviders(<AuthorsPage />);

    await userEvent
      .setup()
      .click(await screen.findByLabelText("Include J. Smith"));

    expect(
      screen.getByText(
        /1 more are out until the name they would be folded into/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/more are left out/)).not.toBeInTheDocument();
  });

  it("does not offer a held back group for folding", async () => {
    // No `keep_name`: folding it would repoint a merge somebody already made,
    // so the server would answer 409 and there is no button to reach it with.
    stub([author()], [TOLKIEN, { ...LE_GUIN, keep_name: null }]);
    renderWithProviders(<AuthorsPage />);

    // It says the batch leaves it alone, not that it cannot be folded: the
    // buttons on the same card still reach the single merge, which does repoint
    // that standing row.
    expect(
      await screen.findByText(/Folding all leaves this group alone/),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Keep this name" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByLabelText("Fold into Ursula K. Le Guin"),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/1 groups ticked/)).toBeInTheDocument();
    expect(screen.getByText(/1 more are left out/)).toBeInTheDocument();
  });

  it("shows the batch and the tick together, or neither", async () => {
    // One predicate decides both. While the bar needed two groups and the tick
    // needed only a name, a single group rendered a ticked checkbox with
    // nothing on the page to act on it.
    stub([author()], [TOLKIEN]);
    renderWithProviders(<AuthorsPage />);

    expect(
      await screen.findByLabelText("Fold into J. R. R. Tolkien"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Fold the ticked groups" }),
    ).toBeInTheDocument();
  });

  it("shows neither when every group is held back", async () => {
    stub([author()], [{ ...TOLKIEN, keep_name: null }]);
    renderWithProviders(<AuthorsPage />);
    await screen.findByText("Probably the same person");

    expect(
      screen.queryByRole("button", { name: "Fold the ticked groups" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Fold into J. R. R. Tolkien"),
    ).not.toBeInTheDocument();
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
