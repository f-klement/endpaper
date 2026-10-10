/** Tests for src/pages/SeriesPage. */

import { screen } from "@testing-library/react";
import fc from "fast-check";
import { beforeEach, describe, expect, it } from "vitest";

import SeriesPage from "../../../src/pages/SeriesPage";
import { resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";
import { answersOf } from "../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../property";
import { forget, overSchema } from "../../schemaPage";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
});

describe("SeriesPage", () => {
  it("lists the series", async () => {
    api.on("/api/books/series", {
      body: [{ name: "Dune", book_count: 3, missing_indexes: [2] }],
    });
    renderWithProviders(<SeriesPage />);

    expect(await screen.findByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("Missing: 2")).toBeInTheDocument();
  });

  it("says when there are none", async () => {
    api.on("/api/books/series", { body: [] });
    renderWithProviders(<SeriesPage />);

    expect(await screen.findByText("No series yet")).toBeInTheDocument();
  });

  it("surfaces a failure", async () => {
    api.on("/api/books/series", { status: 500, body: { detail: "Nope" } });
    renderWithProviders(<SeriesPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});

/** How many entries a list body holds, or -1 for one that is not a list. */
const entries = (body: unknown) => (Array.isArray(body) ? body.length : -1);

describe("SeriesPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do.
  it("is drawn every shape of answer its main request declares", async () => {
    await witness(answersOf("list_series"), {
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
            const rendered = await overSchema(<SeriesPage />, answers);
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
