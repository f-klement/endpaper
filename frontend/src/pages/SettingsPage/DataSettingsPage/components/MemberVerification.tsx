import {
  VerificationProvenance,
  type MemberVerificationOut,
} from "../../../../api/generated/model";
import { Button, ErrorState, Spinner } from "../../../../components";
import { useTranslation, type Translate } from "../../../../i18n";

interface MemberVerificationProps {
  members: MemberVerificationOut[];
  isLoading: boolean;
  error: unknown;
  onConfirm: (userId: number) => void;
  isConfirming: boolean;
  confirmError: unknown;
}

/**
 * Every account's confirmation state, and the override.
 *
 * **The override is the reason an unconfirmed account may do nothing.** A
 * confirmation step completable only by receiving mail cannot be completed at
 * all by a household with no mail server, which is the ordinary configuration
 * here, so this list is the primary path for some libraries and the exception
 * for others.
 *
 * The whole list rather than the unconfirmed rows, so an admin can see that a
 * directory account is not waiting on them and that a confirmed one carries who
 * confirmed it. **It shows no address**, only whether there is one: a code
 * cannot be sent without one, which is what an admin needs to know here, and
 * the addresses themselves live on the account screen.
 *
 * Presentational.
 */
export default function MemberVerification({
  members,
  isLoading,
  error,
  onConfirm,
  isConfirming,
  confirmError,
}: MemberVerificationProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("settings.verificationHint")}
      </p>

      {isLoading && <Spinner label={t("common.loading")} />}
      {error != null && (
        <ErrorState error={error} fallback={t("settings.couldNotLoad")} />
      )}
      {confirmError != null && (
        <ErrorState
          error={confirmError}
          fallback={t("settings.verificationFailed")}
        />
      )}

      <ul className="space-y-2">
        {members.map((member) => (
          <li
            key={member.id}
            className="flex items-center gap-3 rounded-lg border border-paper-100 p-3 dark:border-paper-800"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-paper-900 dark:text-paper-100">
                {member.username}
              </span>
              <span className="block text-xs text-paper-600 dark:text-paper-400">
                {describe(member, t)}
              </span>
              {member.verified_at === null && !member.has_address && (
                <span className="block text-xs text-paper-600 dark:text-paper-400">
                  {t("settings.verificationNoAddress")}
                </span>
              )}
            </span>
            {member.applies && member.verified_at === null && (
              <Button
                onClick={() => onConfirm(member.id)}
                disabled={isConfirming}
                aria-label={t("settings.verificationConfirmFor", {
                  name: member.username,
                })}
              >
                {t("settings.verificationConfirm")}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * One sentence for one row's state.
 *
 * A function rather than a lookup table keyed on the provenance, because two of
 * the five sentences are not about the provenance at all: an account nothing
 * confirmed has none, and a directory account is described by what authenticated
 * it rather than by what confirmed it.
 */
function describe(member: MemberVerificationOut, t: Translate): string {
  if (!member.applies) {
    return t("settings.verificationElsewhere");
  }
  if (member.verified_at === null) {
    return t("settings.verificationWaiting");
  }
  if (member.verification_source === VerificationProvenance.admin) {
    return t("settings.verificationBySomebody", {
      name: member.verified_by ?? "",
    });
  }
  if (member.verification_source === VerificationProvenance.email) {
    return t("settings.verificationByEmail");
  }
  return t("settings.verificationNotAsked");
}
