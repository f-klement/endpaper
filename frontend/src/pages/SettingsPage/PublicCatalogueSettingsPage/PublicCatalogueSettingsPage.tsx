import { useState } from "react";
import { Link } from "react-router-dom";

import type { SettingsOut } from "../../../api/generated/model";
import { Button, Modal } from "../../../components";
import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import AdminSettings from "../components/AdminSettings";
import SettingsSubPage from "../components/SettingsSubPage";
import ToggleField from "../components/ToggleField";
import { useSettings } from "../hooks";

/**
 * Library mode, and whether the catalogue is published.
 *
 * **Its own screen rather than a card on another one**, and that is the same
 * argument the two switches themselves make: publishing a catalogue is the one
 * setting in this application that makes rows readable with no session at all,
 * and a control that important does not belong in a row of toggles somebody
 * scrolls past. It has an address, an explanation, and a confirmation that
 * names what becomes public.
 *
 * **Publishing takes a confirmation by whichever route it happens.** There are
 * two: the publish switch, and library mode turned back on while the publish
 * row is still stored true. The second is publishing just as much as the first
 * and was one unconfirmed click for a round.
 *
 * **The nesting is drawn, not enforced here.** The publish switch is disabled
 * while library mode is off, which is advice to this one client; the guarantee
 * is `settings_store.public_catalogue_is_published`, which reads both rows on
 * the server. That distinction matters: a stored publish row left on while
 * library mode is off is treated as off by every route, so turning library mode
 * back off cannot leave a catalogue public. This screen therefore shows the two
 * rows **as stored** and reads `public_catalogue_published` for what is
 * actually true.
 */
export default function PublicCatalogueSettingsPage() {
  const { t } = useTranslation();
  const state = useSettings();
  // Which switch the open confirmation is for, or null for none. **A field
  // rather than a boolean**, because there are two ways to publish and they
  // write different rows: the publish switch itself, and library mode turned
  // back on while the publish row is still true. The second is the one the
  // first version missed.
  const [confirming, setConfirming] = useState<
    "public_catalogue_enabled" | "library_mode" | null
  >(null);

  return (
    <SettingsSubPage icon="globe" title={t("settings.public.title")}>
      <AdminSettings state={state}>
        {(settings: SettingsOut) => (
          <>
            <SettingsSection title={t("settings.public.modeTitle")} icon="book">
              <ToggleField
                label={t("settings.public.modeLabel")}
                // **The hint is false in one state and that is the state that
                // matters.** With the publish row stored true and library mode
                // off, turning library mode on publishes the catalogue, so
                // "It publishes nothing" would be the sentence a household read
                // immediately before publishing by accident.
                hint={
                  settings.public_catalogue_enabled && !settings.library_mode
                    ? t("settings.public.modeRepublishes")
                    : t("settings.public.modeHint")
                }
                checked={settings.library_mode ?? false}
                disabled={state.isSaving}
                onChange={(checked) => {
                  // Turning library mode on while the publish row is already
                  // true **is** publishing, so it takes the same confirmation.
                  // Without this, publish on, mode off, mode on republished the
                  // catalogue in one click and #95's "publishing takes two
                  // deliberate acts" held only on the first route into it.
                  if (checked && settings.public_catalogue_enabled) {
                    setConfirming("library_mode");
                    return;
                  }
                  state.save({ library_mode: checked });
                }}
              />
            </SettingsSection>

            <SettingsSection
              title={t("settings.public.publishTitle")}
              icon="globe"
            >
              <ToggleField
                label={t("settings.public.publishLabel")}
                hint={
                  settings.library_mode
                    ? t("settings.public.publishHint")
                    : t("settings.public.publishNeedsMode")
                }
                checked={settings.public_catalogue_enabled ?? false}
                // Off is always allowed and never confirmed: making something
                // less public is not a decision anybody needs protecting from.
                disabled={state.isSaving || !settings.library_mode}
                onChange={(checked) => {
                  if (checked) {
                    setConfirming("public_catalogue_enabled");
                    return;
                  }
                  state.save({ public_catalogue_enabled: false });
                }}
              />

              {settings.public_catalogue_published && (
                <p
                  role="status"
                  className="mt-3 text-sm text-paper-700 dark:text-paper-300"
                >
                  {t("settings.public.liveNotice")}{" "}
                  <Link
                    to="/catalogue"
                    className="text-accent-700 dark:text-accent-300"
                  >
                    {t("settings.public.liveLink")}
                  </Link>
                </p>
              )}

              <div className="mt-4">
                <ToggleField
                  label={t("settings.public.indexingLabel")}
                  hint={t("settings.public.indexingHint")}
                  checked={settings.public_catalogue_indexing_enabled ?? false}
                  disabled={
                    state.isSaving || !settings.public_catalogue_published
                  }
                  onChange={(checked) =>
                    state.save({ public_catalogue_indexing_enabled: checked })
                  }
                />
              </div>
            </SettingsSection>

            {confirming !== null && (
              <Modal
                title={t("settings.public.confirmTitle")}
                onClose={() => setConfirming(null)}
              >
                {/* **The confirmation names what becomes public, and what does
                    not.** A dialog that only asks "are you sure" moves the
                    decision without informing it, which is the failure mode
                    this control exists to avoid: a household enabling a
                    privacy change by misreading a label. */}
                <p className="text-sm text-paper-700 dark:text-paper-300">
                  {t("settings.public.confirmBody")}
                </p>
                <ul className="mt-3 space-y-1 text-sm text-paper-700 list-disc pl-5 dark:text-paper-300">
                  <li>{t("settings.public.confirmShown")}</li>
                  <li>{t("settings.public.confirmWithheld")}</li>
                  <li>{t("settings.public.confirmPrivate")}</li>
                  <li>{t("settings.public.confirmIndexing")}</li>
                </ul>
                <div className="mt-5 flex justify-end gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => setConfirming(null)}
                  >
                    {t("common.cancel")}
                  </Button>
                  <Button
                    onClick={() => {
                      // The switch the reader actually touched, so cancelling
                      // leaves both rows exactly as they were and accepting
                      // writes only the one that was asked for.
                      state.save({ [confirming]: true });
                      setConfirming(null);
                    }}
                  >
                    {t("settings.public.confirmAction")}
                  </Button>
                </div>
              </Modal>
            )}
          </>
        )}
      </AdminSettings>
    </SettingsSubPage>
  );
}
