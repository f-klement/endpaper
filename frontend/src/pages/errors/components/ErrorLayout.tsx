import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useTranslation } from "../../../i18n";

interface ErrorLayoutProps {
  glyph: string;
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
  glyph,
  code,
  title,
  message,
  action,
}: ErrorLayoutProps) {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-sm bg-white rounded-2xl border border-gray-100 shadow-sm p-8 text-center dark:bg-gray-900 dark:border-gray-800">
        <div className="text-5xl mb-3">{glyph}</div>
        <p className="text-xs font-semibold tracking-widest uppercase text-sky-500 mb-2">
          {code}
        </p>
        <h1 className="text-xl font-bold text-gray-900 mb-2 dark:text-gray-100">
          {title}
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">{message}</p>
        <div className="mt-6">
          {action ?? (
            <Link
              to="/"
              className="inline-block px-5 py-2.5 bg-sky-500 hover:bg-sky-600 text-white text-sm font-semibold rounded-lg transition-colors"
            >
              {t("error.backToLibrary")}
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
