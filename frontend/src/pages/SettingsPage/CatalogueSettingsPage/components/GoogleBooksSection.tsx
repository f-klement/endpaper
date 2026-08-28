import { useState } from "react";

import type {
  SettingsOut,
  SettingsUpdate,
} from "../../../../api/generated/model";
import { HelpButton, Icon } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import GoogleBooksHelp from "../../../components/GoogleBooksHelp";
import { SettingsSection } from "../../../components";
import ToggleField from "../../components/ToggleField";

interface GoogleBooksSectionProps {
  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;
}

/**
 * The lookup toggle and the key it needs.
 *
 * **The key field is write only.** The server never sends a stored key back, so
 * it cannot be a controlled mirror of `settings`: an empty box means "leave the
 * stored key alone", and the reveal only ever shows what was typed here in this
 * session. What is stored is described instead, by its preview.
 *
 * A key managed through the environment is shown as such and the field is
 * disabled, because there is nothing here to edit and nothing to unmask.
 */
export default function GoogleBooksSection({
  settings,
  isSaving,
  onSave,
}: GoogleBooksSectionProps) {
  const { t } = useTranslation();
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  const fromEnv = settings.google_books_api_key_from_env === true;

  return (
    <SettingsSection title={t("settings.googleBooks")} icon="search">
      <ToggleField
        label={t("settings.googleBooksEnable")}
        hint={t("settings.googleBooksHint")}
        checked={settings.google_books_enabled}
        disabled={isSaving}
        onChange={(checked) => onSave({ google_books_enabled: checked })}
      />

      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <label
            htmlFor="google-books-key"
            className="block text-xs font-medium text-paper-600 dark:text-paper-300"
          >
            {t("settings.apiKey")}
          </label>
          <HelpButton
            label={t("settings.apiKeyHelp")}
            onClick={() => setShowHelp(true)}
          />
        </div>

        <div className="relative">
          <input
            id="google-books-key"
            type={showKey ? "text" : "password"}
            autoComplete="off"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={t("settings.apiKeyPlaceholder")}
            // Managed outside the app, so there is nothing here to edit
            // and nothing to unmask.
            disabled={fromEnv}
            className="w-full px-3 py-2 pr-10 rounded-xl border border-paper-200 text-sm disabled:bg-paper-50 disabled:text-paper-400 disabled:cursor-not-allowed dark:border-paper-700 dark:disabled:bg-paper-800"
          />
          {!fromEnv && (
            <button
              type="button"
              onClick={() => setShowKey((shown) => !shown)}
              aria-label={showKey ? t("field.hide") : t("field.show")}
              aria-pressed={showKey}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-paper-600 hover:text-paper-800 text-sm leading-none dark:text-paper-400 dark:hover:text-paper-300"
            >
              <span aria-hidden="true">
                <Icon name={showKey ? "eyeOff" : "eye"} className="w-4 h-4" />
              </span>
            </button>
          )}
        </div>
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {settings.has_google_books_api_key
            ? t("settings.apiKeySet", {
                preview: settings.google_books_api_key_preview,
              })
            : t("settings.apiKeyMissing")}
        </p>

        {fromEnv && (
          <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-200 dark:bg-amber-950 dark:border-amber-900">
            {t("settings.apiKeyFromEnv")}
          </p>
        )}
        {!fromEnv && (
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              disabled={isSaving || apiKey.trim() === ""}
              onClick={() => {
                onSave({ google_books_api_key: apiKey.trim() });
                setApiKey("");
              }}
              className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
            >
              {isSaving ? t("common.saving") : t("common.save")}
            </button>
            {settings.has_google_books_api_key && (
              <button
                type="button"
                disabled={isSaving}
                // An empty string clears it; `undefined` would mean
                // "leave alone", which is the opposite.
                onClick={() => onSave({ google_books_api_key: "" })}
                className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium text-danger-600 hover:bg-danger-100 disabled:opacity-40 transition-colors dark:border-paper-700 dark:text-danger-300"
              >
                {t("settings.apiKeyClear")}
              </button>
            )}
          </div>
        )}
        <p className="text-xs text-paper-600 leading-relaxed pt-1 dark:text-paper-400">
          {t("settings.apiKeyHint")}
        </p>
      </div>

      {showHelp && (
        <GoogleBooksHelp
          isUnconfigured={!settings.has_google_books_api_key}
          onClose={() => setShowHelp(false)}
        />
      )}
    </SettingsSection>
  );
}
