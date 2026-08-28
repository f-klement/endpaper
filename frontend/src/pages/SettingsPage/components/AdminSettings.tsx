import type { ReactNode } from "react";

import type { SettingsOut } from "../../../api/generated/model";
import { ErrorState, Spinner } from "../../../components";
import { useTranslation } from "../../../i18n";
import type { UseSettingsResult } from "../hooks";

interface AdminSettingsProps {
  state: UseSettingsResult;
  /** Rendered only once the record is in hand, so nothing has to guard it. */
  children: (settings: SettingsOut) => ReactNode;
}

/**
 * The admin gate and the save banner, in one place.
 *
 * Four of the six settings routes read and write the same server record, and
 * every one of them needs the same four states around it: loading, refused,
 * failed, and saved. Written out per route that is four copies of a
 * distinction that is easy to get subtly wrong, and one of them is not
 * cosmetic: **a 403 is a legitimate answer here, not a failure.** The settings
 * endpoint is admin only, every member reaches these screens, and rendering an
 * error page at somebody who simply is not an admin is the wrong sentence.
 *
 * The children are a function of the record rather than a node, so a caller
 * never holds a possibly-undefined `settings` and there is nothing to narrow.
 */
export default function AdminSettings({ state, children }: AdminSettingsProps) {
  const { t } = useTranslation();

  return (
    <>
      {state.isLoading && <Spinner label={t("common.loading")} />}

      {state.isForbidden && (
        <p className="text-sm text-paper-600 text-center dark:text-paper-400">
          {t("settings.adminOnly")}
        </p>
      )}

      {state.error != null && !state.isForbidden && (
        <ErrorState error={state.error} fallback={t("settings.couldNotLoad")} />
      )}

      {state.settings && children(state.settings)}

      {state.saveError != null && (
        <ErrorState
          error={state.saveError}
          fallback={t("common.somethingWentWrong")}
        />
      )}
      {state.hasSaved && state.saveError == null && (
        <p
          role="status"
          className="text-sm text-green-800 text-center dark:text-green-400"
        >
          {t("settings.saved")}
        </p>
      )}
    </>
  );
}
