/** Tests for src/pages/SettingsPage/components/OverdueSection.tsx. */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  OverdueNotifyReason,
  type OverdueNotifyResult,
  OverdueSender,
  type SettingsOut,
} from "../../../../../src/api/generated/model";
import OverdueSection from "../../../../../src/pages/SettingsPage/LendingSettingsPage/components/OverdueSection";
import { renderLocalised } from "../../../../utils";

function makeSettings(overrides: Partial<SettingsOut> = {}): SettingsOut {
  return {
    google_books_enabled: false,
    google_books_api_key_preview: "",
    has_google_books_api_key: false,
    goodreads_lookup_enabled: true,
    default_locale: Locale.en,
    overdue_webhook_enabled: false,
    overdue_webhook_url: "",
    overdue_webhook_secret_preview: "",
    has_overdue_webhook_secret: false,
    overdue_reminder_days: 7,
    ...overrides,
  };
}

function renderSection(
  settings: Partial<SettingsOut> = {},
  extra: { sendResult?: OverdueNotifyResult | null } = {},
) {
  const onSave = vi.fn();
  const onSendNow = vi.fn();
  const rendered = renderLocalised(
    <OverdueSection
      settings={makeSettings(settings)}
      isSaving={false}
      onSave={onSave}
      onSendNow={onSendNow}
      isSending={false}
      sendResult={extra.sendResult ?? null}
      sendError={null}
    />,
  );
  return { ...rendered, onSave, onSendNow };
}

describe("OverdueSection", () => {
  it("says on the page that private books are left out", () => {
    // Stated where it is configured, not only in the docs: a library that
    // expects five entries and gets four has no other way to learn why.
    renderSection();
    expect(
      screen.getByText(/Private books are never included/),
    ).toBeInTheDocument();
  });

  it("switches the webhook on", async () => {
    const user = userEvent.setup();
    const { onSave } = renderSection();

    await user.click(
      screen.getByRole("checkbox", {
        name: "Send the reminder to a webhook",
      }),
    );

    expect(onSave).toHaveBeenCalledWith({ overdue_webhook_enabled: true });
  });

  it("shows the stored webhook address in full", () => {
    // A destination nobody can read back is a destination nobody can
    // proofread, and spotting a wrong one is what the field is for.
    renderSection({ overdue_webhook_url: "https://example.org/hooks/books" });
    expect(screen.getByLabelText("Webhook address")).toHaveValue(
      "https://example.org/hooks/books",
    );
  });

  it("saves the address only when it is asked to", async () => {
    const user = userEvent.setup();
    const { onSave } = renderSection();

    fireEvent.change(screen.getByLabelText("Webhook address"), {
      target: { value: "https://a.test/h" },
    });
    expect(onSave).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Save address" }));
    expect(onSave).toHaveBeenCalledWith({
      overdue_webhook_url: "https://a.test/h",
    });
  });

  it("names its reveal button for its own field", () => {
    // The Google Books key on the same page already uses the shared "Show".
    // Two reveal buttons announced identically leave a screen reader user no
    // way to tell which secret they are about to put on screen.
    renderSection();
    expect(
      screen.getByRole("button", { name: "Show the signing secret" }),
    ).toBeInTheDocument();
  });

  it("shows only a masked preview of the secret", () => {
    renderSection({
      has_overdue_webhook_secret: true,
      overdue_webhook_secret_preview: "••••••••cret",
    });

    expect(screen.getByText(/A secret is stored/)).toBeInTheDocument();
    expect(screen.getByLabelText("Signing secret")).toHaveValue("");
  });

  it("clears the secret with an empty string, not an absent field", async () => {
    // `undefined` would mean "leave alone", which is the opposite.
    const user = userEvent.setup();
    const { onSave } = renderSection({ has_overdue_webhook_secret: true });

    await user.click(
      screen.getByRole("button", { name: "Remove stored secret" }),
    );

    expect(onSave).toHaveBeenCalledWith({ overdue_webhook_secret: "" });
  });

  it("offers no clear button when no secret is stored", () => {
    renderSection();
    expect(
      screen.queryByRole("button", { name: "Remove stored secret" }),
    ).not.toBeInTheDocument();
  });

  it("saves a changed reminder interval only when asked", async () => {
    // A write per keystroke would save the 1 on the way to 14.
    const user = userEvent.setup();
    const { onSave } = renderSection();

    const field = screen.getByLabelText(
      "Days between reminders for the same loan",
    );
    await user.clear(field);
    fireEvent.change(field, { target: { value: "3" } });
    expect(onSave).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Save interval" }));
    expect(onSave).toHaveBeenCalledWith({ overdue_reminder_days: 3 });
  });

  it("offers no save for an interval the server would refuse", async () => {
    // Zero would mean resending the same list on every tick.
    const user = userEvent.setup();
    renderSection();

    const field = screen.getByLabelText(
      "Days between reminders for the same loan",
    );
    await user.clear(field);
    fireEvent.change(field, { target: { value: "0" } });

    expect(
      screen.queryByRole("button", { name: "Save interval" }),
    ).not.toBeInTheDocument();
  });

  it("runs the digest on request", async () => {
    const user = userEvent.setup();
    const { onSendNow } = renderSection();

    await user.click(screen.getByRole("button", { name: "Send now" }));

    expect(onSendNow).toHaveBeenCalled();
  });

  it("reports the count rather than saying done", () => {
    renderSection(
      {},
      { sendResult: { sent: true, loans: 3, skipped_private: 0 } },
    );
    expect(screen.getByRole("status")).toHaveTextContent("3 loans");
  });

  it("says a refused webhook is a refused webhook", () => {
    // The finding this replaced: `sent: false` alone made a broken address and
    // a quiet week the same line, which is what the button exists to tell
    // apart.
    renderSection(
      {},
      {
        sendResult: {
          sent: false,
          loans: 2,
          skipped_private: 0,
          reason: OverdueNotifyReason.unreachable,
        },
      },
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "The webhook could not be reached",
    );
  });

  it.each([
    [OverdueNotifyReason.disabled, "switched off"],
    [OverdueNotifyReason.no_url, "no webhook address is stored"],
    [OverdueNotifyReason.nothing_due, "nothing is overdue"],
    [OverdueNotifyReason.unreachable, "could not be reached"],
  ])("renders its own sentence for %s", (reason, fragment) => {
    renderSection(
      {},
      { sendResult: { sent: false, loans: 0, skipped_private: 0, reason } },
    );
    expect(screen.getByRole("status")).toHaveTextContent(fragment);
  });

  it("gives five distinct sentences, not one repeated", () => {
    // A Record keyed off the generated union is only worth having if the five
    // values it maps to actually differ. It read "four" until `misconfigured`
    // arrived with the mail and Telegram channels.
    const seen = new Set<string>();
    for (const reason of Object.values(OverdueNotifyReason)) {
      const { unmount } = renderSection(
        {},
        { sendResult: { sent: false, loans: 0, skipped_private: 0, reason } },
      );
      seen.add(screen.getByRole("status").textContent ?? "");
      unmount();
    }
    expect(seen.size).toBe(5);
  });

  it("names how many private books were held back", () => {
    renderSection(
      {},
      { sendResult: { sent: true, loans: 2, skipped_private: 1 } },
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "1 private books were left out.",
    );
  });
});

