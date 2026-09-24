import type { BookOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { longMonthDate } from "../../../lib/date";
import StarRating from "./StarRating";

interface ReadingPanelProps {
  book: BookOut;
  onRate: (rating: number | null) => void;
}

/**
 * What this reader thinks of the book, and when they read it.
 *
 * Separate from the status buttons above it because the dates are *derived*
 * from those, not entered here. Showing them next to the control that produces
 * them is what makes the derivation visible instead of surprising.
 */
export default function ReadingPanel({ book, onRate }: ReadingPanelProps) {
  const { t, locale } = useTranslation();

  return (
    <div className="space-y-2">
      {/* h3, not h2: the section handle that folds this panel away is the
          h2 above it, so a flat h2 here would show a reader's heading list a
          page with no grouping in it at all. */}
      <h3 className="text-sm font-semibold text-paper-900 dark:text-paper-100">
        {t("rating.label")}
      </h3>
      <StarRating value={book.my_rating} onChange={onRate} />

      {(book.my_started_at || book.my_finished_at) && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {[
            book.my_started_at &&
              t("reading.started", {
                date: longMonthDate(book.my_started_at, locale),
              }),
            book.my_finished_at &&
              t("reading.finished", {
                date: longMonthDate(book.my_finished_at, locale),
              }),
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}
