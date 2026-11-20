import type { PatronOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { numericDate } from "../../../lib/date";
import { hasExpired } from "../types";

interface PatronRowProps {
  patron: PatronOut;
  /** Today where the reader is, `YYYY-MM-DD`, which decides "expired". */
  today: string;
  isBusy: boolean;
  onEdit: (patron: PatronOut) => void;
  onDelete: (patron: PatronOut) => void;
}

/**
 * One patron: who, which card, how to reach them, and whether the
 * registration still holds.
 *
 * **A lapsed registration says so in words**, not by colour alone, so the
 * state survives a reader who cannot tell the two hues apart.
 *
 * The delete confirmation says what the erasure does to the loan history,
 * because "delete this person" reads as though their loans go too, and what
 * actually happens is the opposite trade: the person goes, the dates stay.
 */
export default function PatronRow({
  patron,
  today,
  isBusy,
  onEdit,
  onDelete,
}: PatronRowProps) {
  const { t, locale } = useTranslation();
  const expired = hasExpired(patron, today);
  const address = [
    [patron.street, patron.house_number].filter(Boolean).join(" "),
    [patron.postcode, patron.city].filter(Boolean).join(" "),
  ]
    .filter((line) => line !== "")
    .join(", ");
  const contact = [patron.email, patron.phone, address].filter(Boolean);

  return (
    <li className="bg-paper-0 border border-paper-200 rounded-2xl p-4 dark:bg-paper-900 dark:border-paper-700">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold text-paper-900 dark:text-paper-100">
          {patron.name}
        </h2>
        <span className="text-xs font-mono text-paper-600 dark:text-paper-400">
          {t("patrons.card", { number: patron.card_number })}
        </span>
      </div>

      {contact.map((line) => (
        <p
          key={line}
          className="text-sm text-paper-700 mt-0.5 break-words dark:text-paper-300"
        >
          {line}
        </p>
      ))}

      <p
        className={
          expired
            ? "text-xs font-medium text-danger-600 mt-2 dark:text-danger-300"
            : "text-xs text-paper-600 mt-2 dark:text-paper-400"
        }
      >
        {patron.expires_on == null
          ? t("patrons.noExpiry")
          : t(expired ? "patrons.expiredOn" : "patrons.validUntil", {
              date: numericDate(patron.expires_on, locale),
            })}
      </p>

      <div className="flex flex-wrap gap-3 mt-3 text-xs">
        <button
          type="button"
          disabled={isBusy}
          onClick={() => onEdit(patron)}
          className="text-paper-600 hover:underline disabled:opacity-40 dark:text-paper-400"
        >
          {t("common.edit")}
        </button>
        <button
          type="button"
          disabled={isBusy}
          onClick={() => {
            if (confirm(t("patrons.deleteConfirm", { name: patron.name }))) {
              onDelete(patron);
            }
          }}
          className="text-danger-600 hover:underline disabled:opacity-40 dark:text-danger-300"
        >
          {t("common.delete")}
        </button>
      </div>
    </li>
  );
}
