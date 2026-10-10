import { useState } from "react";

import {
  OverdueNotifyReason,
  type OverdueNotifyResult,
  type SenderHealth,
  type SenderOutcome,
  type SettingsOut,
  type SettingsUpdate,
} from "../../../../api/generated/model";
import { ErrorState } from "../../../../components";
import { useTranslation, type MessageKey } from "../../../../i18n";
import {
  SENDER_LABELS,
  SENDER_ROW_REASONS,
} from "../../../../i18n/senderNames";
import { SenderHealthLine, SettingsSection } from "../../../components";
import SecretField from "../../components/SecretField";
import ToggleField from "../../components/ToggleField";

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
  [OverdueNotifyReason.in_app_only]: "settings.overdueNotSentInAppOnly",
  [OverdueNotifyReason.unexpected]: "settings.overdueNotSentUnexpected",
};

interface OverdueSectionProps {
  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;

  onSendNow: () => void;
  isSending: boolean;
  sendResult: OverdueNotifyResult | null;
  sendError: unknown;
  /** The webhook's standing record, or undefined when it is switched off. */
  health: SenderHealth | undefined;
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
  settings,
  isSaving,
  onSave,
  onSendNow,
  isSending,
  sendResult,
  sendError,
  health,
}: OverdueSectionProps) {
  const { t } = useTranslation();
  // A draft rather than a controlled mirror of `settings`: typing a URL should
  // not save it a character at a time.
  const [url, setUrl] = useState(settings.overdue_webhook_url ?? "");
  const urlDirty = url !== (settings.overdue_webhook_url ?? "");

  return (
    <SettingsSection title={t("settings.overdue")} icon="handshake">
      <ToggleField
        label={t("settings.overdueEnable")}
        hint={t("settings.overdueHint")}
        checked={settings.overdue_webhook_enabled ?? false}
        disabled={isSaving}
        onChange={(checked) => onSave({ overdue_webhook_enabled: checked })}
      />

      {/* Directly under the switch it belongs to. The per run report at the
          bottom of this card says what one run did; this says what has been
          happening, which is the question somebody opening this screen is
          actually asking. */}
      <SenderHealthLine health={health} />

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

      <SecretField
        id="overdue-webhook-secret"
        label={t("settings.overdueSecret")}
        placeholder={t("settings.overdueSecretPlaceholder")}
        showLabel={t("settings.overdueSecretShow")}
        hideLabel={t("settings.overdueSecretHide")}
        status={
          settings.has_overdue_webhook_secret
            ? t("settings.overdueSecretSet", {
                preview: settings.overdue_webhook_secret_preview ?? "",
              })
            : t("settings.overdueSecretMissing")
        }
        saveLabel={t("settings.overdueSecretSave")}
        clearLabel={t("settings.overdueSecretClear")}
        hasStored={settings.has_overdue_webhook_secret === true}
        isSaving={isSaving}
        onSave={(value) => onSave({ overdue_webhook_secret: value })}
        // An empty string clears it; `undefined` would mean "leave alone",
        // which is the opposite.
        onClear={() => onSave({ overdue_webhook_secret: "" })}
      />

      <ReminderDaysField
        stored={settings.overdue_reminder_days}
        isSaving={isSaving}
        onSave={onSave}
      />

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
        {sendResult && <SendReport result={sendResult} />}
        {sendError != null && (
          <ErrorState
            error={sendError}
            fallback={t("common.somethingWentWrong")}
          />
        )}
      </div>
    </SettingsSection>
  );
}

interface ReminderDaysFieldProps {
  stored: number | undefined;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;
}

/** How long to wait before chasing the same loan again. */
function ReminderDaysField({
  stored,
  isSaving,
  onSave,
}: ReminderDaysFieldProps) {
  const { t } = useTranslation();
  const [days, setDays] = useState(String(stored ?? 7));

  const daysDirty = days !== String(stored ?? 7);
  // The server refuses anything outside these bounds with a 422, so the button
  // is withheld rather than offering a save that can only fail. Zero in
  // particular would mean resending the same list on every tick.
  const parsedDays =
    /^\d+$/.test(days.trim()) && Number(days) >= 1 && Number(days) <= 365
      ? Number(days)
      : null;

  return (
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
  );
}

/**
 * What one run did: the whole run in a sentence, then one line per channel.
 *
 * A fragment, so its lines sit in the caller's spacing beside the send button.
 */
function SendReport({ result }: { result: OverdueNotifyResult }) {
  const { t } = useTranslation();

  return (
    <>
      {/* The count, not "done". "Nothing is overdue" and "the receiver
            refused it" both look like silence otherwise. */}
      <p role="status" className="text-xs text-paper-600 dark:text-paper-400">
        {result.sent
          ? t("settings.overdueSent", { count: result.loans ?? 0 })
          : /* `reason` is null exactly when `sent` is true, so the
                   fallback is unreachable in practice. It is here because the
                   type allows the pair and a screen that renders nothing at
                   all is worse than one that is vague. */
            t(
              result.reason
                ? REASON_LABELS[result.reason]
                : "settings.overdueNothingSent",
            )}
        {(result.skipped_private ?? 0) > 0 &&
          ` ${t("settings.overdueSkippedPrivate", {
            count: result.skipped_private ?? 0,
          })}`}
      </p>
      {/* One line per channel that was tried. `sent` at the top is true when
            any channel delivered, and the loans are stamped on that, so a run
            that reached the chat and not the webhook would otherwise read as a
            clean send with the failure nowhere on the screen. */}
      {(result.senders?.length ?? 0) > 0 && (
        <ul className="text-xs text-paper-600 dark:text-paper-400 space-y-0.5">
          {(result.senders ?? []).map((entry: SenderOutcome) => (
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
    </>
  );
}
