import { useState } from "react";

import type {
  AuthorSuggestionOut,
  SuggestionReason,
} from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";

interface SuggestionCardProps {
  group: AuthorSuggestionOut;
  isMerging: boolean;
  onMerge: (keys: string[], keepName: string) => void;
}

/**
 * What the server said about a group, said in words a reader can weigh.
 *
 * **Keyed by `SuggestionReason` rather than by `string`, and that is the guard
 * rather than a tidy-up.** While this was `Record<string, MessageKey>` the
 * lookup below fell back to rendering the raw value, so a rule the server grew
 * and this map did not know showed a reader the bare word `identity` beside
 * `same name, spaced differently`. A fifth rule now fails `bun run typecheck`
 * here instead of shipping untranslated.
 */
const REASONS: Record<SuggestionReason, MessageKey> = {
  identity: "authors.reasonIdentity",
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
          .map((reason) => REASONS[reason])
          // **A reason this build does not know is dropped, never rendered
          // raw.** The type above makes that unreachable for a client and
          // server built together, and this is the version skew case: an older
          // page against a newer API used to print the bare value, which is how
          // `identity` reached a reader as a debug string.
          //
          // **Both the whole line and part of it are dropped this way**, and
          // the partial case is the one worth being clear about: a group built
          // by a known rule and an unknown one renders only the known reason,
          // so the reader is told less than the group's edges support. Taken
          // deliberately. Every name keeps its own checkbox and a merge is
          // reversible, so under-explaining a reversible action beats printing
          // a word that means nothing to a reader, and the window is a skew
          // window rather than a steady state.
          .filter((key) => key !== undefined)
          .map((key) => t(key))
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
