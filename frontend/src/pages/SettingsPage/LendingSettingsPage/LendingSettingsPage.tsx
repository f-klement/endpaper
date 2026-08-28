import { useTranslation } from "../../../i18n";
import AdminSettings from "../components/AdminSettings";
import SettingsSubPage from "../components/SettingsSubPage";
import { useSettings } from "../hooks";
import OverdueSection from "./components/OverdueSection";
import ReminderSendersSection from "./components/ReminderSendersSection";
import { useOverdueDigest } from "./hooks";

/**
 * Loans, and how somebody gets told about one that is late.
 *
 * Two cards, and they are one screen because neither is usable without the
 * other: the digest decides what is sent and when, and the senders decide where
 * it goes. Reading them on separate routes would let a household turn the
 * reminder on and never find out that nothing is configured to carry it.
 *
 * Admin only, both, so the whole body sits inside `AdminSettings`.
 */
export default function LendingSettingsPage() {
  const { t } = useTranslation();
  const state = useSettings();
  const overdue = useOverdueDigest();

  return (
    <SettingsSubPage icon="handshake" title={t("settings.lending.title")}>
      <AdminSettings state={state}>
        {(settings) => (
          <>
            <OverdueSection
              settings={settings}
              isSaving={state.isSaving}
              onSave={state.save}
              onSendNow={overdue.send}
              isSending={overdue.isSending}
              sendResult={overdue.result}
              sendError={overdue.error}
            />

            <ReminderSendersSection
              settings={settings}
              isSaving={state.isSaving}
              onSave={state.save}
            />
          </>
        )}
      </AdminSettings>
    </SettingsSubPage>
  );
}
