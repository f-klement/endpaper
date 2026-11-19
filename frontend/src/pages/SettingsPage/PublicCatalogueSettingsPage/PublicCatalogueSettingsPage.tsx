import { useState } from "react";
import { Link } from "react-router-dom";

import type { SettingsOut } from "../../../api/generated/model";
import { Button, Modal } from "../../../components";
import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import AdminSettings from "../components/AdminSettings";
import SettingsSubPage from "../components/SettingsSubPage";
import ToggleField from "../components/ToggleField";
import { useSettings, type UseSettingsResult } from "../hooks";

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
  const [confirming, setConfirming] = useState<Confirming>(null);

  return (
    <SettingsSubPage icon="globe" title={t("settings.public.title")}>
      <AdminSettings state={state}>
        {(settings: SettingsOut) => (
          <>
            <LibraryModeSection
              settings={settings}
              state={state}
              onConfirm={setConfirming}
            />

            <PublishSection
              settings={settings}
              state={state}
              onConfirm={setConfirming}
            />

            <ProtocolsSection settings={settings} state={state} />

            {confirming !== null && (
              <PublishConfirmation
                confirming={confirming}
                showsAvailability={
                  settings.public_availability_enabled ?? false
                }
                state={state}
                onClose={() => setConfirming(null)}
              />
            )}
          </>
        )}
      </AdminSettings>
    </SettingsSubPage>
  );
}

/** The row a confirmation would write, or null while none is open. */
type Confirming = "public_catalogue_enabled" | "library_mode" | null;

interface SectionProps {
  settings: SettingsOut;
  state: UseSettingsResult;
  /** Opens the confirmation for the switch that would publish. */
  onConfirm: (row: Exclude<Confirming, null>) => void;
}

/** Library mode: the switch, and the hint that tells the truth about it. */
function LibraryModeSection({ settings, state, onConfirm }: SectionProps) {
  const { t } = useTranslation();

  return (
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
            onConfirm("library_mode");
            return;
          }
          state.save({ library_mode: checked });
        }}
      />
    </SettingsSection>
  );
}

/** The publish switch, the live notice, and the indexing switch under it. */
function PublishSection({ settings, state, onConfirm }: SectionProps) {
  const { t } = useTranslation();

  return (
    <SettingsSection title={t("settings.public.publishTitle")} icon="globe">
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
            onConfirm("public_catalogue_enabled");
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

      <IndexingField settings={settings} state={state} />
      <AvailabilityField settings={settings} state={state} />
    </SettingsSection>
  );
}

/** Whether search engines may index the catalogue: disabled until it is live. */
function IndexingField({
  settings,
  state,
}: {
  settings: SettingsOut;
  state: UseSettingsResult;
}) {
  const { t } = useTranslation();

  return (
    <div className="mt-4">
      <ToggleField
        label={t("settings.public.indexingLabel")}
        hint={t("settings.public.indexingHint")}
        checked={settings.public_catalogue_indexing_enabled ?? false}
        disabled={state.isSaving || !settings.public_catalogue_published}
        onChange={(checked) =>
          state.save({ public_catalogue_indexing_enabled: checked })
        }
      />
    </div>
  );
}

/**
 * Whether a published record says on the shelf or on loan: disabled until the
 * catalogue is live, like indexing, because the server answers only then
 * (`settings_store.availability_is_shown`). No confirmation: it shows a
 * stranger that a loan is open and never who has the book or when it returns.
 */
function AvailabilityField({
  settings,
  state,
}: {
  settings: SettingsOut;
  state: UseSettingsResult;
}) {
  const { t } = useTranslation();

  return (
    <div className="mt-4">
      <ToggleField
        label={t("settings.availability.label")}
        hint={t("settings.availability.hint")}
        checked={settings.public_availability_enabled ?? false}
        disabled={state.isSaving || !settings.public_catalogue_published}
        onChange={(checked) =>
          state.save({ public_availability_enabled: checked })
        }
      />
    </div>
  );
}

/**
 * The protocols this catalogue is served over to other libraries' software.
 *
 * **Under publishing, and disabled until the catalogue is live**, like the
 * indexing switch: the server serves SRU only when the catalogue is published
 * as well (`settings_store.sru_is_served`), so the control says so rather than
 * accepting a switch that does nothing yet. Each export protocol gets a toggle
 * of its own here, and no confirmation: a protocol serves exactly what the
 * published catalogue already shows, which is what the publish confirmation
 * named.
 */
function ProtocolsSection({
  settings,
  state,
}: {
  settings: SettingsOut;
  state: UseSettingsResult;
}) {
  const { t } = useTranslation();

  return (
    <SettingsSection title={t("settings.protocols.title")} icon="library">
      <ToggleField
        label={t("settings.protocols.sruLabel")}
        hint={
          settings.public_catalogue_published
            ? t("settings.protocols.sruHint")
            : t("settings.protocols.sruNeedsPublishing")
        }
        checked={settings.sru_server_enabled ?? false}
        disabled={state.isSaving || !settings.public_catalogue_published}
        onChange={(checked) => state.save({ sru_server_enabled: checked })}
      />
    </SettingsSection>
  );
}

/** The dialog either route into publishing opens. */
function PublishConfirmation({
  confirming,
  showsAvailability,
  state,
  onClose,
}: {
  confirming: Exclude<Confirming, null>;
  /** The availability row is stored on, so publishing shows loans at once. */
  showsAvailability: boolean;
  state: UseSettingsResult;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  return (
    <Modal title={t("settings.public.confirmTitle")} onClose={onClose}>
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
        {showsAvailability && (
          <li>{t("settings.availability.confirmShown")}</li>
        )}
        <li>{t("settings.public.confirmWithheld")}</li>
        <li>{t("settings.public.confirmPrivate")}</li>
        <li>{t("settings.public.confirmIndexing")}</li>
      </ul>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button
          onClick={() => {
            // The switch the reader actually touched, so cancelling
            // leaves both rows exactly as they were and accepting
            // writes only the one that was asked for.
            state.save({ [confirming]: true });
            onClose();
          }}
        >
          {t("settings.public.confirmAction")}
        </Button>
      </div>
    </Modal>
  );
}
