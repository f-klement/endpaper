/**
 * Data access for the Lending route.
 *
 * One hook: running the overdue digest by hand. The settings the two cards
 * read and write are the shared admin record, which stays in the settings
 * root's `hooks.ts` because four routes need it.
 */

import { useState } from "react";

import { useNotifyOverdue } from "../../../api/generated/endpoints/loans/loans";
import type { OverdueNotifyResult } from "../../../api/generated/model";

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
  const [result, setResult] = useState<OverdueNotifyResult | null>(null);

  const mutation = useNotifyOverdue({
    mutation: { onSuccess: (data: OverdueNotifyResult) => setResult(data) },
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
