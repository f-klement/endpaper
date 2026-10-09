import { OverdueNotifyReason, OverdueSender } from "../api/generated/model";

import type { MessageKey } from "./index";

/**
 * One name per reminder channel, for every screen that draws a sender.
 *
 * **Here rather than in a page folder, because two pages need it.** It was
 * extracted out of `OverdueSection` into the Lending route's `types.ts` so the
 * per run report and the standing health record would share one table, and then
 * copied a third time into the library page's channel banner, which is the
 * duplication the extraction existed to stop. A page may not import another
 * page's internals, so the shared home is this one.
 *
 * `i18n/tagNames.ts` is the precedent: a lookup from a domain value to a message
 * key, owned by the catalogue rather than by any screen.
 *
 * A `Record` over the generated union rather than a chain of conditions, so a
 * sender added on the server is a compile error here rather than a blank line
 * where a channel's name should be.
 */
export const SENDER_LABELS: Record<OverdueSender, MessageKey> = {
  [OverdueSender.in_app]: "settings.overdueSenderInApp",
  [OverdueSender.webhook]: "settings.overdueSenderWebhook",
  [OverdueSender.email]: "settings.overdueSenderEmail",
  [OverdueSender.telegram]: "settings.overdueSenderTelegram",
};

/**
 * Each reason as a fragment that reads after a channel's name.
 *
 * **Here for the same reason as the table above, one ticket later.** It lived
 * in the Lending route's `types.ts` while the Lending route was the only screen
 * that drew a channel's health. The overdue page (#102) draws the same line, so
 * `SenderHealthLine` moved out to `pages/components/` and this moved with it:
 * a shared component may not import a page's internals either.
 *
 * **Fragments, not the whole-run sentences beside them.** Printed in a per
 * channel row those were wrong twice over: the email row read "Email: The
 * webhook could not be reached, so nothing was sent", and the Telegram row read
 * "Telegram: Nothing was sent. The message below says which", where that row is
 * the message below.
 *
 * `disabled`, `nothing_due` and `in_app_only` cannot appear against a channel,
 * because a sender entry exists only for a channel that was switched on and a
 * run that had something to send. They are given a fragment anyway: the
 * `Record` is exhaustive over the union, which is what makes a further reason a
 * compile error.
 */
export const SENDER_ROW_REASONS: Record<OverdueNotifyReason, MessageKey> = {
  [OverdueNotifyReason.disabled]: "settings.overdueRowDisabled",
  [OverdueNotifyReason.no_url]: "settings.overdueRowNoUrl",
  [OverdueNotifyReason.nothing_due]: "settings.overdueRowNothingDue",
  [OverdueNotifyReason.unreachable]: "settings.overdueRowUnreachable",
  [OverdueNotifyReason.misconfigured]: "settings.overdueRowMisconfigured",
  [OverdueNotifyReason.in_app_only]: "settings.overdueRowInAppOnly",
};
