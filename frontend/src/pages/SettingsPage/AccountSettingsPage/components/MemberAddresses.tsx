import { ErrorState, Spinner } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import { SettingsSection } from "../../../components";
import type { UseMemberEmailsResult } from "../hooks";
import AddressField from "./AddressField";

interface MemberAddressesProps {
  state: UseMemberEmailsResult;
}

/**
 * Every member's address, for an admin.
 *
 * **A member is shown nothing at all here, not a refusal**, and that is the one
 * place this screen differs from the other settings pages. `AdminSettings`
 * draws "only an admin can change these" beside the section it is refusing,
 * which is right where the section is a library setting somebody might expect
 * to change. Here the section is *other people's addresses*, and announcing its
 * existence to every member is the disclosure the feature was scoped to avoid.
 * The endpoint answers 403 regardless; this decides what is drawn.
 *
 * The list is not a place to look up a colleague's address. It is where an
 * admin finds the empty row, or the typo, when somebody's reminders go nowhere:
 * `#82`'s delivery record says a send failed and cannot say the address is
 * wrong.
 */
export default function MemberAddresses({ state }: MemberAddressesProps) {
  const { t } = useTranslation();

  // Two ways to draw nothing, and they are different facts. `isOffered` is
  // false when the caller is not an admin and the request was therefore never
  // made; `isForbidden` is the server having said so anyway, which is what a
  // stale session prop looks like. Both end here, and neither says a word.
  if (!state.isOffered || state.isForbidden) return null;
  if (state.isLoading) return <Spinner label={t("common.loading")} />;
  if (state.error != null)
    return (
      <ErrorState error={state.error} fallback={t("settings.couldNotLoad")} />
    );
  if (!state.members) return null;

  return (
    <SettingsSection title={t("account.members.title")} icon="user">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("account.members.hint")}
      </p>
      {state.members.map((member) => (
        <AddressField
          key={member.id}
          member={member}
          label={member.username}
          disabled={state.isSaving}
          onSave={(email) => state.save(member.id, email)}
        />
      ))}
      {state.isDirectoryOwned && (
        <p role="status" className="text-sm text-paper-700 dark:text-paper-300">
          {t("account.email.directoryRefused")}
        </p>
      )}
      {state.saveError != null && !state.isDirectoryOwned && (
        <ErrorState
          error={state.saveError}
          fallback={t("account.email.couldNotSave")}
        />
      )}
      {state.hasSaved && state.saveError == null && (
        <p role="status" className="text-sm text-green-800 dark:text-green-400">
          {t("settings.saved")}
        </p>
      )}
    </SettingsSection>
  );
}
