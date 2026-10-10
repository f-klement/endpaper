/** Tests for src/pages/StatsPage. */

import { screen } from "@testing-library/react";
import fc from "fast-check";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Locale, TagCategory, TagKey } from "../../../src/api/generated/model";
import { getToken, setSession } from "../../../src/api/mutator";
import StatsPage from "../../../src/pages/StatsPage";
import { makeStats, makeUser, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";
import { answersOf } from "../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../property";
import { forget, overSchema, type OverSchema } from "../../schemaPage";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
});

describe("StatsPage", () => {
  it("shows a spinner while loading", () => {
    api.on("/api/stats", { body: makeStats() });
    renderWithProviders(<StatsPage />);
    expect(
      screen.getByRole("status", { name: "Loading stats" }),
    ).toBeInTheDocument();
  });

  it("shows the total once loaded", async () => {
    api.on("/api/stats", { body: makeStats({ total: 137 }) });
    renderWithProviders(<StatsPage />);
    expect(await screen.findByText("137")).toBeInTheDocument();
  });

  it("reports a failure instead of a blank page", async () => {
    api.on("/api/stats", {
      status: 401,
      body: { detail: "Not authenticated" },
    });
    renderWithProviders(<StatsPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("lists each member and their count", async () => {
    api.on("/api/stats", {
      body: makeStats({
        total: 5,
        per_user: [
          { username: "kim", count: 3 },
          { username: "sam", count: 2 },
        ],
      }),
    });
    renderWithProviders(<StatsPage />);

    expect(await screen.findByText("kim")).toBeInTheDocument();
    expect(screen.getByText("sam")).toBeInTheDocument();
  });

  it("groups tag rows under their category heading", async () => {
    api.on("/api/stats", {
      body: makeStats({
        total: 2,
        by_tag: [
          { name: "Fiction", category: TagCategory.type, count: 2 },
          { name: "Fantasy", category: TagCategory.genre, count: 1 },
          { name: "Adult", category: TagCategory.age, count: 1 },
        ],
      }),
    });
    renderWithProviders(<StatsPage />);

    expect(await screen.findByText("By Type")).toBeInTheDocument();
    expect(screen.getByText("By Genre")).toBeInTheDocument();
    expect(screen.getByText("By Age")).toBeInTheDocument();
  });

  it("prints a seeded tag in the reader's language", async () => {
    // This page was the last screen naming a tag: it prints the name off its
    // own stat row rather than off a TagOut, so it needed the key carried
    // there too.
    api.on("/api/stats", {
      body: makeStats({
        total: 1,
        by_tag: [
          {
            name: "Computing",
            category: TagCategory.genre,
            key: TagKey.computing,
            count: 1,
          },
        ],
      }),
    });
    renderWithProviders(<StatsPage />, { locale: Locale.de });

    expect(await screen.findByText("Informatik")).toBeInTheDocument();
    expect(screen.queryByText("Computing")).not.toBeInTheDocument();
  });

  it("keeps apart two tags that read the same in German", async () => {
    // The seeded Computing is Informatik on a German page, and a household can
    // name a tag Informatik itself. Keyed by the label, the two rows shared a
    // React key and a refetch could show one row's count on the other.
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    api.on("/api/stats", {
      body: makeStats({
        total: 3,
        by_tag: [
          {
            name: "Computing",
            category: TagCategory.genre,
            key: TagKey.computing,
            count: 2,
          },
          { name: "Informatik", category: TagCategory.genre, count: 1 },
        ],
      }),
    });
    renderWithProviders(<StatsPage />, { locale: Locale.de });

    expect(await screen.findAllByText("Informatik")).toHaveLength(2);
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("same key");
  });

  it("omits a section with no rows", async () => {
    api.on("/api/stats", {
      body: makeStats({
        total: 1,
        by_tag: [{ name: "Fantasy", category: TagCategory.genre, count: 1 }],
      }),
    });
    renderWithProviders(<StatsPage />);

    expect(await screen.findByText("By Genre")).toBeInTheDocument();
    expect(screen.queryByText("By Type")).not.toBeInTheDocument();
    expect(screen.queryByText("Books Added by Member")).not.toBeInTheDocument();
  });

  it("renders an all-zero collection without dividing by zero", async () => {
    // Bars scale against the group maximum; a 0 there would produce NaN widths.
    api.on("/api/stats", {
      body: makeStats({ total: 0, per_user: [{ username: "kim", count: 0 }] }),
    });
    renderWithProviders(<StatsPage />);

    expect(await screen.findByText("kim")).toBeInTheDocument();
  });

  it("renders the months section when there is history", async () => {
    api.on("/api/stats", {
      body: makeStats({
        total: 3,
        by_month: [
          { month: "2026-01", count: 1 },
          { month: "2026-02", count: 2 },
        ],
      }),
    });
    renderWithProviders(<StatsPage />);

    expect(
      await screen.findByText("Books Added Over Time"),
    ).toBeInTheDocument();
  });
});

describe("pages read", () => {
  it("charts the pages read each month", async () => {
    api.on("/api/stats", {
      body: makeStats({
        pages_by_month: [
          { month: "2026-02", count: 210 },
          { month: "2026-03", count: 340 },
        ],
      }),
    });
    renderWithProviders(<StatsPage />);

    // The scope is in the heading itself: a reader who keeps audiobooks has no
    // other way to learn why this total is lower than they expect.
    expect(
      await screen.findByText("Pages Read, by Month (books tracked by page)"),
    ).toBeInTheDocument();
    expect(screen.getByText("340")).toBeInTheDocument();
  });

  it("draws no section when nothing has been recorded", async () => {
    // Page tracked books only, so a library of only audiobooks has
    // an empty series rather than a converted one.
    api.on("/api/stats", { body: makeStats({ total: 1, pages_by_month: [] }) });
    renderWithProviders(<StatsPage />);

    expect(await screen.findByText("1")).toBeInTheDocument();
    expect(screen.queryByText(/Pages Read, by Month/)).not.toBeInTheDocument();
  });
});

describe("the count column", () => {
  it("gives a four digit page total room to sit on one line", async () => {
    // `w-6` is 24px and four digits at text-sm is about 31px, so 900 pages in a
    // month wrapped under its own bar. Every other section counts books, which
    // is why nothing caught it.
    api.on("/api/stats", {
      body: makeStats({ pages_by_month: [{ month: "2026-03", count: 9000 }] }),
    });
    renderWithProviders(<StatsPage />);

    const count = await screen.findByText("9000");
    expect(count.className).toContain("w-12");
    expect(count.className).not.toContain("w-6");
  });

  it("leaves the book-counting sections on the narrow column", async () => {
    api.on("/api/stats", {
      body: makeStats({ total: 3, per_user: [{ username: "kim", count: 3 }] }),
    });
    renderWithProviders(<StatsPage />);

    const count = await screen.findByText("3", { selector: "span" });
    expect(count.className).toContain("w-6");
  });
});

/** The token the property's examples are signed in with. */
const SESSION = "a-session-the-property-signed-in-with";

/** Whether any request was answered 401, which ends a session. */
const endedBy = (rendered: OverSchema) =>
  rendered.answered.some(([, answer]) => answer.status === 401);

/** The length of every list a stats body holds. */
const lists = (body: unknown) =>
  Object.values((body ?? {}) as Record<string, unknown>)
    .filter(Array.isArray)
    .map((list) => list.length);

describe("StatsPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do.
  it("is drawn every shape of answer its main request declares", async () => {
    await witness(answersOf("get_stats"), {
      "holds an empty list": (answer) =>
        lists(answer.body).some((n) => n === 0),
      "holds a list with an entry": (answer) =>
        lists(answer.body).some((n) => n > 0),
    });
  });

  // Signed in, so a drawn 401 has a session to end: the mutator clears it,
  // and every other answer leaves it where it was.
  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.gen(),
        async (answers) => {
          try {
            setSession(SESSION, makeUser());
            const rendered = await overSchema(<StatsPage />, answers);
            expect(rendered.problems).toEqual([]);
            expect(getToken()).toBe(endedBy(rendered) ? null : SESSION);
            return rendered;
          } finally {
            forget();
          }
        },
        {
          "showed a value an answer carried": (_, rendered) =>
            rendered.echoed > 0,
          "was drawn a 401 and ended the session": (_, rendered) =>
            endedBy(rendered),
        },
      ),
    ).toBe(PROFILE.runs);
  });
});
