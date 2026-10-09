/** Tests for src/pages/StatsPage. */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { Locale, TagCategory, TagKey } from "../../../src/api/generated/model";
import StatsPage, { formatMonth } from "../../../src/pages/StatsPage";
import { makeStats, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
});

describe("formatMonth", () => {
  it("turns a bucket key into a readable label", () => {
    expect(formatMonth("2026-03")).toMatch(/2026/);
  });

  it("returns an empty string for a malformed key", () => {
    expect(formatMonth("")).toBe("");
    expect(formatMonth("2026")).toBe("");
  });
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
