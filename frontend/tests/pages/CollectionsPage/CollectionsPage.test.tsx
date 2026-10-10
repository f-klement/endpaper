/** Tests for src/pages/CollectionsPage. */

import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fc from "fast-check";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CollectionsPage from "../../../src/pages/CollectionsPage";
import { makeCollection, resetIds } from "../../factories";
import {
  expectRequest,
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

describe("CollectionsPage", () => {
  it("lists the collections with what the reader can see", async () => {
    api.on("/api/collections", {
      body: [makeCollection({ name: "Ebooks", book_count: 12 })],
    });
    renderWithProviders(<CollectionsPage />);

    expect(await screen.findByText("Ebooks")).toBeInTheDocument();
    expect(screen.getByText("12 books")).toBeInTheDocument();
  });

  it("says when there are none", async () => {
    api.on("/api/collections", { body: [] });
    renderWithProviders(<CollectionsPage />);

    expect(await screen.findByText("No collections yet")).toBeInTheDocument();
  });

  it("creates one from the name typed in", async () => {
    api.on("/api/collections", { body: [] });
    api.on("/api/collections", { body: makeCollection() }, "POST");
    renderWithProviders(<CollectionsPage />);
    await screen.findByText("No collections yet");

    await userEvent.type(screen.getByLabelText("Name"), "Sold");
    await userEvent.click(
      screen.getByRole("button", { name: "Add collection" }),
    );

    expect(expectRequest(api, "/api/collections", "POST").body).toEqual({
      name: "Sold",
    });
  });

  it("refuses to send a name of only spaces", async () => {
    api.on("/api/collections", { body: [] });
    renderWithProviders(<CollectionsPage />);
    await screen.findByText("No collections yet");

    await userEvent.type(screen.getByLabelText("Name"), "   ");

    expect(
      screen.getByRole("button", { name: "Add collection" }),
    ).toBeDisabled();
  });

  it("sends nothing for a name of only spaces submitted without the button", async () => {
    // The button refuses it above; the form refuses it as well, for a submit
    // that does not go through the button.
    api.on("/api/collections", { body: [] });
    renderWithProviders(<CollectionsPage />);
    await screen.findByText("No collections yet");
    const box = screen.getByLabelText("Name");
    fireEvent.change(box, { target: { value: "   " } });

    await act(async () => {
      fireEvent.submit(box.closest("form")!);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(api.lastCall("/api/collections", "POST")).toBeUndefined();
  });

  it("surfaces a name that is already taken", async () => {
    api.on("/api/collections", {
      body: [makeCollection({ name: "Ebooks" })],
    });
    api.on(
      "/api/collections",
      {
        status: 409,
        body: { detail: "A collection with that name already exists." },
      },
      "POST",
    );
    renderWithProviders(<CollectionsPage />);
    await screen.findByText("Ebooks");

    await userEvent.type(screen.getByLabelText("Name"), "ebooks");
    await userEvent.click(
      screen.getByRole("button", { name: "Add collection" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A collection with that name already exists.",
    );
  });

  it("renames one", async () => {
    api.on("/api/collections", {
      body: [makeCollection({ id: 7, name: "Ebooks" })],
    });
    api.on(/\/api\/collections\/7$/, { body: makeCollection() }, "PATCH");
    vi.spyOn(window, "prompt").mockReturnValue("Digital");
    renderWithProviders(<CollectionsPage />);
    await screen.findByText("Ebooks");

    await userEvent.click(screen.getByRole("button", { name: "Rename" }));

    expect(expectRequest(api, "/api/collections/7", "PATCH").body).toEqual({
      name: "Digital",
    });
  });

  it("deletes one only after the confirmation names the count", async () => {
    api.on("/api/collections", {
      body: [makeCollection({ id: 7, name: "Ebooks", book_count: 214 })],
    });
    api.on(/\/api\/collections\/7$/, { status: 204 }, "DELETE");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<CollectionsPage />);
    await screen.findByText("Ebooks");

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(confirm.mock.calls[0]?.[0]).toContain("214");
    expect(api.lastCall("/api/collections/7", "DELETE")).toBeDefined();
  });

  it("says when a member is not allowed to delete one", async () => {
    api.on("/api/collections", {
      body: [makeCollection({ id: 7, name: "Ebooks" })],
    });
    api.on(
      /\/api\/collections\/7$/,
      { status: 403, body: { detail: "Admin only" } },
      "DELETE",
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<CollectionsPage />);
    await screen.findByText("Ebooks");

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Admin only");
  });

  it("surfaces a failure to load", async () => {
    api.on("/api/collections", { status: 500, body: { detail: "Nope" } });
    renderWithProviders(<CollectionsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});

/** How many entries a list body holds, or -1 for one that is not a list. */
const entries = (body: unknown) => (Array.isArray(body) ? body.length : -1);

describe("CollectionsPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do.
  it("is drawn every shape of answer its main request declares", async () => {
    await witness(answersOf("list_collections"), {
      "is an empty list": (answer) => entries(answer.body) === 0,
      "is a list with an entry": (answer) => entries(answer.body) > 0,
    });
  });

  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.gen(),
        async (answers) => {
          try {
            const rendered = await overSchema(<CollectionsPage />, answers);
            expect(rendered.problems).toEqual([]);
            return rendered;
          } finally {
            forget();
          }
        },
        {
          "showed a value an answer carried": (_, rendered) =>
            rendered.echoed > 0,
        },
      ),
    ).toBe(PROFILE.runs);
  });
});
