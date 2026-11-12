import { useState, type ChangeEvent } from "react";

import {
  OverdueSender,
  type SenderHealth,
  type SettingsOut,
  type SettingsUpdate,
} from "../../../../api/generated/model";
import {
  useTranslation,
  type MessageKey,
  type Translate,
} from "../../../../i18n";
import { SettingsSection } from "../../../components";
import SecretField from "../../components/SecretField";
import ToggleField from "../../components/ToggleField";
import { SenderHealthLine } from "../../../components";

/**
 * The reminder channels beside the webhook: the app itself, a mailbox and a
 * group chat.
 *
 * The webhook stays in `OverdueSection` beside the interval and the send button,
 * because it is the channel that was here first and its form is the one an
 * existing install already knows. These two are the ones added on the argument
 * that a webhook makes the household build the receiver: **SMTP is universal**
 * and **Telegram is one fixed host**.
 *
 * **The in app notice is first, and it is the only one that ships switched
 * on.** Mail and Telegram are better dependencies than a webhook and they are
 * still dependencies: somebody has to obtain an SMTP account or a bot token
 * before either does anything. This one needs neither, so a household that has
 * configured nothing is still told, which is what #86 was filed about. It has
 * one control because there is nothing else to say: no destination, no
 * credential, and nothing an operator can pin from the environment.
 *
 * **Encryption is three radio buttons, not two switches, and that is the point
 * of the shape.** STARTTLS and implicit TLS are two protocols on one socket, and
 * the server refuses a configuration naming both. A pair of checkboxes makes
 * that refusal reachable by clicking; a single choice makes it unreachable.
 * There is deliberately no "do not check certificates" option: nothing in the
 * app can switch verification off, so offering the control would be a lie.
 *
 * The secrets are `SecretField`s, like the webhook secret above them. The
 * browser never received the stored value, so an empty box has to mean "leave
 * it alone".
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

const HINT_CLASS = "text-xs text-paper-600 dark:text-paper-400";

const LABEL_CLASS =
  "block text-xs font-medium text-paper-600 dark:text-paper-300";

interface ReminderSendersSectionProps {
  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;
  /** Keyed by sender. A channel that is switched off is absent. */
  health: Partial<Record<OverdueSender, SenderHealth>>;
}

export default function ReminderSendersSection({
  settings,
  isSaving,
  onSave,
  health,
}: ReminderSendersSectionProps) {
  const { t } = useTranslation();

  const tokenPinned = settings.telegram_bot_token_from_env === true;

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

      {/* First, and above the divider the other channels sit under, because it
          is the one that works before anything else is configured. */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-paper-700 dark:text-paper-200">
          {t("settings.inApp")}
        </h3>
        <ToggleField
          label={t("settings.inAppEnable")}
          hint={t("settings.inAppHint")}
          checked={settings.overdue_in_app_enabled ?? true}
          disabled={isSaving}
          onChange={(checked) => onSave({ overdue_in_app_enabled: checked })}
        />
        {/* No health line, deliberately. This channel hands the digest to
            nobody, so its recorded outcome is never a failure and the line
            could only ever read "working": a reassurance about a delivery
            nothing checked. `SenderHealthLine` says the same in full. */}
        {/* The one place the privacy note above does not apply, and saying so
            here is the point: this channel has a reader, so it can show that
            reader their own private books without disclosing them to anybody. */}
        <p className={`${HINT_CLASS} leading-relaxed`}>
          {t("settings.inAppPrivacyNote")}
        </p>
      </div>

      <MailBlock
        settings={settings}
        isSaving={isSaving}
        onSave={onSave}
        health={health[OverdueSender.email]}
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

        <SenderHealthLine health={health[OverdueSender.telegram]} />

        <SecretField
          id="telegram-bot-token"
          label={t("settings.telegramToken")}
          placeholder={t("settings.telegramTokenPlaceholder")}
          showLabel={t("settings.telegramTokenShow")}
          hideLabel={t("settings.telegramTokenHide")}
          status={secretStatus(
            {
              pinned: tokenPinned,
              stored: settings.has_telegram_bot_token,
              preview: settings.telegram_bot_token_preview,
            },
            {
              pinned: t("settings.telegramFromEnv"),
              set: "settings.telegramTokenSet",
              missing: "settings.telegramTokenMissing",
            },
            t,
          )}
          saveLabel={t("settings.telegramTokenSave")}
          clearLabel={t("settings.telegramTokenClear")}
          hasStored={settings.has_telegram_bot_token === true}
          pinned={tokenPinned}
          isSaving={isSaving}
          onSave={(value) => onSave({ telegram_bot_token: value })}
          onClear={() => onSave({ telegram_bot_token: "" })}
        />

        <TelegramChatField
          settings={settings}
          isSaving={isSaving}
          onSave={onSave}
        />
      </div>
    </SettingsSection>
  );
}

interface ChannelProps {
  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;
}

/** The chat a Telegram digest goes to, and its save. */
function TelegramChatField({ settings, isSaving, onSave }: ChannelProps) {
  const { t } = useTranslation();

  // A draft rather than a controlled mirror of `settings`, like the mail
  // fields in `MailBlock`.
  const stored = settings.telegram_chat_id ?? "";
  const [chat, setChat] = useState(stored);
  const chatPinned = settings.telegram_chat_id_from_env === true;

  return (
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
      {!chatPinned && chat !== stored && (
        <SaveButton
          isSaving={isSaving}
          label={t("settings.telegramChatSave")}
          onClick={() => onSave({ telegram_chat_id: chat.trim() })}
        />
      )}
    </div>
  );
}

interface MailBlockProps extends ChannelProps {
  health: SenderHealth | undefined;
}

