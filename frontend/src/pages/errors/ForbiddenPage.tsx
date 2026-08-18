import { useTranslation } from "../../i18n";
import ErrorLayout from "./components/ErrorLayout";

/**
 * The 403 page.
 *
 * Rarely reached by design: a book someone may not see is reported as 404, not
 * 403, so that its existence stays private. This is for the narrower case
 * where the thing is known to exist but the decision is not the caller's,
 * changing another member's book from public to private, for instance.
 */
export default function ForbiddenPage() {
  const { t } = useTranslation();
  return (
    <ErrorLayout
      glyph="🚫"
      code={t("error.403.code")}
      title={t("error.403.title")}
      message={t("error.403.message")}
    />
  );
}
