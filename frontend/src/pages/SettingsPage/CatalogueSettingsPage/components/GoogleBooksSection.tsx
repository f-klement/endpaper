import { useState } from "react";

import type {
  SettingsOut,
  SettingsUpdate,
} from "../../../../api/generated/model";
import { HelpButton } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import GoogleBooksHelp from "../../../components/GoogleBooksHelp";
import { SettingsSection } from "../../../components";
import SecretField from "../../components/SecretField";
import ToggleField from "../../components/ToggleField";

interface GoogleBooksSectionProps {
  settings: SettingsOut;
  isSaving: boolean;
  onSave: (patch: SettingsUpdate) => void;
}

/**
 * The lookup toggle and the key it needs.
 *
 * The key is a write only `SecretField`, which says what that means. A key
 * managed through the environment is shown as such and the field is disabled,
 * because there is nothing here to edit and nothing to unmask.
 */
export default function GoogleBooksSection({
  settings,
  isSaving,
  onSave,
}: GoogleBooksSectionProps) {
  const { t } = useTranslation();
  const [showHelp, setShowHelp] = useState(false);

  return (
    <SettingsSection title={t("settings.googleBooks")} icon="search">
      <ToggleField
        label={t("settings.googleBooksEnable")}
        hint={t("settings.googleBooksHint")}
        checked={settings.google_books_enabled}
        disabled={isSaving}
        onChange={(checked) => onSave({ google_books_enabled: checked })}
      />

      <SecretField
        id="google-books-key"
        label={t("settings.apiKey")}
        labelAside={
          <HelpButton
            label={t("settings.apiKeyHelp")}
            onClick={() => setShowHelp(true)}
          />
        }
        placeholder={t("settings.apiKeyPlaceholder")}
        // The shared labels where the other secrets name their own: this is
        // the only reveal button on its page, so none needs telling apart.
        showLabel={t("field.show")}
        hideLabel={t("field.hide")}
        status={
          settings.has_google_books_api_key
            ? t("settings.apiKeySet", {
                preview: settings.google_books_api_key_preview,
              })
            : t("settings.apiKeyMissing")
        }
        saveLabel={t("common.save")}
        clearLabel={t("settings.apiKeyClear")}
        hasStored={settings.has_google_books_api_key}
        pinned={settings.google_books_api_key_from_env === true}
        pinnedNotice={
          <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-200 dark:bg-amber-950 dark:border-amber-900">
            {t("settings.apiKeyFromEnv")}
          </p>
        }
        isSaving={isSaving}
        onSave={(value) => onSave({ google_books_api_key: value })}
        // An empty string clears it; `undefined` would mean "leave alone",
        // which is the opposite.
        onClear={() => onSave({ google_books_api_key: "" })}
      >
        <p className="text-xs text-paper-600 leading-relaxed pt-1 dark:text-paper-400">
          {t("settings.apiKeyHint")}
        </p>
      </SecretField>

      {showHelp && (
        <GoogleBooksHelp
          isUnconfigured={!settings.has_google_books_api_key}
          onClose={() => setShowHelp(false)}
        />
      )}
    </SettingsSection>
  );
}
