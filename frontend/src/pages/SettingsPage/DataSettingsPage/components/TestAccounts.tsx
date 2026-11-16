import { useState, type FormEvent } from "react";

import { AuthMode, type UserOut } from "../../../../api/generated/model";
import { Button, ErrorState, Spinner } from "../../../../components";
import { useTranslation } from "../../../../i18n";

interface TestAccountsProps {
  accounts: UserOut[];
  isLoading: boolean;
  error: unknown;
  onCreate: (username: string, password: string, email: string) => void;
  isCreating: boolean;
  createError: unknown;
  onSwitch: (username: string, password: string) => void;
  isSwitching: boolean;
  switchError: unknown;
  /** Decides which sentence says how to get back. */
  mode: AuthMode;
}

/**
 * Admin-created accounts for seeing the library as an ordinary member sees it.
 *
 * Presentational: every refusal that matters is the server's. This list holds
 * only test accounts because that is what the endpoint returns, and switching
 * to something else fails there whatever is typed here.
 *
 * The password is asked for on every switch and never remembered. It is what
 * makes this a login on another account's behalf rather than impersonation,
 * and an admin who cannot produce it is an admin who did not set it.
 */
export default function TestAccounts({
  accounts,
  isLoading,
  error,
  onCreate,
  isCreating,
  createError,
  onSwitch,
  isSwitching,
  switchError,
  mode,
}: TestAccountsProps) {
  const { t } = useTranslation();
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newEmail, setNewEmail] = useState("");

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onCreate(newUsername.trim(), newPassword, newEmail.trim());
    setNewUsername("");
    setNewPassword("");
    setNewEmail("");
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("settings.testAccountsHint")}
      </p>
      {/* Said before the switch rather than discovered after it. Under proxy
          the menu hands the session back; in the other two modes the admin's
          own token has been replaced and signing in again is the way back. */}
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {mode === AuthMode.proxy
          ? t("settings.testAccountsReturnProxy")
          : t("settings.testAccountsReturnToken")}
      </p>

      {isLoading && <Spinner label={t("common.loading")} />}
      {error != null && (
        <ErrorState error={error} fallback={t("settings.couldNotLoad")} />
      )}

      {!isLoading && accounts.length === 0 && (
        <p className="text-sm text-paper-600 dark:text-paper-400">
          {t("settings.testAccountsEmpty")}
        </p>
      )}

      <AccountList
        accounts={accounts}
        onSwitch={onSwitch}
        isSwitching={isSwitching}
        switchError={switchError}
      />

      <form onSubmit={create} className="space-y-2 pt-1">
        <div className="flex gap-2">
          <div className="flex-1">
            <label htmlFor="test-account-username" className="sr-only">
              {t("login.username")}
            </label>
            <input
              id="test-account-username"
              type="text"
              className="field"
              autoComplete="off"
              required
              value={newUsername}
              onChange={(event) => setNewUsername(event.target.value)}
              placeholder={t("login.usernamePlaceholder")}
            />
          </div>
          <div className="flex-1">
            <label htmlFor="test-account-password" className="sr-only">
              {t("login.password")}
            </label>
            <input
              id="test-account-password"
              type="password"
              className="field"
              autoComplete="new-password"
              required
              // The server's floor, restated so the browser can say so before
              // a round trip. It is not the enforcement: `UserCreate` is.
              minLength={8}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder={t("settings.testAccountsPasswordPlaceholder")}
            />
          </div>
        </div>
        {/* Optional, and the one moment an admin is already typing somebody
            else's details. Without it the only way to give a new account an
            address is to make it, find it in the member list and edit it,
            which is three screens for a field that was on the form.

            **The hint is not decoration.** Registration and the account screen
            both say that nothing is sent to the address yet, and the admin
            typing somebody else's is the reader most likely to assume it will
            be used. */}
        <div>
          <label htmlFor="test-account-email" className="sr-only">
            {t("settings.testAccountsAddress")}
          </label>
          <input
            id="test-account-email"
            type="email"
            className="field"
            autoComplete="off"
            aria-describedby="test-account-email-hint"
            value={newEmail}
            onChange={(event) => setNewEmail(event.target.value)}
            placeholder={t("settings.testAccountsAddressPlaceholder")}
          />
          <p
            id="test-account-email-hint"
            className="mt-1 text-xs text-paper-600 dark:text-paper-400"
          >
            {t("settings.testAccountsAddressHint")}
          </p>
        </div>
        <Button type="submit" variant="secondary" isLoading={isCreating}>
          {t("settings.testAccountsCreate")}
        </Button>
      </form>

      {createError != null && (
        <ErrorState
          error={createError}
          fallback={t("settings.testAccountsCreateFailed")}
        />
      )}
    </div>
  );
}

