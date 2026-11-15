/**
 * Tests for AccountSettingsPage/components/ReadwiseAccount.tsx.
 *
 * The card is presentational, so it is drawn here from a state object built by
 * hand rather than through the hook: each state the card can be in is one
 * literal, and the verbs are spies. The page test drives the real hook.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  ReadwiseOutcome,
  type ReadwiseAccountOut,
} from "../../../../../src/api/generated/model";
import ReadwiseAccount from "../../../../../src/pages/SettingsPage/AccountSettingsPage/components/ReadwiseAccount";
import type { UseReadwiseAccountResult } from "../../../../../src/pages/SettingsPage/AccountSettingsPage/hooks";
import { renderLocalised } from "../../../../utils";

const UNLINKED: ReadwiseAccountOut = {
  has_token: false,
  token_set_at: null,
  last_run_at: null,
  last_outcome: null,
  waiting_count: 0,
  waiting: [],
};

const LINKED: ReadwiseAccountOut = {
  ...UNLINKED,
  has_token: true,
  token_set_at: "2026-11-01T10:00:00Z",
};

function stateOf(
  overrides: Partial<UseReadwiseAccountResult> = {},
): UseReadwiseAccountResult {
  return {
    account: UNLINKED,
    isLoading: false,
    error: null,
    save: vi.fn<UseReadwiseAccountResult["save"]>(),
    remove: vi.fn<() => void>(),
    sync: vi.fn<() => void>(),
    synced: undefined,
    isSaving: false,
    isSyncing: false,
    saveError: null,
    syncError: null,
    ...overrides,
  };
}

function draw(state: UseReadwiseAccountResult, locale: Locale = Locale.en) {
  return renderLocalised(<ReadwiseAccount state={state} />, { locale });
}

const field = () => screen.getByLabelText("Readwise access token");
const button = (name: string) => screen.getByRole("button", { name });

describe("ReadwiseAccount", () => {
  it("shows a spinner while the account loads", () => {
    draw(stateOf({ isLoading: true, account: undefined }));

    expect(screen.getByRole("status", { name: "Loading..." })).toBeVisible();
    expect(screen.queryByLabelText("Readwise access token")).toBeNull();
  });

  it("shows the load failure instead of the form", () => {
    draw(stateOf({ error: "boom", account: undefined }));

    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    expect(screen.queryByLabelText("Readwise access token")).toBeNull();
  });

  it("falls back to its own words for a failure that carries none", () => {
    draw(stateOf({ error: {}, account: undefined }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not load the settings.",
    );
  });

  it("draws nothing before an account has arrived", () => {
    const { container } = draw(stateOf({ account: undefined }));

    expect(container).toBeEmptyDOMElement();
  });

  it("offers only saving to a member with no token", () => {
    draw(stateOf());

    expect(screen.getByRole("status")).toHaveTextContent(
      "No Readwise token is saved.",
    );
    expect(button("Save token")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Fetch now" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove token" })).toBeNull();
  });

  it("keeps saving refused while the field holds only spaces", async () => {
    draw(stateOf());

    await userEvent.type(field(), "   ");

    expect(button("Save token")).toBeDisabled();
  });

  it("saves the trimmed token and empties the field once it is taken", async () => {
    const save = vi.fn<UseReadwiseAccountResult["save"]>((_token, onSaved) =>
      onSaved(),
    );
    draw(stateOf({ save }));

    await userEvent.type(field(), "  secret  ");
    await userEvent.click(button("Save token"));

    expect(save).toHaveBeenCalledWith("secret", expect.any(Function));
    expect(field()).toHaveValue("");
  });

  it("keeps a typed token through the spinner and the load failure", async () => {
    const { rerender } = draw(stateOf());

    await userEvent.type(field(), "secret");
    rerender(<ReadwiseAccount state={stateOf({ isLoading: true })} />);
    rerender(<ReadwiseAccount state={stateOf({ error: "boom" })} />);
    rerender(<ReadwiseAccount state={stateOf()} />);

    expect(field()).toHaveValue("secret");
  });

  it("keeps the field when the save was not taken", async () => {
    draw(stateOf());

    await userEvent.type(field(), "secret");
    await userEvent.click(button("Save token"));

    expect(field()).toHaveValue("secret");
  });

  it("offers replacing, fetching and removing once a token is saved", async () => {
    const state = stateOf({ account: LINKED });
    draw(state);

    expect(screen.getByRole("status")).toHaveTextContent(
      "A token is saved. Highlights are fetched once a day, or now with the button.",
    );
    expect(button("Replace token")).toBeVisible();

    await userEvent.click(button("Fetch now"));
    await userEvent.click(button("Remove token"));

    expect(state.sync).toHaveBeenCalledOnce();
    expect(state.remove).toHaveBeenCalledOnce();
  });

  it.each([
    ["a date", { last_run_at: "2026-11-02T10:00:00Z" }],
    ["an outcome", { last_outcome: ReadwiseOutcome.synced }],
  ])("says a run has not happened when only %s is known", (_known, half) => {
    draw(stateOf({ account: { ...LINKED, ...half } }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "A token is saved. Highlights are fetched once a day, or now with the button.",
    );
  });

  it.each([
    [ReadwiseOutcome.synced, "everything arrived."],
    [
      ReadwiseOutcome.incomplete,
      "only part arrived. The rest comes with the next fetch.",
    ],
    [
      ReadwiseOutcome.token_refused,
      "Readwise refused the token. Save a new one.",
    ],
    [
      ReadwiseOutcome.rate_limited,
      "Readwise asked to wait. The next fetch tries again.",
    ],
    [ReadwiseOutcome.unavailable, "Readwise could not be reached."],
    [
      ReadwiseOutcome.unreadable,
      "the saved token can no longer be read here. Save it again.",
    ],
  ])("names the last run's outcome %s in words", (outcome, words) => {
    draw(
      stateOf({
        account: {
          ...LINKED,
          last_run_at: "2026-08-19T10:00:00Z",
          last_outcome: outcome,
        },
      }),
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      `Last fetched on 8/19/2026: ${words}`,
    );
  });

  it("dates the last run in the app's locale", () => {
    draw(
      stateOf({
        account: {
          ...LINKED,
          last_run_at: "2026-08-19T10:00:00Z",
          last_outcome: ReadwiseOutcome.synced,
        },
      }),
      Locale.de,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/19\.8\.2026/);
  });

  it("holds every button while a save is in flight", async () => {
    draw(stateOf({ account: LINKED, isSaving: true }));

    await userEvent.type(field(), "secret");

    expect(button("Replace token")).toBeDisabled();
    expect(button("Replace token")).toHaveAttribute("aria-busy", "true");
    expect(button("Fetch now")).toBeDisabled();
    expect(button("Remove token")).toBeDisabled();
  });

  it("holds fetching and removing while a fetch is in flight", async () => {
    draw(stateOf({ account: LINKED, isSyncing: true }));

    await userEvent.type(field(), "secret");

    expect(button("Replace token")).toBeEnabled();
    expect(button("Fetch now")).toBeDisabled();
    expect(button("Remove token")).toBeDisabled();
  });

  it("counts what the last fetch from this page did", () => {
    draw(
      stateOf({
        account: LINKED,
        synced: {
          created: 3,
          updated: 2,
          deleted: 1,
          skipped: 0,
          unchanged: 0,
          outcome: ReadwiseOutcome.synced,
          waiting_count: 0,
        },
      }),
    );

    expect(screen.getByText("New: 3. Changed: 2. Removed: 1.")).toBeVisible();
  });

  it("lists the waiting books, with an author where Readwise has one", () => {
    draw(
      stateOf({
        account: {
          ...LINKED,
          waiting_count: 2,
          waiting: [
            { title: "Dune", author: "Frank Herbert" },
            { title: "Anonymous Notes", author: null },
          ],
        },
      }),
    );

    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["Dune, Frank Herbert", "Anonymous Notes"]);
    expect(
      screen.getByText(/Books in Readwise that match no single book here: 2\./),
    ).toBeVisible();
  });

  it("lists nothing when no book is waiting", () => {
    draw(stateOf({ account: LINKED }));

    expect(screen.queryByRole("list")).toBeNull();
  });

  it("shows a save failure and a fetch failure each in its own words", () => {
    draw(stateOf({ account: LINKED, saveError: {}, syncError: {} }));

    const alerts = screen.getAllByRole("alert").map((a) => a.textContent);
    expect(alerts).toEqual([
      "The token could not be saved.",
      "The highlights could not be fetched.",
    ]);
  });
});
