import { useState, type FormEvent } from "react";

import { ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";
import type { UseRecoveryResult } from "../hooks";

interface RecoveryPanelProps {
  state: UseRecoveryResult;
  onBack: () => void;
}

/**
 * Getting back into an account an admin has to approve.
 *
 * **Both halves on one card, deliberately.** The two are separated by a
 * telephone call rather than by a click, so a wizard that hid the second step
 * behind the first would strand somebody who already has a code and came back
 * to type it. The order on screen is the order in time, and neither half waits
 * on the other.
 *
 * Presentational. Every refusal here is the server's, and every message it can
 * produce says the same thing whether or not the account exists, which is what
 * keeps this form from being a way to read the household's roster.
 */
export default function RecoveryPanel({ state, onBack }: RecoveryPanelProps) {
  const { t } = useTranslation();
  const [askUsername, setAskUsername] = useState("");
  const [username, setUsername] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");

  function submitAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    state.ask(askUsername.trim());
  }

  function submitRedeem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    state.redeem(username.trim(), code, password);
  }

  return (
    <div className="bg-paper-0 rounded-2xl shadow-sm border border-paper-100 p-6 space-y-6 dark:bg-paper-900 dark:border-paper-800">
      <div>
        <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100">
          {t("recovery.title")}
        </h2>
        <p className="mt-1 text-xs text-paper-600 dark:text-paper-400">
          {t("recovery.intro")}
        </p>
      </div>

      <form onSubmit={submitAsk} className="space-y-3">
        <div>
          <label
            htmlFor="recovery-ask-username"
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
          >
            {t("login.username")}
          </label>
          <input
            id="recovery-ask-username"
            type="text"
            value={askUsername}
            onChange={(event) => setAskUsername(event.target.value)}
            required
            autoComplete="username"
            className="w-full px-3 py-2.5 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
            placeholder={t("login.usernamePlaceholder")}
          />
        </div>
        {state.askError != null && (
          <ErrorState error={state.askError} fallback={t("recovery.failed")} />
        )}
        {state.hasAsked && state.askError == null && (
          <p
            role="status"
            className="text-sm text-paper-700 dark:text-paper-300"
          >
            {t("recovery.asked")}
          </p>
        )}
        <button
          type="submit"
          disabled={state.isAsking}
          className="w-full py-2.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent font-semibold rounded-lg transition-colors text-sm"
        >
          {state.isAsking ? t("login.pleaseWait") : t("recovery.ask")}
        </button>
      </form>

      <hr className="border-paper-100 dark:border-paper-800" />

      <form onSubmit={submitRedeem} className="space-y-3">
        <div>
          <label
            htmlFor="recovery-username"
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
          >
            {t("login.username")}
          </label>
          <input
            id="recovery-username"
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
            htmlFor="recovery-code"
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
          >
            {t("recovery.codeLabel")}
          </label>
          <input
            id="recovery-code"
            type="text"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            required
            // Off, and not a slip: a one time code is never worth a browser
            // remembering, and a suggestion list under this field would be the
            // previous member's code offered to the next one on a shared
            // machine.
            autoComplete="off"
            spellCheck={false}
            className="w-full px-3 py-2.5 rounded-lg border border-paper-200 text-sm font-mono tracking-wider dark:border-paper-700"
            placeholder={t("recovery.codePlaceholder")}
          />
        </div>
        <div>
          <label
            htmlFor="recovery-password"
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
          >
            {t("recovery.newPassword")}
          </label>
          <input
            id="recovery-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            autoComplete="new-password"
            className="w-full px-3 py-2.5 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
            placeholder={t("recovery.newPasswordPlaceholder")}
          />
        </div>
        {state.redeemError != null && (
          <ErrorState
            error={state.redeemError}
            fallback={t("recovery.failed")}
          />
        )}
        {state.hasRedeemed && state.redeemError == null && (
          <p
            role="status"
            className="text-sm text-green-800 dark:text-green-400"
          >
            {t("recovery.done")}
          </p>
        )}
        <button
          type="submit"
          disabled={state.isRedeeming}
          className="w-full py-2.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent font-semibold rounded-lg transition-colors text-sm"
        >
          {state.isRedeeming
            ? t("login.pleaseWait")
            : t("recovery.setPassword")}
        </button>
      </form>

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
