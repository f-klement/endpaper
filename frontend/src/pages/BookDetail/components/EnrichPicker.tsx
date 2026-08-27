import type { BookMatch, ClassificationIn } from "../../../api/generated/model";
import { Modal, Spinner } from "../../../components";
import { CoverImage } from "../../components";
import { errorText } from "../../../components/ErrorState";
import { useTranslation } from "../../../i18n";

interface EnrichPickerProps {
  candidates: BookMatch[];
  isSearching: boolean;
  isWorking: boolean;
  isConfigured: boolean;
  error: unknown;
  onChoose: (match: BookMatch) => void;
  onClose: () => void;
}

/** A one-line description of an edition, skipping the parts it lacks. */
function summarise(match: BookMatch): string {
  return [match.publisher, match.year, match.language?.toUpperCase()]
    .filter(Boolean)
    .join(" · ");
}

/** The exact scheme evidence a selected candidate will post back. */
function classificationText(classification: ClassificationIn): string {
  const label = classification.label ? `: ${classification.label}` : "";
  return `${classification.scheme.toUpperCase()} ${classification.number}${label}`;
}

/**
 * Choosing which edition to take the details from.
 *
 * The button used to write straight away, taking whichever result a search
 * returned first. That is wrong often enough to matter: a paperback and its
 * hardback are the same book, different page counts and different covers, and
 * a catalogue will happily hand back the other one. Nothing is written until a
 * row here is clicked.
 *
 * Presentational. The search, the choice and the merge all live in the page's
 * hooks and on the server.
 */
export default function EnrichPicker({
  candidates,
  isSearching,
  isWorking,
  isConfigured,
  error,
  onChoose,
  onClose,
}: EnrichPickerProps) {
  const { t } = useTranslation();

  return (
    <Modal title={t("enrich.pickTitle")} onClose={onClose}>
      <p className="text-sm text-paper-600 mb-3 dark:text-paper-400">
        {t("enrich.pickHint")}
      </p>

      {isSearching && <Spinner label={t("enrich.working")} />}

      {error != null && (
        <p
          role="alert"
          className="text-sm text-danger-600 dark:text-danger-300"
        >
          {errorText(error, t("common.somethingWentWrong"), t)}
        </p>
      )}

      {!isSearching && error == null && candidates.length === 0 && (
        <p className="text-sm text-paper-600 dark:text-paper-400">
          {t("enrich.notFound")}
        </p>
      )}

      {candidates.length > 0 && (
        <ul className="space-y-2 max-h-80 overflow-y-auto">
          {candidates.map((match, index) => (
            <li key={`${match.isbn13 ?? match.google_books_id ?? ""}-${index}`}>
              <button
                type="button"
                disabled={isWorking}
                onClick={() => onChoose(match)}
                className="w-full flex gap-3 text-left p-2.5 rounded-xl border border-paper-200 hover:border-accent-300 hover:bg-accent-50 disabled:opacity-50 transition-colors dark:border-paper-800 dark:hover:border-accent-700 dark:hover:bg-accent-500/10"
              >
                <CoverImage
                  src={match.cover_url}
                  alt=""
                  iconClassName="w-5 h-5"
                  className="w-10 h-14 object-cover rounded shrink-0 bg-paper-100 dark:bg-paper-800"
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-paper-900 truncate dark:text-paper-100">
                    {match.title}
                  </span>
                  {match.subtitle && (
                    <span className="block text-xs text-paper-600 truncate dark:text-paper-400">
                      {match.subtitle}
                    </span>
                  )}
                  <span className="block text-xs text-paper-600 truncate mt-0.5 dark:text-paper-400">
                    {summarise(match)}
                  </span>
                  {/* What this row would add, so an obviously thin one can be
                      skipped without clicking it to find out. */}
                  <span className="block text-xs text-paper-600 truncate dark:text-paper-400">
                    {match.page_count
                      ? t("book.pages", { count: match.page_count })
                      : ""}
                    {match.source
                      ? ` · ${match.source.replace(/\+/g, ", ")}`
                      : ""}
                  </span>
                  <span className="block mt-1 text-xs text-paper-600 dark:text-paper-400">
                    <span className="font-medium text-paper-700 dark:text-paper-300">
                      {t("enrich.proposedClassifications")}
                    </span>
                    {match.classifications?.length ? (
                      match.classifications.map((classification) => (
                        <span
                          key={`${classification.scheme}-${classification.number}`}
                          className="block"
                        >
                          {classificationText(classification)}
                        </span>
                      ))
                    ) : (
                      <span className="block">
                        {t("enrich.noClassifications")}
                      </span>
                    )}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {!isConfigured && candidates.length > 0 && (
        <p className="text-xs text-paper-600 mt-3 dark:text-paper-400">
          {t("search.withoutKey")}
        </p>
      )}
    </Modal>
  );
}
