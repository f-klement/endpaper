import { Link } from "react-router-dom";

import { Locale, type SettingsUpdate } from "../../../api/generated/model";
import { Icon } from "../../../components";
import { useTranslation, type Translate } from "../../../i18n";
import { paletteEntry, useTheme, WALLPAPER_OFF } from "../../../theme";
import { PATTERNS } from "../../../theme/patterns";
import { SettingsSection } from "../../components";
import { MODE_LABELS } from "../../types";
import AdminSettings from "../components/AdminSettings";
import SettingsSubPage from "../components/SettingsSubPage";
import { useSettings } from "../hooks";

/**
 * The wallpaper choice, named.
 *
 * Three states in one field. The summary names the choice rather than what
 * happens to be on the page: somebody who picked Surprise me should read
 * "Surprise me" here, not this visit's pattern, which would read as pinned.
 *
 * Membership in `PATTERNS`, not `patternFor`, and the difference matters. An id
 * this build no longer has degrades to a random pattern on the page, and asking
 * `patternFor` for its name would print that pattern here as though it were the
 * one chosen. Both cases that end in a different wallpaper every visit are
 * named as such.
 */
function wallpaperName(wallpaper: string | null, t: Translate): string {
  return wallpaper === WALLPAPER_OFF
    ? t("appearance.wallpaperNone")
    : (PATTERNS.find((pattern) => pattern.id === wallpaper)?.name ??
        t("appearance.wallpaperSurprise"));
}

const LANGUAGES = [
  { value: Locale.en, label: "settings.language.en" },
  { value: Locale.de, label: "settings.language.de" },
] as const;

/** One shape for both language pickers, so they cannot drift apart. */
function languageButtonClass(isChosen: boolean): string {
  const base =
    "flex-1 py-2 rounded-xl text-sm font-medium border transition-colors disabled:opacity-50 ";
  return isChosen
    ? base +
        "bg-accent-50 border-accent-300 text-accent-800 " +
        "dark:bg-accent-950 dark:border-accent-800 dark:text-accent-200"
    : base +
        "bg-paper-0 border-paper-200 text-paper-600 hover:bg-paper-50 " +
        "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800";
}

/**
 * What the app looks like, and what language it speaks.
 *
 * Three settings the owner grouped together, and the two language ones are not
 * the pair their names suggest. **Language is per person and per device**: it
 * needs no admin account and is stored in this browser. **Default language is
 * the interface language for somebody who has not chosen one yet**, which is
 * why it sits here rather than with the catalogue: it says nothing about what
 * language a book is in.
 *
 * The palette, light or dark, and the wallpaper are a link rather than controls,
 * because the only honest preview of a wallpaper is the page itself. That
 * screen is `/settings/appearance/theme`, and the card here is the summary, so
 * somebody scanning this page still sees what is set.
 */
export default function AppearanceSettingsPage() {
  const { t, locale, setLocale } = useTranslation();
  const { appearance, wallpaperOff } = useTheme();
  const state = useSettings();

  return (
    <SettingsSubPage icon="theme" title={t("settings.appearance.title")}>
      <SettingsSection title={t("appearance.title")} icon="theme">
        <Link
          to="/settings/appearance/theme"
          className="flex items-center gap-3 rounded-xl border border-paper-200 bg-paper-0 px-3 py-2.5 hover:bg-paper-50 dark:border-paper-700 dark:bg-paper-900 dark:hover:bg-paper-800"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium text-paper-900 dark:text-paper-100">
              {t("theme.summary", {
                palette: paletteEntry(appearance.palette).label,
                mode: t(MODE_LABELS[appearance.mode]),
                wallpaper: wallpaperName(appearance.wallpaper, t),
              })}
            </span>
            <span className="block text-xs text-paper-600 dark:text-paper-400">
              {t("theme.change")}
            </span>
          </span>
          <span
            aria-hidden="true"
            className="text-paper-600 dark:text-paper-400"
          >
            <Icon name="chevron" className="w-4 h-4" />
          </span>
        </Link>
        {/* Said rather than left to be noticed. The wallpaper is decoration and
            goes first when somebody asks their system for more contrast, and a
            decoration that vanishes with no explanation reads as a fault in
            this app rather than as the setting being honoured. */}
        {wallpaperOff && (
          <p className="text-xs text-paper-600 dark:text-paper-400">
            {t("theme.wallpaperOff")}
          </p>
        )}
      </SettingsSection>

      {/* Before anything the server has to authorise: it is per person and per
          device, so it works for a member who can change nothing else. */}
      <SettingsSection title={t("settings.language")} icon="globe">
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
              className={languageButtonClass(locale === language.value)}
            >
              {t(language.label)}
            </button>
          ))}
        </div>
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("settings.languageHint")}
        </p>
      </SettingsSection>

      <AdminSettings state={state}>
        {(settings) => (
          <SettingsSection title={t("settings.defaultLanguage")} icon="flag">
            <div
              className="flex gap-2"
              role="group"
              aria-label={t("settings.defaultLanguage")}
            >
              {LANGUAGES.map((language) => (
                <button
                  key={language.value}
                  type="button"
                  disabled={state.isSaving}
                  onClick={() =>
                    state.save({
                      default_locale: language.value,
                    } satisfies SettingsUpdate)
                  }
                  aria-pressed={settings.default_locale === language.value}
                  className={languageButtonClass(
                    settings.default_locale === language.value,
                  )}
                >
                  {t(language.label)}
                </button>
              ))}
            </div>
          </SettingsSection>
        )}
      </AdminSettings>
    </SettingsSubPage>
  );
}
