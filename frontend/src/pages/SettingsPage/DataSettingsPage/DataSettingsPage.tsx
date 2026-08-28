import type { AuthMode, UserOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import AdminSettings from "../components/AdminSettings";
import SettingsSubPage from "../components/SettingsSubPage";
import { useSettings } from "../hooks";
import BackupSection from "./components/BackupSection";
import TestAccounts from "./components/TestAccounts";
import { useBackup, useSwitchToTestAccount, useTestAccounts } from "./hooks";

interface DataSettingsPageProps {
  /** Which sentence the test accounts card uses to say how to get back. */
  mode: AuthMode;
  /**
   * A switch lands here: it is a sign-in on another account, so it goes
   * through the same handler the login form uses.
   */
  onSignIn: (user: UserOut, token: string) => void;
}

/**
 * The library's data, and the accounts for looking at it.
 *
 * The weakest of the six groupings, and it is recorded as such rather than
 * argued into soundness: an archive and a preview account share only that an
 * admin is the one who touches them. The owner settled it there on 2026-08-27,
 * and `testAccounts` is the row to reconsider if this screen ever needs a third
 * card to justify itself.
 *
 * Under a directory, a test account is the only way an admin can see what an
 * ordinary member sees: registration is refused and nobody's directory password
 * is ours to type.
 */
export default function DataSettingsPage({
  mode,
  onSignIn,
}: DataSettingsPageProps) {
  const { t } = useTranslation();
  const state = useSettings();
  const backup = useBackup();
  // The settings record answering at all is what says this account is an
  // admin, and the test accounts endpoint is admin only, so asking without
  // that flag would be a 403 on every visit by every member.
  const testAccounts = useTestAccounts(state.settings !== undefined);
  const switching = useSwitchToTestAccount(onSignIn);

  return (
    <SettingsSubPage icon="inbox" title={t("settings.data.title")}>
      <AdminSettings state={state}>
        {() => (
          <>
            <BackupSection
              isDownloading={backup.isDownloading}
              downloadError={backup.downloadError}
              onDownload={backup.download}
              isRestoring={backup.isRestoring}
              restoreError={backup.restoreError}
              restored={backup.restored}
              onRestore={backup.restore}
            />

            <SettingsSection title={t("settings.testAccounts")} icon="user">
              <TestAccounts
                accounts={testAccounts.accounts}
                isLoading={testAccounts.isLoading}
                error={testAccounts.error}
                onCreate={testAccounts.create}
                isCreating={testAccounts.isCreating}
                createError={testAccounts.createError}
                onSwitch={switching.switchTo}
                isSwitching={switching.isSwitching}
                switchError={switching.switchError}
                mode={mode}
              />
            </SettingsSection>
          </>
        )}
      </AdminSettings>
    </SettingsSubPage>
  );
}
