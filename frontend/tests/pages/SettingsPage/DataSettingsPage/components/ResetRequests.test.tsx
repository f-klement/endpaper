/**
 * Tests for DataSettingsPage/components/ResetRequests.tsx.
 *
 * The admin's half of the reset flow. The first test is the one that matters:
 * this screen has no control that starts a reset, because an admin who could
 * start one would have a takeover button with a friendly name. The absence is
 * structural (there is no endpoint either) and is asserted here because a
 * button is what would be added by somebody who did not know that.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ResetRequests from "../../../../../src/pages/SettingsPage/DataSettingsPage/components/ResetRequests";
import { renderLocalised } from "../../../../utils";

const request = {
  user_id: 7,
  username: "kim",
  requested_at: "2026-09-06T10:00:00",
  expires_at: "2026-09-13T10:00:00",
  approved_at: null,
  approved_by: null,
  code_expires_at: null,
};

function draw(overrides: Record<string, unknown> = {}) {
  return renderLocalised(
    <ResetRequests
      requests={[request]}
      isLoading={false}
      error={null}
      codes={{}}
      onApprove={vi.fn()}
      onDecline={vi.fn()}
      isWorking={false}
      actionError={null}
      {...overrides}
    />,
  );
}

describe("ResetRequests", () => {
  it("offers no way to start a reset", () => {
    draw();

    // Approve and Decline, and nothing that begins one. Named buttons rather
    // than a count, so a third control added for some other purpose does not
    // silently satisfy this.
    const buttons = screen
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? button.textContent);
    expect(buttons).toEqual([
      "Approve a reset for kim",
      "Decline the reset for kim",
    ]);
  });

  it("shows the code once, where the admin can read it out", () => {
    draw({
      codes: {
        7: { code: "ABCD-EFGH-JKLM", expiresAt: "2026-09-06T11:00:00" },
      },
    });

    expect(screen.getByText("ABCD-EFGH-JKLM")).toBeInTheDocument();
    // The row's own sentence, not the section hint above it, which also says
    // "shown once" and would make this pass with no code drawn at all.
    expect(screen.getByText(/read this code to kim/i)).toBeInTheDocument();
  });

  it("says when the code stops working, from what the server sent", () => {
    // The lifetime is `accounts.RESET_CODE_TTL` and belongs to the server. A
    // string saying "an hour" would be a second copy of it that stops being
    // true when the constant moves, so the served expiry is what is drawn.
    draw({
      codes: {
        7: { code: "ABCD-EFGH-JKLM", expiresAt: "2026-09-06T11:00:00" },
      },
    });

    const sentence = screen.getByText(/read this code to kim/i);
    expect(sentence.textContent).toContain(
      new Date("2026-09-06T11:00:00").toLocaleTimeString(),
    );
  });

  it("shows no code before an approval", () => {
    draw();

    expect(screen.queryByText(/read this code to/i)).not.toBeInTheDocument();
  });

  it("still says when the code dies once the code itself is gone", () => {
    // The reload case. The plaintext lives in component state, so after a
    // refresh `codes` is empty and this row's own field is all that is left.
    draw({
      requests: [
        {
          ...request,
          approved_at: "2026-09-06T10:30:00",
          approved_by: "sam",
          code_expires_at: "2026-09-06T11:30:00",
        },
      ],
      codes: {},
    });

    expect(
      screen.getByText(
        `The code stops working at ${new Date("2026-09-06T11:30:00").toLocaleTimeString()}.`,
      ),
    ).toBeInTheDocument();
  });

  it("says who approved a request that has already been granted", () => {
    // The code cannot be shown again, so this is the only thing the queue can
    // say about a request an admin has already dealt with.
    draw({
      requests: [
        { ...request, approved_at: "2026-09-06T11:00:00", approved_by: "sam" },
      ],
    });

    expect(screen.getByText("Approved by sam")).toBeInTheDocument();
  });

  it("says plainly when nobody is waiting", () => {
    draw({ requests: [] });

    expect(screen.getByText("Nobody is waiting.")).toBeInTheDocument();
  });

  it("approves and declines by member id", async () => {
    const onApprove = vi.fn();
    const onDecline = vi.fn();
    draw({ onApprove, onDecline });

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Approve a reset for kim" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Decline the reset for kim" }),
    );

    expect(onApprove).toHaveBeenCalledWith(7);
    expect(onDecline).toHaveBeenCalledWith(7);
  });
});
