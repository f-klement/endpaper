import { Link } from "react-router-dom";

import type { BookOut } from "../../../api/generated/model";
import { ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";

interface CopiesPanelProps {
  /** The copy being looked at, so it can be marked in the list. */
  book: BookOut;
  copies: BookOut[];
  isAdding: boolean;
  error: unknown;
  /** The list could not be read. Said out loud, because the alternative is a
   * panel that looks exactly like a book with one copy. */
  listError: unknown;
  onAdd: () => void;
}

/**
 * The other objects on the shelf that are this same book.
 *
 * Not `CopyPanel`, which edits the collector details of *this* copy. This one
 * is about there being more than one of them: a library that holds two
 * paperbacks owns two objects, each with its own shelf, condition and loan.
 *
 * Rendered even when there is only one, because the add action lives here and
 * a control that appears only once a thing exists cannot be used to make the
 * thing. The list is suppressed in that case, since "1 copy: this one" tells
 * nobody anything.
 */
export default function CopiesPanel({
  book,
  copies,
  isAdding,
  error,
  listError,
  onAdd,
}: CopiesPanelProps) {
  const { t } = useTranslation();
  const hasMore = copies.length > 1;

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-1 dark:text-paper-200">
        {t("copies.title")}
      </p>
      <p className="text-xs text-paper-600 mb-2 dark:text-paper-300">
        {hasMore
          ? t("copies.count", { count: copies.length })
          : t("copies.hint")}
      </p>

      {hasMore && (
        <ul className="space-y-1 mb-2">
          {copies.map((copy) => {
            const isThisOne = copy.id === book.id;
            return (
              <li
                key={copy.id}
                className="flex items-center justify-between gap-2 text-sm bg-paper-100 rounded-lg px-3 py-2 dark:bg-paper-800"
              >
                <span className="text-paper-700 truncate dark:text-paper-200">
                  {copy.location || t("copies.noShelf")}
                  {copy.active_loan && (
                    <span className="text-paper-600 dark:text-paper-300">
                      {" "}
                      ({t("copies.onLoan")})
                    </span>
                  )}
                </span>
                {isThisOne ? (
                  <span className="shrink-0 text-xs text-paper-600 dark:text-paper-300">
                    {t("copies.thisOne")}
                  </span>
                ) : (
                  <Link
                    to={`/book/${copy.id}`}
                    className="shrink-0 text-xs font-medium text-accent-600 hover:text-accent-700 dark:text-accent-400 dark:hover:text-accent-300"
                  >
                    {t("copies.open")}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {listError != null && (
        <div className="mb-2">
          <ErrorState error={listError} fallback={t("copies.loadFailed")} />
        </div>
      )}

      {error != null && (
        <div className="mb-2">
          <ErrorState error={error} fallback={t("copies.addFailed")} />
        </div>
      )}

      <button
        onClick={onAdd}
        disabled={isAdding}
        className="w-full py-2 border border-paper-200 text-paper-700 rounded-lg text-sm font-medium hover:bg-paper-50 disabled:text-paper-600 transition-colors dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
      >
        {isAdding ? t("copies.adding") : t("copies.add")}
      </button>
    </div>
  );
}
