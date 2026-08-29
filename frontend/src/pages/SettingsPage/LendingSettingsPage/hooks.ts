/**
 * Data access for the Lending route.
 *
 * Two hooks: running the overdue digest by hand, and the standing record of
 * what each channel last did. The settings the cards read and write are the
 * shared admin record, which stays in the settings root's `hooks.ts` because
 * four routes need it.
 */

import { useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { useNotifyOverdue } from "../../../api/generated/endpoints/loans/loans";
import {
  getGetSenderHealthQueryKey,
  useGetSenderHealth,
} from "../../../api/generated/endpoints/settings/settings";
import type {
  OverdueNotifyResult,
  OverdueSender,
  SenderHealth,
} from "../../../api/generated/model";

/**
 * Running the overdue digest by hand.
 *
 * The whole reason the endpoint exists: a webhook that only fires on an hourly
 * timer is a webhook nobody can tell they configured correctly. It reports
 * what it sent rather than "done", because "nothing is overdue" and "the
 * receiver refused it" are different answers and both look like silence.
 *
 * The result is held here rather than read from `mutation.data` at the call
 * site so the count survives the button being pressed again.
 */
export function useOverdueDigest() {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<OverdueNotifyResult | null>(null);

  const mutation = useNotifyOverdue({
    mutation: {
      onSuccess: (data: OverdueNotifyResult) => {
        setResult(data);
        // A manual run records itself, exactly as a tick does, so the lines
        // under each channel are stale the instant this returns. Dropped
        // rather than patched: the record carries a failure count and a start
        // date this response does not.
        void queryClient.invalidateQueries({
          queryKey: getGetSenderHealthQueryKey(),
        });
      },
    },
  });

  return {
    result,
    // `mutate`, not `mutateAsync`: nothing awaits it, and a rejected promise
    // nobody holds is an unhandled rejection. The failure renders from `error`.
    send: () => {
      setResult(null);
      mutation.mutate();
    },
    isSending: mutation.isPending,
    error: mutation.error,
  };
}

/**
 * What each switched-on channel last did, keyed by sender (#82).
 *
 * A map rather than the list the server sends, because every consumer asks
 * about one channel beside the fields that configure it. A channel that is off
 * is absent, which is what makes `SenderHealthLine` render nothing for it
 * without a second flag saying so.
 *
 * Empty while it loads and empty for a member, whose request is refused. That
 * is the same arrangement `useSettings` has, and this page is admin only
 * anyway; the fallback exists because the two requests do not land together.
 */
export function useSenderHealth(): Partial<
  Record<OverdueSender, SenderHealth>
> {
  const query = useGetSenderHealth({ query: { retry: false } });
  return Object.fromEntries(
    (query.data ?? []).map((entry: SenderHealth) => [entry.sender, entry]),
  );
}