describe("the per channel rows", () => {
  // `sent` at the top is true when **any** channel delivered, and the loans are
  // stamped on that, so a run that reached the chat and not the webhook reads
  // as a clean send unless these rows say otherwise. There was no test here at
  // all on the one render surface this feature adds.
  function withSenders(senders: OverdueNotifyResult["senders"]) {
    return renderSection(
      {},
      {
        sendResult: {
          sent: senders?.some((entry) => entry.sent) ?? false,
          loans: 1,
          skipped_private: 0,
          reason: null,
          senders,
        },
      },
    );
  }

  it("names every channel that was tried", () => {
    withSenders([
      {
        sender: OverdueSender.webhook,
        sent: true,
        loans: 1,
        skipped_private: 0,
      },
      { sender: OverdueSender.email, sent: true, loans: 1, skipped_private: 0 },
      {
        sender: OverdueSender.telegram,
        sent: true,
        loans: 1,
        skipped_private: 0,
      },
    ]);

    expect(screen.getByText("Webhook: sent.")).toBeInTheDocument();
    expect(screen.getByText("Email: sent.")).toBeInTheDocument();
    expect(screen.getByText("Telegram: sent.")).toBeInTheDocument();
  });

  it("shows the one that failed beside the ones that did not", () => {
    withSenders([
      {
        sender: OverdueSender.webhook,
        sent: false,
        loans: 1,
        skipped_private: 0,
        reason: OverdueNotifyReason.unreachable,
      },
      {
        sender: OverdueSender.telegram,
        sent: true,
        loans: 1,
        skipped_private: 0,
      },
    ]);

    expect(screen.getByRole("status")).toHaveTextContent("Sent, covering 1");
    expect(
      screen.getByText(/Webhook: could not be reached/),
    ).toBeInTheDocument();
  });

  it("does not name the webhook in another channel's row", () => {
    // The whole-run sentence reads "The webhook could not be reached", and
    // printing it here made the email row blame the wrong channel.
    withSenders([
      {
        sender: OverdueSender.email,
        sent: false,
        loans: 1,
        skipped_private: 0,
        reason: OverdueNotifyReason.unreachable,
      },
    ]);

    const row = screen.getByText(/^Email:/);
    expect(row).toHaveTextContent("Email: could not be reached.");
    expect(row.textContent).not.toMatch(/webhook/i);
  });

  it("does not point a row at itself", () => {
    // The `misconfigured` sentence ends "The message below says which", and
    // this row is the message below.
    withSenders([
      {
        sender: OverdueSender.telegram,
        sent: false,
        loans: 1,
        skipped_private: 0,
        reason: OverdueNotifyReason.misconfigured,
      },
    ]);

    const row = screen.getByText(/^Telegram:/);
    expect(row).toHaveTextContent("Telegram: its settings cannot be used.");
    expect(row.textContent).not.toMatch(/below/i);
  });

  it("renders no list when nothing was attempted", () => {
    renderSection(
      {},
      {
        sendResult: {
          sent: false,
          loans: 0,
          skipped_private: 0,
          reason: OverdueNotifyReason.nothing_due,
          senders: [],
        },
      },
    );

    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("gives a distinct fragment per reason", () => {
    // A Record over the union is only worth having if its values differ.
    const seen = new Set<string>();
    for (const reason of Object.values(OverdueNotifyReason)) {
      const { unmount } = withSenders([
        {
          sender: OverdueSender.webhook,
          sent: false,
          loans: 1,
          skipped_private: 0,
          reason,
        },
      ]);
      seen.add(screen.getByRole("listitem").textContent ?? "");
      unmount();
    }
    expect(seen.size).toBe(5);
  });
});
