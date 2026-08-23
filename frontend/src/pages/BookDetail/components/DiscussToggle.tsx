import type { BookOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface DiscussToggleProps {
  book: BookOut;
  /** Whose checkbox this is. Used to keep the reader out of their own list. */
  currentUserId: number;
  onChange: (wantsToDiscuss: boolean) => void;
}

/**
 * "Ask me about this book", and who else has said it.
 *
 * Beside the reading status rather than in the copy panel, because it is a
 * fact about a reader and not about the object: two people holding the same
 * copy can feel entirely differently about it, and the copy panel is about
 * what the household owns.
 *
 * The second line is what makes the first one worth ticking. A flag only its
 * owner can see is not a way to be asked about anything, so everybody who has
 * offered is named, and the reader is left out of that list: they know.
 */
export default function DiscussToggle({
  book,
  currentUserId,
  onChange,
}: DiscussToggleProps) {
  const { t } = useTranslation();
  const others = (book.discuss_with ?? []).filter(
    (member) => member.id !== currentUserId,
  );

  return (
    <div className="space-y-1.5">
      <label className="flex items-start gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={book.my_wants_to_discuss ?? false}
          onChange={(event) => onChange(event.target.checked)}
          className="mt-0.5 w-4 h-4 rounded border-paper-300 text-accent-600"
        />
        <span className="text-sm text-paper-600 dark:text-paper-300">
          {t("discuss.toggle")}
        </span>
      </label>

      {others.length > 0 && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("discuss.others", {
            names: others.map((member) => member.username).join(", "),
          })}
        </p>
      )}
    </div>
  );
}
