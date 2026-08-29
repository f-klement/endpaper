import { Skeleton } from "../../components";

interface LoanRowSkeletonProps {
  /** How many placeholder rows to draw. */
  count?: number;
  /** The list's test id, which differs per page. */
  testId: string;
}

/**
 * The loading placeholder for a list of `LoanRow`s, drawn by the loans page and
 * the overdue page (#102).
 *
 * **It lives here for the same reason `LoanRow` does, and it did not at first.**
 * The overdue page opened with these fifteen lines copied verbatim from
 * `LoansPage`, in the same diff that moved `LoanRow` up a level with the
 * argument that the choice is one move or one copy and the copy is what causes
 * drift. A placeholder that stops matching the row it stands in for is exactly
 * that drift: the row gains a line, one page's skeleton grows with it and the
 * other jumps when the data lands.
 *
 * `count` defaults to three, which is what both callers asked for. `testId` is
 * a prop rather than a constant because the two pages name their lists
 * differently and their tests assert on those names.
 */
export default function LoanRowSkeleton({
  count = 3,
  testId,
}: LoanRowSkeletonProps) {
  return (
    <div className="space-y-3" data-testid={testId}>
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className="bg-paper-0 rounded-xl p-4 border border-paper-100 animate-pulse dark:bg-paper-900 dark:border-paper-800"
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
  );
}
