/** Tests for src/pages/DuplicatesPage. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DuplicatesPage from "../../../src/pages/DuplicatesPage";
import { makeBook, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

function group(titles: string[]) {
  return {
    key: "dune|frank herbert",
    books: titles.map((title) => makeBook({ title })),
  };
}

describe("DuplicatesPage", () => {
  it("says so when nothing looks duplicated", async () => {
    api.on("/api/books/duplicates", { body: [] });
    renderWithProviders(<DuplicatesPage />);

    expect(await screen.findByText("No duplicates found")).toBeInTheDocument();
  });

  it("lists each entry in a group", async () => {
    api.on("/api/books/duplicates", {
      body: [group(["Dune", "Dune (paperback)"])],
    });
    renderWithProviders(<DuplicatesPage />);

    expect(await screen.findByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("Dune (paperback)")).toBeInTheDocument();
  });

  it("offers a keep button per entry, because which one survives matters", async () => {
    api.on("/api/books/duplicates", {
      body: [group(["Dune", "Dune (paperback)"])],
    });
    renderWithProviders(<DuplicatesPage />);

    expect(
      await screen.findAllByRole("button", { name: "Keep this one" }),
    ).toHaveLength(2);
  });

  it("merges the group into the chosen entry", async () => {
    const duplicates = group(["Dune", "Dune (paperback)"]);
    api.on("/api/books/duplicates", { body: [duplicates] });
    api.on("/api/books/merge", { body: duplicates.books[0] });
    renderWithProviders(<DuplicatesPage />);

    const [first] = await screen.findAllByRole("button", {
      name: "Keep this one",
    });
    await userEvent.setup().click(first!);

    await waitFor(() =>
      expect(api.lastCall("/api/books/merge", "POST")?.body).toEqual({
        book_ids: duplicates.books.map((b) => b.id),
        keep_id: duplicates.books[0]!.id,
      }),
    );
  });

  it("asks before merging, since it cannot be undone", async () => {
    const duplicates = group(["Dune", "Dune (paperback)"]);
    api.on("/api/books/duplicates", { body: [duplicates] });
    api.on("/api/books/merge", { body: duplicates.books[0] });
    renderWithProviders(<DuplicatesPage />);

    const [first] = await screen.findAllByRole("button", {
      name: "Keep this one",
    });
    await userEvent.setup().click(first!);

    expect(window.confirm).toHaveBeenCalled();
  });

  it("does not merge when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const duplicates = group(["Dune", "Dune (paperback)"]);
    api.on("/api/books/duplicates", { body: [duplicates] });
    renderWithProviders(<DuplicatesPage />);

    const [first] = await screen.findAllByRole("button", {
      name: "Keep this one",
    });
    await userEvent.setup().click(first!);

    expect(api.lastCall("/api/books/merge")).toBeUndefined();
  });

  it("reports a failed merge", async () => {
    const duplicates = group(["Dune", "Dune (paperback)"]);
    api.on("/api/books/duplicates", { body: [duplicates] });
    api.on("/api/books/merge", {
      status: 422,
      body: { detail: "Nothing to merge" },
    });
    renderWithProviders(<DuplicatesPage />);

    const [first] = await screen.findAllByRole("button", {
      name: "Keep this one",
    });
    await userEvent.setup().click(first!);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nothing to merge",
    );
  });

  it("surfaces a failed check", async () => {
    api.on("/api/books/duplicates", { status: 500, body: { detail: "Nope" } });
    renderWithProviders(<DuplicatesPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});
