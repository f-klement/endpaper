/** Tests for src/pages/SettingsPage/components/ReminderSendersSection.tsx. */

import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  type SettingsOut,
} from "../../../../../src/api/generated/model";
import ReminderSendersSection from "../../../../../src/pages/SettingsPage/LendingSettingsPage/components/ReminderSendersSection";
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
    overdue_mail_enabled: false,
    overdue_mail_to: "",
    mail_server: "",
    mail_port: "587",
    mail_username: "",
    mail_password_preview: "",
    has_mail_password: false,
    mail_use_tls: true,
    mail_use_ssl: false,
    mail_default_sender: "",
    mail_from_env: [],
    overdue_telegram_enabled: false,
    telegram_bot_token_preview: "",
    has_telegram_bot_token: false,
    telegram_bot_token_from_env: false,
    telegram_chat_id: "",
    telegram_chat_id_from_env: false,
    ...overrides,
  };
}

function renderSection(settings: Partial<SettingsOut> = {}) {
  const onSave = vi.fn();
  const rendered = renderLocalised(
    <ReminderSendersSection
      settings={makeSettings(settings)}
      isSaving={false}
      onSave={onSave}
    />,
  );
  return { ...rendered, onSave };
}

describe("ReminderSendersSection", () => {
  it("says on the page that private books are left out of both channels", () => {
    renderSection();
    expect(screen.getByText(/private books/i)).toBeInTheDocument();
  });

  it("switches mail on by itself", () => {
    const { onSave } = renderSection();
    fireEvent.click(screen.getByLabelText("Send the reminder by email"));
    expect(onSave).toHaveBeenCalledWith({ overdue_mail_enabled: true });
  });

  it("switches Telegram on by itself", () => {
    const { onSave } = renderSection();
    fireEvent.click(
      screen.getByLabelText("Send the reminder to a Telegram chat"),
    );
    expect(onSave).toHaveBeenCalledWith({ overdue_telegram_enabled: true });
  });

  describe("the mail password", () => {
    it("is never rendered in full, only its preview", () => {
      renderSection({
        has_mail_password: true,
        mail_password_preview: "••••••••2345",
      });
      expect(screen.getByText(/••••••••2345/)).toBeInTheDocument();
      expect(screen.getByLabelText("Mail password")).toHaveValue("");
    });

    it("starts as a password field", () => {
      renderSection();
      expect(screen.getByLabelText("Mail password")).toHaveAttribute(
        "type",
        "password",
      );
    });

    it("has a reveal button naming which secret it reveals", () => {
      // Four write only fields on this page. A reveal button announced as
      // "Show" leaves a screen reader user no way to tell which one it is.
      renderSection();
      expect(screen.getByLabelText("Show the mail password")).toBeVisible();
      expect(screen.getByLabelText("Show the bot token")).toBeVisible();
    });

    it("clears with an empty string, which is not the same as leaving it alone", () => {
      const { onSave } = renderSection({ has_mail_password: true });
      fireEvent.click(screen.getByText("Remove stored password"));
      expect(onSave).toHaveBeenCalledWith({ mail_password: "" });
    });

    it("offers no clear button when nothing is stored", () => {
      renderSection();
      expect(screen.queryByText("Remove stored password")).toBeNull();
    });
  });

  describe("encryption", () => {
    it("is one choice, so a configuration the server refuses cannot be clicked", () => {
      // STARTTLS and implicit TLS are two protocols on one socket, and the
      // server refuses both at once. Radio buttons make that unreachable.
      renderSection();
      const options = screen.getAllByRole("radio");
      expect(options).toHaveLength(3);
      expect(
        options.filter((option) => (option as HTMLInputElement).checked),
      ).toHaveLength(1);
    });

    it("sends the pair the server stores, never both true", () => {
      const { onSave } = renderSection();
      fireEvent.click(screen.getByLabelText("TLS"));
      expect(onSave).toHaveBeenCalledWith({
        mail_use_tls: false,
        mail_use_ssl: true,
      });
    });

    it("offers no way to switch certificate checking off", () => {
      // There is no such setting on the server, so a control here would be a
      // lie about what the app can do.
      renderSection();
      expect(screen.queryByText(/certificate/i)).not.toHaveAttribute("type");
      expect(
        screen.getByText(/Certificates and host names are always checked/),
      ).toBeInTheDocument();
    });
  });

  describe("a setting the deployment pinned", () => {
    it("is shown, not editable, and says so", () => {
      renderSection({
        mail_server: "smtp.deployment.test",
        mail_from_env: ["mail_server"],
      });
      expect(screen.getByLabelText("Mail server")).toBeDisabled();
      expect(screen.getByText(/mail_server/)).toBeInTheDocument();
    });

    it("leaves the unpinned fields editable", () => {
      renderSection({ mail_from_env: ["mail_server"] });
      expect(screen.getByLabelText("Mail username")).not.toBeDisabled();
    });

    it("is left out of the patch, so the save cannot 409", () => {
      const { onSave } = renderSection({ mail_from_env: ["mail_server"] });
      fireEvent.change(screen.getByLabelText("Mail username"), {
        target: { value: "library" },
      });
      fireEvent.click(screen.getByText("Save mail settings"));

      expect(onSave).toHaveBeenCalledTimes(1);
      const patch = onSave.mock.calls[0]?.[0] as Record<string, unknown>;
      expect(patch).not.toHaveProperty("mail_server");
      expect(patch).toHaveProperty("mail_username", "library");
    });

    it("hides the save button for a pinned secret", () => {
      renderSection({ mail_from_env: ["mail_password"] });
      expect(screen.queryByText("Save password")).toBeNull();
    });

    it("hides the save button for a pinned bot token", () => {
      renderSection({ telegram_bot_token_from_env: true });
      expect(screen.queryByText("Save token")).toBeNull();
    });
  });

  describe("the chat id", () => {
    it("is shown in full, unlike the token beside it", () => {
      // The same asymmetry the webhook URL has: a destination nobody can read
      // back is a destination nobody can proofread.
      renderSection({ telegram_chat_id: "-1001234567890" });
      expect(screen.getByLabelText("Chat id")).toHaveValue("-1001234567890");
    });

    it("saves only once it has been edited", () => {
      const { onSave } = renderSection();
      expect(screen.queryByText("Save chat id")).toBeNull();

      fireEvent.change(screen.getByLabelText("Chat id"), {
        target: { value: "-100999" },
      });
      fireEvent.click(screen.getByText("Save chat id"));
      expect(onSave).toHaveBeenCalledWith({ telegram_chat_id: "-100999" });
    });
  });

  it("does not offer a Telegram host field", () => {
    // The host is a constant on the server, and that is the one property this
    // channel has that the webhook does not. A field here would give it away.
    renderSection();
    expect(screen.queryByText(/api\.telegram\.org/)).toBeNull();
  });
});
