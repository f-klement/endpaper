import { useState } from "react";

import {
  OverdueNotifyReason,
  type OverdueNotifyResult,
  OverdueSender,
  type SenderOutcome,
  type SettingsOut,
  type SettingsUpdate,
} from "../../../api/generated/model";
import { CollapsibleSection, ErrorState, Icon } from "../../../components";
import { useTranslation, type MessageKey } from "../../../i18n";
import ToggleField from "./ToggleField";

/**
 * One sentence per way the digest sent nothing.
 *
 * A `Record` over the generated union rather than a chain of conditions, so
 * adding a reason on the server is a compile error here rather than a silent
 * fall through to "nothing was sent", which is precisely how a refused webhook
 * and a quiet week came to read identically.
 */
const REASON_LABELS: Record<OverdueNotifyReason, MessageKey> = {
  [OverdueNotifyReason.disabled]: "settings.overdueNotSentDisabled",
  [OverdueNotifyReason.no_url]: "settings.overdueNotSentNoUrl",
  [OverdueNotifyReason.nothing_due]: "settings.overdueNotSentNothingDue",
  [OverdueNotifyReason.unreachable]: "settings.overdueNotSentUnreachable",
  [OverdueNotifyReason.misconfigured]: "settings.overdueNotSentMisconfigured",
};

/**
 * One name per channel, as a `Record` for the same reason as above: a sender
 * added on the server is a compile error here rather than a blank line.
 */
const SENDER_LABELS: Record<OverdueSender, MessageKey> = {
  [OverdueSender.webhook]: "settings.overdueSenderWebhook",
  [OverdueSender.email]: "settings.overdueSenderEmail",
  [OverdueSender.telegram]: "settings.overdueSenderTelegram",
};

/**
 * The same five reasons again, as a fragment that reads after a channel's name.
 *
 * **A second table rather than reusing `REASON_LABELS`, because those are whole
 * sentences about the run.** Printed in a per-channel row they were wrong twice
 * over: the email row read "Email: The **webhook** could not be reached, so
 * nothing was sent", and the Telegram row read "Telegram: Nothing was sent. The
 * message below says which", where that row *is* the message below.
 *
 * `disabled` and `nothing_due` cannot appear here, because `senders` holds only
 * channels that were switched on and only for a run that had loans to send.
 * They are given a fragment anyway: the `Record` is exhaustive over the union,
 * which is what makes a sixth reason a compile error.
 */
const SENDER_ROW_REASONS: Record<OverdueNotifyReason, MessageKey> = {
  [OverdueNotifyReason.disabled]: "settings.overdueRowDisabled",
  [OverdueNotifyReason.no_url]: "settings.overdueRowNoUrl",
  [OverdueNotifyReason.nothing_due]: "settings.overdueRowNothingDue",
  [OverdueNotifyReason.unreachable]: "settings.overdueRowUnreachable",
  [OverdueNotifyReason.misconfigured]: "settings.overdueRowMisconfigured",
};

interface OverdueSectionProps {
  /** The fold is the page's to decide, so it is passed in rather than held here. */
  isOpen: boolean;
  onToggle: () => void;

  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;

  onSendNow: () => void;
  isSending: boolean;
  sendResult: OverdueNotifyResult | null;
  sendError: unknown;
}

/**
 * The reminder itself: how often it goes out, when it last did, and the webhook.
 *
 * The webhook is here rather than beside the other two channels because it is
 * the one that was here first, and because the interval and the send button
 * belong to the feature rather than to any one channel. Mail and Telegram are
 * in `ReminderSendersSection`, added on the argument that a webhook makes the
 * household build the receiver.
 *
 * The URL is a plain field and the secret is a write-only one. That asymmetry
 * is deliberate: a destination nobody can read back is a destination nobody
 * can proofread, and spotting a wrong one is the whole point of showing it,
 * while the browser has no use at all for the signing secret.
 */