interface AccountListProps {
  accounts: UserOut[];
  onSwitch: (username: string, password: string) => void;
  isSwitching: boolean;
  switchError: unknown;
}

/** The accounts, each with its switch, and what the last switch came to. */
function AccountList({
  accounts,
  onSwitch,
  isSwitching,
  switchError,
}: AccountListProps) {
  const { t } = useTranslation();
  // Which row has its password field open. One at a time, so the field is
  // never ambiguous about which account it is for.
  const [selected, setSelected] = useState<string | null>(null);
  const [password, setPassword] = useState("");

  function submitSwitch(event: FormEvent<HTMLFormElement>, username: string) {
    event.preventDefault();
    onSwitch(username, password);
  }

  // Opening a row closes any other, and either way the password starts empty.
  function toggle(username: string) {
    setSelected(selected === username ? null : username);
    setPassword("");
  }

  return (
    <>
      <ul className="space-y-2">
        {accounts.map((account) => (
          <TestAccountRow
            key={account.id}
            account={account}
            isOpen={selected === account.username}
            onToggle={() => toggle(account.username)}
            password={password}
            onPasswordChange={setPassword}
            onSubmit={(event) => submitSwitch(event, account.username)}
            isSwitching={isSwitching}
          />
        ))}
      </ul>

      {switchError != null && (
        <ErrorState
          error={switchError}
          fallback={t("settings.testAccountsSwitchFailed")}
        />
      )}
    </>
  );
}

interface TestAccountRowProps {
  account: UserOut;
  /** Whether this row's password field is the one open. */
  isOpen: boolean;
  onToggle: () => void;
  password: string;
  onPasswordChange: (password: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  isSwitching: boolean;
}

/** One account: its name, the switch button, and the password field when open. */
function TestAccountRow({
  account,
  isOpen,
  onToggle,
  password,
  onPasswordChange,
  onSubmit,
  isSwitching,
}: TestAccountRowProps) {
  const { t } = useTranslation();

  return (
    <li className="border border-paper-200 rounded-xl px-3 py-2.5 dark:border-paper-800">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-paper-800 truncate dark:text-paper-100">
          {account.username}
        </span>
        <Button
          size="sm"
          variant="secondary"
          aria-label={t("settings.testAccountsSwitchTo", {
            name: account.username,
          })}
          onClick={onToggle}
        >
          {t("settings.testAccountsSwitch")}
        </Button>
      </div>

      {isOpen && (
        <form className="flex gap-2 pt-2.5" onSubmit={onSubmit}>
          <label htmlFor={`switch-password-${account.id}`} className="sr-only">
            {t("settings.testAccountsPasswordFor", {
              name: account.username,
            })}
          </label>
          <input
            id={`switch-password-${account.id}`}
            type="password"
            className="field"
            autoComplete="off"
            required
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            placeholder={t("login.passwordPlaceholder")}
          />
          <Button type="submit" size="md" isLoading={isSwitching}>
            {t("settings.testAccountsSwitch")}
          </Button>
        </form>
      )}
    </li>
  );
}
