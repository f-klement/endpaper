import { useState } from "react";

import type {
  SettingsOut,
  SettingsUpdate,
} from "../../../../api/generated/model";
import { Button, ErrorState } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import { SettingsSection } from "../../../components";
import ToggleField from "../../components/ToggleField";

interface HarvestSectionProps {
  settings: SettingsOut;
  isSaving: boolean;
  saveError: unknown;
  onSave: (data: SettingsUpdate) => void;
}

/**
 * The OAI-PMH harvester's switch, and the repository it reads.
 *
 * **The address is the one setting that makes the server connect where a
 * person typed**, and the hint says so in those words. A household address is
 * admitted, over http or https (owner, 2026-11-20): migrating off another
 * system on the same network is the case the harvester exists for. The server
 * checks the address and answers 400 for one it may not reach.
 *
 * **The switch cannot be turned on while no address is stored**, which the
 * server refuses with a 409 (`routers/settings._refuse_harvest_without_a_repository`),
 * so it is disabled here with the reason under it, and clearing the address
 * while it is on is not offered: the shape of the OAI-PMH provider's own field.
 */
export default function HarvestSection({
  settings,
  isSaving,
  saveError,
  onSave,
}: HarvestSectionProps) {
  const { t } = useTranslation();
  const stored = settings.oai_harvest_base_url ?? "";
  const enabled = settings.oai_harvest_enabled ?? false;

  return (
    <SettingsSection title={t("harvest.title")} icon="library">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("harvest.explain")}
      </p>
      <HarvestSwitch
        enabled={enabled}
        hasAddress={stored.trim() !== ""}
        isSaving={isSaving}
        onSave={onSave}
      />
      {/* Keyed on the stored address, so the draft starts again from it
          whenever it changes, a save from another tab included; a draft held
          past that would offer to save over the newer address. */}
      <AddressField
        key={stored}
        stored={stored}
        enabled={enabled}
        isSaving={isSaving}
        onSave={onSave}
      />
      {saveError != null && (
        <ErrorState
          error={saveError}
          fallback={t("common.somethingWentWrong")}
        />
      )}
    </SettingsSection>
  );
}

interface HarvestSwitchProps {
  enabled: boolean;
  hasAddress: boolean;
  isSaving: boolean;
  onSave: (data: SettingsUpdate) => void;
}

function HarvestSwitch({
  enabled,
  hasAddress,
  isSaving,
  onSave,
}: HarvestSwitchProps) {
  const { t } = useTranslation();
  return (
    <ToggleField
      label={t("harvest.switchLabel")}
      hint={
        hasAddress || enabled
          ? t("harvest.switchHint")
          : t("harvest.needsAddress")
      }
      checked={enabled}
      // Off is always allowed. On needs a stored address.
      disabled={isSaving || (!enabled && !hasAddress)}
      onChange={(checked) => onSave({ oai_harvest_enabled: checked })}
    />
  );
}

interface AddressFieldProps {
  stored: string;
  enabled: boolean;
  isSaving: boolean;
  onSave: (data: SettingsUpdate) => void;
}

function AddressField({
  stored,
  enabled,
  isSaving,
  onSave,
}: AddressFieldProps) {
  const { t } = useTranslation();
  // A draft rather than a mirror of `settings`: the address is saved by its
  // own button, not on every keystroke.
  const [address, setAddress] = useState(stored);
  const draft = address.trim();

  return (
    <div className="mt-4 space-y-1.5">
      <label
        htmlFor="oai-harvest-base-url"
        className="block text-xs font-medium text-paper-600 dark:text-paper-300"
      >
        {t("harvest.addressLabel")}
      </label>
      <input
        id="oai-harvest-base-url"
        type="url"
        autoComplete="off"
        value={address}
        onChange={(event) => setAddress(event.target.value)}
        className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
      />
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("harvest.addressHint")}
      </p>
      {draft !== stored && (
        <Button
          size="sm"
          disabled={isSaving || (enabled && draft === "")}
          onClick={() => onSave({ oai_harvest_base_url: draft })}
        >
          {t("harvest.addressSave")}
        </Button>
      )}
    </div>
  );
}
