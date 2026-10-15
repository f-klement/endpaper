import { useState } from "react";

import type { ReadwiseOutcome } from "../../../../api/generated/model";
import { Button, ErrorState, Spinner } from "../../../../components";
import { useTranslation, type MessageKey } from "../../../../i18n";
import { numericDate } from "../../../../lib/date";
import type { UseReadwiseAccountResult } from "../hooks";

interface ReadwiseAccountProps {
  state: UseReadwiseAccountResult;
}

const OUTCOMES: Record<ReadwiseOutcome, MessageKey> = {
  synced: "readwise.outcome.synced",
  incomplete: "readwise.outcome.incomplete",
  token_refused: "readwise.outcome.tokenRefused",
  rate_limited: "readwise.outcome.rateLimited",
  unavailable: "readwise.outcome.unavailable",
  unreadable: "readwise.outcome.unreadable",
};

/**
 * The member's Readwise token, the pull it allows, and what waits for a book.
 *
 * **The token field is always empty**: the server never sends a token back, so
 * an empty box is not "no token" and saving replaces whatever is stored. The
 * books listed are Readwise books no book here matched; their highlights
 * arrive once the book is in the library. Presentational.
 */
export default function ReadwiseAccount({ state }: ReadwiseAccountProps) {
  const { t, locale } = useTranslation();
  const [token, setToken] = useState("");
  const { account, synced } = state;

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
        {t("readwise.hint")}
      </p>
      <label
        htmlFor="readwise-token"
        className="block text-xs font-medium text-paper-600 dark:text-paper-300"
      >
        {t("readwise.token")}
      </label>
      <input
        id="readwise-token"
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={token}
        onChange={(event) => setToken(event.target.value)}
        className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
      />
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={() => state.save(token.trim(), () => setToken(""))}
          isLoading={state.isSaving}
          disabled={state.isSaving || token.trim() === ""}
        >
          {account.has_token ? t("readwise.replace") : t("readwise.save")}
        </Button>
        {account.has_token && (
          <>
            <Button
              size="sm"
              variant="secondary"
              onClick={state.sync}
              isLoading={state.isSyncing}
              disabled={state.isSyncing || state.isSaving}
            >
              {t("readwise.sync")}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={state.remove}
              disabled={state.isSaving || state.isSyncing}
            >
              {t("readwise.remove")}
            </Button>
          </>
        )}
      </div>
      <p role="status" className="text-sm text-paper-800 dark:text-paper-200">
        {!account.has_token
          ? t("readwise.none")
          : account.last_run_at == null || account.last_outcome == null
            ? t("readwise.notYet")
            : t("readwise.lastRun", {
                date: numericDate(account.last_run_at, locale),
                outcome: t(OUTCOMES[account.last_outcome]),
              })}
      </p>
      {synced !== undefined && (
        <p className="text-sm text-paper-800 dark:text-paper-200">
          {t("readwise.pulled", {
            created: synced.created,
            updated: synced.updated,
            deleted: synced.deleted,
          })}
        </p>
      )}
      {account.waiting_count > 0 && (
        <div className="space-y-1">
          <p className="text-sm text-paper-800 dark:text-paper-200">
            {t("readwise.waiting", { count: account.waiting_count })}
          </p>
          <ul className="text-sm list-disc pl-5">
            {/* Keyed on what is shown rather than on the position. Two
                Readwise books sharing a title and author would share a key,
                which React warns about and still renders. */}
            {account.waiting.map((book) => (
              <li key={`${book.title}\u0000${book.author ?? ""}`}>
                {book.author == null
                  ? book.title
                  : t("readwise.waitingBook", {
                      title: book.title,
                      author: book.author,
                    })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {state.saveError != null && (
        <ErrorState
          error={state.saveError}
          fallback={t("readwise.couldNotSave")}
        />
      )}
      {state.syncError != null && (
        <ErrorState
          error={state.syncError}
          fallback={t("readwise.couldNotSync")}
        />
      )}
    </div>
  );
}
