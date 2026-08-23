/** Tests for src/pages/BookDetail. */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigate };
});

import {
  OwnershipStatus,
  ReadStatus,
  type UserOut,
} from "../../../src/api/generated/model";
import BookDetail from "../../../src/pages/BookDetail";
import {
  makeBook,
  makeLoan,
  makeNote,
  makeProgress,
  makeTagSet,
  resetIds,
} from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

const OWNER: UserOut = {
  id: 1,
  username: "owner",
  is_admin: false,
  created_at: "2026-01-01T00:00:00",
};
const OTHER: UserOut = {
  id: 2,
  username: "other",
  is_admin: false,
  created_at: "2026-01-01T00:00:00",
};
const ADMIN: UserOut = {
  id: 3,
  username: "admin",
  is_admin: true,
  created_at: "2026-01-01T00:00:00",
};

let api: MockApi;

beforeEach(() => {
  resetIds();
  navigate.mockReset();
  api = mockApi();
});

/** Stub the requests the page makes on mount. */
function stubLoad({
  book = makeBook({ id: 1, added_by: OWNER }),
  notes = [] as ReturnType<typeof makeNote>[],
  progress = [] as ReturnType<typeof makeProgress>[],
  tags = makeTagSet(),
  users = [OWNER, OTHER],
  googleBooks = false,
  goodreads = false,
} = {}) {
  api.on("/api/books/1/notes", { body: notes });
  api.on("/api/books/1/progress", { body: progress });
  // One element rather than none: a book with one copy is a copy, it is just
  // the only one, and that is what the endpoint answers.
  api.on("/api/books/1/copies", { body: [book] });
  api.on("/api/books/tags", { body: tags });
  api.on("/api/collections", { body: [] });
  api.on("/api/users", { body: users });
  api.on("/api/settings/features", {
    body: {
      google_books_enabled: googleBooks,
      // Toggled on and a key stored. The two are separate flags because a
      // toggle with no key produces a button that can only ever 400.
      google_books_ready: googleBooks,
      goodreads_lookup_enabled: goodreads,
      default_locale: "en",
    },
  });
  api.on(/\/api\/books\/1$/, { body: book });
  return book;
}

function renderDetail(currentUser: UserOut = OWNER) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/book/:id"
        element={<BookDetail currentUser={currentUser} />}
      />
    </Routes>,
    { route: "/book/1" },
  );
}

