import { useState } from "react";

import {
  useListLoans,
  useMyOverdue,
} from "../../api/generated/endpoints/loans/loans";
import type {
  LoanOut,
  MyOverdueOut,
  PageLoanOut,
} from "../../api/generated/model";
import { useLoanReturn } from "../hooks";

/** Rows per request. The list is read top-down, so a page is generous. */
export const PAGE_SIZE = 50;

/** What the list reads before its first page has arrived. */
const NO_ROWS: Pick<PageLoanOut, "items" | "total"> = { items: [], total: 0 };

export interface UseLoansResult {
  loans: LoanOut[];
  total: number;
  showAll: boolean;
  setShowAll: (showAll: boolean) => void;
  overdueOnly: boolean;
  setOverdueOnly: (overdueOnly: boolean) => void;
  /**
   * How many open loans this member is being chased about, whatever the
   * current filter.
   *
   * **The same number the overdue page lists, because the nudge links there.**
   * It was `useListLoans({overdue_only: true})`, which is a different rule:
   * that endpoint is rooted at the Shelf and stops there, so it counts every
   * overdue loan over a book this member can see, housemates' included, while
   * the page counts the ones they lent or borrowed. Measured for a non admin
   * member: the nudge said 2 and the page it linked to showed 1. Zero when the
   * in app channel is switched off, which is what stops the nudge offering a
   * page the server has just emptied.
   *
   * **In library mode the two rules meet**, because the page widens to every
   * loan on the shelf for every member. Reading the wide set here would still
   * be wrong: it would be right in one mode and wrong in the other, and this
   * count has to be the one the page it links to computes, whichever is in
   * force.
   */
  overdueCount: number;

  isLoading: boolean;
  error: unknown;
  refetch: () => void;

  returningIds: ReadonlySet<number>;
  markReturned: (loanId: number) => void;
}

export function useLoans(): UseLoansResult {
  const [showAll, setShowAll] = useState(false);
  const [overdueOnly, setOverdueOnly] = useState(false);

  const params = {
    active_only: !showAll,
    overdue_only: overdueOnly,
    page_size: PAGE_SIZE,
  };
  const loans = useListLoans(params);

  // A separate query so the nudge is right even while the list is filtered to
  // something else, and the same one the library banner and the overdue page
  // read. It answers `{enabled, count}` and costs no rows at all.
  const overdue = useMyOverdue({ query: { staleTime: 60_000 } });

  const returning = useLoanReturn();
  const page = loans.data ?? NO_ROWS;

  return {
    loans: page.items,
    total: page.total,
    showAll,
    overdueOnly,
    setOverdueOnly,
    overdueCount: overdueCount(overdue.data),
    setShowAll,

    isLoading: loans.isPending,
    error: loans.error ?? returning.error,
    refetch: () => void loans.refetch(),

    returningIds: returning.returningIds,
    markReturned: returning.markReturned,
  };
}

/** The overdue count the nudge shows: none while the in app channel is off. */
function overdueCount(answer: MyOverdueOut | undefined): number {
  return answer?.enabled ? (answer.count ?? 0) : 0;
}
