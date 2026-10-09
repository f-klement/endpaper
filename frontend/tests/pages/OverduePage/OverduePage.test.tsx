/** Tests for src/pages/OverduePage. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { OverdueSender } from "../../../src/api/generated/model";
import OverduePage from "../../../src/pages/OverduePage";
import { makeBook, makeLoan, makeLoanPage, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/api/loans/overdue/mine", { body: { enabled: true, count: 0 } });
  // A member by default, because the endpoint is admin only and that is what
  // most readers are. **Every test that is about the panel overrides this**:
  // stubbing the 403 here once left the admin path through the switched-off
  // state with no coverage at all, which is how the panel came to contradict
  // the page three lines below it.
  api.on("/api/settings/sender-health", {
    status: 403,
    body: { detail: "no" },
  });
});

/** Answer the health endpoint as an admin would see it. */
function asAdmin(channels: unknown[] = []) {
  api.on("/api/settings/sender-health", { body: channels });
}

/** One overdue loan, on a book with a title worth asserting on. */
function overdueLoan(title = "Piranesi") {
  return makeLoan({
    is_overdue: true,
    due_at: "2026-01-05T00:00:00",
    book: makeBook({ title }),
  });
}

describe("OverduePage", () => {
  it("shows skeletons while loading", () => {
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([]) });
    renderWithProviders(<OverduePage />);
    expect(screen.getByTestId("overdue-skeletons")).toBeInTheDocument();
  });

  it("lists the books that are late", async () => {
    api.on(/\/api\/loans\/overdue(\?|$)/, {
      body: makeLoanPage([overdueLoan()]),
    });
    renderWithProviders(<OverduePage />);

    expect(await screen.findByText("Piranesi")).toBeInTheDocument();
  });

  it("reads the viewer-narrowed endpoint, not the loans list", async () => {
    // The whole reason the endpoint exists. `/api/loans?overdue_only=true` is
    // rooted at the Shelf and applies no lender-or-borrower arm, so it answers
    // with loans this page's own banner did not count.
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([]) });
    renderWithProviders(<OverduePage />);

    await screen.findByText("Nothing is overdue");
    expect(api.lastCall(/\/api\/loans\/overdue(\?|$)/)).toBeDefined();
    expect(api.calls.some((call) => call.url.includes("overdue_only"))).toBe(
      false,
    );
  });

  it("reports a load failure", async () => {
    api.on(/\/api\/loans\/overdue(\?|$)/, {
      status: 500,
      body: { detail: "Server exploded" },
    });
    renderWithProviders(<OverduePage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Server exploded",
    );
  });

  it("does not report the health record's 403 as a page error", async () => {
    // A member's query fails by design. A red box on a page that loaded
    // correctly would make every member think something was broken.
    api.on(/\/api\/loans\/overdue(\?|$)/, {
      body: makeLoanPage([overdueLoan()]),
    });
    renderWithProviders(<OverduePage />);

    await screen.findByText("Piranesi");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("marks a book returned from here", async () => {
    const loan = overdueLoan();
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([loan]) });
    api.on(`/api/loans/${loan.id}/return`, { body: loan }, "PUT");
    renderWithProviders(<OverduePage />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: /mark returned/i,
      }),
    );

    await waitFor(() =>
      expect(api.lastCall(`/api/loans/${loan.id}/return`, "PUT")).toBeDefined(),
    );
  });
});

describe("the two empty states are not the same news", () => {
  it("reassures when nothing is late", async () => {
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([]) });
    renderWithProviders(<OverduePage />);

    expect(await screen.findByText("Nothing is overdue")).toBeInTheDocument();
  });

  it("says so when the household switched the reminder off", async () => {
    // The server empties the list on the same switch, so without this the page
    // would tell a household that nothing was late when it had simply stopped
    // looking.
    api.on("/api/loans/overdue/mine", { body: { enabled: false, count: 0 } });
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([]) });
    renderWithProviders(<OverduePage />);

    expect(
      await screen.findByText("The in app reminder is switched off"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Nothing is overdue")).not.toBeInTheDocument();
  });
});

describe("the delivery status", () => {
  it("is absent for a member, who may not read the record", async () => {
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([]) });
    renderWithProviders(<OverduePage />);

    await screen.findByText("Nothing is overdue");
    expect(screen.queryByText("Reminder channels")).not.toBeInTheDocument();
  });

  it("draws a channel's standing state for an admin", async () => {
    asAdmin([
      {
        sender: OverdueSender.telegram,
        last_run_at: "2026-08-01T09:00:00",
        sent: true,
        reason: null,
        detail: null,
        failing_since: null,
        failures: 0,
        broken: false,
      },
    ]);
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([]) });
    renderWithProviders(<OverduePage />);

    expect(await screen.findByText("Reminder channels")).toBeInTheDocument();
    expect(screen.getByText("Telegram")).toBeInTheDocument();
    expect(screen.getByText(/Working\./)).toBeInTheDocument();
  });

  it("does not contradict the switched-off state an admin is reading", async () => {
    // Both sentences used to render together: the panel said the reminders
    // appeared here and nowhere else, and the list said the in app reminder
    // was switched off. `notifications.health` never consults that switch, so
    // the panel had no way to know. It now claims nothing about this page.
    asAdmin([]);
    api.on("/api/loans/overdue/mine", { body: { enabled: false, count: 0 } });
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([]) });
    renderWithProviders(<OverduePage />);

    await screen.findByText("The in app reminder is switched off");
    expect(screen.getByText("Reminder channels")).toBeInTheDocument();
    // The pattern's own subject is pinned in `DeliveryStatus.test.tsx`, which
    // asserts it still matches the retired sentence. Without that this line
    // would pass against any page at all.
    expect(screen.queryByText(/appear here/)).not.toBeInTheDocument();
  });

  it("says which rows are on screen when the badge counts more than the list", async () => {
    // The badge prints `total` and the request asks for one page of 50, so
    // above the cap the two disagreed in silence and the rest was unreachable:
    // this page has no pager. The line is not a pager either, it is the page
    // admitting the cap. Library mode (#18) is the audience that makes 50
    // reachable, and the ticket names staff explicitly.
    api.on(/\/api\/loans\/overdue(\?|$)/, {
      body: makeLoanPage([overdueLoan()], { total: 63 }),
    });
    renderWithProviders(<OverduePage />);

    expect(
      await screen.findByText("Showing the 1 most overdue of 63."),
    ).toBeInTheDocument();
  });

  it("says nothing about a cap when the list holds every overdue loan", async () => {
    // The other half, and it is the one that would go quiet: a line rendered
    // unconditionally would satisfy the test above and be wrong on every
    // ordinary page.
    api.on(/\/api\/loans\/overdue(\?|$)/, {
      body: makeLoanPage([overdueLoan()]),
    });
    renderWithProviders(<OverduePage />);

    await screen.findByText("Piranesi");
    expect(screen.queryByText(/most overdue of/)).not.toBeInTheDocument();
  });

  it("tells an admin when the record could not be read", async () => {
    // A 500 rendered exactly like a member's 403 before, and this page keeps
    // that query's error out of its own error slot, so the fault was silent.
    api.on("/api/settings/sender-health", { status: 500, body: {} });
    api.on(/\/api\/loans\/overdue(\?|$)/, { body: makeLoanPage([]) });
    renderWithProviders(<OverduePage />);

    expect(
      await screen.findByText(/channel record could not be read/),
    ).toBeInTheDocument();
  });
});
