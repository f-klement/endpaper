/** Tests for src/pages/DuplicatesPage. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fc from "fast-check";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BookFormat, Locale } from "../../../src/api/generated/model";
import type { DuplicateMember } from "../../../src/api/generated/model";
import DuplicatesPage from "../../../src/pages/DuplicatesPage";
import { resetIds } from "../../factories";
import { answersOf } from "../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../property";
import { forget, overSchema } from "../../schemaPage";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;
let nextId: number;

beforeEach(() => {
  resetIds();
  nextId = 1;
  api = mockApi();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

/**
 * One row as the duplicates route sends it.
 *
 * Built here rather than from `makeBook`: the route stopped sending a whole
 * book, and a fixture carrying forty fields the wire no longer has would keep
 * passing whatever the contract said.
 */
function member(overrides: Partial<DuplicateMember> = {}): DuplicateMember {
  return {
    id: nextId++,
    title: "Dune",
    format: null,
    publisher: "Chilton",
    year: 1965,
    isbn: "9780441013593",
    cover_url: null,
    ...overrides,
  };
}

function group(titles: string[], size?: number) {
  const books = titles.map((title) => member({ title }));
  return { key: "dune|frank herbert", size: size ?? books.length, books };
}

/** The most members one merge accepts, which is the cap the server shows at. */
const MEMBER_CAP = 20;

/** The most books one answer carries, across all its groups. */
const BOOK_BUDGET = 200;

/**
 * The fewest groups a truncated answer can hold.
 *
 * A group shows at most `MEMBER_CAP`, so nine of them cannot exhaust the
 * budget: an answer that stopped before this many groups is a response the
 * server cannot produce, and a fixture claiming one is a test of nothing.
 *
 * **Both constants above are copies**, and nothing on this side can read the
 * originals. What holds them is `schemas/test_book.py::
 * TestTheAnswerCapIsBiggerThanOneGroup`, which pins the property this derives
 * rather than the number: if the real constants move so that the floor drops
 * to one, that arm reddens and these copies go stale together with it.
 */
const TRUNCATION_FLOOR = Math.floor(BOOK_BUDGET / MEMBER_CAP);

/**
 * A group the server truncated: the cap's worth of members, claiming `size`.
 *
 * Any other shape is unreachable. Below the cap the two numbers are equal and
 * the schema refuses them apart, so a fixture with two members claiming
 * twenty one tests a response that cannot exist.
 */
/** `howMany` whole pairs, which is the smallest group the server emits. */
function pairs(howMany: number) {
  return Array.from({ length: howMany }, (_unused, index) => ({
    key: `dune-${index}|frank herbert`,
    size: 2,
    books: [member(), member()],
  }));
}

function cappedGroup(size: number) {
  return {
    key: "dune|frank herbert",
    size,
    books: Array.from({ length: MEMBER_CAP }, () => member()),
  };
}

function report(groups: ReturnType<typeof group>[], totalGroups?: number) {
  return { groups, total_groups: totalGroups ?? groups.length };
}

