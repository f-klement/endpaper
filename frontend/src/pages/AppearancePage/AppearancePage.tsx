import { Link } from "react-router-dom";

import { useTranslation } from "../../i18n";
import { useTheme } from "../../theme";
import { Page, PageHeader, SettingsSection } from "../components";
import { MODE_LABELS, MODE_ORDER } from "../types";
import Licences from "./components/Licences";
import PaletteChoice from "./components/PaletteChoice";
import PreviewShelf from "./components/PreviewShelf";
import WallpaperChoice from "./components/WallpaperChoice";
import { usePreviewBooks } from "./hooks";

/** How many of the reader's own books the preview shows. */
const PREVIEW_BOOKS = 2;

/**
 * The appearance picker.
 *
 * Its own route rather than a section of the settings list, because the only
 * honest preview of a wallpaper is the page: the pattern is painted on the
 * body, so this screen is the app surface with the controls laid over it and a
 * choice shows itself the moment it is made. A dialog would have covered the
 * thing being previewed, and a swatch alone cannot say what a palette does to a
 * page.
 *
 * Nothing here has a Save button. Every choice applies at once, is cached
 * against this account, and is pushed to the server by `AppearanceSync`, which
 * is the same path the settings list already used.
 *
 * The route sits inside `AppRoutes`, which `AppShell` renders only once there
 * is a session. That is load bearing rather than incidental: `ThemeProvider`
 * outlives a sign-out, so a picker reachable from the login screen would write
 * a choice into the previous member's cache under `last`, which is the failure
 * `release()` exists to prevent.
 */
export default function AppearancePage() {
  const { t } = useTranslation();
  const { appearance, setAppearance, wallpaperOff } = useTheme();
  const books = usePreviewBooks(PREVIEW_BOOKS);

  return (
    <Page width="wide">
      <PageHeader
        icon="theme"
        title={t("appearance.title")}
        actions={
          /* Appearance, not the settings index: this screen is a child of that
             route, and a way back that skips a level leaves a reader who came
             through it unable to reach the two language settings beside it. */
          <Link
            to="/settings/appearance"
            className="text-sm font-medium text-accent-700 dark:text-accent-300"
          >
            {t("settings.appearance.title")}
          </Link>
        }
      />

      <div className="space-y-5">
        <SettingsSection title={t("appearance.preview")} icon="book">
          <PreviewShelf books={books} />
          <p className="text-xs text-paper-600 dark:text-paper-400">
            {t("appearance.intro")}
          </p>
        </SettingsSection>

        <SettingsSection title={t("appearance.mode")} icon="lamp">
          <div
            className="flex gap-2"
            role="group"
            aria-label={t("appearance.mode")}
          >
            {MODE_ORDER.map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setAppearance({ mode })}
                aria-pressed={appearance.mode === mode}
                className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors ${
                  appearance.mode === mode
                    ? "bg-accent-50 border-accent-300 text-accent-800 dark:bg-accent-950 dark:border-accent-800 dark:text-accent-200"
                    : "bg-paper-0 border-paper-200 text-paper-600 hover:bg-paper-50 dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
                }`}
              >
                {t(MODE_LABELS[mode])}
              </button>
            ))}
          </div>
          <p className="text-xs text-paper-600 dark:text-paper-400">
            {appearance.mode === "system"
              ? t("theme.systemHint")
              : t("theme.hint")}
          </p>
        </SettingsSection>

        <SettingsSection title={t("appearance.palette")} icon="theme">
          <PaletteChoice />
        </SettingsSection>

        <SettingsSection title={t("appearance.wallpaper")} icon="sparkle">
          {/* Said rather than left to be noticed. The wallpaper is decoration
              and goes first when somebody asks their system for more contrast,
              and a decoration that vanishes with no explanation reads as a
              fault in this app rather than as the setting being honoured. The
              tiles stay live underneath it: the choice is still recorded, and
              it is what comes back when the system stops asking. */}
          {wallpaperOff && (
            <p className="text-xs text-paper-600 dark:text-paper-400">
              {t("theme.wallpaperOff")}
            </p>
          )}
          <WallpaperChoice />
        </SettingsSection>

        <SettingsSection title={t("appearance.licences")} icon="flag">
          <Licences />
        </SettingsSection>
      </div>
    </Page>
  );
}
