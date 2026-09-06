import type { AuthorMergeGroup } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface BatchBarProps {
  /**
   * Exactly what pressing the button would send.
   *
   * **The request itself, not the groups it came from**, because that is what
   * these counts describe. While it was the groups, a reader who unticked a
   * name inside a ticked group was shown the old number: the request carried
   * one key fewer and both the sentence and the confirmation still said the
   * old total. One source, so the number and the write cannot drift apart.
   */
  payload: AuthorMergeGroup[];
  /** Groups the server held back, which cannot be ticked. */
  heldBack: number;
  /** Groups the reader has narrowed past what the batch can send. */
  withdrawn: number;
  isMerging: boolean;
  onFold: () => void;
}

/**
 * Folding every proposed group in one request.
 *
 * **The one thing a reader has to be able to check before pressing it is how
 * much it is.** So the line beside the button carries both numbers, and the
 * confirm dialog repeats them: the groups, and the spellings, which is what is
 * actually written. A batch of four groups can be eight rows or eighty, and the
 * group count alone hides the difference.
 *
 * The button itself carries no number, because this app has no plural rules
 * engine and deliberately does not: see `i18n/index.tsx`. A label reading "Fold
 * 1 groups" is the cost of putting a count in a verb phrase, and a label is
 * where it reads worst. The sentence and the question still say "1 groups",
 * which is the same cost every count in this catalogue pays.
 *
 * It offers only what the cards below already show, and every card can be
 * unticked, because a batch nobody could narrow is a batch nobody could review.
 * The alternative shape, one button applying whatever the server proposed, was
 * refused for the reason `SuggestionCard` gives its names a checkbox each:
 * grouping is transitive, so the wrong answer must not be the easy one.
 *
 * **Two ways a group can be left out, counted apart because the reasons are
 * not the reader's to confuse.** Held back means the server would not fold it:
 * it carries no `keep_name`, because folding it would repoint a merge somebody
 * already made. Withdrawn means the reader narrowed it past what the batch can
 * send, by unticking the name it would keep or leaving fewer than two. One
 * number covering both would attribute the reader's own edit to somebody else's
 * merge.
 */
export default function BatchBar({
  payload,
  heldBack,
  withdrawn,
  isMerging,
  onFold,
}: BatchBarProps) {
  const { t } = useTranslation();
  const spellings = payload.reduce(
    (total, group) => total + group.keys.length,
    0,
  );

  function confirmAndFold() {
    if (
      confirm(
        t("authors.batchConfirm", {
          count: payload.length,
          spellings,
        }),
      )
    ) {
      onFold();
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-paper-200 bg-paper-0 p-3 dark:border-paper-700 dark:bg-paper-900">
      <p className="min-w-0 flex-1 text-sm text-paper-600 dark:text-paper-400">
        {t("authors.batchExplain", { count: payload.length, spellings })}
        {heldBack > 0 &&
          ` ${t("authors.batchHeldBackCount", { count: heldBack })}`}
        {withdrawn > 0 &&
          ` ${t("authors.batchWithdrawnCount", { count: withdrawn })}`}
      </p>
      <button
        type="button"
        disabled={isMerging || payload.length === 0}
        onClick={confirmAndFold}
        className="shrink-0 px-3 py-2 rounded-xl bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
      >
        {isMerging ? t("authors.merging") : t("authors.foldAll")}
      </button>
    </div>
  );
}