describe("BookDetail", () => {
  it("renders the book's details", async () => {
    stubLoad({
      book: makeBook({
        id: 1,
        title: "Dune",
        author: "Frank Herbert",
        publisher: "Chilton",
        added_by: OWNER,
      }),
    });
    renderDetail();

    expect(
      await screen.findByRole("heading", { name: "Dune" }),
    ).toBeInTheDocument();
    // The credit line is a phrase with each name inside it linked, so the
    // sentence is spread across elements and the link is what to assert on.
    expect(
      screen.getByRole("link", { name: "Frank Herbert" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Chilton")).toBeInTheDocument();
  });

  it("reports a book that could not be loaded", async () => {
    api.on("/api/books/1/notes", { body: [] });
    api.on("/api/books/tags", { body: [] });
    api.on("/api/users", { body: [] });
    api.on(/\/api\/books\/1$/, {
      status: 404,
      body: { detail: "Book not found" },
    });
    renderDetail();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Book not found",
    );
  });

  describe("reading status", () => {
    it("marks the current status as pressed", async () => {
      stubLoad({
        book: makeBook({
          id: 1,
          my_status: ReadStatus.reading,
          added_by: OWNER,
        }),
      });
      renderDetail();

      expect(
        await screen.findByRole("button", { name: /Reading/ }),
      ).toHaveAttribute("aria-pressed", "true");
    });

    it("updates the status when another option is chosen", async () => {
      stubLoad();
      api.on("/api/books/1/status", {
        body: makeBook({ id: 1, my_status: ReadStatus.read }),
      });
      renderDetail();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Read" }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/1/status", "PUT")?.body).toEqual({
          status: "read",
        }),
      );
    });

    it("surfaces a failed status change", async () => {
      stubLoad();
      api.on("/api/books/1/status", {
        status: 404,
        body: { detail: "Book not found" },
      });
      renderDetail();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Read" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Book not found",
      );
    });
  });

  describe("privacy", () => {
    it("lets the owner toggle it", async () => {
      stubLoad({
        book: makeBook({ id: 1, is_private: false, added_by: OWNER }),
      });
      api.on("/api/books/1/privacy", {
        body: makeBook({ id: 1, is_private: true }),
      });
      renderDetail(OWNER);

      await userEvent
        .setup()
        .click(await screen.findByRole("checkbox", { name: /Private/ }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/1/privacy", "PATCH")?.body).toEqual({
          is_private: true,
        }),
      );
    });

    it("hides the toggle from everyone else", async () => {
      stubLoad({ book: makeBook({ id: 1, added_by: OWNER }) });
      renderDetail(OTHER);

      await screen.findByRole("heading", { name: "Dune" });
      expect(
        screen.queryByRole("checkbox", { name: /Private/ }),
      ).not.toBeInTheDocument();
    });

    it("shows a read-only marker on someone else's private book", async () => {
      stubLoad({
        book: makeBook({ id: 1, is_private: true, added_by: OWNER }),
      });
      renderDetail(OTHER);

      // The lock is a drawn icon now, so the assertion is on the words. The
      // icon is decorative and carries no accessible name by design.
      expect(await screen.findByText("Private")).toBeInTheDocument();
    });
  });

  describe("tags", () => {
    it("lists the book's tags", async () => {
      const tags = makeTagSet();
      stubLoad({
        book: makeBook({ id: 1, tags: [tags[1]!], added_by: OWNER }),
        tags,
      });
      renderDetail();

      expect(await screen.findByText("Fantasy")).toBeInTheDocument();
    });

    it("says so when there are none", async () => {
      stubLoad({ book: makeBook({ id: 1, tags: [], added_by: OWNER }) });
      renderDetail();

      expect(await screen.findByText("No tags yet")).toBeInTheDocument();
    });

    it("adds a tag", async () => {
      const tags = makeTagSet();
      stubLoad({ book: makeBook({ id: 1, tags: [], added_by: OWNER }), tags });
      api.on(/\/api\/books\/1\/tags\//, { body: makeBook({ id: 1 }) });
      renderDetail();

      const user = userEvent.setup();
      await user.click(await screen.findByRole("button", { name: "+ Add" }));
      // The tag categories start closed: the curated vocabulary is 105 tags.
      await user.click(await screen.findByRole("button", { name: /Genre/ }));
      await user.click(await screen.findByRole("button", { name: "Fantasy" }));

      await waitFor(() =>
        expect(
          api.lastCall(`/api/books/1/tags/${tags[1]!.id}`, "POST"),
        ).toBeDefined(),
      );
    });

    it("removes a tag", async () => {
      const tags = makeTagSet();
      stubLoad({
        book: makeBook({ id: 1, tags: [tags[1]!], added_by: OWNER }),
        tags,
      });
      api.on(/\/api\/books\/1\/tags\//, { body: makeBook({ id: 1 }) });
      renderDetail();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Remove Fantasy" }));

      await waitFor(() =>
        expect(
          api.lastCall(`/api/books/1/tags/${tags[1]!.id}`, "DELETE"),
        ).toBeDefined(),
      );
    });

    it("does not offer a tag the book already has", async () => {
      const tags = makeTagSet();
      stubLoad({
        book: makeBook({ id: 1, tags: [tags[1]!], added_by: OWNER }),
        tags,
      });
      renderDetail();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "+ Add" }));

      // "Fantasy" appears once, as the assigned pill, not again in the picker.
      expect(screen.getAllByText("Fantasy")).toHaveLength(1);
    });
  });

  describe("loans", () => {
    it("offers the other members as borrowers", async () => {
      stubLoad();
      renderDetail(OWNER);

      const select = await screen.findByLabelText("Loan to");
      expect(
        within(select).getByRole("option", { name: "other" }),
      ).toBeInTheDocument();
      // Lending to yourself is not a thing.
      expect(
        within(select).queryByRole("option", { name: "owner" }),
      ).not.toBeInTheDocument();
    });

    it("records a loan", async () => {
      stubLoad();
      api.on(/\/api\/loans$/, { body: makeLoan() });
      renderDetail(OWNER);

      const user = userEvent.setup();
      await user.selectOptions(
        await screen.findByLabelText("Loan to"),
        String(OTHER.id),
      );
      await user.click(screen.getByRole("button", { name: "Loan" }));

      // An explicit timeout, because the default 1000ms is a budget this test
      // was already spending most of before it asserted. `user-event` does its
      // own async work per interaction, so the wall clock here is a function of
      // how loaded the worker is rather than of what the code does, and the
      // pair of loan tests failed in CI while passing locally for exactly that
      // reason. The assertion is unchanged; only the patience is.
      await waitFor(
        () =>
          expect(api.lastCall(/\/api\/loans$/, "POST")?.body).toEqual({
            book_id: 1,
            loaned_to_user_id: OTHER.id,
            // Exactly one borrower: the API rejects both or neither with a 422.
            loaned_to_name: null,
            // Explicitly null rather than absent: a loan with no deadline is the
            // common case, and the field is always sent.
            due_at: null,
            // False, not absent, on a book nobody said not to lend. The server
            // reads it only on a book marked "never lent".
            acknowledge_not_lendable: false,
          }),
        { timeout: 5000 },
      );
    });

    it("records a loan to somebody with no account", async () => {
      // The people most likely to keep a book are the ones who will never have
      // an account here.
      stubLoad();
      api.on(/\/api\/loans$/, { body: makeLoan() });
      renderDetail(OWNER);

      const user = userEvent.setup();
      await user.click(await screen.findByLabelText("Someone else"));
      // `fireEvent.change`, not `user.type`. Typing thirteen characters costs
      // thirteen async round trips and was most of this test's 2.4 seconds; the
      // field has no per-keystroke behaviour to exercise, so a single change
      // event tests the same thing. CLAUDE.md already says user-event is the
      // wrong tool where its own scheduling is what is being measured.
      fireEvent.change(screen.getByLabelText("Borrower's name"), {
        target: { value: "the neighbour" },
      });
      await user.click(screen.getByRole("button", { name: "Loan" }));

      await waitFor(
        () =>
          expect(api.lastCall(/\/api\/loans$/, "POST")?.body).toEqual({
            book_id: 1,
            // Exactly one of the two. Both is a 422.
            loaned_to_user_id: null,
            loaned_to_name: "the neighbour",
            due_at: null,
            acknowledge_not_lendable: false,
          }),
        { timeout: 5000 },
      );
    });

    it("keeps the Loan button disabled until a name is typed", async () => {
      stubLoad();
      renderDetail(OWNER);

      await userEvent
        .setup()
        .click(await screen.findByLabelText("Someone else"));

      expect(screen.getByRole("button", { name: "Loan" })).toBeDisabled();
    });

    it("will not lend to a name that is only whitespace", async () => {
      stubLoad();
      renderDetail(OWNER);

      const user = userEvent.setup();
      await user.click(await screen.findByLabelText("Someone else"));
      fireEvent.change(screen.getByLabelText("Borrower's name"), { target: { value: "   " } });

      expect(screen.getByRole("button", { name: "Loan" })).toBeDisabled();
    });

    it("names an external borrower on the badge", async () => {
      stubLoad({
        book: makeBook({
          id: 1,
          added_by: OWNER,
          active_loan: makeLoan({
            id: 9,
            loaned_to: null,
            loaned_to_user_id: null,
            loaned_to_name: "the neighbour",
          }),
        }),
      });
      renderDetail();

      expect(
        await screen.findByText(/the neighbour, who has no account/),
      ).toBeInTheDocument();
    });

    it("keeps the Loan button disabled until a borrower is picked", async () => {
      stubLoad();
      renderDetail(OWNER);
      expect(
        await screen.findByRole("button", { name: "Loan" }),
      ).toBeDisabled();
    });

    it("offers a return instead when the book is out", async () => {
      stubLoad({
        book: makeBook({
          id: 1,
          added_by: OWNER,
          active_loan: makeLoan({ id: 9 }),
        }),
      });
      renderDetail();

      expect(
        await screen.findByRole("button", { name: "Mark as Returned" }),
      ).toBeInTheDocument();
    });

    it("records a return", async () => {
      stubLoad({
        book: makeBook({
          id: 1,
          added_by: OWNER,
          active_loan: makeLoan({ id: 9 }),
        }),
      });
      api.on("/api/loans/9/return", { body: makeLoan({ id: 9 }) });
      renderDetail();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Mark as Returned" }));

      await waitFor(() =>
        expect(api.lastCall("/api/loans/9/return", "PUT")).toBeDefined(),
      );
    });

    it("reports a conflicting loan", async () => {
      stubLoad();
      api.on(/\/api\/loans$/, {
        status: 409,
        body: { detail: "Book is already loaned out" },
      });
      renderDetail(OWNER);

      const user = userEvent.setup();
      await user.selectOptions(
        await screen.findByLabelText("Loan to"),
        String(OTHER.id),
      );
      await user.click(screen.getByRole("button", { name: "Loan" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Book is already loaned out",
      );
    });
  });

  describe("metadata refresh", () => {
    it("is offered when the book has an ISBN", async () => {
      stubLoad({
        book: makeBook({ id: 1, isbn: "9780441013593", added_by: OWNER }),
      });
      renderDetail();
      expect(
        await screen.findByRole("button", { name: "Refresh Metadata" }),
      ).toBeInTheDocument();
    });

    it("is hidden when it has none", async () => {
      stubLoad({ book: makeBook({ id: 1, isbn: null, added_by: OWNER }) });
      renderDetail();

      await screen.findByRole("heading", { name: "Dune" });
      expect(
        screen.queryByRole("button", { name: "Refresh Metadata" }),
      ).not.toBeInTheDocument();
    });

    it("reports a failed refresh next to its own button", async () => {
      stubLoad();
      api.on("/api/books/1/refresh", {
        status: 404,
        body: { detail: "No metadata found" },
      });
      renderDetail();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Refresh Metadata" }));

      expect(await screen.findByText("No metadata found")).toBeInTheDocument();
    });
  });

  describe("notes", () => {
    it("says so when there are none", async () => {
      stubLoad({ notes: [] });
      renderDetail();
      expect(await screen.findByText("No notes yet")).toBeInTheDocument();
    });

    it("lists existing notes", async () => {
      stubLoad({ notes: [makeNote({ content: "Loved the ending" })] });
      renderDetail();
      expect(await screen.findByText("Loved the ending")).toBeInTheDocument();
    });

    it("adds a note, trimming whitespace", async () => {
      stubLoad();
      api.on(
        "/api/books/1/notes",
        { body: makeNote({ content: "New" }) },
        "POST",
      );
      renderDetail();

      const user = userEvent.setup();
      fireEvent.change(await screen.findByLabelText("Add a note"), { target: { value: "  padded  " } });
      await user.click(screen.getByRole("button", { name: "Add" }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/1/notes", "POST")?.body).toEqual({
          content: "padded",
        }),
      );
    });

    it("keeps Add disabled for an empty note", async () => {
      stubLoad();
      renderDetail();
      await screen.findByLabelText("Add a note");
      expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    });

    it("lets the author edit their own note", async () => {
      stubLoad({
        notes: [makeNote({ id: 5, user_id: OWNER.id, content: "v1" })],
      });
      api.on("/api/books/1/notes/5", {
        body: makeNote({ id: 5, content: "v2" }),
      });
      renderDetail(OWNER);

      const user = userEvent.setup();
      await user.click(await screen.findByRole("button", { name: "Edit" }));
      const box = screen.getByLabelText("Edit note");
      await user.clear(box);
      fireEvent.change(box, { target: { value: "v2" } });
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/1/notes/5", "PUT")?.body).toEqual({
          content: "v2",
        }),
      );
    });

    it("hides Edit on someone else's note", async () => {
      stubLoad({ notes: [makeNote({ user_id: OTHER.id })] });
      renderDetail(OWNER);

      await screen.findByText("A note");
      expect(
        screen.queryByRole("button", { name: "Edit" }),
      ).not.toBeInTheDocument();
    });

    it("hides Delete from a non-author, non-admin", async () => {
      stubLoad({ notes: [makeNote({ user_id: OTHER.id })] });
      renderDetail(OWNER);

      await screen.findByText("A note");
      expect(
        screen.queryByRole("button", { name: "Delete" }),
      ).not.toBeInTheDocument();
    });

    it("offers Delete to an admin on anyone's note", async () => {
      stubLoad({
        notes: [makeNote({ user_id: OTHER.id })],
        users: [OWNER, OTHER, ADMIN],
      });
      renderDetail(ADMIN);

      expect(
        await screen.findByRole("button", { name: "Delete" }),
      ).toBeInTheDocument();
    });
  });

  describe("deleting the book", () => {
    it("deletes and returns to the library", async () => {
      stubLoad();
      api.on(/\/api\/books\/1$/, { status: 204 }, "DELETE");
      renderDetail();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Move to Trash" }));

      await waitFor(() => expect(navigate).toHaveBeenCalledWith("/"));
    });

    it("does not ask for confirmation, because it can be taken back", async () => {
      // The delete is reversible and raises a toast offering exactly that. A
      // modal in front of it would be friction ahead of an action undone in
      // one tap. The irreversible verb lives in the trash and does ask.
      stubLoad();
      api.on(/\/api\/books\/1$/, { status: 204 }, "DELETE");
      const confirmSpy = vi.spyOn(window, "confirm");
      renderDetail();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Move to Trash" }));

      await waitFor(() =>
        expect(api.lastCall(/\/api\/books\/1$/, "DELETE")).toBeDefined(),
      );
      expect(confirmSpy).not.toHaveBeenCalled();
    });
  });

  it("uploads a replacement cover", async () => {
    stubLoad();
    api.on("/api/books/1/cover", {
      body: makeBook({ id: 1, cover_url: "/covers/1.png" }),
    });
    renderDetail();

    const input = await screen.findByLabelText("Upload Cover");
    await userEvent
      .setup()
      .upload(input, new File(["png"], "cover.png", { type: "image/png" }));

    await waitFor(() =>
      expect(api.lastCall("/api/books/1/cover", "POST")).toBeDefined(),
    );
  });
});

