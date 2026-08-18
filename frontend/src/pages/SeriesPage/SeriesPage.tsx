import { EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import SeriesCard from "./components/SeriesCard";
import { useSeries } from "./hooks";

export default function SeriesPage() {
  const { t } = useTranslation();
  const { series, isLoading, error, refetch } = useSeries();

  if (isLoading) return <Spinner label={t("common.loading")} />;

  return (
    <div className="max-w-2xl mx-auto px-4 pt-5 pb-4 space-y-4">
      <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
        📚 {t("series.title")}
      </h1>

      {error != null ? (
        <ErrorState
          error={error}
          fallback={t("series.couldNotLoad")}
          onRetry={refetch}
        />
      ) : series.length === 0 ? (
        <EmptyState
          glyph="🔗"
          title={t("series.none")}
          hint={t("series.noneHint")}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {series.map((entry) => (
            <SeriesCard key={entry.name} series={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
