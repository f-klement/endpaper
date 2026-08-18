import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Locale, type SettingsUpdate } from "../../api/generated/model";
import { ErrorState, HelpButton, Spinner } from "../../components";
import { useTranslation, type MessageKey } from "../../i18n";
import { useTheme, type ThemePreference } from "../../theme";
import GoogleBooksHelp from "../components/GoogleBooksHelp";
import GoodreadsImport from "./components/GoodreadsImport";
import SettingsSection from "./components/SettingsSection";
import ToggleField from "./components/ToggleField";
import { useGoodreadsImport, useSettings } from "./hooks";

const THEMES: { value: ThemePreference; label: MessageKey }[] = [
  { value: "light", label: "theme.light" },
  { value: "dark", label: "theme.dark" },
  // Listed last rather than first: it is the default, and a default reads
  // better as the thing you return to than the thing you start at.
  { value: "system", label: "theme.system" },
];

const LANGUAGES = [
  { value: Locale.en, label: "settings.language.en" },
  { value: Locale.de, label: "settings.language.de" },
] as const;

export default function SettingsPage() {
  const { t, locale, setLocale } = useTranslation();
  const { preference, setPreference } = useTheme();
  const navigate = useNavigate();
  const {
    settings,
    isLoading,
    error,
    isForbidden,
    save,
    isSaving,
    saveError,
    hasSaved,
  } = useSettings();
  const goodreads = useGoodreadsImport();

  // The API key is the one field the server never sends back, so it cannot be
  // a controlled mirror of `settings`. It is a write-only box: empty means
  // "leave the stored key alone".
  const [apiKey, setApiKey] = useState("");
  // The typed value, not the stored one: the server never returns a key, so
  // this only ever reveals what the admin has just entered themselves.
  const [showKey, setShowKey] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  const fromEnv = settings?.google_books_api_key_from_env === true;

  function update(patch: SettingsUpdate) {
    save(patch);
  }

  return (
    <div className="max-w-lg mx-auto px-4 pt-5 pb-4 space-y-6">
      <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
        ⚙️ {t("settings.title")}
      </h1>

      {/* Language is per person and per device, so it works without an admin
          account and is rendered before anything the server has to authorise. */}
      <SettingsSection title={t("settings.language")} glyph="🌍">
        <div
          className="flex gap-2"
          role="group"
          aria-label={t("settings.language")}
        >
          {LANGUAGES.map((language) => (
            <button
              key={language.value}
              type="button"
              onClick={() => setLocale(language.value)}
              aria-pressed={locale === language.value}
              className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors ${
                locale === language.value
                  ? "bg-sky-50 border-sky-300 text-sky-700"
                  : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              {t(language.label)}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t("settings.languageHint")}
        </p>
      </SettingsSection>

      <SettingsSection title={t("theme.label")} glyph="🌗">
        <div className="flex gap-2" role="group" aria-label={t("theme.label")}>
          {THEMES.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setPreference(option.value)}
              aria-pressed={preference === option.value}
              className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors ${
                preference === option.value
                  ? "bg-sky-50 border-sky-300 text-sky-700 dark:bg-sky-950 dark:border-sky-700 dark:text-sky-200"
                  : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50 dark:bg-gray-900 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
              }`}
            >
              {t(option.label)}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {preference === "system" ? t("theme.systemHint") : t("theme.hint")}
        </p>
      </SettingsSection>

      {isLoading && <Spinner label={t("common.loading")} />}

      {/* A non-admin gets the language switch and nothing else. That is not an
          error worth showing an error page for, so it is stated plainly. */}
      {isForbidden && (
        <p className="text-sm text-gray-500 text-center dark:text-gray-400">
          {t("settings.adminOnly")}
        </p>
      )}

      {error != null && !isForbidden && (
        <ErrorState error={error} fallback={t("settings.couldNotLoad")} />
      )}

      {settings && (
        <>
          <SettingsSection title={t("settings.googleBooks")} glyph="🔎">
            <ToggleField
              label={t("settings.googleBooksEnable")}
              hint={t("settings.googleBooksHint")}
              checked={settings.google_books_enabled}
              disabled={isSaving}
              onChange={(checked) => update({ google_books_enabled: checked })}
            />

            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <label
                  htmlFor="google-books-key"
                  className="block text-xs font-medium text-gray-600 dark:text-gray-300"
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
                  className="w-full px-3 py-2 pr-10 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 disabled:bg-gray-50 disabled:text-gray-400 disabled:cursor-not-allowed dark:border-gray-700 dark:disabled:bg-gray-800"
                />
                {!fromEnv && (
                  <button
                    type="button"
                    onClick={() => setShowKey((shown) => !shown)}
                    aria-label={showKey ? t("field.hide") : t("field.show")}
                    aria-pressed={showKey}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-sm leading-none dark:text-gray-500 dark:hover:text-gray-300"
                  >
                    <span aria-hidden="true">{showKey ? "🙈" : "👁"}</span>
                  </button>
                )}
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">
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
                      update({ google_books_api_key: apiKey.trim() });
                      setApiKey("");
                    }}
                    className="px-3 py-1.5 rounded-lg bg-sky-500 text-white text-xs font-medium hover:bg-sky-600 disabled:opacity-40 transition-colors"
                  >
                    {isSaving ? t("common.saving") : t("common.save")}
                  </button>
                  {settings.has_google_books_api_key && (
                    <button
                      type="button"
                      disabled={isSaving}
                      // An empty string clears it; `undefined` would mean
                      // "leave alone", which is the opposite.
                      onClick={() => update({ google_books_api_key: "" })}
                      className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-40 transition-colors dark:border-gray-700 dark:text-red-400"
                    >
                      {t("settings.apiKeyClear")}
                    </button>
                  )}
                </div>
              )}
              <p className="text-xs text-gray-500 leading-relaxed pt-1 dark:text-gray-400">
                {t("settings.apiKeyHint")}
              </p>
            </div>
          </SettingsSection>

          <SettingsSection title={t("settings.goodreads")} glyph="📖">
            <ToggleField
              label={t("settings.goodreadsEnable")}
              hint={t("settings.goodreadsHint")}
              checked={settings.goodreads_lookup_enabled}
              disabled={isSaving}
              onChange={(checked) =>
                update({ goodreads_lookup_enabled: checked })
              }
            />

            <div className="pt-2 border-t border-gray-100 dark:border-gray-800">
              <h3 className="text-xs font-medium text-gray-600 mb-2 dark:text-gray-300">
                {t("goodreads.import")}
              </h3>
              <GoodreadsImport
                isUploading={goodreads.isUploading}
                result={goodreads.result}
                error={goodreads.error}
                onUpload={goodreads.upload}
                onReviewUnconfirmed={() => navigate("/?ownership=unknown")}
              />
            </div>
          </SettingsSection>

          <SettingsSection title={t("settings.defaultLanguage")} glyph="🏳️">
            <div
              className="flex gap-2"
              role="group"
              aria-label={t("settings.defaultLanguage")}
            >
              {LANGUAGES.map((language) => (
                <button
                  key={language.value}
                  type="button"
                  disabled={isSaving}
                  onClick={() => update({ default_locale: language.value })}
                  aria-pressed={settings.default_locale === language.value}
                  className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors disabled:opacity-50 ${
                    settings.default_locale === language.value
                      ? "bg-sky-50 border-sky-300 text-sky-700"
                      : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {t(language.label)}
                </button>
              ))}
            </div>
          </SettingsSection>

          {showHelp && (
            <GoogleBooksHelp
              isUnconfigured={!settings.has_google_books_api_key}
              onClose={() => setShowHelp(false)}
            />
          )}

          {saveError != null && (
            <ErrorState
              error={saveError}
              fallback={t("common.somethingWentWrong")}
            />
          )}
          {hasSaved && saveError == null && (
            <p
              role="status"
              className="text-sm text-green-600 text-center dark:text-green-400"
            >
              {t("settings.saved")}
            </p>
          )}
        </>
      )}
    </div>
  );
}
