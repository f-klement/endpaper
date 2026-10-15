import type { KosyncDocumentOut, Locale } from "../../../api/generated/model";
import { Button, ErrorState } from "../../../components";
import { useTranslation, type Translate } from "../../../i18n";
import { numericDate } from "../../../lib/date";

interface KosyncDocumentsProps {
  linked: KosyncDocumentOut[];
  waiting: KosyncDocumentOut[];
  onLink: (document: string) => void;
  onUnlink: (document: string) => void;
  isSaving: boolean;
  error: unknown;
}

/**
 * The member's KOReader documents linked to this book, and the ones waiting
 * for a book, each a press away from being this one.
 *
 * **Drawn only when there is something in either list**, so a member who
 * never set KOReader up sees nothing here at all.
 *
 * A document is described by what the device said it is when the member let
 * it say so, and otherwise by the device and where it got to, which is all a
 * push carries.
 */
export default function KosyncDocuments({
  linked,
  waiting,
  onLink,
  onUnlink,
  isSaving,
  error,
}: KosyncDocumentsProps) {
  const { t, locale } = useTranslation();
  if (linked.length === 0 && waiting.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-paper-900 dark:text-paper-100">
        {t("kosync.book.title")}
      </h3>
      {linked.length > 0 && (
        <DocumentList
          heading={t("kosync.book.linked")}
          documents={linked}
          action={t("kosync.book.unlink")}
          onAction={onUnlink}
          isSaving={isSaving}
          t={t}
          locale={locale}
        />
      )}
      {waiting.length > 0 && (
        <DocumentList
          heading={t("kosync.book.waiting")}
          documents={waiting}
          action={t("kosync.book.link")}
          onAction={onLink}
          isSaving={isSaving}
          t={t}
          locale={locale}
        />
      )}
      {error != null && (
        <ErrorState error={error} fallback={t("kosync.book.couldNotSave")} />
      )}
    </div>
  );
}

interface DocumentListProps {
  heading: string;
  documents: KosyncDocumentOut[];
  action: string;
  onAction: (document: string) => void;
  isSaving: boolean;
  t: Translate;
  locale: Locale;
}

function DocumentList({
  heading,
  documents,
  action,
  onAction,
  isSaving,
  t,
  locale,
}: DocumentListProps) {
  return (
    <section aria-label={heading} className="space-y-2">
      <p className="text-xs text-paper-600 dark:text-paper-400">{heading}</p>
      <ul className="space-y-2">
        {documents.map((row) => (
          <li key={row.document} className="flex items-center gap-3">
            <span className="min-w-0 flex-1 text-sm text-paper-800 dark:text-paper-200">
              {describe(row, t, locale)}
            </span>
            <Button
              size="sm"
              variant="secondary"
              disabled={isSaving}
              onClick={() => onAction(row.document)}
            >
              {action}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** One line saying which document this is, as well as a push can say it. */
function describe(
  row: KosyncDocumentOut,
  t: Translate,
  locale: Locale,
): string {
  return t("kosync.book.document", {
    name: row.title ?? row.filename ?? t("kosync.book.unnamed"),
    percent: wholePercent(row.percentage),
    device: row.device,
    date: numericDate(row.pushed_at, locale),
  });
}

/**
 * The whole percent, held to 0 to 100. The protocol does not bound what a
 * device pushes and the server stores it as sent, so a value outside that
 * range is shown at the nearer end, an infinite product included.
 */
function wholePercent(percentage: number): number {
  const whole = Math.floor(percentage * 100);
  return Number.isNaN(whole) ? 0 : Math.min(100, Math.max(0, whole));
}
