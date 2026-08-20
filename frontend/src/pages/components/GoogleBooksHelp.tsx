import { Link } from "react-router-dom";

import { Modal } from "../../components";
import { useTranslation } from "../../i18n";

interface GoogleBooksHelpProps {
  /** True when an admin has not stored a key yet, which changes the emphasis. */
  isUnconfigured: boolean;
  onClose: () => void;
}

/**
 * How to get a Google Books API key, and where to put it.
 *
 * Lives at `pages/components/` because two pages need it: the search box on the
 * scan page and the enrichment button on a book. The steps are spelled out
 * rather than linked, because "create a project, enable an API, make a
 * credential" is three different screens in a console most people have never
 * opened, and a bare link drops them at the first of them with no idea which of
 * the forty products they are looking for.
 */
export default function GoogleBooksHelp({
  isUnconfigured,
  onClose,
}: GoogleBooksHelpProps) {
  const { t } = useTranslation();

  return (
    <Modal title={t("help.googleBooks.title")} onClose={onClose}>
      <p>{t("help.googleBooks.what")}</p>

      {isUnconfigured && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {t("help.googleBooks.notConfigured")}
        </p>
      )}

      <ol className="list-decimal list-outside pl-5 space-y-1.5">
        <li>
          <a
            href="https://console.cloud.google.com/projectcreate"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-700 hover:text-accent-800 underline dark:text-accent-400"
          >
            {t("help.googleBooks.step1")}
          </a>
        </li>
        <li>
          <a
            href="https://console.cloud.google.com/apis/library/books.googleapis.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-700 hover:text-accent-800 underline dark:text-accent-400"
          >
            {t("help.googleBooks.step2")}
          </a>
        </li>
        <li>
          <a
            href="https://console.cloud.google.com/apis/credentials"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-700 hover:text-accent-800 underline dark:text-accent-400"
          >
            {t("help.googleBooks.step3")}
          </a>
        </li>
        <li>{t("help.googleBooks.step4")}</li>
      </ol>

      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("help.googleBooks.cost")}
      </p>
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("help.googleBooks.restrict")}
      </p>

      {/* The modal closes on navigate, because leaving a dialog open behind a
          route change strands focus in something no longer on screen. */}
      <Link
        to="/settings"
        onClick={onClose}
        className="inline-block mt-1 px-4 py-2 rounded-xl bg-accent-fill text-on-accent text-sm font-medium hover:bg-accent-fill-hover transition-colors"
      >
        {t("help.googleBooks.toSettings")}
      </Link>

      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("help.googleBooks.adminOnly")}
      </p>
    </Modal>
  );
}
