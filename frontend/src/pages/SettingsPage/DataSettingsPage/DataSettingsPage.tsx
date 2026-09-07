import type { AuthMode, UserOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import AdminSettings from "../components/AdminSettings";
import SettingsSubPage from "../components/SettingsSubPage";
import { useSettings } from "../hooks";
import ToggleField from "../components/ToggleField";
import BackupSection from "./components/BackupSection";
import MemberVerification from "./components/MemberVerification";
import ResetRequests from "./components/ResetRequests";
import TestAccounts from "./components/TestAccounts";
import {
  useBackup,
  useMemberVerification,
  useResetOffered,
  useResetRequests,
  useSwitchToTestAccount,
  useTestAccounts,
} from "./hooks";

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
  // The same `enabled` and the same reason: both endpoints are admin only, so
  // asking without the flag is a 403 on every visit by every member.
  // **Both conditions, and the second is the server's answer rather than a
  // derivation from `mode`.** Under ldap or proxy this app holds no password, so
  // every request is refused at the route and the queue could only ever be
  // empty beside a hint describing a mechanism that cannot run. `/auth/config`
  // already publishes the fact for the login page, so reading it here is one
  // source rather than two.
  const offersReset = useResetOffered();
  const resets = useResetRequests(state.settings !== undefined && offersReset);
  const verification = useMemberVerification(state.settings !== undefined);

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

            {/* Before the two lists it governs, because it is what decides
                whether either has anything in it: a household that has not
                turned this on confirms nothing and sees an empty list. */}
            <SettingsSection title={t("settings.verification")} icon="user">
              <ToggleField
                label={t("settings.openToOutsiders")}
                hint={t("settings.openToOutsidersHint")}
                checked={state.settings?.accounts_open_to_outsiders ?? false}
                disabled={state.isSaving}
                onChange={(checked) =>
                  state.save({ accounts_open_to_outsiders: checked })
                }
              />
              <MemberVerification
                members={verification.members}
                isLoading={verification.isLoading}
                error={verification.error}
                onConfirm={verification.confirm}
                isConfirming={verification.isConfirming}
                confirmError={verification.confirmError}
              />
            </SettingsSection>

            {offersReset && (
              <SettingsSection title={t("settings.resetRequests")} icon="user">
                <ResetRequests
                  requests={resets.requests}
                  isLoading={resets.isLoading}
                  error={resets.error}
                  codes={resets.codes}
                  onApprove={resets.approve}
                  onDecline={resets.decline}
                  isWorking={resets.isWorking}
                  actionError={resets.actionError}
                />
              </SettingsSection>
            )}

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
