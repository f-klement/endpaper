import { Link } from "react-router-dom";

import { Button, EmptyState, ErrorState } from "../../components";
import { LoanRow, LoanRowSkeleton, Page, PageHeader } from "../components";
import { useTranslation } from "../../i18n";
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
                  ? "border border-danger-300 dark:border-danger-700"
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

      {/* Hidden while already filtered to overdue, and the reason changed with
          the destination (#102). It used to be that the nudge was asking for
          something the reader was already looking at. It is now that the two
          count different sets: this sentence counts the loans this member is
          chased about, and the filter shows every overdue loan over a book
          they can see. One screen must not carry two numbers both called
          overdue. */}
      {loans.overdueCount > 0 && !loans.overdueOnly && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-danger-300 bg-danger-100 px-3 py-2.5 dark:border-danger-300 dark:bg-danger-700">
          <p className="text-sm text-danger-700 dark:text-danger-100">
            {t("loans.overdueBanner", { count: loans.overdueCount })}
          </p>
          {/* A link to the overdue page rather than a second spelling of the
              "Overdue only" button two lines above it (#102). The two did the
              same thing, and the page is where the delivery status is. The
              count beside it is read through the page's own rule, so the
              sentence and the screen it opens cannot disagree. */}
          <Link
            to="/loans/overdue"
            className="shrink-0 text-xs font-medium text-danger-700 underline hover:no-underline dark:text-danger-100"
          >
            {t("loans.chaseThem")}
          </Link>
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
        <LoanRowSkeleton count={SKELETON_COUNT} testId="loan-skeletons" />
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
