/**
 * Tests for src/pages/TrashPage.
 *
 * The page exists so a delete can be taken back, so the tests are about the
 * two verbs and the asymmetry between them: putting a book back is one tap,
 * and destroying it asks first, because that one really is final.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TrashPage from "../../../src/pages/TrashPage";
import { makeBook, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/api/settings/features", {
    body: {
      google_books_enabled: false,
      google_books_ready: false,
      goodreads_lookup_enabled: false,
      default_locale: "en",
    },
  });
});

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
        deleted_at: "2026-08-19T10:00:00",
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
      makeBook({ id: 7, title: "Dune", deleted_at: "2026-08-19T10:00:00" }),
    ]);
    renderWithProviders(<TrashPage />);

    expect(await screen.findByText(/^Deleted \d/)).toBeInTheDocument();
  });

  it("says the trash does not empty itself", async () => {
    stubTrash([makeBook({ id: 7, deleted_at: "2026-08-19T10:00:00" })]);
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
          deleted_at: "2026-08-19T10:00:00",
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

  describe("deleting for good", () => {
    it("asks first, because this one cannot be undone", async () => {
      stubTrash([
        makeBook({
          id: 7,
          title: "Deleted Book",
          deleted_at: "2026-08-19T10:00:00",
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
          deleted_at: "2026-08-19T10:00:00",
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
      stubTrash([makeBook({ id: 7, deleted_at: "2026-08-19T10:00:00" })]);
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
      renderWithProviders(<TrashPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "Empty the trash" }));

      expect(confirmSpy).toHaveBeenCalled();
      expect(api.lastCall("/api/books/trash", "DELETE")).toBeUndefined();
    });

    it("empties it once confirmed", async () => {
      stubTrash([makeBook({ id: 7, deleted_at: "2026-08-19T10:00:00" })]);
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