describe("BookDetail ownership", () => {
  it("shows where the book physically is", async () => {
    stubLoad({
      book: makeBook({
        id: 1,
        added_by: OWNER,
        ownership: OwnershipStatus.unknown,
      }),
    });
    renderDetail();

    expect(
      await screen.findByRole("button", { name: "Not confirmed" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("records a confirmation", async () => {
    const book = stubLoad({
      book: makeBook({
        id: 1,
        added_by: OWNER,
        ownership: OwnershipStatus.unknown,
      }),
    });
    api.on("/api/books/1/ownership", {
      body: { ...book, ownership: OwnershipStatus.owned },
    });
    renderDetail();

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "On the shelf" }));

    await waitFor(() =>
      expect(api.lastCall("/ownership", "PATCH")?.body).toEqual({
        ownership: "owned",
      }),
    );
  });

  it("is not the same control as the reading status", async () => {
    // "I have read this" and "we own a copy" are independent claims, and the
    // page has to let them disagree.
    stubLoad({
      book: makeBook({
        id: 1,
        added_by: OWNER,
        my_status: ReadStatus.read,
        ownership: OwnershipStatus.not_owned,
      }),
    });
    renderDetail();

    expect(await screen.findByRole("button", { name: "Read" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Not owned" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

/** One candidate as the picker receives it. */
const CANDIDATE = {
  source: "open_library",
  google_books_id: "abc123",
  title: "Dune",
  subtitle: null,
  author: "Frank Herbert",
  publisher: "Chilton",
  year: 1965,
  description: null,
  page_count: 412,
  language: "en",
  categories: null,
  cover_url: null,
  isbn13: "9780441013593",
  series_name: null,
  series_index: null,
  suggested_tag_ids: [],
};

describe("BookDetail enrichment", () => {
  it("is offered even with no Google Books key", async () => {
    // It used to hide itself without one. The other five catalogues need no
    // key, so hiding it left a household unable to fill in exactly the books
    // those catalogues cover best.
    stubLoad({ googleBooks: false });
    renderDetail();
    expect(
      await screen.findByRole("button", { name: "Find more details" }),
    ).toBeInTheDocument();
  });

  it("offers the lookup when enabled", async () => {
    stubLoad({ googleBooks: true });
    renderDetail();
    expect(
      await screen.findByRole("button", { name: "Find more details" }),
    ).toBeInTheDocument();
  });

  it("writes nothing until an edition is chosen", async () => {
    // The whole reason the picker exists. The button used to take whichever
    // result came back first, and a catalogue will happily return the other
    // printing of the right book.
    stubLoad({ googleBooks: true });
    api.on("/api/books/1/enrich/candidates", { body: [CANDIDATE] });
    renderDetail();

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Find more details" }));

    await screen.findByRole("heading", { name: "Which edition is this?" });
    expect(api.lastCall("/enrich/apply", "POST")).toBeUndefined();
  });

  it("offers the editions it found", async () => {
    stubLoad({ googleBooks: true });
    api.on("/api/books/1/enrich/candidates", {
      body: [CANDIDATE, { ...CANDIDATE, year: 1999, page_count: 500 }],
    });
    renderDetail();

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Find more details" }));

    const dialog = await screen.findByRole("dialog");
    // Scoped to the dialog: the page heading is also the book's title.
    expect(within(dialog).getAllByText("Dune")).toHaveLength(2);
  });

  it("fills gaps rather than overwriting typed values", async () => {
    const book = stubLoad({ googleBooks: true });
    api.on("/api/books/1/enrich/candidates", { body: [CANDIDATE] });
    api.on("/api/books/1/enrich/apply", {
      body: { book, found: true, updated_fields: ["page_count"] },
    });
    renderDetail();

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Find more details" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByText("Dune"));

    await waitFor(() =>
      expect(api.lastCall("/enrich/apply", "POST")).toBeDefined(),
    );
    const query = new URL(
      api.lastCall("/enrich/apply", "POST")!.url,
      "http://localhost",
    ).searchParams;
    expect(query.get("overwrite")).toBe("false");
  });

  it("says what it added", async () => {
    const book = stubLoad({ googleBooks: true });
    api.on("/api/books/1/enrich/candidates", { body: [CANDIDATE] });
    api.on("/api/books/1/enrich/apply", {
      body: { book, found: true, updated_fields: ["page_count", "language"] },
    });
    renderDetail();

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Find more details" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByText("Dune"));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Added: page count, language.",
    );
  });
});

describe("BookDetail Goodreads link", () => {
  it("is hidden unless an admin switched it on", async () => {
    stubLoad({ goodreads: false });
    renderDetail();
    await screen.findByRole("heading", { name: "Dune" });
    expect(
      screen.queryByRole("link", { name: "Look up on Goodreads" }),
    ).not.toBeInTheDocument();
  });

  it("searches by ISBN when there is one", async () => {
    stubLoad({
      goodreads: true,
      book: makeBook({ id: 1, added_by: OWNER, isbn: "9780441013593" }),
    });
    renderDetail();

    const link = await screen.findByRole("link", {
      name: "Look up on Goodreads",
    });
    expect(link).toHaveAttribute(
      "href",
      "https://www.goodreads.com/search?q=9780441013593",
    );
  });

  it("falls back to the title", async () => {
    stubLoad({
      goodreads: true,
      book: makeBook({ id: 1, added_by: OWNER, title: "Dune", isbn: null }),
    });
    renderDetail();

    const link = await screen.findByRole("link", {
      name: "Look up on Goodreads",
    });
    expect(link).toHaveAttribute(
      "href",
      "https://www.goodreads.com/search?q=Dune",
    );
  });

  it("does not leak the referring page to a third party", async () => {
    stubLoad({ goodreads: true });
    renderDetail();

    const link = await screen.findByRole("link", {
      name: "Look up on Goodreads",
    });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});

describe("BookDetail enrichment fields", () => {
  it("shows the page count, language and categories", async () => {
    stubLoad({
      book: makeBook({
        id: 1,
        added_by: OWNER,
        page_count: 412,
        language: "en",
        categories: ["Fiction", "Science Fiction"],
      }),
    });
    renderDetail();

    expect(await screen.findByText("412 pages")).toBeInTheDocument();
    expect(screen.getByText("en")).toBeInTheDocument();
    expect(screen.getByText("Science Fiction")).toBeInTheDocument();
  });

  it("leaves the sections out when there is nothing to show", async () => {
    stubLoad({ book: makeBook({ id: 1, added_by: OWNER, categories: [] }) });
    renderDetail();
    await screen.findByRole("heading", { name: "Dune" });
    expect(screen.queryByText("Categories")).not.toBeInTheDocument();
  });
});

describe("BookDetail lending with a due date", () => {
  it("sends the chosen date as the end of that day", async () => {
    // Midnight would make a book due "today" overdue from the moment it was
    // lent, which is not what anyone means by a return date.
    stubLoad();
    api.on(/\/api\/loans$/, { body: makeLoan() });
    renderDetail(OWNER);

    const user = userEvent.setup();
    await user.selectOptions(
      await screen.findByLabelText("Loan to"),
      String(OTHER.id),
    );
    fireEvent.change(screen.getByLabelText("Due back"), { target: { value: "2026-09-01" } });
    await user.click(screen.getByRole("button", { name: "Loan" }));

    await waitFor(() =>
      expect(api.lastCall(/\/api\/loans$/, "POST")?.body).toMatchObject({
        due_at: "2026-09-01T23:59:59",
      }),
    );
  });

  it("offers no date field once the book is already out", async () => {
    stubLoad({
      book: makeBook({ id: 1, added_by: OWNER, active_loan: makeLoan() }),
    });
    renderDetail(OWNER);

    await screen.findByRole("heading", { name: "Dune" });
    expect(screen.queryByLabelText("Due back")).not.toBeInTheDocument();
  });
});

describe("BookDetail reading progress", () => {
  it("records a page against the book being viewed", async () => {
    const user = userEvent.setup();
    stubLoad({ book: makeBook({ id: 1, added_by: OWNER, page_count: 412 }) });
    api.on(
      "/api/books/1/progress",
      { status: 201, body: makeProgress() },
      "POST",
    );
    renderDetail(OWNER);

    await screen.findByRole("heading", { name: "Dune" });
    await user.type(screen.getByRole("spinbutton", { name: "Page" }), "64");
    await user.click(screen.getByRole("button", { name: "Record progress" }));

    await waitFor(() =>
      expect(api.lastCall("/api/books/1/progress", "POST")?.body).toEqual({
        page: 64,
      }),
    );
  });

  it("shows the history the server returns", async () => {
    stubLoad({
      book: makeBook({ id: 1, added_by: OWNER, page_count: 412 }),
      progress: [makeProgress({ page: 120 })],
    });
    renderDetail(OWNER);

    expect(await screen.findByText(/Page 120/)).toBeInTheDocument();
  });

  it("deletes one entry", async () => {
    const user = userEvent.setup();
    const entry = makeProgress({ page: 120 });
    stubLoad({
      book: makeBook({ id: 1, added_by: OWNER, page_count: 412 }),
      progress: [entry],
    });
    api.on(`/api/books/1/progress/${entry.id}`, { status: 204 }, "DELETE");
    renderDetail(OWNER);

    await screen.findByText(/Page 120/);
    await user.click(screen.getByRole("button", { name: "Remove this entry" }));

    await waitFor(() =>
      expect(
        api.lastCall(`/api/books/1/progress/${entry.id}`, "DELETE"),
      ).toBeDefined(),
    );
  });

  it("re-reads the book after recording, because the status may have moved", async () => {
    // The first entry on an unstarted book promotes it to reading, and that
    // change is on the book payload rather than in the response.
    const user = userEvent.setup();
    stubLoad({ book: makeBook({ id: 1, added_by: OWNER, page_count: 412 }) });
    api.on(
      "/api/books/1/progress",
      { status: 201, body: makeProgress() },
      "POST",
    );
    renderDetail(OWNER);

    await screen.findByRole("heading", { name: "Dune" });
    const before = api.calls.filter((call) =>
      /\/api\/books\/1$/.test(call.url),
    ).length;

    await user.type(screen.getByRole("spinbutton", { name: "Page" }), "64");
    await user.click(screen.getByRole("button", { name: "Record progress" }));

    await waitFor(() =>
      expect(
        api.calls.filter((call) => /\/api\/books\/1$/.test(call.url)).length,
      ).toBeGreaterThan(before),
    );
  });
});
