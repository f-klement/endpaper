/**
 * Tests for src/pages/SettingsPage/CatalogueSettingsPage/components/SourceTest.tsx.
 *
 * The answer drawn is the disposition the server sends, in words, and the ISBN
 * it asked; the request names no ISBN, so the server picks its default.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it } from "vitest";

import SourceTest from "../../../../../src/pages/SettingsPage/CatalogueSettingsPage/components/SourceTest";
import { mockApi, renderWithProviders, type MockApi } from "../../../../utils";

let api: MockApi;

beforeEach(() => {
  api = mockApi();
});

it("tests the source with no ISBN and says how it answered", async () => {
  api.on(
    "/api/settings/catalogue-sources/dnb/test",
    {
      body: {
        probed_on: "2026-11-22",
        isbn: "9783446249974",
        disposition: "answered_nothing",
      },
    },
    "POST",
  );
  renderWithProviders(<SourceTest source="dnb" name="DNB" />);

  await userEvent.click(screen.getByRole("button", { name: "Test DNB" }));

  expect(await screen.findByRole("status")).toHaveTextContent(
    "Replied, with no record for ISBN 9783446249974.",
  );
  const sent = api.calls.find((call) => call.method === "POST");
  expect(sent?.body).toEqual({});
});
