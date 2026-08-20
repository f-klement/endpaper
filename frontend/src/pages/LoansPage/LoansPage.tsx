import { Button, EmptyState, ErrorState, Skeleton } from "../../components";
import { Page, PageHeader } from "../components";
import { useTranslation } from "../../i18n";
import LoanRow from "./components/LoanRow";
import { useLoans } from "./hooks";

/** Placeholder rows rendered while the list loads. */
const SKELETON_COUNT = 3;

export default function LoansPage() {
  const { t } = useTranslation();
  const loans = useLoans();

  return (
    <Page width="narrow">
      <PageHeader
        icon="handshake"
        title={t("loans.title")}
        actions={
          <>
            <Button
              variant={loans.overdueOnly ? "danger" : "secondary"}
              size="sm"
              aria-pressed={loans.overdueOnly}
              // `danger` carries no border of its own, so the pressed state
              // gets one here rather than losing the frame the others have.
              className={
                loans.overdueOnly
                  ? "border border-bloom-300 dark:border-bloom-700"
                  : ""
              }
              onClick={() => loans.setOverdueOnly(!loans.overdueOnly)}
            >
              {t("loans.overdueOnly")}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              aria-pressed={loans.showAll}
              onClick={() => loans.setShowAll(!loans.showAll)}
            >
              {loans.showAll ? t("loans.activeOnly") : t("loans.showAll")}
            </Button>
          </>
        }
      />

      {/* Hidden while already filtered to overdue: the nudge would be asking
          for something the reader is already looking at. */}
      {loans.overdueCount > 0 && !loans.overdueOnly && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-bloom-300 bg-bloom-100 px-3 py-2.5 dark:border-bloom-700 dark:bg-bloom-700">
          <p className="text-sm text-bloom-700 dark:text-bloom-100">
            {t("loans.overdueBanner", { count: loans.overdueCount })}
          </p>
          <button
            type="button"
            onClick={() => loans.setOverdueOnly(true)}
            className="shrink-0 text-xs font-medium text-bloom-700 underline hover:no-underline dark:text-bloom-100"
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
              className="bg-white rounded-xl p-4 border border-paper-100 animate-pulse dark:bg-paper-900 dark:border-paper-800"
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
          icon="check"
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
    </Page>
  );
}
