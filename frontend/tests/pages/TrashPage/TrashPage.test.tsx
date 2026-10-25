/**
 * Tests for src/pages/TrashPage.
 *
 * The page exists so a delete can be taken back, so the tests are about the
 * two verbs and the asymmetry between them: putting a book back is one tap,
 * and destroying it asks first, because that one really is final.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fc from "fast-check";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getUpdateStatusMutationKey } from "../../../src/api/generated/endpoints/books/books";
import { Locale } from "../../../src/api/generated/model";
import { ToastProvider } from "../../../src/app/toast";
import TrashPage from "../../../src/pages/TrashPage";
import { makeBook, resetIds } from "../../factories";
import {
  createTestQueryClient,
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
  api.on("/api/settings/features", {
    body: {
      google_books_ready: false,
      goodreads_lookup_enabled: false,
      default_locale: "en",
    },
  });
});

/** The list row holding a title. */
function rowOf(title: string): HTMLElement {
  return screen.getByText(title).closest("li")!;
}

function twoBooks() {
  stubTrash([
    makeBook({ id: 7, title: "Dune", deleted_at: "2026-08-19T10:00:00Z" }),
    makeBook({ id: 8, title: "Emma", deleted_at: "2026-08-19T10:00:00Z" }),
  ]);
}

function stubTrash(items: ReturnType<typeof makeBook>[]) {
  api.on("/api/books/trash", {
    body: { items, total: items.length, page: 1, page_size: 50 },
  });
}

