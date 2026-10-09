/**
 * Tests for LoginPage/components/ConfirmPanel.tsx.
 *
 * Returning the code that was sent to an address. One username field for both
 * the confirmation and the resend, because they are the same account.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ConfirmPanel from "../../../../src/pages/LoginPage/components/ConfirmPanel";
import type { UseAddressConfirmationResult } from "../../../../src/pages/LoginPage/hooks";
import { renderLocalised } from "../../../utils";

function state(
  overrides: Partial<UseAddressConfirmationResult> = {},
): UseAddressConfirmationResult {
  return {
    confirm: vi.fn(),
    isConfirming: false,
    hasConfirmed: false,
    confirmError: null,
    resend: vi.fn(),
    isResending: false,
    hasResent: false,
    resendError: null,
    ...overrides,
  };
}

describe("ConfirmPanel", () => {
  it("confirms with the code that was typed", async () => {
    const confirm = vi.fn();
    renderLocalised(
      <ConfirmPanel state={state({ confirm })} onBack={vi.fn()} />,
    );

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Username"), "kim");
    await user.type(screen.getByLabelText("One time code"), "ABCD-EFGH-JKLM");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(confirm).toHaveBeenCalledWith("kim", "ABCD-EFGH-JKLM");
  });

  it("will not resend to nobody", async () => {
    // The resend takes the same username field, so an empty one would send a
    // request naming nothing and spend the budget on it.
    const resend = vi.fn();
    renderLocalised(
      <ConfirmPanel state={state({ resend })} onBack={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", { name: "Send it again" }),
    ).toBeDisabled();
  });

  it("resends for the account that was typed", async () => {
    const resend = vi.fn();
    renderLocalised(
      <ConfirmPanel state={state({ resend })} onBack={vi.fn()} />,
    );

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Username"), "kim");
    await user.click(screen.getByRole("button", { name: "Send it again" }));

    expect(resend).toHaveBeenCalledWith("kim");
  });

  it("says nothing about whether the account was waiting", () => {
    renderLocalised(
      <ConfirmPanel state={state({ hasResent: true })} onBack={vi.fn()} />,
    );

    expect(
      screen.getByText(/if that account is waiting to be confirmed/i),
    ).toBeInTheDocument();
  });

  it("tells the member to sign in once it is confirmed", () => {
    renderLocalised(
      <ConfirmPanel state={state({ hasConfirmed: true })} onBack={vi.fn()} />,
    );

    expect(
      screen.getByText("Your account is confirmed. Sign in."),
    ).toBeInTheDocument();
  });
});
