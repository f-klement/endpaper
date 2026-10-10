/**
 * Tests for src/pages/PublicCataloguePage/PublicBookPage.tsx.
 *
 * One published record. The interesting half is the record it cannot draw: the
 * payload carries no member, no loan, no reading status and no price, so this
 * file asserts the shape of what arrives rather than trying to prove a negative
 * about the component. What proves the negative is
 * `backend/tests/schemas/test_public.py`, on the model that decides.
 */

import { screen } from "@testing-library/react";
import fc from "fast-check";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { Locale, type PublicBookOut } from "../../../src/api/generated/model";
import { en, interpolate, type Translate } from "../../../src/i18n";
import { PublicBookPage } from "../../../src/pages/PublicCataloguePage";
import { publicFacts } from "../../../src/pages/PublicCataloguePage/PublicBookPage";
import { answersOf } from "../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../property";
import { forget, overSchema } from "../../schemaPage";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

const RECORD = {
  id: 12,
  title: "Dune",
  subtitle: null,
  author: "Frank Herbert",
  authors: ["Frank Herbert"],
  publisher: "Chilton",
  year: 1965,
  isbn: "9780441013593",
  language: "en",
  page_count: 412,
  format: "paperback",
  series_name: "Dune",
  series_index: 1,
  description: "A desert planet.",
  cover_url: null,
  tags: [],
  categories: [],
  classifications: [
    { scheme: "ddc", number: "813.54", label: "American fiction" },
  ],
};

beforeEach(() => {
  localStorage.clear();
  api = mockApi();
  api.on(/\/api\/public\/books\/12/, { body: RECORD });
});

function render() {
  // Through a `<Routes>`, because the page reads the id with `useParams` and a
  // component rendered outside a matched route sees no params at all.
  return renderWithProviders(
    <Routes>
      <Route path="/catalogue/:id" element={<PublicBookPage />} />
    </Routes>,
    { route: "/catalogue/12" },
  );
}

describe("PublicBookPage", () => {
  it("shows the record", async () => {
    render();
    expect(
      await screen.findByRole("heading", { name: "Dune" }),
    ).toBeInTheDocument();
  });

  it("reads the bibliographic facts as pairs", async () => {
    // A `<dl>`, so a screen reader says "ISBN, 978..." rather than two
    // unrelated strings. Asserted through the term, which only exists in one.
    render();
    expect(await screen.findByText("ISBN")).toBeInTheDocument();
    expect(screen.getByText("9780441013593")).toBeInTheDocument();
  });

  it("shows the classification, which is what library mode is for", async () => {
    render();
    expect(await screen.findByText("813.54")).toBeInTheDocument();
    expect(screen.getByText("American fiction")).toBeInTheDocument();
  });

  it("says a carrier is a carrier rather than a subject", async () => {
    // `#162`. A public record showing `CD-ROM` unmarked asserts that the book
    // is about CD-ROM, which is not what the catalogue said. The heading is
    // already public; the kind is what makes it read correctly.
    api.on(/\/api\/public\/books\/12/, {
      body: {
        ...RECORD,
        classifications: [
          {
            scheme: "gnd",
            number: "4139307-7",
            label: "CD-ROM",
            kind: "carrier",
          },
        ],
      },
    });
    render();

    expect(await screen.findByText("Carrier type")).toBeInTheDocument();
  });

  it("marks nothing on an ordinary subject", async () => {
    // Anti vacuity for the case above.
    render();

    expect(await screen.findByText("813.54")).toBeInTheDocument();
    expect(screen.queryByText("Carrier type")).not.toBeInTheDocument();
    expect(screen.queryByText("Content type")).not.toBeInTheDocument();
  });

  it("answers a book that is not published with the same not found", async () => {
    // The server answers 404 for a book that never existed, one in the trash
    // and one marked private alike, so that a stranger cannot count through
    // ids. A client that told them apart would give back what was withheld.
    api.on(/\/api\/public\/books\/12/, {
      status: 404,
      body: { detail: "Book not found" },
    });
    render();

    expect(await screen.findByText("Book not found.")).toBeInTheDocument();
  });

  it("offers a way back to the catalogue from a missing record", async () => {
    api.on(/\/api\/public\/books\/12/, {
      status: 404,
      body: { detail: "Book not found" },
    });
    render();

    expect(
      await screen.findByRole("link", { name: "Back to the catalogue" }),
    ).toHaveAttribute("href", "/catalogue");
  });
});

/** The English catalogue, as the page's own translator reads it. */
const english: Translate = (key, params) =>
  interpolate(en[key], params ?? {}, Locale.en);

function factsOf(overrides: Partial<PublicBookOut> = {}): [string, string][] {
  return publicFacts({ ...RECORD, ...overrides } as PublicBookOut, english);
}

describe("publicFacts", () => {
  it("lists every fact a full record carries, in the page's order", () => {
    expect(factsOf()).toEqual([
      ["ISBN", "9780441013593"],
      ["Publisher", "Chilton"],
      ["Year", "1965"],
      ["Language", "en"],
      ["Pages", "412"],
      ["Format", "Paperback"],
      ["Series", "Dune 1"],
    ]);
  });

  it("leaves out a fact the record does not carry", () => {
    expect(
      factsOf({
        isbn: null,
        publisher: "",
        year: null,
        language: null,
        page_count: undefined,
        format: null,
        series_name: null,
      }),
    ).toEqual([]);
  });

  it("leaves out a year of zero, which is no year a book can be stored with", () => {
    const facts = factsOf({ year: 0 });

    expect(facts.map(([label]) => label)).not.toContain("Year");
  });

  it("names a series without a number when it has none", () => {
    expect(factsOf({ series_index: null })).toContainEqual(["Series", "Dune"]);
  });
});

/** A record's field, or `undefined` for an answer that is not a record. */
const field = (body: unknown, key: string) =>
  (body as Record<string, unknown> | undefined)?.[key];

describe("PublicBookPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do, and, since
  // this page renders to a visitor with no account, that it asks for nothing
  // the document requires an account for, whatever it is sent.
  it("is drawn an error body, a null fact and a classified record", async () => {
    await witness(answersOf("get_public_book"), {
      "is an error body": (answer) => answer.status === 422,
      "is a record whose year is null": (answer) =>
        answer.status === 200 && field(answer.body, "year") === null,
      "is a record with a classification": (answer) =>
        answer.status === 200 &&
        ((field(answer.body, "classifications") as unknown[] | undefined)
          ?.length ?? 0) > 0,
    });
  });

  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.gen(),
        async (answers) => {
          try {
            const rendered = await overSchema(
              <Routes>
                <Route path="/catalogue/:id" element={<PublicBookPage />} />
              </Routes>,
              answers,
              { route: "/catalogue/12", anonymous: true },
            );
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