describe("TrashPage", () => {
  it("lists what was deleted", async () => {
    stubTrash([
      makeBook({
        id: 7,
        title: "Deleted Book",
        deleted_at: "2026-08-19T10:00:00Z",
      }),
    ]);
    renderWithProviders(<TrashPage />);

    expect(await screen.findByText("Deleted Book")).toBeInTheDocument();
  });

  it("says when a book was deleted", async () => {
    // Anchored on a digit. The page's own explanation opens with "Deleted
    // books wait here", so a looser pattern matches two elements and
    // findByText refuses to choose between them.
    stubTrash([
      makeBook({ id: 7, title: "Dune", deleted_at: "2026-08-19T10:00:00Z" }),
    ]);
    renderWithProviders(<TrashPage />);

    expect(await screen.findByText(/^Deleted \d/)).toBeInTheDocument();
  });

  it("says when in the app's locale, not the browser's", async () => {
    // **The arm the defect survived.** This page rendered the date with a bare
    // `toLocaleDateString()`, so it took whatever locale the host had rather
    // than the one the member chose, and every existing assertion here was
    // anchored loosely enough not to notice. The two locales spell this date
    // differently, so asserting both is what observes it: `19.8.2026` against
    // `8/19/2026`.
    stubTrash([
      makeBook({ id: 7, title: "Dune", deleted_at: "2026-08-19T10:00:00Z" }),
    ]);
    renderWithProviders(<TrashPage />, { locale: Locale.de });

    expect(await screen.findByText(/19\.8\.2026/)).toBeInTheDocument();
    expect(screen.queryByText(/8\/19\/2026/)).not.toBeInTheDocument();
  });

  it("says the trash does not empty itself", async () => {
    stubTrash([makeBook({ id: 7, deleted_at: "2026-08-19T10:00:00Z" })]);
    renderWithProviders(<TrashPage />);

    expect(await screen.findByText(/until you empty it/)).toBeInTheDocument();
  });

  it("shows an empty state when nothing has been deleted", async () => {
    stubTrash([]);
    renderWithProviders(<TrashPage />);

    expect(await screen.findByText("The trash is empty")).toBeInTheDocument();
  });

  it("offers no empty-the-trash button when there is nothing in it", async () => {
    stubTrash([]);
    renderWithProviders(<TrashPage />);

    await screen.findByText("The trash is empty");
    expect(
      screen.queryByRole("button", { name: "Empty the trash" }),
    ).not.toBeInTheDocument();
  });

  describe("putting a book back", () => {
    it("restores without asking", async () => {
      stubTrash([
        makeBook({
          id: 7,
          title: "Deleted Book",
          deleted_at: "2026-08-19T10:00:00Z",
        }),
      ]);
      api.on("/api/books/7/restore", { body: makeBook({ id: 7 }) });
      const confirmSpy = vi.spyOn(window, "confirm");
      renderWithProviders(<TrashPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: /Put back/ }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/7/restore", "POST")).toBeDefined(),
      );
      expect(confirmSpy).not.toHaveBeenCalled();
    });
  });

  describe("a book mid request", () => {
    // The page shows which row is waiting on the server, and only that row:
    // the busy marker is a book id, so a second row must stay pressable.
    it("marks the row being put back, and only that row", async () => {
      twoBooks();
      const reply = heldOpen();
      api.on("/api/books/7/restore", reply.respond, "POST");
      renderWithProviders(
        <ToastProvider>
          <TrashPage />
        </ToastProvider>,
      );
      await screen.findByText("Dune");

      await userEvent
        .setup()
        .click(within(rowOf("Dune")).getByRole("button", { name: /Put back/ }));

      await waitFor(() =>
        expect(
          within(rowOf("Dune")).getByRole("button", {
            name: "Delete for good",
          }),
        ).toBeDisabled(),
      );
      expect(
        within(rowOf("Emma")).getByRole("button", { name: "Delete for good" }),
      ).toBeEnabled();

      reply.release({ body: makeBook({ id: 7 }) });

      expect(await screen.findByText("Back on the shelf.")).toBeInTheDocument();
    });

    it("marks the row being deleted for good, and only that row", async () => {
      twoBooks();
      const reply = heldOpen();
      api.on("/api/books/8/permanent", reply.respond, "DELETE");
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderWithProviders(<TrashPage />);
      await screen.findByText("Emma");

      await userEvent.setup().click(
        within(rowOf("Emma")).getByRole("button", {
          name: "Delete for good",
        }),
      );

      await waitFor(() =>
        expect(
          within(rowOf("Emma")).getByRole("button", { name: /Put back/ }),
        ).toBeDisabled(),
      );
      expect(
        within(rowOf("Dune")).getByRole("button", { name: /Put back/ }),
      ).toBeEnabled();

      reply.release({ status: 204 });
    });

    it("marks both rows while one is being put back and the other deleted", async () => {
      twoBooks();
      const restoring = heldOpen();
      const purging = heldOpen();
      api.on("/api/books/7/restore", restoring.respond, "POST");
      api.on("/api/books/8/permanent", purging.respond, "DELETE");
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderWithProviders(<TrashPage />);
      await screen.findByText("Dune");
      const user = userEvent.setup();

      await user.click(
        within(rowOf("Dune")).getByRole("button", { name: /Put back/ }),
      );
      await user.click(
        within(rowOf("Emma")).getByRole("button", { name: "Delete for good" }),
      );

      await waitFor(() =>
        expect(api.lastCall("/api/books/8/permanent", "DELETE")).toBeDefined(),
      );
      await waitFor(() =>
        expect(
          within(rowOf("Dune")).getByRole("button", {
            name: "Delete for good",
          }),
        ).toBeDisabled(),
      );
      for (const name of [/Put back/, "Delete for good"])
        expect(
          within(rowOf("Emma")).getByRole("button", { name }),
        ).toBeDisabled();

      restoring.release({ body: makeBook({ id: 7 }) });
      purging.release({ status: 204 });
    });

    it("keeps each row marked until its own put back answers", async () => {
      // A mutation remembers only its latest call, so reading the hook's own
      // variables would unmark Dune the moment Emma was pressed. And a write
      // that has answered stays in the mutation cache, so only reading the
      // pending ones lets Dune go once its own answer lands.
      twoBooks();
      const dune = heldOpen();
      const emma = heldOpen();
      api.on("/api/books/7/restore", dune.respond, "POST");
      api.on("/api/books/8/restore", emma.respond, "POST");
      renderWithProviders(<TrashPage />);
      await screen.findByText("Dune");
      const user = userEvent.setup();

      await user.click(
        within(rowOf("Dune")).getByRole("button", { name: /Put back/ }),
      );
      await user.click(
        within(rowOf("Emma")).getByRole("button", { name: /Put back/ }),
      );

      await waitFor(() =>
        expect(api.lastCall("/api/books/8/restore", "POST")).toBeDefined(),
      );
      await waitFor(() => {
        for (const title of ["Dune", "Emma"])
          expect(
            within(rowOf(title)).getByRole("button", {
              name: "Delete for good",
            }),
          ).toBeDisabled();
      });

      dune.release({ body: makeBook({ id: 7 }) });

      await waitFor(() =>
        expect(
          within(rowOf("Dune")).getByRole("button", { name: /Put back/ }),
        ).toBeEnabled(),
      );
      expect(
        within(rowOf("Emma")).getByRole("button", { name: /Put back/ }),
      ).toBeDisabled();

      emma.release({ body: makeBook({ id: 8 }) });
    });

    it("reports a failed put back when another row's put back was pressed after it", async () => {
      // The hook's own `error` is its latest call's, Emma's here, so Dune's
      // failure would show nothing at all.
      twoBooks();
      const dune = heldOpen();
      const emma = heldOpen();
      api.on("/api/books/7/restore", dune.respond, "POST");
      api.on("/api/books/8/restore", emma.respond, "POST");
      renderWithProviders(
        <ToastProvider>
          <TrashPage />
        </ToastProvider>,
      );
      await screen.findByText("Dune");
      const user = userEvent.setup();

      await user.click(
        within(rowOf("Dune")).getByRole("button", { name: /Put back/ }),
      );
      await user.click(
        within(rowOf("Emma")).getByRole("button", { name: /Put back/ }),
      );
      await waitFor(() =>
        expect(api.lastCall("/api/books/8/restore", "POST")).toBeDefined(),
      );

      dune.release({ status: 400, body: { detail: "Dune is not deleted" } });
      emma.release({ body: makeBook({ id: 8 }) });

      expect(await screen.findByText("Back on the shelf.")).toBeInTheDocument();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Dune is not deleted",
      );
    });

    it("reports a failed delete for good when another row's delete was pressed after it", async () => {
      // The purge twin: its failure is wired separately from the put back's,
      // so the test above cannot see it go silent.
      twoBooks();
      const dune = heldOpen();
      const emma = heldOpen();
      api.on("/api/books/7/permanent", dune.respond, "DELETE");
      api.on("/api/books/8/permanent", emma.respond, "DELETE");
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderWithProviders(<TrashPage />);
      await screen.findByText("Dune");
      const user = userEvent.setup();

      await user.click(
        within(rowOf("Dune")).getByRole("button", { name: "Delete for good" }),
      );
      await user.click(
        within(rowOf("Emma")).getByRole("button", { name: "Delete for good" }),
      );
      await waitFor(() =>
        expect(api.lastCall("/api/books/8/permanent", "DELETE")).toBeDefined(),
      );

      dune.release({ status: 400, body: { detail: "Dune is on loan" } });
      emma.release({ status: 204 });

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Dune is on loan",
      );
    });

    it("leaves a row pressable while a different write on its book is out", async () => {
      // Only a put back or a delete marks a trash row. A status change on the
      // same book carries the same id, and it must not refuse a press here.
      twoBooks();
      const queryClient = createTestQueryClient();
      void queryClient
        .getMutationCache()
        .build(queryClient, {
          mutationKey: getUpdateStatusMutationKey(),
          mutationFn: () => new Promise(() => {}),
        })
        .execute({ bookId: 7 });
      renderWithProviders(<TrashPage />, { queryClient });
      await screen.findByText("Dune");

      expect(queryClient.isMutating()).toBe(1);
      expect(
        within(rowOf("Dune")).getByRole("button", { name: /Put back/ }),
      ).toBeEnabled();
    });
  });

  describe("deleting for good", () => {
    it("asks first, because this one cannot be undone", async () => {
      stubTrash([
        makeBook({
          id: 7,
          title: "Deleted Book",
          deleted_at: "2026-08-19T10:00:00Z",
        }),
      ]);
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
      renderWithProviders(<TrashPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Delete for good" }));

      expect(confirmSpy).toHaveBeenCalled();
      expect(api.lastCall("/api/books/7/permanent", "DELETE")).toBeUndefined();
    });

    it("destroys the book once confirmed", async () => {
      stubTrash([
        makeBook({
          id: 7,
          title: "Deleted Book",
          deleted_at: "2026-08-19T10:00:00Z",
        }),
      ]);
      api.on("/api/books/7/permanent", { status: 204 }, "DELETE");
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderWithProviders(<TrashPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Delete for good" }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/7/permanent", "DELETE")).toBeDefined(),
      );
    });

    it("asks before emptying the whole trash", async () => {
      stubTrash([makeBook({ id: 7, deleted_at: "2026-08-19T10:00:00Z" })]);
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
      renderWithProviders(<TrashPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Empty the trash" }));

      expect(confirmSpy).toHaveBeenCalled();
      expect(api.lastCall("/api/books/trash", "DELETE")).toBeUndefined();
    });

    it("empties it once confirmed", async () => {
      stubTrash([makeBook({ id: 7, deleted_at: "2026-08-19T10:00:00Z" })]);
      api.on("/api/books/trash", { body: { purged: 1 } }, "DELETE");
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderWithProviders(<TrashPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Empty the trash" }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/trash", "DELETE")).toBeDefined(),
      );
    });

    it("says how many books emptying deleted, as the server counted them", async () => {
      // One row on screen and three in the reply: the toast reads the reply.
      stubTrash([makeBook({ id: 7, deleted_at: "2026-08-19T10:00:00Z" })]);
      api.on("/api/books/trash", { body: { purged: 3 } }, "DELETE");
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderWithProviders(
        <ToastProvider>
          <TrashPage />
        </ToastProvider>,
      );

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Empty the trash" }));

      expect(
        await screen.findByText("3 books deleted for good."),
      ).toBeInTheDocument();
    });
  });

  it("surfaces a failure to load", async () => {
    api.on("/api/books/trash", {
      status: 500,
      body: { detail: "Something went wrong" },
    });
    renderWithProviders(<TrashPage />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

/** How many entries a page body holds, or -1 for one that is not a page. */
const entries = (body: unknown) =>
  (body as { items?: unknown[] } | undefined)?.items?.length ?? -1;

describe("TrashPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do.
  it("is drawn every shape of answer its main request declares", async () => {
    await witness(answersOf("list_trash"), {
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
            const rendered = await overSchema(<TrashPage />, answers);
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
