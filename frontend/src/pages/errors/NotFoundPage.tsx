import { useTranslation } from "../../i18n";
import ErrorLayout from "./components/ErrorLayout";

/**
 * The 404 page.
 *
 * Replaces a catch-all route that silently redirected every unknown URL to the
 * library. That looked tidy but meant a mistyped or dead link quietly landed
 * somewhere else, with no sign anything had gone wrong.
 */
export default function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <ErrorLayout
      icon="inbox"
      code={t("error.404.code")}
      title={t("error.404.title")}
      message={t("error.404.message")}
    />
  );
}
