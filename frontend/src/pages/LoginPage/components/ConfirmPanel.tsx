import { useState, type FormEvent } from "react";

import { ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";
import type { UseAddressConfirmationResult } from "../hooks";

interface ConfirmPanelProps {
  state: UseAddressConfirmationResult;
  onBack: () => void;
}

/**
 * Returning the code that was sent to an address.
 *
 * One username field for both actions, because they are the same account and
 * asking twice on one card would read as two unrelated forms. The resend is a
 * secondary control rather than a second form: it is what somebody presses when
 * nothing arrived.
 *
 * Presentational, and every message it can show says the same thing whether or
 * not the account exists.
 */
export default function ConfirmPanel({ state, onBack }: ConfirmPanelProps) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [code, setCode] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    state.confirm(username.trim(), code);
  }

  return (
    <div className="bg-paper-0 rounded-2xl shadow-sm border border-paper-100 p-6 space-y-4 dark:bg-paper-900 dark:border-paper-800">
      <div>
        <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100">
          {t("verify.title")}
        </h2>
        <p className="mt-1 text-xs text-paper-600 dark:text-paper-400">
          {t("verify.intro")}
        </p>
      </div>

      <form onSubmit={submit} className="space-y-3">
        <div>
          <label
            htmlFor="confirm-username"
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
          >
            {t("login.username")}
          </label>
          <input
            id="confirm-username"
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
            autoComplete="username"
            className="w-full px-3 py-2.5 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
            placeholder={t("login.usernamePlaceholder")}
          />
        </div>
        <div>
          <label
            htmlFor="confirm-code"
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
          >
            {t("recovery.codeLabel")}
          </label>
          <input
            id="confirm-code"
            type="text"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            required
            // See RecoveryPanel: a one time code is never worth remembering.
            autoComplete="off"
            spellCheck={false}
            className="w-full px-3 py-2.5 rounded-lg border border-paper-200 text-sm font-mono tracking-wider dark:border-paper-700"
            placeholder={t("recovery.codePlaceholder")}
          />
        </div>

        {state.confirmError != null && (
          <ErrorState
            error={state.confirmError}
            fallback={t("verify.failed")}
          />
        )}
        {state.hasConfirmed && state.confirmError == null && (
          <p
            role="status"
            className="text-sm text-green-800 dark:text-green-400"
          >
            {t("verify.done")}
          </p>
        )}
        {state.hasResent && state.resendError == null && (
          <p
            role="status"
            className="text-sm text-paper-700 dark:text-paper-300"
          >
            {t("verify.resent")}
          </p>
        )}

        <button
          type="submit"
          disabled={state.isConfirming}
          className="w-full py-2.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent font-semibold rounded-lg transition-colors text-sm"
        >
          {state.isConfirming ? t("login.pleaseWait") : t("verify.submit")}
        </button>
      </form>

      <button
        type="button"
        onClick={() => state.resend(username.trim())}
        disabled={state.isResending || username.trim() === ""}
        className="w-full text-sm font-medium text-accent-700 disabled:opacity-50 dark:text-accent-300"
      >
        {t("verify.resend")}
      </button>
      <button
        type="button"
        onClick={onBack}
        className="w-full text-sm font-medium text-accent-700 dark:text-accent-300"
      >
        {t("login.backToSignIn")}
      </button>
    </div>
  );
}
