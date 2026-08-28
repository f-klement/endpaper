import { useState } from "react";

import type {
  SettingsOut,
  SettingsUpdate,
} from "../../../../api/generated/model";
import { Icon } from "../../../../components";
import { useTranslation, type Translate } from "../../../../i18n";
import { SettingsSection } from "../../../components";
import ToggleField from "../../components/ToggleField";

/**
 * The two reminder channels a household already has: a mailbox and a group chat.
 *
 * The webhook stays in `OverdueSection` beside the interval and the send button,
 * because it is the channel that was here first and its form is the one an
 * existing install already knows. These two are the ones added on the argument
 * that a webhook makes the household build the receiver: **SMTP is universal**
 * and **Telegram is one fixed host**.
 *
 * **Encryption is three radio buttons, not two switches, and that is the point
 * of the shape.** STARTTLS and implicit TLS are two protocols on one socket, and
 * the server refuses a configuration naming both. A pair of checkboxes makes
 * that refusal reachable by clicking; a single choice makes it unreachable.
 * There is deliberately no "do not check certificates" option: nothing in the
 * app can switch verification off, so offering the control would be a lie.
 *
 * The secrets are write only boxes, like the Google key and the webhook secret
 * above them. The browser never received the stored value, so an empty box has
 * to mean "leave it alone".
 */

/** What the two transport flags mean together, as one choice. */
type Encryption = "starttls" | "tls" | "none";

function encryptionOf(settings: SettingsOut): Encryption {
  if (settings.mail_use_ssl) return "tls";
  if (settings.mail_use_tls) return "starttls";
  return "none";
}

/** The pair the server stores. `tls` and `starttls` are never both true. */
function flagsFor(
  choice: Encryption,
): Pick<SettingsUpdate, "mail_use_tls" | "mail_use_ssl"> {
  return {
    mail_use_tls: choice === "starttls",
    mail_use_ssl: choice === "tls",
  };
}

const ENCRYPTION_LABELS = {
  starttls: "settings.mailSecurityStartTls",
  tls: "settings.mailSecurityTls",
  none: "settings.mailSecurityNone",
} as const;

const FIELD_CLASS =
  "w-full px-3 py-2 rounded-xl border border-paper-200 text-sm " +
  "disabled:opacity-50 dark:border-paper-700";

const SAVE_CLASS =
  "px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium " +
  "hover:bg-accent-fill-hover disabled:opacity-40 transition-colors";

const CLEAR_CLASS =
  "px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium " +
  "text-danger-600 hover:bg-danger-100 disabled:opacity-40 transition-colors " +
  "dark:border-paper-700 dark:text-danger-300";

const HINT_CLASS = "text-xs text-paper-600 dark:text-paper-400";

const LABEL_CLASS =
  "block text-xs font-medium text-paper-600 dark:text-paper-300";

interface SecretBoxProps {
  id: string;
  label: string;
  placeholder: string;
  showLabel: string;
  hideLabel: string;
  status: string;
  saveLabel: string;
  clearLabel: string;
  hasStored: boolean;
  pinned: boolean;
  isSaving: boolean;
  onSave: (value: string) => void;
  onClear: () => void;
}

/**
 * A write only credential field.
 *
 * Its own component because the page now holds four of them, and the reveal
 * button is the part that goes wrong: each one needs a label naming **which**
 * secret it reveals, or a screen reader user hears "Show" four times with
 * nothing to tell them apart.
 */
