/** Tests for src/pages/StatsPage. */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { TagCategory } from "../../../src/api/generated/model";
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
