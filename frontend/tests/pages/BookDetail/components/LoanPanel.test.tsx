/**
 * Tests for src/pages/BookDetail/components/LoanPanel.tsx.
 *
 * Mostly about the one rule this panel enforces: a book marked "never lent"
 * costs an extra deliberate tick, and neither hides that nor forbids it.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LendingWillingness } from "../../../../src/api/generated/model";
import LoanPanel from "../../../../src/pages/BookDetail/components/LoanPanel";
import { makeBook, makeUser, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

function renderPanel(overrides = {}, props = {}) {
  const onLend = vi.fn();
  const onSaveLending = vi.fn();
  const member = makeUser({ id: 9, username: "ana" });
  renderLocalised(
    <LoanPanel
      book={makeBook(overrides)}
      members={[member]}
      isBusy={false}
      isSavingDetails={false}
      onSaveLending={onSaveLending}
      onLend={onLend}
      onMarkReturned={vi.fn()}
      {...props}
    />,
  );
  return { onLend, onSaveLending, member };
}

async function pickBorrower() {
  await userEvent
    .setup()
    .selectOptions(screen.getByLabelText("Loan to"), "9");
}

describe("the lending willingness", () => {
  it("offers the three answers and the unanswered state", () => {
    renderPanel();

    const select = screen.getByLabelText("Lending");

    expect(
      [...select.querySelectorAll("option")].map((option) => option.textContent),
    ).toEqual([
      "Not recorded",
      "Happy to lend",
      "Using it myself right now",
      "Never lent",
    ]);
  });

  it("shows what the book already says", () => {
    renderPanel({ lending: LendingWillingness.happy });
    expect(screen.getByLabelText("Lending")).toHaveValue("happy");
  });

  it("saves a chosen answer", async () => {
    const { onSaveLending } = renderPanel();

    await userEvent
      .setup()
      .selectOptions(screen.getByLabelText("Lending"), "never");

    expect(onSaveLending).toHaveBeenCalledWith({ lending: "never" });
  });

  it("clears with a null, not an empty string", async () => {
    // The API tells absent from null apart, and an empty string is neither.
    const { onSaveLending } = renderPanel({
      lending: LendingWillingness.never,
    });

    await userEvent
      .setup()
      .selectOptions(screen.getByLabelText("Lending"), "");

    expect(onSaveLending).toHaveBeenCalledWith({ lending: null });
  });
});

describe("lending a book marked never lent", () => {
  const neverLent = { lending: LendingWillingness.never };

  it("says so rather than letting the button lie", async () => {
    renderPanel(neverLent);
    expect(
      screen.getByText("This book is marked as never lent."),
    ).toBeInTheDocument();
  });

  it("keeps the lend button disabled until it is acknowledged", async () => {
    renderPanel(neverLent);
    await pickBorrower();

    expect(screen.getByRole("button", { name: "Loan" })).toBeDisabled();
  });

  it("enables it once acknowledged", async () => {
    renderPanel(neverLent);
    await pickBorrower();

    await userEvent
      .setup()
      .click(screen.getByRole("checkbox", { name: "Lend it anyway" }));

    expect(screen.getByRole("button", { name: "Loan" })).toBeEnabled();
  });

  it("sends the acknowledgement with the loan", async () => {
    const { onLend } = renderPanel(neverLent);
    const user = userEvent.setup();
    await pickBorrower();
    await user.click(
      screen.getByRole("checkbox", { name: "Lend it anyway" }),
    );

    await user.click(screen.getByRole("button", { name: "Loan" }));

    expect(onLend).toHaveBeenCalledWith(
      { kind: "member", userId: 9 },
      null,
      true,
    );
  });
});

describe("lending any other book", () => {
  it("asks for no acknowledgement", async () => {
    renderPanel({ lending: LendingWillingness.happy });
    await pickBorrower();

    expect(
      screen.queryByRole("checkbox", { name: "Lend it anyway" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Loan" })).toBeEnabled();
  });

  it("sends false rather than omitting the flag", async () => {
    // "in_use" is a conversation, not a rule, and an unanswered book has no
    // rule at all. Neither is refused by the server.
    const { onLend } = renderPanel({ lending: LendingWillingness.in_use });
    await pickBorrower();

    await userEvent.setup().click(screen.getByRole("button", { name: "Loan" }));

    expect(onLend).toHaveBeenCalledWith(
      { kind: "member", userId: 9 },
      null,
      false,
    );
  });
});
