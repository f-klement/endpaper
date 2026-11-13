import { useState } from "react";

import type {
  CredentialKeyOut,
  SettingsOut,
} from "../../../../api/generated/model";
import { ErrorState } from "../../../../components";
import { useTranslation, type Translate } from "../../../../i18n";
import { catalogueName } from "../../../../lib/catalogueName";
import { SettingsSection } from "../../../components";
import { useCredentialKey, useSourceCredentials } from "../hooks";

/**
 * The key that seals every catalogue login, and the phrase that is its only form.
 *
 * **The phrase is shown once, and the server is what makes that true.** Creating
 * a key is refused when one already exists, so there is no call that renders a
 * key in being and nothing here could re-display one if it tried. This component
 * holds the words in state until the reader says they have written them down;
 * a reload loses them, which is the design working rather than a defect, and is
 * why the notice says to write them down before offering a way past it.
 *
 * **The cost sits beside the field, not only in the docs.** Losing this key
 * means typing every catalogue login in again, and a backup restored onto
 * another machine needs the phrase, because the archive deliberately carries
 * the sealed logins and never the key.
 */
export default function CredentialKeySection({
  settings,
}: {
  settings: SettingsOut;
}) {
  const { t } = useTranslation();
  const key = useCredentialKey();
  const credentials = useSourceCredentials();
  // Both here rather than in the panels they open: each panel's trigger sits
  // in the button row, and the panel goes below the row.
  const [entering, setEntering] = useState(false);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);

  if (key.isLoading || !key.key) return null;

  const held = key.key;

  return (
    <SettingsSection title={t("settings.credentialKey")} icon="lock">
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("settings.credentialKeyHint")}
      </p>

      <KeyStatus
        held={held}
        phrase={key.phrase}
        onDismiss={key.dismissPhrase}
      />

      {held.problem && (
        <p className="text-xs text-danger-700 bg-danger-100 border border-danger-200 rounded-lg px-3 py-2 dark:text-danger-200 dark:bg-danger-950 dark:border-danger-900">
          {held.problem}
        </p>
      )}

      <UnreadableLogins
        settings={settings}
        sources={held.unreadable_sources}
        isWorking={credentials.isWorking}
        onRemove={credentials.remove}
      />

      <UnreadableSettings count={(held.unreadable_settings ?? []).length} />

      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("settings.credentialKeyCost")}
      </p>

      {/* Without this every refusal the server words carefully reaches nobody:
          the two create-key conflicts, the pinned-key discard, and above all
          the 400 on a phrase that failed its checksum, which is the whole
          reason the encoding carries one. */}
      <KeyErrors keyError={key.error} credentialsError={credentials.error} />

      <KeyButtons
        held={held}
        phrase={key.phrase}
        isWorking={key.isWorking}
        onCreate={key.create}
        entering={entering}
        onEnter={() => setEntering(true)}
        confirmingDiscard={confirmingDiscard}
        onConfirmDiscard={() => setConfirmingDiscard(true)}
      />

      {confirmingDiscard && (
        <DiscardQuestion
          isWorking={key.isWorking}
          onDiscard={key.forget}
          onClose={() => setConfirmingDiscard(false)}
        />
      )}

      {entering && (
        <RestoreEntry
          isWorking={key.isWorking}
          onRestore={key.restore}
          onClose={() => setEntering(false)}
        />
      )}
    </SettingsSection>
  );
}

/** Where the key lives, in words, or nothing when the server did not say. */
function locationLabel(location: string | undefined, t: Translate): string {
  if (!location) return "";
  if (location === "env") return t("settings.credentialKeyLocationEnv");
  if (location === "keychain")
    return t("settings.credentialKeyLocationKeychain");
  return t("settings.credentialKeyLocationFile");
}

