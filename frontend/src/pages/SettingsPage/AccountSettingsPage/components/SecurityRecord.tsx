import {
  VerificationProvenance,
  type MySecurityOut,
} from "../../../../api/generated/model";
import { ErrorState, Spinner } from "../../../../components";
import { useTranslation, type Translate } from "../../../../i18n";

interface SecurityRecordProps {
  security: MySecurityOut | undefined;
  isLoading: boolean;
  error: unknown;
}

/**
 * What has happened to this account, and who did it.
 *
 * **The member's half of an admin confirmed reset, and it is the property that
 * makes the whole flow acceptable.** An admin approving a reset is by
 * construction a way into somebody's account; what stops it being a quiet one
 * is that the account says so afterwards, permanently, with the approver's
 * name. The sentence is present whether or not anything happened, because a
 * screen that only appeared after a reset would be one nobody had ever seen and
 * so nobody would miss.
 *
 * Presentational.
 */
export default function SecurityRecord({
  security,
  isLoading,
  error,
}: SecurityRecordProps) {
  const { t } = useTranslation();

  if (isLoading) {
    return <Spinner label={t("common.loading")} />;
  }
  if (error != null) {
    return <ErrorState error={error} fallback={t("settings.couldNotLoad")} />;
  }
  if (security === undefined) {
    return null;
  }

  const resetOn = security.password_reset_at;
  const approver = security.password_reset_approved_by;

  return (
    <div className="space-y-2">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("account.security.hint")}
      </p>
      <p className="text-sm text-paper-800 dark:text-paper-200">
        {resetOn == null
          ? t("account.security.noReset")
          : approver == null
            ? // An approver whose account is gone. The date is still the fact
              // that matters, so it is said without a name rather than not at
              // all.
              t("account.security.resetUnknown", {
                date: new Date(resetOn).toLocaleDateString(),
              })
            : t("account.security.reset", {
                date: new Date(resetOn).toLocaleDateString(),
                name: approver,
              })}
      </p>
      <p className="text-sm text-paper-800 dark:text-paper-200">
        {/* One sentence per provenance, and the directory arm is here because
            the admin screen has one: two components mapping the same closed set
            with different coverage is how a member gets told nobody asked them
            for an address their directory supplies. */}
        {confirmation(security, t)}
      </p>
    </div>
  );
}

/** What settled this account's address, in one sentence. */
function confirmation(security: MySecurityOut, t: Translate): string {
  switch (security.verification_source) {
    case VerificationProvenance.admin:
      return t("account.security.confirmedBy", {
        name: security.verified_by ?? "",
      });
    case VerificationProvenance.email:
      return t("account.security.confirmedByEmail");
    case VerificationProvenance.directory:
      return t("account.security.directory");
    default:
      return t("account.security.notAsked");
  }
}
