import { Link } from "react-router-dom";

import type { CollectionOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface CollectionCardProps {
  collection: CollectionOut;
  isBusy: boolean;
  onRename: (collection: CollectionOut, name: string) => void;
  onDelete: (collection: CollectionOut) => void;
}

/**
 * One collection, how much of it this reader can see, and the two things that
 * can be done to it.
 *
 * The count is what the caller may see rather than what the shelf holds, which
 * is the same rule every other count in this app follows. The delete
 * confirmation says the number out loud, because "delete Ebooks" and "unfile
 * 214 books" are the same press and only one of them is obvious.
 */
export default function CollectionCard({
  collection,
  isBusy,
  onRename,
  onDelete,
}: CollectionCardProps) {
  const { t } = useTranslation();

  return (
    <div className="bg-paper-0 border border-paper-200 rounded-2xl p-4 dark:bg-paper-900 dark:border-paper-700">
      <h2 className="font-semibold text-paper-900 dark:text-paper-100">
        {collection.name}
      </h2>
      <p className="text-xs text-paper-600 mt-0.5 dark:text-paper-400">
        {t("collections.bookCount", { count: collection.book_count ?? 0 })}
      </p>

      <div className="flex flex-wrap gap-3 mt-3 text-xs">
        <Link
          to={`/?collection=${collection.id}`}
          className="text-accent-700 hover:underline dark:text-accent-400"
        >
          {t("collections.browse")}
        </Link>
        <button
          type="button"
          disabled={isBusy}
          onClick={() => {
            const name = prompt(t("collections.renamePrompt"), collection.name);
            // null is cancel and an empty string is nothing to rename to, and
            // neither is a request worth sending.
            if (name !== null && name.trim() !== "") {
              onRename(collection, name.trim());
            }
          }}
          className="text-paper-600 hover:underline disabled:opacity-40 dark:text-paper-400"
        >
          {t("collections.rename")}
        </button>
        <button
          type="button"
          disabled={isBusy}
          onClick={() => {
            if (
              confirm(
                t("collections.deleteConfirm", {
                  name: collection.name,
                  count: collection.book_count ?? 0,
                }),
              )
            ) {
              onDelete(collection);
            }
          }}
          className="text-danger-600 hover:underline disabled:opacity-40 dark:text-danger-300"
        >
          {t("collections.delete")}
        </button>
      </div>
    </div>
  );
}
