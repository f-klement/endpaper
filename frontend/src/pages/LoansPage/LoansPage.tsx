import { EmptyState, ErrorState, Skeleton } from "../../components";
import { useTranslation } from "../../i18n";
import LoanRow from "./components/LoanRow";
import { useLoans } from "./hooks";

/** Placeholder rows rendered while the list loads. */
const SKELETON_COUNT = 3;

export default function LoansPage() {
  const { t } = useTranslation();
  const loans = useLoans();

  return (
    <div className="max-w-lg mx-auto px-4 pt-5">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
          🤝 {t("loans.title")}
        </h1>
        <div className="flex items-center gap-3">
          <button
            onClick={() => loans.setOverdueOnly(!loans.overdueOnly)}
            aria-pressed={loans.overdueOnly}
            className={`text-sm hover:underline ${
              loans.overdueOnly ? "text-red-600 font-medium" : "text-gray-500"
            }`}
          >
            {t("loans.overdueOnly")}
          </button>
          <button
            onClick={() => loans.setShowAll(!loans.showAll)}
            className="text-sm text-sky-600 hover:underline dark:text-sky-400"
          >
            {loans.showAll ? t("loans.activeOnly") : t("loans.showAll")}
          </button>
        </div>
      </div>

      {/* Hidden while already filtered to overdue: the nudge would be asking
          for something the reader is already looking at. */}
      {loans.overdueCount > 0 && !loans.overdueOnly && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 dark:border-red-900 dark:bg-red-950">
          <p className="text-sm text-red-800">
            {t("loans.overdueBanner", { count: loans.overdueCount })}
          </p>
          <button
            type="button"
            onClick={() => loans.setOverdueOnly(true)}
            className="shrink-0 text-xs font-medium text-red-900 underline hover:no-underline"
          >
            {t("loans.chaseThem")}
          </button>
        </div>
      )}

      {loans.error != null && (
        <div className="mb-3">
          <ErrorState
            error={loans.error}
            fallback={t("loans.couldNotLoad")}
            onRetry={loans.refetch}
          />
        </div>
      )}

      {loans.isLoading ? (
        <div className="space-y-3" data-testid="loan-skeletons">
          {Array.from({ length: SKELETON_COUNT }).map((_, index) => (
            <div
              key={index}
              className="bg-white rounded-xl p-4 border border-gray-100 animate-pulse dark:bg-gray-900 dark:border-gray-800"
            >
              <div className="flex gap-3">
                <Skeleton className="w-12 h-16" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : loans.loans.length === 0 ? (
        <EmptyState
          glyph="✅"
          title={loans.showAll ? t("loans.none") : t("loans.noneActive")}
          hint={t("loans.allAccountedFor")}
        />
      ) : (
        <div className="space-y-3">
          {loans.loans.map((loan) => (
            <LoanRow
              key={loan.id}
              loan={loan}
              isReturning={loans.returningId === loan.id}
              onMarkReturned={loans.markReturned}
            />
          ))}
        </div>
      )}
    </div>
  );
}
