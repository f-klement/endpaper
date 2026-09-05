import { EmptyState, ErrorState } from "../../components";
import {
  LoanRow,
  LoanRowSkeleton,
  Page,
  PageCount,
  PageHeader,
} from "../components";
import { useTranslation } from "../../i18n";
import DeliveryStatus from "./components/DeliveryStatus";
import { useOverdue } from "./hooks";

/** Placeholder rows rendered while the list loads. */
const SKELETON_COUNT = 3;

/**
 * Every book that is late, and what the reminder channels have been doing
 * about it (#102).
 *
 * **A page rather than a section of the library page.** The library page keeps
 * the banner: a count and a link is a reminder, and a list under the grid is a
 * second loans page nobody asked for. This is where a reader goes once the
 * banner has told them there is something to do.
 *
 * **Not the loans page with a filter, either, and the difference is who may
 * read what.** The loans list is rooted at the Shelf and stops there, so it
 * shows every loan over a book the reader can see. This page asks
 * `GET /api/loans/overdue`, which is `notifications.overdue_for_viewer`: a
 * member reads the loans they lent or borrowed, and staff read every overdue
 * loan on their shelf. **In library mode every member reads all of them**,
 * because a volunteer chasing a book somebody else lent out is the case that
 * mode exists for, and the two lists then agree on the overdue rows rather
 * than merely not contradicting each other. Whichever rule is in force, it is
 * the same one the banner counts through: two screens disagreeing about how
 * many loans are overdue would be worse than either alone.
 *
 * Private books are outside all of it. Both arms are rooted at the Shelf, so
 * the mode widens which loans a member reads and never which books exist.
 *
 * The delivery panel sits above the list because it qualifies the whole of it.
 * What it can and cannot say is in `DeliveryStatus`.
 */
export default function OverduePage() {
  const { t } = useTranslation();
  const overdue = useOverdue();

  return (
    <Page width="narrow">
      <PageHeader
        icon="alert"
        title={t("overdue.title")}
        badge={
          overdue.total > 0 ? <PageCount>{overdue.total}</PageCount> : undefined
        }
      />

      <DeliveryStatus record={overdue.channels} />

      {overdue.error != null && (
        <div className="mb-3">
          <ErrorState
            error={overdue.error}
            fallback={t("overdue.couldNotLoad")}
            onRetry={overdue.refetch}
          />
        </div>
      )}

      {overdue.isLoading ? (
        <LoanRowSkeleton count={SKELETON_COUNT} testId="overdue-skeletons" />
      ) : overdue.loans.length === 0 ? (
        // Two empties, and they are not the same news. The switch being off is
        // a household decision somebody can undo; nothing being late is the
        // answer the reader wanted.
        <EmptyState
          icon="check"
          title={overdue.enabled ? t("overdue.none") : t("overdue.switchedOff")}
          hint={
            overdue.enabled
              ? t("overdue.noneHint")
              : t("overdue.switchedOffHint")
          }
        />
      ) : (
        <div className="space-y-3">
          {overdue.loans.map((loan) => (
            <LoanRow
              key={loan.id}
              loan={loan}
              isReturning={overdue.returningId === loan.id}
              onMarkReturned={overdue.markReturned}
            />
          ))}

          {overdue.total > overdue.loans.length && (
            // The badge counts every overdue loan; the list holds one page of
            // them. Without this line the two disagree in silence above 50 and
            // the rest is unreachable, because this page has no pager and a
            // pager is more than the ticket. Library mode (#18) is what makes
            // 50 reachable, so this says which rows are on screen rather than
            // pretending the cap is not there.
            //
            // It says that and stops. A first version added "The rest are on
            // the loans page", which is not true: that page is capped at the
            // same 50, has no pager either, and orders by `loaned_at desc`
            // rather than by the due date, so above the cap it holds neither
            // all of the remainder nor the same remainder.
            <p className="text-sm text-paper-600 dark:text-paper-400 pt-1">
              {t("overdue.capped", {
                shown: overdue.loans.length,
                total: overdue.total,
              })}
            </p>
          )}
        </div>
      )}
    </Page>
  );
}
