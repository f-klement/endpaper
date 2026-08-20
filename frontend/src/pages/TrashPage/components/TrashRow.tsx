import type { BookOut } from "../../../api/generated/model";
import { Button, Icon } from "../../../components";
import { useTranslation } from "../../../i18n";

interface TrashRowProps {
  book: BookOut;
  isBusy: boolean;
  onRestore: () => void;
  onPurge: () => void;
}

/**
 * One deleted book, with the two things that can happen to it.
 *
 * Restore is the primary action and delete-for-good is a quiet one. That is
 * the right way round: somebody opens the trash because they want something
 * back, and the destructive verb should not be the easiest thing to hit on the
 * page whose whole purpose is undoing a destructive verb.
 */
export default function TrashRow({
  book,
  isBusy,
  onRestore,
  onPurge,
}: TrashRowProps) {
  const { t } = useTranslation();
  const deletedOn = book.deleted_at
    ? new Date(book.deleted_at).toLocaleDateString()
    : null;

  return (
    <li className="flex items-center gap-3 rounded-xl border border-paper-200 p-3 dark:border-paper-800">
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-paper-900 dark:text-paper-100">
          {book.title}
        </span>
        {book.author && (
          <span className="block truncate text-xs text-paper-500 dark:text-paper-400">
            {t("book.by", { author: book.author })}
          </span>
        )}
        {deletedOn && (
          <span className="mt-0.5 block text-xs text-paper-400 dark:text-paper-500">
            {t("trash.deletedOn", { date: deletedOn })}
          </span>
        )}
      </span>

      <Button
        size="sm"
        variant="secondary"
        isLoading={isBusy}
        onClick={onRestore}
        icon={<Icon name="undo" className="h-4 w-4" />}
      >
        {t("trash.restore")}
      </Button>
      <button
        type="button"
        disabled={isBusy}
        onClick={() => {
          if (confirm(t("trash.deleteForeverConfirm", { title: book.title })))
            onPurge();
        }}
        className="shrink-0 text-xs text-paper-400 underline hover:text-bloom-600 disabled:opacity-50 dark:text-paper-500 dark:hover:text-bloom-300"
      >
        {t("trash.deleteForever")}
      </button>
    </li>
  );
}
