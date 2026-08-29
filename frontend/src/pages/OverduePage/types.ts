import type { OverdueSender, SenderHealth } from "../../api/generated/model";

/**
 * One channel's standing record, paired with the channel it is about.
 *
 * **The pairing is the whole type, and it exists because the two halves come
 * from different places.** The record arrives from the server keyed by sender;
 * the name comes from `i18n/senderNames.ts`. Carrying them separately down to
 * the row is what let the library page's banner print one channel's name beside
 * another's failure, twice, before `SENDER_ROW_REASONS` was extracted.
 */
export interface DeliveryChannel {
  sender: OverdueSender;
  health: SenderHealth;
}

/**
 * What the page knows about the reminder channels, which is one of three
 * things rather than a list or the absence of one.
 *
 * **`null` collapsed three cases into one and two of them are not the same
 * news.** `GET /api/settings/sender-health` is admin only, so a member's 403 is
 * the expected answer and drawing nothing is right; the first render before it
 * answers is also nothing, and also right. A 500 is neither: an admin then sees
 * a page that loaded, no panel, and no indication that anything failed, because
 * this page deliberately keeps that query's error out of its own error slot.
 *
 * Three named states rather than a nullable list beside a boolean, so a caller
 * cannot render two of them at once and every arm has to be answered.
 */
export type DeliveryRecord =
  /** Loading, or a viewer the endpoint refuses. Draw nothing. */
  | { state: "hidden" }
  /** The request failed for a reason that is not a refusal. Say so. */
  | { state: "unreadable" }
  /** Read. Empty means no channel that pushes is switched on. */
  | { state: "channels"; channels: DeliveryChannel[] };