function SecretBox({
  id,
  label,
  placeholder,
  showLabel,
  hideLabel,
  status,
  saveLabel,
  clearLabel,
  hasStored,
  pinned,
  isSaving,
  onSave,
  onClear,
}: SecretBoxProps) {
  const [value, setValue] = useState("");
  const [shown, setShown] = useState(false);

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className={LABEL_CLASS}>
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={shown ? "text" : "password"}
          autoComplete="off"
          disabled={pinned}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={placeholder}
          className={`${FIELD_CLASS} pr-10`}
        />
        <button
          type="button"
          onClick={() => setShown((was) => !was)}
          aria-label={shown ? hideLabel : showLabel}
          aria-pressed={shown}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-paper-600 hover:text-paper-800 text-sm leading-none dark:text-paper-400 dark:hover:text-paper-300"
        >
          <span aria-hidden="true">
            <Icon name={shown ? "eyeOff" : "eye"} className="w-4 h-4" />
          </span>
        </button>
      </div>
      <p className={HINT_CLASS}>{status}</p>
      {!pinned && (
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            disabled={isSaving || value.trim() === ""}
            onClick={() => {
              onSave(value.trim());
              setValue("");
            }}
            className={SAVE_CLASS}
          >
            {saveLabel}
          </button>
          {hasStored && (
            <button
              type="button"
              disabled={isSaving}
              onClick={onClear}
              className={CLEAR_CLASS}
            >
              {clearLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

interface ReminderSendersSectionProps {
  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;
}

export default function ReminderSendersSection({
  settings,
  isSaving,
  onSave,
}: ReminderSendersSectionProps) {
  const { t } = useTranslation();

  // Drafts rather than controlled mirrors of `settings`: typing a host should
  // not save it a character at a time, and a controlled field whose value only
  // changes after a round trip snaps back mid edit.
  const [server, setServer] = useState(settings.mail_server ?? "");
  const [port, setPort] = useState(settings.mail_port ?? "");
  const [username, setUsername] = useState(settings.mail_username ?? "");
  const [from, setFrom] = useState(settings.mail_default_sender ?? "");
  const [to, setTo] = useState(settings.overdue_mail_to ?? "");
  const [chat, setChat] = useState(settings.telegram_chat_id ?? "");

  const pinned = new Set(settings.mail_from_env ?? []);
  const tokenPinned = settings.telegram_bot_token_from_env === true;
  const chatPinned = settings.telegram_chat_id_from_env === true;

  const mailDirty =
    server !== (settings.mail_server ?? "") ||
    port !== (settings.mail_port ?? "") ||
    username !== (settings.mail_username ?? "") ||
    from !== (settings.mail_default_sender ?? "") ||
    to !== (settings.overdue_mail_to ?? "");

  // Only the fields this deployment does not pin. Sending a pinned one back
  // would be a 409 the admin cannot act on from here.
  function saveMail() {
    const patch: SettingsUpdate = { overdue_mail_to: to.trim() };
    if (!pinned.has("mail_server")) patch.mail_server = server.trim();
    if (!pinned.has("mail_port")) patch.mail_port = port.trim();
    if (!pinned.has("mail_username")) patch.mail_username = username.trim();
    if (!pinned.has("mail_default_sender"))
      patch.mail_default_sender = from.trim();
    onSave(patch);
  }

  return (
    <SettingsSection title={t("settings.senders")} icon="inbox">
      <p className={`${HINT_CLASS} leading-relaxed`}>
        {t("settings.sendersHint")}
      </p>
      {/* Stated on the screen that configures it, not only in the docs. A
          household that expects every overdue book to be chased and finds one
          missing has no other way to learn why. */}
      <p className={`${HINT_CLASS} leading-relaxed`}>
        {t("settings.sendersPrivacyNote")}
      </p>

      <MailBlock
        settings={settings}
        isSaving={isSaving}
        onSave={onSave}
        pinned={pinned}
        t={t}
        server={server}
        setServer={setServer}
        port={port}
        setPort={setPort}
        username={username}
        setUsername={setUsername}
        from={from}
        setFrom={setFrom}
        to={to}
        setTo={setTo}
        mailDirty={mailDirty}
        saveMail={saveMail}
      />

      <div className="space-y-3 pt-4 border-t border-paper-200 dark:border-paper-700">
        <h3 className="text-sm font-medium text-paper-700 dark:text-paper-200">
          {t("settings.telegram")}
        </h3>
        <ToggleField
          label={t("settings.telegramEnable")}
          hint={t("settings.telegramHint")}
          checked={settings.overdue_telegram_enabled ?? false}
          disabled={isSaving}
          onChange={(checked) => onSave({ overdue_telegram_enabled: checked })}
        />

        <SecretBox
          id="telegram-bot-token"
          label={t("settings.telegramToken")}
          placeholder={t("settings.telegramTokenPlaceholder")}
          showLabel={t("settings.telegramTokenShow")}
          hideLabel={t("settings.telegramTokenHide")}
          status={
            tokenPinned
              ? t("settings.telegramFromEnv")
              : settings.has_telegram_bot_token
                ? t("settings.telegramTokenSet", {
                    preview: settings.telegram_bot_token_preview ?? "",
                  })
                : t("settings.telegramTokenMissing")
          }
          saveLabel={
            isSaving ? t("common.saving") : t("settings.telegramTokenSave")
          }
          clearLabel={t("settings.telegramTokenClear")}
          hasStored={settings.has_telegram_bot_token === true}
          pinned={tokenPinned}
          isSaving={isSaving}
          onSave={(value) => onSave({ telegram_bot_token: value })}
          onClear={() => onSave({ telegram_bot_token: "" })}
        />

        <div className="space-y-1.5">
          <label htmlFor="telegram-chat-id" className={LABEL_CLASS}>
            {t("settings.telegramChat")}
          </label>
          <input
            id="telegram-chat-id"
            type="text"
            autoComplete="off"
            disabled={chatPinned}
            value={chat}
            onChange={(event) => setChat(event.target.value)}
            placeholder={t("settings.telegramChatPlaceholder")}
            className={FIELD_CLASS}
          />
          <p className={HINT_CLASS}>
            {chatPinned
              ? t("settings.telegramFromEnv")
              : t("settings.telegramChatHint")}
          </p>
          {!chatPinned && chat !== (settings.telegram_chat_id ?? "") && (
            <button
              type="button"
              disabled={isSaving}
              onClick={() => onSave({ telegram_chat_id: chat.trim() })}
              className={SAVE_CLASS}
            >
              {isSaving ? t("common.saving") : t("settings.telegramChatSave")}
            </button>
          )}
        </div>
      </div>
    </SettingsSection>
  );
}

interface MailBlockProps {
  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;
  pinned: Set<string>;
  t: Translate;
  server: string;
  setServer: (value: string) => void;
  port: string;
  setPort: (value: string) => void;
  username: string;
  setUsername: (value: string) => void;
  from: string;
  setFrom: (value: string) => void;
  to: string;
  setTo: (value: string) => void;
  mailDirty: boolean;
  saveMail: () => void;
}

/** The mail half, split out only so neither half is a screen of its own. */
function MailBlock({
  settings,
  isSaving,
  onSave,
  pinned,
  t,
  server,
  setServer,
  port,
  setPort,
  username,
  setUsername,
  from,
  setFrom,
  to,
  setTo,
  mailDirty,
  saveMail,
}: MailBlockProps) {
  const encryption = encryptionOf(settings);

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-paper-700 dark:text-paper-200">
        {t("settings.mail")}
      </h3>
      <ToggleField
        label={t("settings.mailEnable")}
        hint={t("settings.mailHint")}
        checked={settings.overdue_mail_enabled ?? false}
        disabled={isSaving}
        onChange={(checked) => onSave({ overdue_mail_enabled: checked })}
      />

      {pinned.size > 0 && (
        <p className={HINT_CLASS}>
          {t("settings.mailFromEnv", {
            fields: [...pinned].join(", "),
          })}
        </p>
      )}

      <div className="space-y-1.5">
        <label htmlFor="mail-server" className={LABEL_CLASS}>
          {t("settings.mailServer")}
        </label>
        <input
          id="mail-server"
          type="text"
          autoComplete="off"
          disabled={pinned.has("mail_server")}
          value={server}
          onChange={(event) => setServer(event.target.value)}
          placeholder={t("settings.mailServerPlaceholder")}
          className={FIELD_CLASS}
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="mail-port" className={LABEL_CLASS}>
          {t("settings.mailPort")}
        </label>
        <input
          id="mail-port"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          disabled={pinned.has("mail_port")}
          value={port}
          onChange={(event) => setPort(event.target.value)}
          className={`${FIELD_CLASS} w-24`}
        />
      </div>

      <fieldset className="space-y-1.5">
        <legend className={LABEL_CLASS}>{t("settings.mailSecurity")}</legend>
        <div className="flex gap-2">
          {(["starttls", "tls", "none"] as const).map((choice) => (
            <label
              key={choice}
              className="flex items-center gap-1.5 text-sm text-paper-700 dark:text-paper-200"
            >
              <input
                type="radio"
                name="mail-encryption"
                checked={encryption === choice}
                disabled={
                  isSaving ||
                  pinned.has("mail_use_tls") ||
                  pinned.has("mail_use_ssl")
                }
                onChange={() => onSave(flagsFor(choice))}
              />
              {t(ENCRYPTION_LABELS[choice])}
            </label>
          ))}
        </div>
        <p className={`${HINT_CLASS} leading-relaxed`}>
          {t("settings.mailSecurityHint")}
        </p>
      </fieldset>

      <div className="space-y-1.5">
        <label htmlFor="mail-username" className={LABEL_CLASS}>
          {t("settings.mailUsername")}
        </label>
        <input
          id="mail-username"
          type="text"
          autoComplete="off"
          disabled={pinned.has("mail_username")}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          placeholder={t("settings.mailUsernamePlaceholder")}
          className={FIELD_CLASS}
        />
      </div>

      <SecretBox
        id="mail-password"
        label={t("settings.mailPassword")}
        placeholder={t("settings.mailPasswordPlaceholder")}
        showLabel={t("settings.mailPasswordShow")}
        hideLabel={t("settings.mailPasswordHide")}
        status={
          pinned.has("mail_password")
            ? t("settings.mailFromEnv", { fields: "mail_password" })
            : settings.has_mail_password
              ? t("settings.mailPasswordSet", {
                  preview: settings.mail_password_preview ?? "",
                })
              : t("settings.mailPasswordMissing")
        }
        saveLabel={
          isSaving ? t("common.saving") : t("settings.mailPasswordSave")
        }
        clearLabel={t("settings.mailPasswordClear")}
        hasStored={settings.has_mail_password === true}
        pinned={pinned.has("mail_password")}
        isSaving={isSaving}
        onSave={(value) => onSave({ mail_password: value })}
        onClear={() => onSave({ mail_password: "" })}
      />

      <div className="space-y-1.5">
        <label htmlFor="mail-from" className={LABEL_CLASS}>
          {t("settings.mailFrom")}
        </label>
        <input
          id="mail-from"
          type="email"
          autoComplete="off"
          disabled={pinned.has("mail_default_sender")}
          value={from}
          onChange={(event) => setFrom(event.target.value)}
          placeholder={t("settings.mailFromPlaceholder")}
          className={FIELD_CLASS}
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="mail-to" className={LABEL_CLASS}>
          {t("settings.mailTo")}
        </label>
        <input
          id="mail-to"
          type="text"
          autoComplete="off"
          value={to}
          onChange={(event) => setTo(event.target.value)}
          placeholder={t("settings.mailToPlaceholder")}
          className={FIELD_CLASS}
        />
        <p className={HINT_CLASS}>{t("settings.mailToHint")}</p>
      </div>

      {mailDirty && (
        <button
          type="button"
          disabled={isSaving}
          onClick={saveMail}
          className={SAVE_CLASS}
        >
          {isSaving ? t("common.saving") : t("settings.mailSave")}
        </button>
      )}
    </div>
  );
}
