import { useState, type FormEvent } from "react";

import { ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";
import type { Mode } from "../hooks";

interface LoginFormProps {
  mode: Mode;
  registrationEnabled: boolean;
  isSubmitting: boolean;
  error: unknown;
  onModeChange: (mode: Mode) => void;
  onSubmit: (username: string, password: string) => void;
}

/** The credentials form. Presentational, used only by LoginPage. */
export default function LoginForm({
  mode,
  registrationEnabled,
  isSubmitting,
  error,
  onModeChange,
  onSubmit,
}: LoginFormProps) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(username, password);
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 dark:bg-gray-900 dark:border-gray-800">
      {registrationEnabled && (
        <div className="flex mb-5 gap-1 p-1 bg-gray-100 rounded-lg dark:bg-gray-800">
          {(["login", "register"] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onModeChange(option)}
              // The tab and the submit button below show the same words, so
              // without this a screen reader announces two identical "Sign
              // In" buttons and neither says which one switches the form.
              aria-label={
                option === "login"
                  ? t("login.switchToSignIn")
                  : t("login.switchToRegister")
              }
              aria-pressed={mode === option}
              className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                mode === option
                  ? "bg-white shadow-sm text-gray-900"
                  : "text-gray-500"
              }`}
            >
              {option === "login"
                ? t("login.signIn")
                : t("login.createAccount")}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label
            htmlFor="username"
            className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-200"
          >
            {t("login.username")}
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
            autoComplete="username"
            className="w-full px-3 py-2.5 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-sky-400 text-sm dark:border-gray-700"
            placeholder={t("login.usernamePlaceholder")}
          />
        </div>

        <div>
          <label
            htmlFor="password"
            className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-200"
          >
            {t("login.password")}
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            autoComplete={
              mode === "register" ? "new-password" : "current-password"
            }
            className="w-full px-3 py-2.5 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-sky-400 text-sm dark:border-gray-700"
            placeholder={t("login.passwordPlaceholder")}
          />
        </div>

        {error != null && (
          <ErrorState error={error} fallback={t("login.failed")} />
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full py-2.5 bg-sky-500 hover:bg-sky-600 disabled:bg-sky-300 text-white font-semibold rounded-lg transition-colors text-sm"
        >
          {isSubmitting
            ? t("login.pleaseWait")
            : mode === "login"
              ? t("login.signIn")
              : t("login.createAccount")}
        </button>
      </form>
    </div>
  );
}
