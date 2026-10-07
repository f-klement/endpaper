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

import { Locale } from "../../../../../src/api/generated/model";
import ResetRequests from "../../../../../src/pages/SettingsPage/DataSettingsPage/components/ResetRequests";
import { renderLocalised } from "../../../../utils";

type OnApprove = NonNullable<
  React.ComponentProps<typeof ResetRequests>["onApprove"]
>;
type OnDecline = NonNullable<
  React.ComponentProps<typeof ResetRequests>["onDecline"]
>;

const request = {
  user_id: 7,
  username: "kim",
  requested_at: "2026-09-06T10:00:00Z",
  expires_at: "2026-09-13T10:00:00Z",
  approved_at: null,
  approved_by: null,
  code_expires_at: null,
};

function draw(
  overrides: Record<string, unknown> = {},
  locale: Locale = Locale.en,
) {
  return renderLocalised(
    <ResetRequests
      requests={[request]}
      isLoading={false}
      error={null}
      codes={{}}
      onApprove={vi.fn<OnApprove>()}
      onDecline={vi.fn<OnDecline>()}
      isWorking={false}
      actionError={null}
      {...overrides}
    />,
    { locale },
  );
}

describe("ResetRequests", () => {
  it("renders its date and its time in the app's locale, not the browser's", () => {
    // **The arm the defect survived, and this file is why it survived so long.**
    // Three timestamps here were rendered with a bare call, one date and two
    // times, and the two assertions that looked at a time built their expected
    // string with the identical bare call, so both sides agreed in every locale.
    // A named locale and a spelling that differs between the two is what makes
    // this an observation: `19.8.2026` against `8/19/2026`, and a 24 hour clock
    // against a 12 hour one.
    const overrides = {
      requests: [
        {
          ...request,
          requested_at: "2026-08-19T14:05:00Z",
          approved_by: "sam",
          code_expires_at: "2026-08-19T15:05:00Z",
        },
      ],
    };

    // Unmounted between the two, because cleanup runs per test rather than per
    // render and two mounted trees would put both spellings in one document.
    // The clock times are the stamps rendered where the suite is, which is
    // west of UTC: 14:05 and 15:05 UTC read as 04:35 and 05:35. The zone is
    // pinned in `tests/setup.ts`. Both dates stay on the 19th, so the locale
    // spellings this arm is about are untouched.
    const german = draw(overrides, Locale.de);
    expect(screen.getByText(/19\.8\.2026/)).toBeInTheDocument();
    expect(screen.getByText(/05:35:00/)).toBeInTheDocument();
    german.unmount();

    draw(overrides, Locale.en);
    expect(screen.getByText(/8\/19\/2026/)).toBeInTheDocument();
    // `\s` rather than a literal space: ICU 72 spells the separator before
    // `AM` as U+202F, and which one a run gets is the runtime's business.
    expect(screen.getByText(/5:35:00\sAM/)).toBeInTheDocument();
  });

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
        7: { code: "ABCD-EFGH-JKLM", expiresAt: "2026-09-06T11:00:00Z" },
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
        7: { code: "ABCD-EFGH-JKLM", expiresAt: "2026-09-06T11:00:00Z" },
      },
    });

    const sentence = screen.getByText(/read this code to kim/i);
    expect(sentence.textContent).toContain(
      // **A named locale, and a path the component does not take.** This built
      // its expectation with a bare `toLocaleTimeString()`, the identical
      // expression the component ran, so both sides resolved in whatever locale
      // the host picked, agreed in every locale, and could observe neither the
      // defect nor its fix. `renderLocalised` defaults to English, so `"en"`
      // here is the app's locale asserted rather than assumed.
      new Date("2026-09-06T11:00:00Z").toLocaleTimeString("en"),
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
          approved_at: "2026-09-06T10:30:00Z",
          approved_by: "sam",
          code_expires_at: "2026-09-06T11:30:00Z",
        },
      ],
      codes: {},
    });

    expect(
      screen.getByText(
        `The code stops working at ${new Date("2026-09-06T11:30:00Z").toLocaleTimeString("en")}.`,
      ),
    ).toBeInTheDocument();
  });

  it("says who approved a request that has already been granted", () => {
    // The code cannot be shown again, so this is the only thing the queue can
    // say about a request an admin has already dealt with.
    draw({
      requests: [
        { ...request, approved_at: "2026-09-06T11:00:00Z", approved_by: "sam" },
      ],
    });

    expect(screen.getByText("Approved by sam")).toBeInTheDocument();
  });

  it("says plainly when nobody is waiting", () => {
    draw({ requests: [] });

    expect(screen.getByText("Nobody is waiting.")).toBeInTheDocument();
  });

  it("approves and declines by member id", async () => {
    const onApprove = vi.fn<(userId: number) => void>();
    const onDecline = vi.fn<(userId: number) => void>();
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
