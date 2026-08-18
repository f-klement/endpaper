import { TagCategory } from "../../api/generated/model";
import { ErrorState, Spinner } from "../../components";
import { useTranslation, type MessageKey } from "../../i18n";
import { TAG_BAR_CLASSES, TAG_CATEGORY_ORDER } from "../types";
import StatSection from "./components/StatSection";
import { useStats } from "./hooks";

/**
 * Section headings per category.
 *
 * Whole phrases rather than "By " plus the category name: German does not
 * build the heading the same way, and composing translated fragments is how
 * one language ends up reading like the other.
 */
const CATEGORY_HEADINGS: Record<TagCategory, MessageKey> = {
  [TagCategory.type]: "stats.byType",
  [TagCategory.genre]: "stats.byGenre",
  [TagCategory.age]: "stats.byAge",
};

/** Turn a "YYYY-MM" bucket key into a localised "Mon YYYY" label. */
export function formatMonth(yearMonth: string, locale?: string): string {
  const [year, month] = yearMonth.split("-");
  if (!year || !month) return "";
  return new Date(Number(year), Number(month) - 1).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
  });
}

export default function StatsPage() {
  const { t, locale } = useTranslation();
  const { stats, isLoading, error, refetch } = useStats();

  if (isLoading) return <Spinner label={t("stats.loading")} />;

  if (error || !stats) {
    return (
      <div className="max-w-lg mx-auto px-4 pt-5">
        <ErrorState
          error={error}
          fallback={t("stats.couldNotLoad")}
          onRetry={refetch}
        />
      </div>
    );
  }

  return (
    <div className="max-w-lg mx-auto px-4 pt-5 pb-4 space-y-6">
      <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
        📊 {t("stats.title")}
      </h1>

      <div className="bg-sky-50 border border-sky-100 rounded-2xl p-5 text-center dark:bg-sky-950">
        <p className="text-5xl font-bold text-sky-600 dark:text-sky-400">
          {stats.total}
        </p>
        <p className="text-sm text-sky-500 mt-1">{t("stats.booksInLibrary")}</p>
      </div>

      <StatSection
        title={t("stats.byMember")}
        rows={stats.per_user.map((row) => ({
          label: row.username,
          count: row.count,
        }))}
        colorClass="bg-sky-400"
        labelWidthClass="w-24"
      />

      {TAG_CATEGORY_ORDER.map((category) => (
        <StatSection
          key={category}
          title={t(CATEGORY_HEADINGS[category])}
          rows={stats.by_tag
            .filter((row) => row.category === category)
            .map((row) => ({ label: row.name, count: row.count }))}
          colorClass={TAG_BAR_CLASSES[category]}
        />
      ))}

      <StatSection
        title={t("stats.overTime")}
        rows={stats.by_month.map((row) => ({
          label: formatMonth(row.month, locale),
          count: row.count,
        }))}
        colorClass="bg-indigo-400"
        labelWidthClass="w-20"
      />
    </div>
  );
}