export default function OverdueSection({
  isOpen,
  onToggle,
  settings,
  isSaving,
  onSave,
  onSendNow,
  isSending,
  sendResult,
  sendError,
}: OverdueSectionProps) {
  const { t } = useTranslation();
  // Both are drafts rather than controlled mirrors of `settings`: typing a URL
  // should not save it a character at a time.
  const [url, setUrl] = useState(settings.overdue_webhook_url ?? "");
  const [secret, setSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [days, setDays] = useState(String(settings.overdue_reminder_days ?? 7));

  const urlDirty = url !== (settings.overdue_webhook_url ?? "");
  const daysDirty = days !== String(settings.overdue_reminder_days ?? 7);
  // The server refuses anything outside these bounds with a 422, so the button
  // is withheld rather than offering a save that can only fail. Zero in
  // particular would mean resending the same list on every tick.
  const parsedDays =
    /^\d+$/.test(days.trim()) && Number(days) >= 1 && Number(days) <= 365
      ? Number(days)
      : null;

  return (
    <CollapsibleSection
      variant="card"
      icon="handshake"
      id="overdue"
      title={t("settings.overdue")}
      isOpen={isOpen}
      onToggle={onToggle}
    >
      <ToggleField
        label={t("settings.overdueEnable")}
        hint={t("settings.overdueHint")}
        checked={settings.overdue_webhook_enabled ?? false}
        disabled={isSaving}
        onChange={(checked) => onSave({ overdue_webhook_enabled: checked })}
      />

      {/* Stated on the screen that configures it, not only in the docs. A
          library that expects every overdue book to be chased and finds one
          missing has no other way to learn why. */}
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("settings.overduePrivacyNote")}
      </p>

      <div className="space-y-1.5">
        <label
          htmlFor="overdue-webhook-url"
          className="block text-xs font-medium text-paper-600 dark:text-paper-300"
        >
          {t("settings.overdueUrl")}
        </label>
        <input
          id="overdue-webhook-url"
          type="url"
          autoComplete="off"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder={t("settings.overdueUrlPlaceholder")}
          className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
        />
        {/* Named for its field rather than "Save". Three buttons reading
            "Save" on one screen is one label a screen reader repeats three
            times with nothing to tell them apart. */}
        {urlDirty && (
          <button
            type="button"
            disabled={isSaving}
            onClick={() => onSave({ overdue_webhook_url: url.trim() })}
            className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
          >
            {isSaving ? t("common.saving") : t("settings.overdueUrlSave")}
          </button>
        )}
      </div>

      <div className="space-y-1.5">
        <label
          htmlFor="overdue-webhook-secret"
          className="block text-xs font-medium text-paper-600 dark:text-paper-300"
        >
          {t("settings.overdueSecret")}
        </label>
        <div className="relative">
          <input
            id="overdue-webhook-secret"
            type={showSecret ? "text" : "password"}
            autoComplete="off"
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
            placeholder={t("settings.overdueSecretPlaceholder")}
            className="w-full px-3 py-2 pr-10 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          />
          {/* Named for its field rather than using the shared "Show", which
              the Google Books key already uses on this page. Two reveal
              buttons announced identically leave a screen reader user no way
              to tell which secret they are about to put on screen. */}
          <button
            type="button"
            onClick={() => setShowSecret((shown) => !shown)}
            aria-label={
              showSecret
                ? t("settings.overdueSecretHide")
                : t("settings.overdueSecretShow")
            }
            aria-pressed={showSecret}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-paper-600 hover:text-paper-800 text-sm leading-none dark:text-paper-400 dark:hover:text-paper-300"
          >
            <span aria-hidden="true">
              <Icon name={showSecret ? "eyeOff" : "eye"} className="w-4 h-4" />
            </span>
          </button>
        </div>
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {settings.has_overdue_webhook_secret
            ? t("settings.overdueSecretSet", {
                preview: settings.overdue_webhook_secret_preview ?? "",
              })
            : t("settings.overdueSecretMissing")}
        </p>
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            disabled={isSaving || secret.trim() === ""}
            onClick={() => {
              onSave({ overdue_webhook_secret: secret.trim() });
              setSecret("");
            }}
            className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
          >
            {isSaving ? t("common.saving") : t("settings.overdueSecretSave")}
          </button>
          {settings.has_overdue_webhook_secret && (
            <button
              type="button"
              disabled={isSaving}
              // An empty string clears it; `undefined` would mean "leave
              // alone", which is the opposite.
              onClick={() => onSave({ overdue_webhook_secret: "" })}
              className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium text-danger-600 hover:bg-danger-100 disabled:opacity-40 transition-colors dark:border-paper-700 dark:text-danger-300"
            >
              {t("settings.overdueSecretClear")}
            </button>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        <label
          htmlFor="overdue-reminder-days"
          className="block text-xs font-medium text-paper-600 dark:text-paper-300"
        >
          {t("settings.overdueDays")}
        </label>
        {/* A draft with its own save, not a write per keystroke. Bound
            straight to `settings` it would be a controlled field whose value
            only changes after a round trip, so clearing it to type 14 snapped
            back to the stored number and saved 714. It would also have saved
            the 1 on the way to 14. */}
        <div className="flex gap-2 items-center">
          <input
            id="overdue-reminder-days"
            type="number"
            min={1}
            max={365}
            value={days}
            onChange={(event) => setDays(event.target.value)}
            className="w-24 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          />
          {daysDirty && parsedDays !== null && (
            <button
              type="button"
              disabled={isSaving}
              onClick={() => onSave({ overdue_reminder_days: parsedDays })}
              className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
            >
              {isSaving ? t("common.saving") : t("settings.overdueDaysSave")}
            </button>
          )}
        </div>
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("settings.overdueDaysHint")}
        </p>
      </div>

      <div className="space-y-1.5 pt-1">
        <button
          type="button"
          disabled={isSending}
          onClick={onSendNow}
          className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-40 transition-colors dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
        >
          {isSending
            ? t("settings.overdueSending")
            : t("settings.overdueSendNow")}
        </button>
        {/* The count, not "done". "Nothing is overdue" and "the receiver
            refused it" both look like silence otherwise. */}
        {sendResult && (
          <p
            role="status"
            className="text-xs text-paper-600 dark:text-paper-400"
          >
            {sendResult.sent
              ? t("settings.overdueSent", { count: sendResult.loans ?? 0 })
              : /* `reason` is null exactly when `sent` is true, so the
                   fallback is unreachable in practice. It is here because the
                   type allows the pair and a screen that renders nothing at
                   all is worse than one that is vague. */
                t(
                  sendResult.reason
                    ? REASON_LABELS[sendResult.reason]
                    : "settings.overdueNothingSent",
                )}
            {(sendResult.skipped_private ?? 0) > 0 &&
              ` ${t("settings.overdueSkippedPrivate", {
                count: sendResult.skipped_private ?? 0,
              })}`}
          </p>
        )}
        {/* One line per channel that was tried. `sent` at the top is true when
            any channel delivered, and the loans are stamped on that, so a run
            that reached the chat and not the webhook would otherwise read as a
            clean send with the failure nowhere on the screen. */}
        {sendResult && (sendResult.senders?.length ?? 0) > 0 && (
          <ul className="text-xs text-paper-600 dark:text-paper-400 space-y-0.5">
            {(sendResult.senders ?? []).map((entry: SenderOutcome) => (
              <li key={entry.sender}>
                {entry.sent
                  ? t("settings.overdueSenderSent", {
                      sender: t(SENDER_LABELS[entry.sender]),
                    })
                  : t("settings.overdueSenderFailed", {
                      sender: t(SENDER_LABELS[entry.sender]),
                      detail: t(
                        entry.reason
                          ? SENDER_ROW_REASONS[entry.reason]
                          : "settings.overdueRowNothingSent",
                      ),
                    })}
              </li>
            ))}
          </ul>
        )}
        {sendError != null && (
          <ErrorState
            error={sendError}
            fallback={t("common.somethingWentWrong")}
          />
        )}
      </div>
    </CollapsibleSection>
  );
}
