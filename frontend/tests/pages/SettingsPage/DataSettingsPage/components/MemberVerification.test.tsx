/**
 * Tests for DataSettingsPage/components/MemberVerification.tsx.
 *
 * The admin override, and the sentence beside each account saying what state it
 * is in. The rule this screen keeps is that it shows **no address**: it is not
 * one of the four routes that serve one, and what an admin needs here is
 * whether a code could be sent at all.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VerificationProvenance } from "../../../../../src/api/generated/model";
import MemberVerification from "../../../../../src/pages/SettingsPage/DataSettingsPage/components/MemberVerification";
import { renderLocalised } from "../../../../utils";

const waiting = {
  id: 7,
  username: "kim",
  verified_at: null,
  verification_source: null,
  verified_by: null,
  has_address: true,
  applies: true,
};

function draw(members: unknown[], overrides: Record<string, unknown> = {}) {
  return renderLocalised(
    <MemberVerification
      members={members as never}
      isLoading={false}
      error={null}
      onConfirm={vi.fn()}
      isConfirming={false}
      confirmError={null}
      {...overrides}
    />,
  );
}

describe("MemberVerification", () => {
  it("offers the override for an account that is waiting", async () => {
    const onConfirm = vi.fn();
    draw([waiting], { onConfirm });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Confirm the account kim" }));

    expect(onConfirm).toHaveBeenCalledWith(7);
  });

  it("offers nothing for an account a directory authenticated", () => {
    // This app never held that credential, so confirming its address would be
    // an assertion it cannot make. The server answers 409; the screen does not
    // draw the button.
    draw([{ ...waiting, applies: false }]);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/signed in by a directory/i)).toBeInTheDocument();
  });

  it("names the admin who confirmed an account", () => {
    // The whole reason the provenance is stored: an admin marking an account
    // confirmed is an assertion about a person, so the list says who made it.
    draw([
      {
        ...waiting,
        verified_at: "2026-09-06T10:00:00",
        verification_source: VerificationProvenance.admin,
        verified_by: "sam",
      },
    ]);

    expect(screen.getByText("Confirmed by sam")).toBeInTheDocument();
  });

  it("distinguishes a code from an admin's word", () => {
    draw([
      {
        ...waiting,
        verified_at: "2026-09-06T10:00:00",
        verification_source: VerificationProvenance.email,
      },
    ]);

    expect(
      screen.getByText(/confirmed by a code sent to an address/i),
    ).toBeInTheDocument();
  });

  it("says an account has no address to send a code to", () => {
    draw([{ ...waiting, has_address: false }]);

    expect(screen.getByText(/no address/i)).toBeInTheDocument();
  });

  it("shows no address anywhere", () => {
    // The schema carries none, and this asserts the screen does not acquire one
    // by some other route: an address belongs to the account page.
    const { container } = draw([waiting]);

    expect(container.textContent).not.toMatch(/@/);
  });
});
