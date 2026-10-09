import { Link } from "react-router-dom";

import type { OverdueSender } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { SENDER_LABELS } from "../../../i18n/senderNames";

interface ChannelAlertBannerProps {
  /** Only the channels the server already decided are broken. */
  senders: OverdueSender[];
}

/**
 * A reminder channel has stopped working, said on a screen somebody passes (#82).
 *
 * **The bar for using this surface is high and the server is what holds it.**
 * One failed send is a network; every send failing for a day is a
 * configuration, and a banner that cannot tell them apart is one a household
 * switches off. `notifications._is_broken` makes that call: a refusal the app
 * decided itself at once, a transport failure only after 24 hours and at least
 * two consecutive failures. This component renders the verdict and does not
 * second-guess it, because the evidence it turns on lives in the health record
 * rather than in this payload.
 *
 * Admin only in effect rather than by a prop: the endpoint behind it answers
 * 403 to anybody else, so a member's query fails and this renders nothing. That
 * is the same arrangement `useSettings` already has, and it keeps the library
 * page from needing to know who is reading it.
 *
 * The amber pairing, matching `UnconfirmedBanner`: this is something to see to,
 * not something that has gone wrong with the reader's own books. Measured:
 * amber-800 on amber-50 is 6.84:1, amber-900 on amber-50 for the link is
 * 8.75:1, and amber-200 on amber-950 in dark is 12.03:1.
 */
export default function ChannelAlertBanner({
  senders,
}: ChannelAlertBannerProps) {
  const { t } = useTranslation();

  if (senders.length === 0) return null;

  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 dark:border-amber-900 dark:bg-amber-950">
      <p className="text-sm text-amber-800 dark:text-amber-200">
        {/* No count in the sentence: this catalogue has no plural forms, so
            every phrase has to read for one and for several. Naming the
            channels does that and says more. */}
        {t("library.channelBroken", {
          channels: senders
            .map((sender) => t(SENDER_LABELS[sender]))
            .join(", "),
        })}
      </p>
      <Link
        to="/settings/lending"
        className="shrink-0 text-xs font-medium text-amber-900 underline hover:no-underline dark:text-amber-200"
      >
        {t("library.channelBrokenAction")}
      </Link>
    </div>
  );
}
