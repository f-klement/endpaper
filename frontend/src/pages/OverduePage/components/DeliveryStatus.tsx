import { SenderHealthLine } from "../../components";
import { useTranslation } from "../../../i18n";
import { SENDER_LABELS } from "../../../i18n/senderNames";
import type { DeliveryRecord } from "../types";

interface DeliveryStatusProps {
  record: DeliveryRecord;
}

/**
 * What the reminder channels have been doing, beside the loans they are about
 * (#102).
 *
 * **This describes a channel, never a loan, and the wording is the only thing
 * holding that.** `SettingKey.SENDER_HEALTH` is written once per sender per
 * run: `notifications.record_run` stores whether each channel's request
 * succeeded and nothing about which loans were in the message. There is no loan
 * id anywhere in the record, so "this book's reminder did not arrive" is not a
 * sentence this data can support, and a per loan per sender table is recorded
 * in `docs/decisions.md` as more than this feature warrants.
 *
 * So the note above the lines says so in as many words. A reader who takes
 * "Telegram is not working" as "the borrower of the book above was not told"
 * has read something true; a reader who takes it as "and every other borrower
 * was" has not, and only the note stops that.
 *
 * **The empty line says what no channel does, and no longer what this page
 * does.** It ended "They appear here, and nowhere else", which is a claim about
 * the in app channel, and `notifications.health` never consults that channel's
 * switch: with the switch off the panel promised the loans appeared here while
 * the list three lines below said the reminder was switched off. Both sentences
 * rendered together. What survives is the half this record can answer.
 *
 * The lines themselves are `SenderHealthLine`, the same component the Lending
 * settings screen draws under each switch. One fact, two questions: settings is
 * where a channel is repaired, this is where somebody asks whether the
 * household's reminders are going out at all.
 */
export default function DeliveryStatus({ record }: DeliveryStatusProps) {
  const { t } = useTranslation();

  if (record.state === "hidden") return null;

  return (
    <section className="card p-4 mb-4">
      <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-200">
        {t("overdue.deliveryTitle")}
      </h2>
      <p className="mt-1 text-xs text-paper-600 dark:text-paper-400">
        {t("overdue.deliveryNote")}
      </p>

      {record.state === "unreadable" ? (
        // Reported rather than drawn as an empty panel. The page keeps this
        // query's error out of its own error slot, because a member's 403 is
        // the expected answer there, so without this line a failure that is
        // not a refusal is silent.
        <p className="mt-3 text-xs font-medium text-amber-800 dark:text-amber-300">
          {t("overdue.deliveryUnreadable")}
        </p>
      ) : record.channels.length === 0 ? (
        <p className="mt-3 text-xs text-paper-600 dark:text-paper-400">
          {t("overdue.deliveryNone")}
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {record.channels.map(({ sender, health }) => (
            <li key={sender}>
              <p className="text-xs font-medium text-paper-900 dark:text-paper-200">
                {t(SENDER_LABELS[sender])}
              </p>
              <SenderHealthLine health={health} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