/** The phrase while it is still on screen, otherwise whether a key is held. */
function KeyStatus({
  held,
  phrase,
  onDismiss,
}: {
  held: CredentialKeyOut;
  phrase: string;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();

  if (phrase) return <PhraseNotice phrase={phrase} onDismiss={onDismiss} />;
  return (
    <p className="text-xs text-paper-600 dark:text-paper-400">
      {held.configured
        ? t("settings.credentialKeyPresent", {
            location: locationLabel(held.location, t),
          })
        : t("settings.credentialKeyMissing")}
    </p>
  );
}

/**
 * The catalogue logins sealed under a key this deployment cannot open.
 *
 * **Each one carries its own remove, and that is not a convenience.** A sealed
 * login blocks making a new key, and the refusal names it. The logins list
 * above hides both controls on a pinned row, and a client cannot tell a pinned
 * row has a sealed row behind it, because the per-source answer short-circuits
 * on the pin without reading the envelope. So the only place a person can act
 * on one is here, where this list is read off the table and already names it.
 */
function UnreadableLogins({
  settings,
  sources,
  isWorking,
  onRemove,
}: {
  settings: SettingsOut;
  sources: string[] | undefined;
  isWorking: boolean;
  onRemove: (source: string) => void;
}) {
  const { t } = useTranslation();
  if (!sources?.length) return null;

  // **A name where the roster has one, the identifier where it does not.**
  // The list above names catalogues properly, and one screen should not spell
  // them two ways. A blanket `catalogueName` is worse than the identifier
  // though: `t()` falls back to the key, so an orphan would render
  // `providers.name.<source>`, and the orphan is the case this field was
  // changed to handle.
  const names = new Map(
    (settings.catalogue_sources ?? []).map((row) => [
      row.source as string,
      t(catalogueName(row.source)),
    ]),
  );

  return (
    <div className="space-y-2 text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-200 dark:bg-amber-950 dark:border-amber-900">
      <p className="text-xs">
        {t(
          sources.length === 1
            ? "settings.credentialKeyUnreadableOne"
            : "settings.credentialKeyUnreadable",
          { count: String(sources.length) },
        )}
      </p>
      <ul className="space-y-1">
        {sources.map((source) => (
          <li
            key={source}
            className="flex flex-wrap items-center justify-between gap-2"
          >
            <span className="text-xs font-medium">
              {names.get(source) ?? source}
            </span>
            <button
              type="button"
              disabled={isWorking}
              onClick={() => onRemove(source)}
              className="px-3 py-1.5 rounded-lg border border-amber-300 text-xs font-medium text-danger-600 hover:bg-danger-100 disabled:opacity-40 transition-colors dark:border-amber-800 dark:text-danger-300"
            >
              {t("settings.credentialClear")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * How many of the app's own secrets are sealed past reading. A count rather
 * than names: each field says it beside itself, where it is entered again.
 */
function UnreadableSettings({ count }: { count: number }) {
  const { t } = useTranslation();
  if (count === 0) return null;

  return (
    <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-200 dark:bg-amber-950 dark:border-amber-900">
      {t(
        count === 1
          ? "settings.credentialKeyUnreadableSettingsOne"
          : "settings.credentialKeyUnreadableSettings",
        { count: String(count) },
      )}
    </p>
  );
}

/** The key's own refusal and the logins' refusal, each where one arrived. */
function KeyErrors({
  keyError,
  credentialsError,
}: {
  keyError: unknown;
  credentialsError: unknown;
}) {
  const { t } = useTranslation();

  return (
    <>
      {keyError != null && (
        <ErrorState error={keyError} fallback={t("settings.couldNotLoad")} />
      )}
      {credentialsError != null && (
        <ErrorState
          error={credentialsError}
          fallback={t("settings.couldNotLoad")}
        />
      )}
    </>
  );
}

/** The button row: make a key, restore one from its phrase, discard it. */
function KeyButtons({
  held,
  phrase,
  isWorking,
  onCreate,
  entering,
  onEnter,
  confirmingDiscard,
  onConfirmDiscard,
}: {
  held: CredentialKeyOut;
  phrase: string;
  isWorking: boolean;
  onCreate: () => void;
  entering: boolean;
  onEnter: () => void;
  confirmingDiscard: boolean;
  onConfirmDiscard: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-wrap gap-2">
      {!held.configured && held.can_generate && !phrase && (
        <button
          type="button"
          disabled={isWorking}
          onClick={onCreate}
          className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
        >
          {t("settings.credentialKeyCreate")}
        </button>
      )}
      {!entering && (
        <button
          type="button"
          onClick={onEnter}
          className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium hover:bg-paper-100 transition-colors dark:border-paper-700 dark:hover:bg-paper-800"
        >
          {t("settings.credentialKeyRestore")}
        </button>
      )}
      {held.configured && held.location !== "env" && !confirmingDiscard && (
        <button
          type="button"
          onClick={onConfirmDiscard}
          className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium text-danger-600 hover:bg-danger-100 transition-colors dark:border-paper-700 dark:text-danger-300"
        >
          {t("settings.credentialKeyForget")}
        </button>
      )}
    </div>
  );
}

/**
 * The words, held on screen until the reader says twice they have them.
 *
 * Two steps, because this is the irreversible one. Discarding a key is
 * recoverable by anybody holding the phrase; dismissing these words destroys
 * the only copy there will ever be, and it sat one click away directly under
 * them.
 */
function PhraseNotice({
  phrase,
  onDismiss,
}: {
  phrase: string;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 dark:border-amber-900 dark:bg-amber-950">
      <p className="text-xs font-medium text-amber-900 dark:text-amber-100">
        {t("settings.credentialKeyPhraseTitle")}
      </p>
      <p className="font-mono text-sm leading-relaxed break-words text-amber-950 select-all dark:text-amber-50">
        {phrase}
      </p>
      <p className="text-xs text-amber-800 dark:text-amber-200">
        {t("settings.credentialKeyShownOnce")}
      </p>
      {confirming ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-amber-900 dark:text-amber-100">
            {t("settings.credentialKeyDismissConfirm")}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                onDismiss();
                setConfirming(false);
              }}
              className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover transition-colors"
            >
              {t("settings.credentialKeyDone")}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="px-3 py-1.5 rounded-lg border border-amber-300 text-xs font-medium dark:border-amber-800"
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover transition-colors"
        >
          {t("settings.credentialKeyDone")}
        </button>
      )}
    </div>
  );
}

/** The question that confirms discarding the key, and the discard itself. */
function DiscardQuestion({
  isWorking,
  onDiscard,
  onClose,
}: {
  isWorking: boolean;
  onDiscard: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2 rounded-xl border border-danger-200 px-3 py-3 dark:border-danger-900">
      <p className="text-xs text-danger-700 dark:text-danger-200">
        {t("settings.credentialKeyForgetHint")}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={isWorking}
          onClick={() => {
            onDiscard();
            onClose();
          }}
          className="px-3 py-1.5 rounded-lg bg-danger-600 text-on-accent text-xs font-medium disabled:opacity-40 transition-colors"
        >
          {t("settings.credentialKeyForget")}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium dark:border-paper-700"
        >
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}

/**
 * The box a recovery phrase is typed back into.
 *
 * It owns what was typed, so closing it, by cancelling or by the server taking
 * the phrase, drops the words with it. A refusal leaves them in place: the
 * checksum's 400 is the one a reader corrects by editing, not by retyping
 * the whole phrase.
 */
function RestoreEntry({
  isWorking,
  onRestore,
  onClose,
}: {
  isWorking: boolean;
  onRestore: (words: string, onDone: () => void) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState("");

  return (
    <div className="space-y-1.5">
      <label
        htmlFor="recovery-phrase"
        className="block text-xs font-medium text-paper-600 dark:text-paper-300"
      >
        {t("settings.credentialKeyRestore")}
      </label>
      <textarea
        id="recovery-phrase"
        rows={3}
        autoComplete="off"
        // Chrome's enhanced spell check ships a field's contents to a
        // third party, and this field holds the key itself.
        spellCheck={false}
        autoCorrect="off"
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
        className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm font-mono dark:border-paper-700"
      />
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("settings.credentialKeyRestoreHint")}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={isWorking || typed.trim() === ""}
          onClick={() =>
            onRestore(typed, () => {
              setTyped("");
              onClose();
            })
          }
          className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
        >
          {t("settings.credentialKeyRestoreSave")}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium dark:border-paper-700"
        >
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}
