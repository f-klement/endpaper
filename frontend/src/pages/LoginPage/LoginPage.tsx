import type { UserOut } from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import { readStoredUser } from "../hooks";
import BackgroundUploader from "./components/BackgroundUploader";
import LoginForm from "./components/LoginForm";
import { useLoginBackground, useLoginForm } from "./hooks";

interface LoginPageProps {
  onSignIn: (user: UserOut, token: string) => void;
}

export default function LoginPage({ onSignIn }: LoginPageProps) {
  const { t } = useTranslation();
  const form = useLoginForm(onSignIn);
  const background = useLoginBackground();

  // Read from the cached account rather than /auth/me: this page also renders
  // when nobody is signed in, and the upload control is admin-only.
  const isAdmin = readStoredUser()?.is_admin === true;

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center p-6 bg-gradient-to-b from-sky-50 to-white"
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
          <div className="text-6xl mb-3">📚</div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            {t("login.appName")}
          </h1>
          <p className="text-gray-500 text-sm mt-1 dark:text-gray-400">
            {t("login.tagline")}
          </p>
        </div>

        <LoginForm
          mode={form.mode}
          registrationEnabled={form.registrationEnabled}
          isSubmitting={form.isSubmitting}
          error={form.error}
          onModeChange={form.setMode}
          onSubmit={form.submit}
        />

        {form.mode === "register" && (
          <p className="text-center text-xs text-gray-400 mt-4 dark:text-gray-500">
            {t("login.firstAccountAdmin")}
          </p>
        )}

        {form.isDirectoryLogin && (
          <p className="text-center text-xs text-gray-400 mt-4 dark:text-gray-500">
            {t("login.directoryHint")}
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
