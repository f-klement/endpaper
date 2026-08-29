/**
 * Data for the overdue page.
 *
 * This is the whole of the page's contact with the API. Two queries and one
 * write, and they answer two different questions: which books are late, and
 * what the reminder channels have been doing.
 */

import {
  useListOverdue,
  useMyOverdue,
  useReturnLoan,
} from "../../api/generated/endpoints/loans/loans";
import { useGetSenderHealth } from "../../api/generated/endpoints/settings/settings";
import type { LoanOut, SenderHealth } from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";
import { ApiError } from "../../api/mutator";
import type { DeliveryRecord } from "./types";

/** Rows per request. The page is read top-down, so a page is generous. */
export const PAGE_SIZE = 50;

export interface UseOverdueResult {
  /** Most overdue first: the server orders by the date the book was due. */
  loans: LoanOut[];
  total: number;

  /**
   * Whether the household has the in app reminder switched on.
   *
   * The list is empty either way when it is off, because the server honours
   * the same switch. This is what lets the empty state say which of the two
   * empties it is, and it is read from `overdue/mine` rather than from the
   * settings record, which is admin only.
   */
  enabled: boolean;

  /**
   * What each switched-on channel that pushes last did, or why it is not
   * being shown.
   *
   * **Hidden for a member, and that is the endpoint's decision rather than
   * this page's.** `GET /api/settings/sender-health` answers 403 to anybody but
   * an admin, because it names channels, their failures and the sentences
   * those failures produced, and only an admin can reach the screen that
   * repairs one. A member's query therefore fails, which is the same
   * arrangement `ChannelAlertBanner` has on the library page.
   *
   * **Hidden, unreadable and empty are three answers, not one.** Empty means
   * an admin looked and no channel that pushes is switched on, which the page
   * says out loud; printing that at somebody who may not look would be the
   * page asserting something it has not checked. A failure that is not a
   * refusal is the third, and it used to render as the first: an admin whose
   * record 500s saw no panel, no error, and a page that looked complete.
   */
  channels: DeliveryRecord;

  isLoading: boolean;
  error: unknown;
  refetch: () => void;

  returningId: number | null;
  markReturned: (loanId: number) => void;
}

export function useOverdue(): UseOverdueResult {
  const invalidate = useInvalidate();

  const overdue = useListOverdue({ page_size: PAGE_SIZE });

  // Only `enabled` is read from this one. The count beside it is the same
  // number as the list's `total` and is deliberately not used here: two
  // spellings of one figure on one screen is how they come to disagree.
  const channel = useMyOverdue({ query: { staleTime: 60_000 } });

  // `retry: false` so a member costs one request rather than four, and five
  // minutes because the record changes at most once an hour.
  const health = useGetSenderHealth({
    query: { retry: false, staleTime: 300_000 },
  });

  const returnLoan = useReturnLoan({
    mutation: { onSuccess: () => invalidate.loans() },
  });

  return {
    loans: overdue.data?.items ?? [],
    total: overdue.data?.total ?? 0,
    enabled: channel.data?.enabled ?? true,
    channels: deliveryRecord(health),

    isLoading: overdue.isPending,
    // The health query's error is deliberately absent: a member's 403 is the
    // expected answer there, and reporting it would put a permanent red box on
    // a page that loaded correctly.
    error: overdue.error ?? returnLoan.error,
    refetch: () => void overdue.refetch(),

    returningId: returnLoan.isPending
      ? (returnLoan.variables?.loanId ?? null)
      : null,
    markReturned: (loanId) => returnLoan.mutate({ loanId }),
  };
}

/**
 * Which of the three the health query is in.
 *
 * `403` is read off `ApiError.status` rather than treated as "any failure",
 * which is the shape `SettingsPage/hooks.ts` already uses for the same
 * endpoint family. Anything else that failed is reported, because the page
 * suppresses that query's error and would otherwise say nothing at all.
 */
function deliveryRecord(query: {
  isSuccess: boolean;
  data?: SenderHealth[];
  error: unknown;
}): DeliveryRecord {
  if (query.isSuccess && query.data) {
    return {
      state: "channels",
      channels: query.data.map((entry) => ({
        sender: entry.sender,
        health: entry,
      })),
    };
  }
  if (query.error instanceof ApiError && query.error.status === 403) {
    return { state: "hidden" };
  }
  return query.error == null ? { state: "hidden" } : { state: "unreadable" };
}
