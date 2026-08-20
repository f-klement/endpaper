import type { BookMatch } from "../../../api/generated/model";
import { Icon, Modal, Spinner } from "../../../components";
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
      <p className="text-sm text-paper-500 mb-3 dark:text-paper-400">
        {t("enrich.pickHint")}
      </p>

      {isSearching && <Spinner label={t("enrich.working")} />}

      {error != null && (
        <p role="alert" className="text-sm text-bloom-600 dark:text-bloom-300">
          {errorText(error, t("common.somethingWentWrong"))}
        </p>
      )}

      {!isSearching && error == null && candidates.length === 0 && (
        <p className="text-sm text-paper-500 dark:text-paper-400">
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
                {match.cover_url ? (
                  <img
                    src={match.cover_url}
                    alt=""
                    className="w-10 h-14 object-cover rounded shrink-0 bg-paper-100 dark:bg-paper-800"
                    onError={(event) => {
                      event.currentTarget.style.visibility = "hidden";
                    }}
                  />
                ) : (
                  <div className="w-10 h-14 rounded shrink-0 bg-paper-100 flex items-center justify-center dark:bg-paper-800">
                    <Icon name="book" className="w-5 h-5" />
                  </div>
                )}
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-paper-900 truncate dark:text-paper-100">
                    {match.title}
                  </span>
                  {match.subtitle && (
                    <span className="block text-xs text-paper-500 truncate dark:text-paper-400">
                      {match.subtitle}
                    </span>
                  )}
                  <span className="block text-xs text-paper-400 truncate mt-0.5 dark:text-paper-500">
                    {summarise(match)}
                  </span>
                  {/* What this row would add, so an obviously thin one can be
                      skipped without clicking it to find out. */}
                  <span className="block text-xs text-paper-400 truncate dark:text-paper-500">
                    {match.page_count
                      ? t("book.pages", { count: match.page_count })
                      : ""}
                    {match.source ? ` · ${match.source.replace(/\+/g, ", ")}` : ""}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {!isConfigured && candidates.length > 0 && (
        <p className="text-xs text-paper-400 mt-3 dark:text-paper-500">
          {t("search.withoutKey")}
        </p>
      )}
    </Modal>
  );
}