/** The mail fields a deployment may pin from its environment. */
const PINNABLE_MAIL_DRAFTS = [
  "mail_server",
  "mail_port",
  "mail_username",
  "mail_default_sender",
] as const;

/** Every mail field edited as a draft; the recipient is never pinned. */
const MAIL_DRAFTS = [...PINNABLE_MAIL_DRAFTS, "overdue_mail_to"] as const;

type MailDrafts = Record<(typeof MAIL_DRAFTS)[number], string>;

function storedMailDrafts(settings: SettingsOut): MailDrafts {
  return {
    mail_server: settings.mail_server ?? "",
    mail_port: settings.mail_port ?? "",
    mail_username: settings.mail_username ?? "",
    mail_default_sender: settings.mail_default_sender ?? "",
    overdue_mail_to: settings.overdue_mail_to ?? "",
  };
}

// Only the fields this deployment does not pin. Sending a pinned one back
// would be a 409 the admin cannot act on from here.
function mailPatch(
  drafts: MailDrafts,
  pinned: ReadonlySet<string>,
): SettingsUpdate {
  const patch: SettingsUpdate = {
    overdue_mail_to: drafts.overdue_mail_to.trim(),
  };
  for (const field of PINNABLE_MAIL_DRAFTS) {
    if (!pinned.has(field)) patch[field] = drafts[field].trim();
  }
  return patch;
}

/**
 * The mail channel: its switch, its standing record, the connection and the
 * recipient.
 *
 * It owns its drafts and their save, so the section above holds nothing of
 * mail's but the slot it sits in.
 */
function MailBlock({ settings, isSaving, onSave, health }: MailBlockProps) {
  const { t } = useTranslation();

  // Drafts rather than controlled mirrors of `settings`: typing a host should
  // not save it a character at a time, and a controlled field whose value only
  // changes after a round trip snaps back mid edit.
  const [drafts, setDrafts] = useState(() => storedMailDrafts(settings));

  const pinned = new Set(settings.mail_from_env ?? []);

  const stored = storedMailDrafts(settings);
  const mailDirty = MAIL_DRAFTS.some(
    (field) => drafts[field] !== stored[field],
  );

  function edit(field: keyof MailDrafts) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const value = event.target.value;
      setDrafts((current) => ({ ...current, [field]: value }));
    };
  }

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

      <SenderHealthLine health={health} />

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
          value={drafts.mail_server}
          onChange={edit("mail_server")}
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
          value={drafts.mail_port}
          onChange={edit("mail_port")}
          className={`${FIELD_CLASS} w-24`}
        />
      </div>

      <EncryptionChoice
        settings={settings}
        isSaving={isSaving}
        onSave={onSave}
        pinned={pinned}
      />

      <div className="space-y-1.5">
        <label htmlFor="mail-username" className={LABEL_CLASS}>
          {t("settings.mailUsername")}
        </label>
        <input
          id="mail-username"
          type="text"
          autoComplete="off"
          disabled={pinned.has("mail_username")}
          value={drafts.mail_username}
          onChange={edit("mail_username")}
          placeholder={t("settings.mailUsernamePlaceholder")}
          className={FIELD_CLASS}
        />
      </div>

      <SecretField
        id="mail-password"
        label={t("settings.mailPassword")}
        placeholder={t("settings.mailPasswordPlaceholder")}
        showLabel={t("settings.mailPasswordShow")}
        hideLabel={t("settings.mailPasswordHide")}
        status={secretStatus(
          {
            pinned: pinned.has("mail_password"),
            stored: settings.has_mail_password,
            preview: settings.mail_password_preview,
          },
          {
            pinned: t("settings.mailFromEnv", { fields: "mail_password" }),
            set: "settings.mailPasswordSet",
            missing: "settings.mailPasswordMissing",
          },
          t,
        )}
        saveLabel={t("settings.mailPasswordSave")}
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
          value={drafts.mail_default_sender}
          onChange={edit("mail_default_sender")}
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
          value={drafts.overdue_mail_to}
          onChange={edit("overdue_mail_to")}
          placeholder={t("settings.mailToPlaceholder")}
          className={FIELD_CLASS}
        />
        <p className={HINT_CLASS}>{t("settings.mailToHint")}</p>
      </div>

      {mailDirty && (
        <SaveButton
          isSaving={isSaving}
          label={t("settings.mailSave")}
          onClick={() => onSave(mailPatch(drafts, pinned))}
        />
      )}
    </div>
  );
}

interface EncryptionChoiceProps extends ChannelProps {
  pinned: ReadonlySet<string>;
}

/** The transport as one of three radio buttons; why three is above. */
function EncryptionChoice({
  settings,
  isSaving,
  onSave,
  pinned,
}: EncryptionChoiceProps) {
  const { t } = useTranslation();
  const encryption = encryptionOf(settings);
  const disabled =
    isSaving || pinned.has("mail_use_tls") || pinned.has("mail_use_ssl");

  return (
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
              disabled={disabled}
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
  );
}

/**
 * What a `SecretField` says about its stored value. A pinned value comes
 * first, because then the stored one is not the one in use.
 */
function secretStatus(
  state: { pinned: boolean; stored: boolean | undefined; preview?: string },
  says: { pinned: string; set: MessageKey; missing: MessageKey },
  t: Translate,
): string {
  if (state.pinned) return says.pinned;
  if (state.stored) return t(says.set, { preview: state.preview ?? "" });
  return t(says.missing);
}

/** A draft's save button, shown by its caller only while the draft differs. */
function SaveButton({
  isSaving,
  label,
  onClick,
}: {
  isSaving: boolean;
  label: string;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      disabled={isSaving}
      onClick={onClick}
      className={SAVE_CLASS}
    >
      {isSaving ? t("common.saving") : label}
    </button>
  );
}
