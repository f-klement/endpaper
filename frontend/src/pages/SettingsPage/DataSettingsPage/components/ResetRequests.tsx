import type { ResetRequestOut } from "../../../../api/generated/model";
import { Button, ErrorState, Spinner } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import type { ApprovedCode } from "../hooks";

interface ResetRequestsProps {
  requests: ResetRequestOut[];
  isLoading: boolean;
  error: unknown;
  /** The code an approval produced, by member id. Shown once, never fetched. */
  codes: Record<number, ApprovedCode>;
  onApprove: (userId: number) => void;
  onDecline: (userId: number) => void;
  isWorking: boolean;
  actionError: unknown;
}

/**
 * The members waiting to be let back in.
 *
 * **There is no control here that starts a reset, and there is no endpoint for
 * one.** An admin approves a request a member made, which is what separates a
 * recovery flow from a way into somebody's account, and the absence is
 * structural rather than a screen that declines to draw a button.
 *
 * The code is shown once, in place, because that is the only time it exists:
 * the server keeps a hash. The sentence beside it says so, so an admin reads it
 * out now rather than expecting to come back for it.
 *
 * Presentational. Every refusal is the server's.
 */
export default function ResetRequests({
  requests,
  isLoading,
  error,
  codes,
  onApprove,
  onDecline,
  isWorking,
  actionError,
}: ResetRequestsProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("settings.resetRequestsHint")}
      </p>

      {isLoading && <Spinner label={t("common.loading")} />}
      {error != null && (
        <ErrorState error={error} fallback={t("settings.couldNotLoad")} />
      )}
      {actionError != null && (
        <ErrorState
          error={actionError}
          fallback={t("settings.resetRequestsFailed")}
        />
      )}

      {!isLoading && requests.length === 0 && (
        <p className="text-sm text-paper-600 dark:text-paper-400">
          {t("settings.resetRequestsEmpty")}
        </p>
      )}

      <ul className="space-y-3">
        {requests.map((request) => {
          const approved = codes[request.user_id];
          return (
            <li
              key={request.user_id}
              className="rounded-lg border border-paper-100 p-3 dark:border-paper-800"
            >
              <p className="text-sm font-medium text-paper-900 dark:text-paper-100">
                {request.username}
              </p>
              <p className="text-xs text-paper-600 dark:text-paper-400">
                {t("settings.resetRequestsAsked", {
                  date: new Date(request.requested_at).toLocaleDateString(),
                })}
              </p>
              {request.approved_by && (
                <p className="text-xs text-paper-600 dark:text-paper-400">
                  {t("settings.resetRequestsApprovedBy", {
                    name: request.approved_by,
                  })}
                </p>
              )}
              {/* The queue's own copy of the expiry, which is what an admin
                  has after a reload: the code itself lives in component state
                  and is gone, so without this a request approved before the
                  page was refreshed says who granted it and nothing about when
                  it stops working. Hidden while the code is on screen, which
                  carries the same time in its own sentence. */}
              {request.code_expires_at && !approved && (
                <p className="text-xs text-paper-600 dark:text-paper-400">
                  {t("settings.resetRequestsCodeExpires", {
                    time: new Date(
                      request.code_expires_at,
                    ).toLocaleTimeString(),
                  })}
                </p>
              )}

              {approved && (
                <div className="mt-2 rounded-lg bg-paper-50 p-3 dark:bg-paper-800">
                  <p className="font-mono text-lg tracking-widest text-paper-900 dark:text-paper-100">
                    {approved.code}
                  </p>
                  <p className="mt-1 text-xs text-paper-600 dark:text-paper-400">
                    {/* The **served** expiry, not a lifetime written into the
                      sentence: the server owns how long a code lives, and a
                      string saying "an hour" is a second copy that stops being
                      true when the constant moves. */}
                    {t("settings.resetRequestsCodeFor", {
                      name: request.username,
                      time: new Date(approved.expiresAt).toLocaleTimeString(),
                    })}
                  </p>
                </div>
              )}

              <div className="mt-3 flex gap-2">
                <Button
                  onClick={() => onApprove(request.user_id)}
                  disabled={isWorking}
                  aria-label={t("settings.resetRequestsApproveFor", {
                    name: request.username,
                  })}
                >
                  {t("settings.resetRequestsApprove")}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => onDecline(request.user_id)}
                  disabled={isWorking}
                  aria-label={t("settings.resetRequestsDeclineFor", {
                    name: request.username,
                  })}
                >
                  {t("settings.resetRequestsDecline")}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
