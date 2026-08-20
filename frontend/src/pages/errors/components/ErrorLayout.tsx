import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon, type IconName } from "../../../components";
import { useTranslation } from "../../../i18n";

interface ErrorLayoutProps {
  icon: IconName;
  code: string;
  title: string;
  message: ReactNode;
  action?: ReactNode;
}

/**
 * The shared frame for every client-side error page.
 *
 * Kept visually in step with `backend/templates/error.html`, which serves the
 * same statuses when the failure happens before React loads. A member should
 * not be able to tell which of the two they are looking at.
 */
export default function ErrorLayout({
  icon,
  code,
  title,
  message,
  action,
}: ErrorLayoutProps) {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="card w-full max-w-sm p-8 text-center">
        <span className="mx-auto mb-4 grid place-items-center w-12 h-12 rounded-full bg-paper-200/60 text-paper-500 dark:bg-paper-800 dark:text-paper-400">
          <Icon name={icon} className="w-6 h-6" />
        </span>
        <p className="text-xs font-semibold tracking-widest uppercase text-accent-600 mb-2">
          {code}
        </p>
        <h1 className="text-xl font-semibold text-paper-900 mb-2 dark:text-paper-100">
          {title}
        </h1>
        <p className="text-sm text-paper-500 dark:text-paper-400">{message}</p>
        <div className="mt-6">
          {action ?? (
            <Link
              to="/"
              className="inline-flex items-center justify-center h-10 px-4 rounded-lg text-sm font-medium bg-accent-600 text-white shadow-[var(--shadow-soft)] transition-[background-color,box-shadow,transform] duration-150 ease-[var(--ease-out-soft)] active:scale-[0.97] hover:bg-accent-700 dark:bg-accent-500 dark:text-paper-950 dark:hover:bg-accent-400"
            >
              {t("error.backToLibrary")}
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
