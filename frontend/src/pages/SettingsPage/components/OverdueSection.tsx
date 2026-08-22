import { useState } from "react";

import {
  OverdueNotifyReason,
  type OverdueNotifyResult,
  type SettingsOut,
  type SettingsUpdate,
} from "../../../api/generated/model";
import { ErrorState, Icon } from "../../../components";
import { useTranslation, type MessageKey } from "../../../i18n";
import { SettingsSection } from "../../components";
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
};

interface OverdueSectionProps {
  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;

  onSendNow: () => void;
  isSending: boolean;
  sendResult: OverdueNotifyResult | null;
  sendError: unknown;
}

/**
 * Where overdue reminders go, and how often.
 *
 * A generic webhook rather than an integration with one chat service, because
 * a self-hosted app other households run should not carry an integration with
 * something nobody else runs.
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
    <SettingsSection title={t("settings.overdue")} icon="handshake">
      <ToggleField
        label={t("settings.overdueEnable")}
        hint={t("settings.overdueHint")}
        checked={settings.overdue_webhook_enabled ?? false}
        disabled={isSaving}
        onChange={(checked) => onSave({ overdue_webhook_enabled: checked })}
      />

      {/* Stated on the screen that configures it, not only in the docs. A
          household that expects every overdue book to be chased and finds one
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
