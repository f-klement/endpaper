import { useState } from "react";
import { Link } from "react-router-dom";

import type { UserOut } from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import { readStoredUser } from "../hooks";
import BackgroundUploader from "./components/BackgroundUploader";
import ConfirmPanel from "./components/ConfirmPanel";
import LoginForm from "./components/LoginForm";
import RecoveryPanel from "./components/RecoveryPanel";
import {
  useAddressConfirmation,
  useLoginBackground,
  useLoginForm,
  usePublishedCatalogue,
  useRecovery,
} from "./hooks";
import { Icon } from "../../components";

interface LoginPageProps {
  onSignIn: (user: UserOut, token: string) => void;
}

export default function LoginPage({ onSignIn }: LoginPageProps) {
  const { t } = useTranslation();
  const form = useLoginForm(onSignIn);
  const background = useLoginBackground();
  const recovery = useRecovery();
  const confirmation = useAddressConfirmation();

  // Which card the page is showing. **A local state rather than a route**,
  // because none of the three is a place: they are three things to do with one
  // set of credentials, nothing links to them from outside, and a route would
  // put "I forgot my password" in somebody's browser history.
  const [panel, setPanel] = useState<"credentials" | "recovery" | "confirm">(
    "credentials",
  );

  // Read from the cached account rather than /auth/me: this page also renders
  // when nobody is signed in, and the upload control is admin-only.
  const isAdmin = readStoredUser()?.is_admin === true;

  // The one way in to the published catalogue from inside the app. Without it
  // `/catalogue` is reachable only by typing it, which is fine for a library
  // that links to it from its own site and useless for everybody else. Drawn
  // only when something is actually published: `public_catalogue_published` is
  // the server's conjunction of both switches, not either row.
  const hasPublicCatalogue = usePublishedCatalogue();

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center p-6 bg-gradient-to-b from-accent-50 to-paper-0"
      style={
        background.url
          ? {
              backgroundImage: `url(${background.url})`,
              backgroundSize: "cover",
              backgroundPosition: "center",
            }
          : {}
      }
    >
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          {/* A mark rather than a 60px emoji. This is the first screen anyone
              sees, so it is the one that decides whether the app looks made or
              assembled. */}
          <span className="mx-auto mb-4 grid place-items-center w-14 h-14 rounded-2xl bg-accent-fill text-on-accent shadow-[var(--shadow-lift)]">
            <Icon name="library" className="w-7 h-7" />
          </span>
          <h1 className="text-2xl font-semibold text-paper-900 dark:text-paper-100">
            {t("login.appName")}
          </h1>
          <p className="text-paper-600 text-sm mt-1 dark:text-paper-400">
            {t("login.tagline")}
          </p>
        </div>

        {panel === "recovery" && (
          <RecoveryPanel
            state={recovery}
            onBack={() => setPanel("credentials")}
          />
        )}
        {panel === "confirm" && (
          <ConfirmPanel
            state={confirmation}
            onBack={() => setPanel("credentials")}
          />
        )}

        {panel === "credentials" && (
          <>
            <LoginForm
              mode={form.mode}
              registrationEnabled={form.registrationEnabled}
              addressRequired={form.verificationRequired}
              isSubmitting={form.isSubmitting}
              error={form.error}
              onModeChange={form.setMode}
              onSubmit={form.submit}
            />

            {/* Said where the account is being made rather than found out
                afterwards: a code has been sent and nothing else will happen
                until it comes back. */}
            {form.awaitingConfirmation && (
              <p
                role="status"
                className="text-center text-sm text-paper-700 mt-4 dark:text-paper-300"
              >
                {t("login.registered")}
              </p>
            )}

            <div className="mt-4 space-y-1 text-center text-sm">
              {form.passwordResetEnabled && (
                <p>
                  <button
                    type="button"
                    onClick={() => setPanel("recovery")}
                    className="font-medium text-accent-700 dark:text-accent-300"
                  >
                    {t("login.forgotPassword")}
                  </button>
                </p>
              )}
              {form.verificationRequired && (
                <p>
                  <button
                    type="button"
                    onClick={() => setPanel("confirm")}
                    className="font-medium text-accent-700 dark:text-accent-300"
                  >
                    {t("login.haveCode")}
                  </button>
                </p>
              )}
            </div>
          </>
        )}

        {panel === "credentials" && form.mode === "register" && (
          <>
            <p className="text-center text-xs text-paper-600 mt-4 dark:text-paper-400">
              {t("login.firstAccountAdmin")}
            </p>
            {/* The moment to say it, which is the cheapest place to prevent
                the situation rather than recover from it: a reset is approved
                by another admin, so the first account has nobody to approve
                its own. `README.md` carries the command line way back. */}
            <p className="text-center text-xs text-paper-600 mt-2 dark:text-paper-400">
              {t("login.soleAdminWarning")}
            </p>
          </>
        )}

        {form.isDirectoryLogin && (
          <p className="text-center text-xs text-paper-600 mt-4 dark:text-paper-400">
            {t("login.directoryHint")}
          </p>
        )}

        {hasPublicCatalogue && (
          <p className="text-center text-sm mt-6">
            <Link
              to="/catalogue"
              className="font-medium text-accent-700 dark:text-accent-300"
            >
              {t("login.browseCatalogue")}
            </Link>
          </p>
        )}

        {isAdmin && (
          <BackgroundUploader
            hasBackground={Boolean(background.url)}
            isUploading={background.isUploading}
            onUpload={background.upload}
          />
        )}
      </div>
    </div>
  );
}
