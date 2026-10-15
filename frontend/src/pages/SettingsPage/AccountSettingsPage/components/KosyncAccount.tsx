import { Button, ErrorState, Spinner } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import { numericDate } from "../../../../lib/date";
import type { UseKosyncAccountResult } from "../hooks";

interface KosyncAccountProps {
  state: UseKosyncAccountResult;
}

/**
 * What a member types into KOReader, and the password that signs it in.
 *
 * **The password is shown once, the moment it is made**, because the server
 * keeps only a digest of it. Making another replaces it and signs every device
 * using the old one out, which is also how a lost device is shut out.
 *
 * The inbox is counted here and linked from each book's page, where the book
 * is already chosen. Presentational.
 */
export default function KosyncAccount({ state }: KosyncAccountProps) {
  const { t, locale } = useTranslation();
  const { account, minted } = state;

  if (state.isLoading) return <Spinner label={t("common.loading")} />;
  if (state.error != null) {
    return (
      <ErrorState error={state.error} fallback={t("settings.couldNotLoad")} />
    );
  }
  if (account === undefined) return null;

  return (
    <div className="space-y-3">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("kosync.hint")}
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-paper-600 dark:text-paper-400">
          {t("kosync.server")}
        </dt>
        <dd className="font-mono break-all">{state.server}</dd>
        <dt className="text-paper-600 dark:text-paper-400">
          {t("kosync.username")}
        </dt>
        <dd className="font-mono break-all">{account.username}</dd>
        {minted !== undefined && (
          <>
            <dt className="text-paper-600 dark:text-paper-400">
              {t("kosync.password")}
            </dt>
            <dd className="font-mono break-all">{minted.password}</dd>
          </>
        )}
      </dl>
      <p role="status" className="text-sm text-paper-800 dark:text-paper-200">
        {minted !== undefined
          ? t("kosync.shownOnce")
          : account.password_set_at == null
            ? t("kosync.none")
            : t("kosync.since", {
                date: numericDate(account.password_set_at, locale),
              })}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={state.mint}
          isLoading={state.isSaving}
          disabled={state.isSaving}
        >
          {account.has_password ? t("kosync.remint") : t("kosync.mint")}
        </Button>
        {account.has_password && (
          <Button
            size="sm"
            variant="secondary"
            onClick={state.revoke}
            disabled={state.isSaving}
          >
            {t("kosync.revoke")}
          </Button>
        )}
      </div>
      {state.waiting > 0 && (
        <p className="text-sm text-paper-800 dark:text-paper-200">
          {t("kosync.waiting", { count: state.waiting })}
        </p>
      )}
      {state.saveError != null && (
        <ErrorState
          error={state.saveError}
          fallback={t("kosync.couldNotSave")}
        />
      )}
    </div>
  );
}
