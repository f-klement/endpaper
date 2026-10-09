import { ReadStatus } from "../../../api/generated/model";
import { Icon, type IconName } from "../../../components";
import { useTranslation } from "../../../i18n";
import { STATUS_LABELS, STATUS_ORDER } from "../../types";

/**
 * A glyph per status, and the only fact about a status this file still owns.
 *
 * The names and the order come from `pages/types.ts`: this used to be one array
 * carrying all three, which made it a second copy of a table that is exhaustive
 * by type inside a list that was not. A `Record` and not a lookup with a
 * default, so a status added to the backend enum is a compile error here rather
 * than a button with a blank square where its glyph goes.
 */
const STATUS_ICONS: Record<ReadStatus, IconName> = {
  [ReadStatus.unread]: "list",
  [ReadStatus.want_to_read]: "bookmark",
  [ReadStatus.reading]: "book",
  [ReadStatus.read]: "check",
  [ReadStatus.did_not_finish]: "ban",
};

interface StatusPickerProps {
  current: ReadStatus;
  onChange: (status: ReadStatus) => void;
}

/**
 * The reader's own progress.
 *
 * Personal to whoever is signed in: a shared shelf does not mean shared
 * reading progress.
 */
export default function StatusPicker({ current, onChange }: StatusPickerProps) {
  const { t } = useTranslation();
  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-2 dark:text-paper-200">
        {t("status.mine")}
      </p>
      {/* One column per status on a wide row: a column short of that wrapped the
          last one onto a line of its own, which read as a different kind of
          control rather than the last of a set. The count is written out because
          Tailwind extracts class names statically and cannot see a computed one,
          so a status added to `STATUS_ORDER` has to be added here too. The
          picker's own test asserts the two agree, since nothing else would. */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {STATUS_ORDER.map((status) => (
          <button
            key={status}
            onClick={() => onChange(status)}
            aria-pressed={current === status}
            className={`py-2 rounded-lg text-sm font-medium border transition-colors ${
              current === status
                ? "bg-accent-fill border-accent-fill text-on-accent"
                : "border-paper-200 text-paper-600 hover:border-accent-300 bg-paper-0 " +
                  "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 " +
                  "dark:hover:border-accent-700"
            }`}
          >
            <Icon name={STATUS_ICONS[status]} className="w-4 h-4" />{" "}
            {t(STATUS_LABELS[status])}
          </button>
        ))}
      </div>
    </div>
  );
}
