/** Tests for src/pages/components/SenderHealthLine.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  OverdueNotifyReason,
  OverdueSender,
  type SenderHealth,
} from "../../../src/api/generated/model";
import SenderHealthLine from "../../../src/pages/components/SenderHealthLine";
import { renderLocalised } from "../../utils";

function health(overrides: Partial<SenderHealth> = {}): SenderHealth {
  return { sender: OverdueSender.email, ...overrides };
}

describe("SenderHealthLine", () => {
  it("says nothing for a channel that is switched off", () => {
    // Absent from the record rather than carrying a flag, so there is one way
    // for a channel to be off and nothing here has to interpret it.
    const { container } = renderLocalised(
      <SenderHealthLine health={undefined} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("distinguishes a channel that has never run from one that works", () => {
    // The pair a household most needs to tell apart on the day they configure
    // one. `sent` is null until the first run, which is why it is checked
    // before the failure branch rather than folded into a falsy test.
    renderLocalised(<SenderHealthLine health={health({ sent: null })} />);

    expect(screen.getByText(/not run yet/i)).toBeInTheDocument();
  });

  it("reports a working channel with the date it last ran", () => {
    renderLocalised(
      <SenderHealthLine
        health={health({ sent: true, last_run_at: "2026-08-27T09:00:00Z" })}
      />,
    );

    // The 27th at 09:00 UTC is the 26th where the suite is, which is the
    // rendering a member west of UTC gets and not a typo. The zone is pinned
    // in `tests/setup.ts`.
    expect(
      screen.getByText(/working\. last run on august 26, 2026/i),
    ).toBeInTheDocument();
  });

  it("reports one failure as something that will be tried again", () => {
    // One failed send is a network. Saying "not working" here is what gets the
    // whole feature switched off.
    renderLocalised(
      <SenderHealthLine
        health={health({
          sent: false,
          broken: false,
          reason: OverdueNotifyReason.unreachable,
          failures: 1,
        })}
      />,
    );

    expect(screen.getByText(/it will be tried again/i)).toBeInTheDocument();
    expect(screen.queryByText(/not working since/i)).not.toBeInTheDocument();
  });

  it("reports a standing failure with when it started and when it last tried", () => {
    // The two facts the container log had and nothing in the app did. No count
    // in the sentence: the refusal arm reports broken on the **first** failure,
    // so "1 attempts have failed in a row" was reachable, and this catalogue
    // has no plural forms. When it was last tried is the more useful fact
    // anyway, because it says whether the verdict is fresh.
    renderLocalised(
      <SenderHealthLine
        health={health({
          sent: false,
          broken: true,
          reason: OverdueNotifyReason.misconfigured,
          failing_since: "2026-08-20T09:00:00Z",
          last_run_at: "2026-08-27T09:00:00Z",
          failures: 14,
        })}
      />,
    );

    // Both stamps render a day earlier than they read, for the reason the
    // working channel arm above gives.
    expect(
      screen.getByText(
        /not working since august 19, 2026\. the last attempt was on august 26, 2026/i,
      ),
    ).toBeInTheDocument();
  });

  it("takes the verdict from the server rather than recomputing it", () => {
    // `broken` is a decision made against a failure window and a count that
    // this payload does not carry, so a threshold here would be a second rule
    // reading half the evidence.
    renderLocalised(
      <SenderHealthLine
        health={health({
          sent: false,
          broken: false,
          reason: OverdueNotifyReason.misconfigured,
          failures: 99,
        })}
      />,
    );

    expect(screen.getByText(/it will be tried again/i)).toBeInTheDocument();
  });
});
