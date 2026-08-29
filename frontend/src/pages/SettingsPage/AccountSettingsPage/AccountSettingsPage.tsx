import type { UserOut } from "../../../api/generated/model";
import { ErrorState, Spinner } from "../../../components";
import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import SettingsSubPage from "../components/SettingsSubPage";
import AddressField from "./components/AddressField";
import MemberAddresses from "./components/MemberAddresses";
import { useMemberEmails, useMyEmail } from "./hooks";

interface AccountSettingsPageProps {
  /**
   * The session's account, never the cached one.
   *
   * The same prop and the same reason as `SettingsPage`: under proxy auth
   * `localStorage["user"]` is written only by a switch into a test account, so
   * it is null for a proxy admin always. Here it decides whether the admin list
   * is **requested**, not whether it is allowed: `require_admin` decides that.
   */
  currentUser: UserOut;
}

/**
 * The member's own account, which today is one field.
 *
 * A route of its own rather than a section on an existing screen, because none
 * of the six fits: Appearance is what the app looks like, and Data and accounts
 * is admin only, so a member would not reach their own address there. The issue
 * this ships called it "the account page" for the same reason.
 *
 * **Nothing sends to this address yet.** The mail reminder still goes to the
 * household mailbox, so the hint says what the field is for rather than
 * implying a reminder will arrive. Saying nothing would leave a field with no
 * visible effect, which reads as broken.
 */
export default function AccountSettingsPage({
  currentUser,
}: AccountSettingsPageProps) {
  const { t } = useTranslation();
  const mine = useMyEmail();
  const members = useMemberEmails(currentUser.is_admin);

  return (
    <SettingsSubPage icon="user" title={t("settings.account.title")}>
      <SettingsSection title={t("account.email.title")} icon="user">
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("account.email.hint")}
        </p>

        {mine.isLoading && <Spinner label={t("common.loading")} />}
        {mine.error != null && (
          <ErrorState
            error={mine.error}
            fallback={t("settings.couldNotLoad")}
          />
        )}
        {mine.mine && (
          <AddressField
            member={mine.mine}
            label={t("account.email.yours")}
            disabled={mine.isSaving}
            onSave={mine.save}
          />
        )}

        {/* The 409 is explained rather than reported: nothing the member did is
            wrong, and the remedy is in the directory. */}
        {mine.isDirectoryOwned && (
          <p
            role="status"
            className="text-sm text-paper-700 dark:text-paper-300"
          >
            {t("account.email.directoryRefused")}
          </p>
        )}
        {mine.saveError != null && !mine.isDirectoryOwned && (
          <ErrorState
            error={mine.saveError}
            fallback={t("account.email.couldNotSave")}
          />
        )}
        {mine.hasSaved && mine.saveError == null && (
          <p
            role="status"
            className="text-sm text-green-800 dark:text-green-400"
          >
            {t("settings.saved")}
          </p>
        )}
      </SettingsSection>

      <MemberAddresses state={members} />
    </SettingsSubPage>
  );
}
