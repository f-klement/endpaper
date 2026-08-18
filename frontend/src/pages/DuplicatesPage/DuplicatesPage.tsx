import { EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import DuplicateCard from "./components/DuplicateCard";
import { useDuplicates } from "./hooks";

export default function DuplicatesPage() {
  const { t } = useTranslation();
  const duplicates = useDuplicates();

  if (duplicates.isLoading) return <Spinner label={t("common.loading")} />;

  return (
    <div className="max-w-2xl mx-auto px-4 pt-5 pb-4 space-y-4">
      <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
        🔍 {t("duplicates.title")}
      </h1>

      {duplicates.error != null ? (
        <ErrorState
          error={duplicates.error}
          fallback={t("duplicates.couldNotLoad")}
          onRetry={duplicates.refetch}
        />
      ) : duplicates.groups.length === 0 ? (
        <>
          {/* Shown after a merge as well as when there was never anything to
              do, which is why the success line sits above rather than instead. */}
          {duplicates.hasMerged && (
            <p
              role="status"
              className="text-sm text-green-600 text-center dark:text-green-400"
            >
              {t("duplicates.merged")}
            </p>
          )}
          <EmptyState
            glyph="✨"
            title={t("duplicates.none")}
            hint={t("duplicates.noneHint")}
          />
        </>
      ) : (
        <>
          <p className="text-sm text-gray-500 leading-relaxed dark:text-gray-400">
            {t("duplicates.explain")}
          </p>
          {duplicates.mergeError != null && (
            <ErrorState error={duplicates.mergeError} />
          )}
          {duplicates.groups.map((group) => (
            <DuplicateCard
              key={group.key}
              group={group}
              isMerging={duplicates.isMerging}
              onMerge={duplicates.merge}
            />
          ))}
        </>
      )}
    </div>
  );
}