describe("DuplicatesPage", () => {
  it("says so when nothing looks duplicated", async () => {
    api.on("/api/books/duplicates", { body: report([]) });
    renderWithProviders(<DuplicatesPage />);

    expect(await screen.findByText("No duplicates found")).toBeInTheDocument();
  });

  it("lists each entry in a group", async () => {
    api.on("/api/books/duplicates", {
      body: report([group(["Dune", "Dune (paperback)"])]),
    });
    renderWithProviders(<DuplicatesPage />);

    expect(await screen.findByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("Dune (paperback)")).toBeInTheDocument();
  });

  it("offers a keep button per entry, because which one survives matters", async () => {
    api.on("/api/books/duplicates", {
      body: report([group(["Dune", "Dune (paperback)"])]),
    });
    renderWithProviders(<DuplicatesPage />);

    expect(
      await screen.findAllByRole("button", { name: "Keep this one" }),
    ).toHaveLength(2);
  });

  it("merges the group into the chosen entry", async () => {
    const duplicates = group(["Dune", "Dune (paperback)"]);
    api.on("/api/books/duplicates", { body: report([duplicates]) });
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
    api.on("/api/books/duplicates", { body: report([duplicates]) });
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
    api.on("/api/books/duplicates", { body: report([duplicates]) });
    renderWithProviders(<DuplicatesPage />);

    const [first] = await screen.findAllByRole("button", {
      name: "Keep this one",
    });
    await userEvent.setup().click(first!);

    expect(api.lastCall("/api/books/merge")).toBeUndefined();
  });

  it("reports a failed merge", async () => {
    const duplicates = group(["Dune", "Dune (paperback)"]);
    api.on("/api/books/duplicates", { body: report([duplicates]) });
    api.on("/api/books/merge", {
      status: 400,
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

  it("names the format, which is the case the feature exists for", async () => {
    api.on("/api/books/duplicates", {
      body: report([
        {
          key: "dune|frank herbert",
          size: 2,
          books: [
            member({ format: BookFormat.hardcover }),
            member({ format: BookFormat.paperback }),
          ],
        },
      ]),
    });
    renderWithProviders(<DuplicatesPage />);

    expect(await screen.findByText(/Hardcover/)).toBeInTheDocument();
    expect(screen.getByText(/Paperback/)).toBeInTheDocument();
  });

  it("says how many groups are waiting behind the ones shown", async () => {
    // At the floor, not at one: a fixture of one shown of ninety seven pins
    // a response the server cannot produce. See `TRUNCATION_FLOOR`.
    api.on("/api/books/duplicates", {
      body: report(pairs(TRUNCATION_FLOOR), 97),
    });
    renderWithProviders(<DuplicatesPage />);

    expect(
      await screen.findByText(`Showing ${TRUNCATION_FLOOR} of 97 groups.`, {
        exact: false,
      }),
    ).toBeInTheDocument();
  });

  it("says nothing about a total when nothing was withheld", async () => {
    api.on("/api/books/duplicates", { body: report(pairs(TRUNCATION_FLOOR)) });
    renderWithProviders(<DuplicatesPage />);

    await screen.findAllByText("Dune");
    // By role, not by text. Querying a substring of `duplicates.capped`
    // disarmed this: with the gate removed AND that string reworded, the
    // suite went green with the line rendering.
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says how many entries of a group it did not show", async () => {
    // A group of `MERGE_BOOKS_MAX + 1`, which is the smallest over cap group
    // the server can emit and the only one that withholds exactly one entry.
    // The fixture used to be two members claiming a size of 21, a shape the
    // server cannot produce and the schema now refuses, which stepped over
    // this case entirely.
    api.on("/api/books/duplicates", { body: report([cappedGroup(21)]) });
    renderWithProviders(<DuplicatesPage />);

    expect(
      await screen.findByText(/More entries in this group.*\(1\)/),
    ).toBeInTheDocument();
  });

  it("reads for several as well as for one", async () => {
    api.on("/api/books/duplicates", { body: report([cappedGroup(27)]) });
    renderWithProviders(<DuplicatesPage />);

    expect(
      await screen.findByText(/More entries in this group.*\(7\)/),
    ).toBeInTheDocument();
  });

  it("reads for one in German too", async () => {
    // The plural rule is a property of the catalogue, not of English, and
    // both arms above render in English. The catalogue tests check parity
    // and the register, not wording, so the exact "1 more entries" defect
    // planted in `de.ts` left the suite green.
    api.on("/api/books/duplicates", { body: report([cappedGroup(21)]) });
    renderWithProviders(<DuplicatesPage />, { locale: Locale.de });

    const line = await screen.findByText(/Weitere Einträge in dieser Gruppe/);

    expect(line).toHaveTextContent("(1)");
    expect(line).not.toHaveTextContent(/^1 /);
  });

  it("merges only the entries it showed", async () => {
    const duplicates = cappedGroup(21);
    api.on("/api/books/duplicates", { body: report([duplicates]) });
    api.on("/api/books/merge", { body: duplicates.books[0] });
    renderWithProviders(<DuplicatesPage />);

    const [first] = await screen.findAllByRole("button", {
      name: "Keep this one",
    });
    await userEvent.setup().click(first!);

    await waitFor(() => {
      const sent = api.lastCall("/api/books/merge", "POST")?.body as {
        book_ids: number[];
      };
      expect(sent.book_ids).toEqual(duplicates.books.map((b) => b.id));
      expect(sent.book_ids).toHaveLength(MEMBER_CAP);
    });
  });

  it("surfaces a failed check", async () => {
    api.on("/api/books/duplicates", { status: 500, body: { detail: "Nope" } });
    renderWithProviders(<DuplicatesPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});

/** A report's groups, or `undefined` for an answer that is not a report. */
const groupsOf = (body: unknown) =>
  (body as { groups?: unknown[] } | undefined)?.groups;

describe("DuplicatesPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do. The
  // report declares a 401 beside its 200, so that is drawn as well.
  it("is drawn an empty report, a group, and a report the server capped", async () => {
    await witness(answersOf("list_duplicates"), {
      "is an empty report": (answer) => groupsOf(answer.body)?.length === 0,
      "holds a group": (answer) => (groupsOf(answer.body)?.length ?? 0) > 0,
      "counts more groups than it holds": (answer) =>
        (answer.body as { total_groups: number }).total_groups >
        (groupsOf(answer.body)?.length ?? 0),
    });
  });

  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.gen(),
        async (answers) => {
          try {
            const rendered = await overSchema(<DuplicatesPage />, answers);
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
