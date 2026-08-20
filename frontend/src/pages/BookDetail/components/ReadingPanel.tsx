import type { BookOut } from "../../../api/generated/model";
import { StarRating } from "../../../components";
import { useTranslation } from "../../../i18n";

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

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(locale, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });

  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100">
        {t("rating.label")}
      </h2>
      <StarRating value={book.my_rating} onChange={onRate} />

      {(book.my_started_at || book.my_finished_at) && (
        <p className="text-xs text-paper-500 dark:text-paper-400">
          {[
            book.my_started_at &&
              t("reading.started", { date: formatDate(book.my_started_at) }),
            book.my_finished_at &&
              t("reading.finished", { date: formatDate(book.my_finished_at) }),
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}
