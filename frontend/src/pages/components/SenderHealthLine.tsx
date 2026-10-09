import type { SenderHealth } from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import { SENDER_ROW_REASONS } from "../../i18n/senderNames";

interface SenderHealthLineProps {
  /** Undefined while the record loads, and for a channel that is switched off. */
  health: SenderHealth | undefined;
}

/**
 * What this channel has been doing, under the fields that configure it (#82).
 *
 * **The half of the ticket that does the work.** The banner on the library page
 * is the interrupt and has a deliberately high bar; this line is always here,
 * and it is what a household reads when they come to ask "is this working". Its
 * absence was the actual gap: a failure existed only on the run that produced
 * it, and once an hourly tick had stamped a loan on any one success, pressing
 * "Send now" inside the reminder window answered "nothing is overdue" and
 * showed nothing at all about the channel that was broken.
 *
 * Four states, and they are four rather than two because "not yet" and "fine"
 * are the pair a household most needs to tell apart on the day they configure a
 * channel, and "failed once" and "failing since Tuesday" are the pair they need
 * afterwards.
 *
 * **Two screens draw it, which is why it lives here** rather than inside the
 * Lending route: settings is where a channel is repaired, and the overdue page
 * (#102) is where somebody asks whether the household's reminders are going out
 * at all. One fact, two questions, one component.
 *
 * **Not "whether a borrower was told", which this cannot answer and an earlier
 * version of this comment claimed it did.** The health record is written once
 * per channel per run and carries no loan id, so no screen built on it can name
 * a person who was or was not reached. `overdue.deliveryNote` exists to say
 * that in as many words, and a docstring promising the opposite in the shared
 * component is where the next reader would pick the wrong framing up.
 *
 * **Not drawn for the in app channel**, which is why `ReminderSendersSection`
 * passes it nothing: that channel hands the digest to nobody, so `sent` is never
 * false for it and this line could only ever read "working". A line that cannot
 * say anything but one thing reports nothing, and "working" beside a channel
 * whose delivery was never checked is worse than nothing: it implies a check.
 */
export default function SenderHealthLine({ health }: SenderHealthLineProps) {
  const { t, locale } = useTranslation();

  if (health === undefined) return null;

  // The year is in it, and that is the point of the line rather than a
  // detail. A record is cleared by writing to the channel's settings and by
  // nothing else: no run clears it, because a run records only the senders it
  // attempted and a household with nothing overdue attempts none. So a
  // standing failure can be months old, and "since 20 August" on a date that
  // is really last year reads as fresh evidence for something that is not.
  const when = (iso: string | null | undefined) =>
    iso === null || iso === undefined
      ? ""
      : new Date(iso).toLocaleDateString(locale, {
          day: "numeric",
          month: "long",
          year: "numeric",
        });

  // `sent` is null until the channel has run at all, so this is checked before
  // the two below rather than folded into a falsy test: `false` and `null` are
  // different answers and reading them as one would report a fresh channel as
  // broken.
  if (health.sent === null || health.sent === undefined) {
    return <Line tone="quiet">{t("settings.senderHealthNotYet")}</Line>;
  }

  if (health.sent) {
    return (
      <Line tone="quiet">
        {t("settings.senderHealthWorking", { when: when(health.last_run_at) })}
      </Line>
    );
  }

  const detail = t(
    health.reason
      ? SENDER_ROW_REASONS[health.reason]
      : "settings.overdueRowNothingSent",
  );

  // Broken is the server's verdict, not a threshold recomputed here: a refusal
  // the app decided itself counts at once, a transport failure only after a day
  // and at least two consecutive failures. The evidence is in the record.
  if (health.broken) {
    return (
      <Line tone="loud">
        {t("settings.senderHealthBroken", {
          detail,
          since: when(health.failing_since),
          when: when(health.last_run_at),
        })}
      </Line>
    );
  }

  return (
    <Line tone="quiet">{t("settings.senderHealthFailedOnce", { detail })}</Line>
  );
}

/**
 * The two tones this line has: a note, and something to see to.
 *
 * **No `role="status"`.** This is static text describing a standing record, and
 * a live region that is present and populated on every render is announced on
 * mount for no event: three of them on one screen is three interruptions before
 * the reader has done anything. The send now result in `OverdueSection` keeps
 * its own, because that one appears in answer to a button being pressed.
 */
function Line({
  tone,
  children,
}: {
  tone: "quiet" | "loud";
  children: string;
}) {
  return (
    <p
      className={
        tone === "loud"
          ? // amber-800 on the card's own background rather than a filled
            // box: this sits inside a card that already has one. Measured:
            // amber-800 on paper-0 (#ffffff) is 7.09:1, and amber-300 on
            // paper-900 (#1c1916) in dark is 12.14:1.
            "text-xs font-medium text-amber-800 dark:text-amber-300"
          : "text-xs text-paper-600 dark:text-paper-400"
      }
    >
      {children}
    </p>
  );
}
