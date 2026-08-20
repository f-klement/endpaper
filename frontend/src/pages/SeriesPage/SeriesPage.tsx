import { EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import SeriesCard from "./components/SeriesCard";
import { useSeries } from "./hooks";
import { Page, PageHeader } from "../components";

export default function SeriesPage() {
  const { t } = useTranslation();
  const { series, isLoading, error, refetch } = useSeries();

  if (isLoading) return <Spinner label={t("common.loading")} />;

  return (
    <Page width="narrow">
      <PageHeader icon="link" title={t("series.title")} />

      {error != null ? (
        <ErrorState
          error={error}
          fallback={t("series.couldNotLoad")}
          onRetry={refetch}
        />
      ) : series.length === 0 ? (
        <EmptyState
          icon="link"
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
    </Page>
  );
}
