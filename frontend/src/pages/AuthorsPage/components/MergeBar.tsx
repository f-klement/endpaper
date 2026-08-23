import { useState, type FormEvent } from "react";

import type { AuthorOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface MergeBarProps {
  selected: AuthorOut[];
  isMerging: boolean;
  onMerge: (keys: string[], keepName: string) => void;
  onClear: () => void;
}

/**
 * Folding names together by hand, for the pairs no rule proposes.
 *
 * **This is the deduplication path, not a shortcut past it.** The suggestion
 * rules catch a spelling, an initial and a fragment, and a misspelling is none
 * of those: `Tolkein` against `Tolkien` shares no word, no initial pattern and
 * no squashed key, so nothing offers it and there is otherwise no way to say
 * they are one person. A misspelling is the first case `models.AuthorAlias`
 * names as what an alias records, so leaving the only entry point behind a
 * heuristic left the feature reachable only where a guess had already been
 * made for you.
 *
 * One selected name is a **rename**: fold this spelling into a name typed by
 * hand. That is the same write, and it was unreachable for the same reason.
 *
 * Sticky at the bottom, like the library's selection bar and for the same
 * reason: the list is scrolled with a thumb and the action belongs where the
 * thumb already is.
 */
export default function MergeBar({
  selected,
  isMerging,
  onMerge,
  onClear,
}: MergeBarProps) {
  const { t } = useTranslation();
  const [otherName, setOtherName] = useState("");
  const keys = selected.map((author) => author.key);
  // One selected name is a rename, and it is worth saying so: "Or a name none
  // of them has" has no referent when there is one of them, and "Fold 1
  // spellings into X" describes the write in a vocabulary that only makes
  // sense for two. The write is identical; only the words change.
  const isRename = selected.length === 1;

  function confirmAndMerge(keepName: string) {
    // One of the selected names is kept, so one fewer spelling moves. The
    // count is the last checkable fact a reader gets: a native `confirm()`
    // covers the page, and the selection deliberately survives the search box,
    // so the names being folded can be off screen.
    if (
      confirm(t("authors.confirm", { count: keys.length - 1, name: keepName }))
    ) {
      onMerge(keys, keepName);
    }
  }

  function submitOther(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Collapsed, not merely trimmed, because the server collapses internal
    // whitespace before storing (`AuthorMergeRequest.tidy`). Sending the raw
    // string meant "Ursula K.  Le Guin" came back as "Ursula K. Le Guin",
    // which differs from what was typed, and the page announced that the merge
    // had gone somewhere else when it had gone exactly where it was asked.
    const trimmed = otherName.trim().replace(/\s+/g, " ");
    if (!trimmed) return;
    // A typed name keeps none of them, so every selected spelling moves.
    const question = isRename
      ? t("authors.renameConfirm", {
          from: selected[0]?.name ?? "",
          name: trimmed,
        })
      : t("authors.confirm", { count: keys.length, name: trimmed });
    if (confirm(question)) {
      onMerge(keys, trimmed);
      setOtherName("");
    }
  }

  return (
    <div className="sticky bottom-0 z-40 -mx-4 px-4 py-3 bg-paper-0/95 backdrop-blur-sm border-t border-paper-200 dark:bg-paper-900/95 dark:border-paper-700">
      <div className="max-w-3xl mx-auto space-y-2">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-paper-700 dark:text-paper-200">
            {t("authors.selectedCount", { count: selected.length })}
          </span>
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-paper-600 hover:underline dark:text-paper-400"
          >
            {t("common.clearSelection")}
          </button>
        </div>

        {/* Keeping one of the selected names needs at least two of them, or
            the merge is a name folding into itself. With one selected the
            field below is the whole action, and it is a rename. */}
        {selected.length > 1 && (
          <div className="flex flex-wrap gap-2">
            {selected.map((author) => (
              <button
                key={author.key}
                type="button"
                disabled={isMerging}
                onClick={() => confirmAndMerge(author.name)}
                className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
              >
                {isMerging
                  ? t("authors.merging")
                  : t("authors.keepNamed", { name: author.name })}
              </button>
            ))}
          </div>
        )}

        <form onSubmit={submitOther} className="flex gap-2">
          <input
            type="text"
            value={otherName}
            onChange={(event) => setOtherName(event.target.value)}
            placeholder={t("authors.otherNamePlaceholder")}
            aria-label={t(
              isRename ? "authors.renameName" : "authors.otherName",
            )}
            maxLength={300}
            className="flex-1 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          />
          <button
            type="submit"
            disabled={isMerging || otherName.trim() === ""}
            className="px-3 py-2 rounded-xl border border-paper-200 text-xs font-medium hover:border-accent-300 disabled:opacity-40 transition-colors dark:border-paper-700"
          >
            {t(isRename ? "authors.rename" : "authors.mergeIntoOther")}
          </button>
        </form>
      </div>
    </div>
  );
}
