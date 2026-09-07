/**
 * Tests for LoginPage/components/RecoveryPanel.tsx.
 *
 * The card a member reaches when they cannot sign in. Both halves are on it at
 * once, because they are separated by a telephone call rather than by a click,
 * and the tests below are mostly about that: somebody who already has a code
 * must be able to spend it without first asking for another.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import RecoveryPanel from "../../../../src/pages/LoginPage/components/RecoveryPanel";
import type { UseRecoveryResult } from "../../../../src/pages/LoginPage/hooks";
import { renderLocalised } from "../../../utils";

function state(overrides: Partial<UseRecoveryResult> = {}): UseRecoveryResult {
  return {
    ask: vi.fn(),
    isAsking: false,
    hasAsked: false,
    askError: null,
    redeem: vi.fn(),
    isRedeeming: false,
    hasRedeemed: false,
    redeemError: null,
    ...overrides,
  };
}

describe("RecoveryPanel", () => {
  it("asks an admin for the account that was typed", async () => {
    const ask = vi.fn();
    renderLocalised(<RecoveryPanel state={state({ ask })} onBack={vi.fn()} />);

    const user = userEvent.setup();
    // Two username fields, one per half of the card. Index rather than a name,
    // because both are the same field asked at two moments.
    const [askField] = screen.getAllByLabelText("Username");
    await user.type(askField!, "  kim  ");
    await user.click(screen.getByRole("button", { name: "Ask an admin" }));

    expect(ask).toHaveBeenCalledWith("kim");
  });

  it("says nothing about whether the account exists", () => {
    // The server answers 202 either way, so there is nothing finer to show. A
    // panel that said "no such account" would be the disclosure the route
    // refuses.
    renderLocalised(
      <RecoveryPanel state={state({ hasAsked: true })} onBack={vi.fn()} />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      /if that account exists/i,
    );
  });

  it("spends a code without asking for one first", async () => {
    // The two halves are separated by a telephone call: somebody who comes back
    // with a code must not have to request a second one to reach this form.
    const redeem = vi.fn();
    renderLocalised(
      <RecoveryPanel state={state({ redeem })} onBack={vi.fn()} />,
    );

    const user = userEvent.setup();
    const [, redeemField] = screen.getAllByLabelText("Username");
    await user.type(redeemField!, "kim");
    await user.type(screen.getByLabelText("One time code"), "ABCD-EFGH-JKLM");
    await user.type(screen.getByLabelText("New password"), "brandnew1");
    await user.click(screen.getByRole("button", { name: "Set my password" }));

    expect(redeem).toHaveBeenCalledWith("kim", "ABCD-EFGH-JKLM", "brandnew1");
  });

  it("tells the member to sign in with what they just set", () => {
    // A code is not a session, so the panel's success message is an
    // instruction rather than a redirect.
    renderLocalised(
      <RecoveryPanel state={state({ hasRedeemed: true })} onBack={vi.fn()} />,
    );

    expect(screen.getByText(/sign in with it/i)).toBeInTheDocument();
  });

  it("never offers to remember the code", () => {
    // A suggestion list under this field is the previous member's code offered
    // to the next one on a shared machine.
    renderLocalised(<RecoveryPanel state={state()} onBack={vi.fn()} />);

    expect(screen.getByLabelText("One time code")).toHaveAttribute(
      "autocomplete",
      "off",
    );
  });

  it("goes back to the sign in card", async () => {
    const onBack = vi.fn();
    renderLocalised(<RecoveryPanel state={state()} onBack={onBack} />);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Back to sign in" }));

    expect(onBack).toHaveBeenCalled();
  });
});
