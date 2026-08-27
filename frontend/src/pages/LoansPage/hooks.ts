import { useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import {
  getListLoansQueryKey,
  useListLoans,
  useReturnLoan,
} from "../../api/generated/endpoints/loans/loans";
import type { LoanOut } from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";

/** Rows per request. The list is read top-down, so a page is generous. */
export const PAGE_SIZE = 50;

export interface UseLoansResult {
  loans: LoanOut[];
  total: number;
  showAll: boolean;
  setShowAll: (showAll: boolean) => void;
  overdueOnly: boolean;
  setOverdueOnly: (overdueOnly: boolean) => void;
  /** How many open loans are past their date, whatever the current filter. */
  overdueCount: number;

  isLoading: boolean;
  error: unknown;
  refetch: () => void;

  returningId: number | null;
  markReturned: (loanId: number) => void;
}

export function useLoans(): UseLoansResult {
  const [showAll, setShowAll] = useState(false);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();

  const params = {
    active_only: !showAll,
    overdue_only: overdueOnly,
    page_size: PAGE_SIZE,
  };
  const loans = useListLoans(params);

  // A separate count so the banner is right even while the list is filtered
  // to something else. One row is enough: only the envelope's total is used.
  const overdue = useListLoans(
    { active_only: true, overdue_only: true, page_size: 1 },
    { query: { staleTime: 30_000 } },
  );

  const returnLoan = useReturnLoan({
    mutation: {
      onSuccess: () => {
        // A return changes the loans list and every book's active_loan, so
        // both caches are dropped rather than patched by hand.
        void queryClient.invalidateQueries({
          queryKey: getListLoansQueryKey(),
        });
        // `invalidate.listings()` rather than `["/api/books"]`: the grid is an
        // infinite query and a hand-written key does not match it.
        invalidate.listings();
      },
    },
  });

  return {
    loans: loans.data?.items ?? [],
    total: loans.data?.total ?? 0,
    showAll,
    overdueOnly,
    setOverdueOnly,
    overdueCount: overdue.data?.total ?? 0,
    setShowAll,

    isLoading: loans.isPending,
    error: loans.error ?? returnLoan.error,
    refetch: () => void loans.refetch(),

    // The row spinner needs to know *which* loan is in flight, which the
    // mutation's own isPending cannot say.
    returningId: returnLoan.isPending
      ? (returnLoan.variables?.loanId ?? null)
      : null,
    markReturned: (loanId) => returnLoan.mutate({ loanId }),
  };
}
