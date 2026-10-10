/**
 * Tests for src/pages/SettingsPage/LendingSettingsPage/LendingSettingsPage.tsx.
 *
 * What each card does is covered by its own test. What is only visible here is
 * that the two arrive together: the digest decides what is sent and when, the
 * senders decide where it goes, and a household that could reach one without
 * the other could turn the reminder on and never find out that nothing is
 * configured to carry it.
 */

import { screen } from "@testing-library/react";
import fc from "fast-check";
import { beforeEach, describe, expect, it } from "vitest";

import LendingSettingsPage from "../../../../src/pages/SettingsPage/LendingSettingsPage";
import { mockApi, renderWithProviders, type MockApi } from "../../../utils";
import { answersOf } from "../../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../../property";
import { forget, overSchema } from "../../../schemaPage";

let api: MockApi;

function render() {
  return renderWithProviders(<LendingSettingsPage />);
}

const SETTINGS = {
  google_books_enabled: false,
  google_books_api_key_preview: "",
  has_google_books_api_key: false,
  goodreads_lookup_enabled: false,
  default_locale: "en",
};

beforeEach(() => {
  localStorage.clear();
  api = mockApi();
  api.on("/api/settings/features", {
    body: {
      goodreads_lookup_enabled: false,
      default_locale: "en",
    },
  });
  api.on(/\/api\/settings$/, { body: SETTINGS });
});

describe("LendingSettingsPage", () => {
  it("puts the reminder and the senders that carry it on one screen", async () => {
    render();

    expect(
      await screen.findByRole("heading", { name: "Overdue reminders" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Mail and chat reminders" }),
    ).toBeInTheDocument();
  });

  it("says plainly that it is admin only rather than showing an error", async () => {
    api.on(
      /\/api\/settings$/,
      { status: 403, body: { detail: "Admins only" } },
      "GET",
    );
    render();

    expect(
      await screen.findByText("Only an admin can change these."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

/** How many entries an answer holds, or -1 for one that is not a list. */
const entries = (body: unknown) => (Array.isArray(body) ? body.length : -1);

describe("LendingSettingsPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do. Every
  // request this page makes for a signed in account declares a 401 beside its
  // 200, and an admin only one a 403, so both are drawn as well.
  it("is drawn no sender and a sender", async () => {
    await witness(answersOf("get_sender_health"), {
      "is no sender": (answer) => entries(answer.body) === 0,
      "is a sender": (answer) => entries(answer.body) > 0,
    });
  });

  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.gen(),
        async (answers) => {
          try {
            const rendered = await overSchema(<LendingSettingsPage />, answers);
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
