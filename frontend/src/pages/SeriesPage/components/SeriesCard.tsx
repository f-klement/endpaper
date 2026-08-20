import { Link } from "react-router-dom";

import type { SeriesOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface SeriesCardProps {
  series: SeriesOut;
}

/** One series, its size, and what is missing from it. Dumb. */
export default function SeriesCard({ series }: SeriesCardProps) {
  const { t } = useTranslation();
  const complete = series.missing_indexes?.length === 0;

  return (
    <Link
      to={`/?series=${encodeURIComponent(series.name)}&sort=series`}
      className="block bg-paper-0 border border-paper-200 rounded-2xl p-4 hover:border-accent-300 transition-colors dark:bg-paper-900 dark:border-paper-700"
    >
      <h2 className="font-semibold text-paper-900 dark:text-paper-100">
        {series.name}
      </h2>
      <p className="text-xs text-paper-600 mt-0.5 dark:text-paper-400">
        {t("series.bookCount", { count: series.book_count })}
      </p>

      {/* The gaps are the reason this page exists, so they are the loudest
          thing on the card. A complete series says so rather than staying
          silent, which would be indistinguishable from "not calculated". */}
      {complete ? (
        <p className="text-xs text-green-600 mt-2 dark:text-green-400">
          {t("series.complete")}
        </p>
      ) : (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-2 py-1 mt-2 inline-block dark:text-amber-300 dark:bg-amber-950 dark:border-amber-900">
          {t("series.missing", {
            numbers: (series.missing_indexes ?? []).join(", "),
          })}
        </p>
      )}
    </Link>
  );
}
