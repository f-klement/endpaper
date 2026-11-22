/**
 * Tests for src/pages/SettingsPage/CatalogueSettingsPage/components/RegistrySection.tsx.
 *
 * Each entry is drawn with the evidence it shipped on and named in the reader's
 * language, a pick is sent by the entry's name, and an aged snapshot says so.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it } from "vitest";

import { Locale } from "../../../../../src/api/generated/model";
import RegistrySection from "../../../../../src/pages/SettingsPage/CatalogueSettingsPage/components/RegistrySection";
import { mockApi, renderWithProviders, type MockApi } from "../../../../utils";

let api: MockApi;

function registry(over: Record<string, unknown> = {}) {
  return {
    listed_by: ["https://irspy.indexdata.com/"],
    taken_on: "2026-11-22",
    aged: false,
    entries: [
      {
        source: "csic",
        name: "CSIC Library Network",
        country: "ES",
        kind: "union",
        host: "eu00.alma.exlibrisgroup.com",
        picked: false,
        evidence: {
          probed_on: "2026-11-22",
          isbn: "9786612490477",
          disposition: "answered",
        },
      },
    ],
    ...over,
  };
}

beforeEach(() => {
  api = mockApi();
});

it("draws an entry with the evidence it shipped on", async () => {
  api.on("/api/settings/catalogue-registry", { body: registry() });
  renderWithProviders(<RegistrySection />);

  expect(
    await screen.findByText(
      "ES, eu00.alma.exlibrisgroup.com. Checked on 11/22/2026: Answered: it holds ISBN 9786612490477.",
    ),
  ).toBeInTheDocument();
});

it("sends a pick by the entry's name", async () => {
  api.on("/api/settings/catalogue-registry", { body: registry() });
  api.on("/api/settings/catalogue-registry/csic", { body: registry() }, "PUT");
  renderWithProviders(<RegistrySection />);

  await userEvent.click(
    await screen.findByRole("checkbox", { name: /CSIC Library Network/ }),
  );

  expect(
    api.calls.some(
      (call) =>
        call.method === "PUT" &&
        call.url.endsWith("/api/settings/catalogue-registry/csic"),
    ),
  ).toBe(true);
});

it("names an entry in the reader's language", async () => {
  api.on("/api/settings/catalogue-registry", { body: registry() });
  renderWithProviders(<RegistrySection />, { locale: Locale.de });

  expect(
    await screen.findByRole("checkbox", { name: /Bibliotheksnetz des CSIC/ }),
  ).toBeInTheDocument();
});

it("says when the snapshot has aged", async () => {
  api.on("/api/settings/catalogue-registry", {
    body: registry({ aged: true }),
  });
  renderWithProviders(<RegistrySection />);

  expect(
    await screen.findByText(/checked on 11\/22\/2026 and is due for a recheck/),
  ).toBeInTheDocument();
});
