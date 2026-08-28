/**
 * The settings route tree's public surface.
 *
 * `app/routes.tsx` imports every settings screen from here and never from a
 * file inside one of the folders. The palette and wallpaper picker is the one
 * exception and is not a settings sub-folder at all: `pages/AppearancePage`,
 * mounted under `/settings/appearance/theme`, because previewing a wallpaper
 * needs the whole page and a `wide` frame.
 */

export { default } from "./SettingsPage";
export { SETTINGS_ROUTES, type SettingsRoute } from "./types";
export { default as AboutSettingsPage } from "./AboutSettingsPage";
export { default as AppearanceSettingsPage } from "./AppearanceSettingsPage";
export { default as CatalogueSettingsPage } from "./CatalogueSettingsPage";
export { default as DataSettingsPage } from "./DataSettingsPage";
export { default as LendingSettingsPage } from "./LendingSettingsPage";
export { default as LibrarySettingsPage } from "./LibrarySettingsPage";
