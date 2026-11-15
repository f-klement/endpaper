import { useState } from "react";

import type {
  Locale,
  ReadwiseAccountOut,
  ReadwiseOutcome,
} from "../../../../api/generated/model";
import { Button, ErrorState, Spinner } from "../../../../components";
import {
  useTranslation,
  type MessageKey,
  type Translate,
} from "../../../../i18n";
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
  // Held here rather than in a part below, so a typed token survives the card
  // falling back to a spinner or an error and coming back.
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
      <Verbs
        state={state}
        hasToken={account.has_token}
        token={token}
        onSaved={() => setToken("")}
      />
      <p role="status" className="text-sm text-paper-800 dark:text-paper-200">
        {lastRun(account, t, locale)}
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
      <WaitingBooks account={account} />
      <Failures state={state} />
    </div>
  );
}

interface VerbsProps {
  state: UseReadwiseAccountResult;
  hasToken: boolean;
  token: string;
  onSaved: () => void;
}

/**
 * Save, and once a token is saved, fetch and remove.
 *
 * Fetch and remove are held while a save or a fetch is in flight, so a remove
 * cannot land in the middle of a save and a fetch cannot start on a token being
 * replaced. Save is held by its own save, and by an empty field.
 */
function Verbs({ state, hasToken, token, onSaved }: VerbsProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap gap-2">
      <Button
        size="sm"
        onClick={() => state.save(token.trim(), onSaved)}
        isLoading={state.isSaving}
        disabled={state.isSaving || token.trim() === ""}
      >
        {hasToken ? t("readwise.replace") : t("readwise.save")}
      </Button>
      {hasToken && (
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
  );
}

/**
 * What the status line says: no token, a token not yet run, or the last run.
 *
 * A run is named only once both its date and its outcome are known; either
 * alone reads as "not yet".
 */
function lastRun(
  account: ReadwiseAccountOut,
  t: Translate,
  locale: Locale,
): string {
  if (!account.has_token) return t("readwise.none");
  if (account.last_run_at == null || account.last_outcome == null)
    return t("readwise.notYet");
  return t("readwise.lastRun", {
    date: numericDate(account.last_run_at, locale),
    outcome: t(OUTCOMES[account.last_outcome]),
  });
}

/** The Readwise books no book here matched, or nothing when there are none. */
function WaitingBooks({ account }: { account: ReadwiseAccountOut }) {
  const { t } = useTranslation();
  if (account.waiting_count <= 0) return null;
  return (
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
  );
}

/** A failed save and a failed fetch, each in its own words. */
function Failures({ state }: { state: UseReadwiseAccountResult }) {
  const { t } = useTranslation();
  return (
    <>
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
    </>
  );
}
