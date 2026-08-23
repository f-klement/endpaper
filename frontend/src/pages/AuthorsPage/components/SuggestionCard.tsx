import { useState } from "react";

import type { AuthorSuggestionOut } from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";

interface SuggestionCardProps {
  group: AuthorSuggestionOut;
  isMerging: boolean;
  onMerge: (keys: string[], keepName: string) => void;
}

/** What the server said about a group, said in words a reader can weigh. */
const REASONS: Record<string, MessageKey> = {
  spelling: "authors.reasonSpelling",
  initials: "authors.reasonInitials",
  fragment: "authors.reasonFragment",
};

/**
 * One group of names that are probably one person.
 *
 * **Every name has a checkbox, and that is not decoration.** The grouping is
 * transitive, so `J. Smith` pulls `John Smith` and `James Smith` into one
 * group even though the last two are two people. Offering the group as a
 * single button would make the wrong answer the easy one.
 *
 * One way to finish: keep one of the names. Typing a third belongs to the
 * merge bar, not here, and this card used to offer it as well. Every key in a
 * group also has a card with a checkbox, so the bar reaches the same write
 * with the same two strings, and the duplicate cost a text field and a button
 * on a surface that is already the busiest on the page. The catalogue-order
 * repair ("Le Guin, Ursula K." split into two people, neither spelled
 * correctly) is still one selection and one typed name away.
 */
export default function SuggestionCard({
  group,
  isMerging,
  onMerge,
}: SuggestionCardProps) {
  const { t } = useTranslation();
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  const included = group.keys.filter((key) => !excluded.has(key));
  const nameFor = (key: string) => group.names[group.keys.indexOf(key)] ?? key;

  function toggle(key: string) {
    setExcluded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function confirmAndMerge(keepName: string, keys: string[]) {
    if (keys.length < 2) return;
    if (
      confirm(t("authors.confirm", { count: keys.length - 1, name: keepName }))
    ) {
      onMerge(keys, keepName);
    }
  }

  return (
    <div className="bg-paper-0 border border-paper-200 rounded-2xl p-4 space-y-3 dark:bg-paper-900 dark:border-paper-700">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {group.reasons
          .map((reason) => (REASONS[reason] ? t(REASONS[reason]) : reason))
          .join(" · ")}
      </p>

      <ul className="space-y-2">
        {group.keys.map((key) => (
          <li
            key={key}
            className="flex items-center gap-3 border border-paper-100 rounded-xl p-2 dark:border-paper-800"
          >
            <input
              type="checkbox"
              checked={!excluded.has(key)}
              onChange={() => toggle(key)}
              aria-label={t("authors.include", { name: nameFor(key) })}
              className="shrink-0"
            />
            <span className="min-w-0 flex-1 text-sm text-paper-900 truncate dark:text-paper-100">
              {nameFor(key)}
            </span>
            <button
              type="button"
              disabled={isMerging || excluded.has(key) || included.length < 2}
              onClick={() => confirmAndMerge(nameFor(key), included)}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
            >
              {isMerging ? t("authors.merging") : t("authors.keepThis")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
