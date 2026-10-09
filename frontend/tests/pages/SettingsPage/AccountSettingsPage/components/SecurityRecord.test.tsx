/**
 * Tests for AccountSettingsPage/components/SecurityRecord.tsx.
 *
 * The member's half of an admin confirmed reset. A reset that left no mark on
 * the account would be indistinguishable from a quiet takeover, so this says
 * both that one happened and who approved it.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerificationProvenance } from "../../../../../src/api/generated/model";
import SecurityRecord from "../../../../../src/pages/SettingsPage/AccountSettingsPage/components/SecurityRecord";
import { renderLocalised } from "../../../../utils";

function draw(security: Record<string, unknown> | undefined) {
  return renderLocalised(
    <SecurityRecord
      security={security as never}
      isLoading={false}
      error={null}
    />,
  );
}

describe("SecurityRecord", () => {
  it("names the admin who approved a reset", () => {
    draw({
      password_reset_at: "2026-09-06T10:00:00",
      password_reset_approved_by: "sam",
      verified_at: null,
      verification_source: null,
      verified_by: null,
    });

    expect(screen.getByText(/approved by sam/i)).toBeInTheDocument();
  });

  it("says so plainly when nothing has happened", () => {
    // Present whether or not anything happened: a screen that only appeared
    // after a reset is one nobody would have seen before and so nobody would
    // miss.
    draw({
      password_reset_at: null,
      password_reset_approved_by: null,
      verified_at: null,
      verification_source: null,
      verified_by: null,
    });

    expect(
      screen.getByText(/no password reset has been approved/i),
    ).toBeInTheDocument();
  });

  it("still gives the date when the approver's account is gone", () => {
    draw({
      password_reset_at: "2026-09-06T10:00:00",
      password_reset_approved_by: null,
      verified_at: null,
      verification_source: null,
      verified_by: null,
    });

    // The section hint says "approved by an admin" whatever happened, so the
    // absence has to be checked against the sentence that names one.
    expect(screen.getByText(/your password was reset on/i)).toBeInTheDocument();
    expect(screen.queryByText(/, approved by /i)).not.toBeInTheDocument();
  });

  it("says who confirmed the address", () => {
    draw({
      password_reset_at: null,
      password_reset_approved_by: null,
      verified_at: "2026-09-01T10:00:00",
      verification_source: VerificationProvenance.admin,
      verified_by: "sam",
    });

    // "An address", not "your address": the columns record that one was
    // confirmed once, and the four routes that write `users.email` touch none
    // of them, so a member who edited theirs afterwards would otherwise read a
    // claim about the current value.
    expect(
      screen.getByText(/an address on this account was confirmed by sam/i),
    ).toBeInTheDocument();
  });

  it("says a directory signs the account in, rather than that nobody asked", () => {
    // The admin screen has a sentence for this provenance, and two components
    // mapping one closed set with different coverage is how a member gets told
    // nobody asked them for an address their directory supplies.
    draw({
      password_reset_at: null,
      password_reset_approved_by: null,
      verified_at: "2026-09-01T10:00:00",
      verification_source: VerificationProvenance.directory,
      verified_by: null,
    });

    expect(
      screen.getByText(/a directory signs this account in/i),
    ).toBeInTheDocument();
  });
});
