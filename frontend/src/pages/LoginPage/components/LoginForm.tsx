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
  onSubmit: (username: string, password: string, email: string) => void;
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
  const [email, setEmail] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(username, password, email);
  }

  return (
    <div className="bg-paper-0 rounded-2xl shadow-sm border border-paper-100 p-6 dark:bg-paper-900 dark:border-paper-800">
      {registrationEnabled && (
        <div className="flex mb-5 gap-1 p-1 bg-paper-100 rounded-lg dark:bg-paper-800">
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
                  ? "bg-paper-0 shadow-sm text-paper-900 dark:bg-paper-800 dark:text-paper-100"
                  : "text-paper-600 dark:text-paper-400"
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
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
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
            className="w-full px-3 py-2.5 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
            placeholder={t("login.usernamePlaceholder")}
          />
        </div>

        <div>
          <label
            htmlFor="password"
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
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
            className="w-full px-3 py-2.5 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
            placeholder={t("login.passwordPlaceholder")}
          />
        </div>

        {/*
          Registration only. Signing in is a form about credentials, and an
          address field there would look like a second thing to remember.
          Optional, and it stays optional: an account with no address is what
          every account here has been.
        */}
        {mode === "register" && (
          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
            >
              {t("login.email")}{" "}
              <span className="font-normal text-paper-600 dark:text-paper-400">
                ({t("login.emailOptional")})
              </span>
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              aria-describedby="email-hint"
              className="w-full px-3 py-2.5 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
              placeholder={t("login.emailPlaceholder")}
            />
            <p
              id="email-hint"
              className="mt-1 text-xs text-paper-600 dark:text-paper-400"
            >
              {t("login.emailHint")}
            </p>
          </div>
        )}

        {error != null && (
          <ErrorState error={error} fallback={t("login.failed")} />
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full py-2.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent font-semibold rounded-lg transition-colors text-sm"
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
