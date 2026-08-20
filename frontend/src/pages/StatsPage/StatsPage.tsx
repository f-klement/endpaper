import { TagCategory } from "../../api/generated/model";
import { ErrorState, Spinner } from "../../components";
import { useTranslation, type MessageKey } from "../../i18n";
import { TAG_BAR_CLASSES, TAG_CATEGORY_ORDER } from "../types";
import StatSection from "./components/StatSection";
import { useStats } from "./hooks";
import { Page, PageHeader } from "../components";

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
  [TagCategory.custom]: "stats.byCustomTag",
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
      <Page width="narrow">
        <ErrorState
          error={error}
          fallback={t("stats.couldNotLoad")}
          onRetry={refetch}
        />
      </Page>
    );
  }

  const finishedTotal = (stats.finished_by_month ?? []).reduce(
    (total, row) => total + row.count,
    0,
  );

  return (
    <Page width="narrow">
      <PageHeader icon="chart" title={t("stats.title")} />

      <div className="bg-accent-50 border border-accent-100 rounded-2xl p-5 text-center dark:bg-accent-950">
        <p className="text-5xl font-bold text-accent-700 dark:text-accent-400">
          {stats.total}
        </p>
        <p className="text-sm text-accent-700 mt-1 dark:text-accent-300">
          {t("stats.booksInLibrary")}
        </p>
      </div>

      {/* Two series the server has always sent and this page ignored, so the
          only question it answered was "what have we bought". Reading is the
          half people actually come here for. */}
      {stats.average_rating != null && (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="card p-4 text-center">
            <p className="text-2xl font-bold text-paper-900 dark:text-paper-50">
              {stats.average_rating.toFixed(1)}
            </p>
            <p className="text-xs text-paper-500 mt-0.5 dark:text-paper-400">
              {t("stats.averageRating", { count: stats.rated_count ?? 0 })}
            </p>
          </div>
          <div className="card p-4 text-center">
            <p className="text-2xl font-bold text-paper-900 dark:text-paper-50">
              {finishedTotal}
            </p>
            <p className="text-xs text-paper-500 mt-0.5 dark:text-paper-400">
              {t("stats.finishedTotal")}
            </p>
          </div>
        </div>
      )}

      <StatSection
        title={t("stats.finishedByMonth")}
        rows={(stats.finished_by_month ?? []).map((row) => ({
          label: formatMonth(row.month, locale),
          count: row.count,
        }))}
        colorClass="bg-bloom-300"
        labelWidthClass="w-20"
      />

      <StatSection
        title={t("stats.byMember")}
        rows={stats.per_user.map((row) => ({
          label: row.username,
          count: row.count,
        }))}
        colorClass="bg-accent-400"
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
    </Page>
  );
}
