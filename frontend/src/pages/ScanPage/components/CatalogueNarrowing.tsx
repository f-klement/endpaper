import type { CatalogueSource } from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";
import { catalogueName } from "../../../lib/catalogueName";
import { useNameList } from "./MatchSource";

interface CatalogueNarrowingProps {
  /**
   * The catalogues this library asks on this path, in its order. The server
   * refuses a narrowing naming any other, so nothing else is offered.
   */
  catalogues: CatalogueSource[];
  /** The ones ticked. Empty asks every catalogue, as an unnarrowed request does. */
  chosen: CatalogueSource[];
  onChange: (chosen: CatalogueSource[]) => void;
  /** Which request the ticks apply to, said under the boxes. */
  hint: MessageKey;
}

/**
 * "Ask only these", for one lookup or one search, in library mode.
 *
 * **Never stored.** The state is the page's and goes with the request it
 * narrows, because the institution's standing list is the policy and this is a
 * cataloguer's judgement about one book. Nothing is offered where there is
 * nothing to narrow: a library asking one catalogue on this path has no choice
 * to make.
 */
export default function CatalogueNarrowing({
  catalogues,
  chosen,
  onChange,
  hint,
}: CatalogueNarrowingProps) {
  const { t } = useTranslation();
  const names = useNameList();
  if (catalogues.length < 2) return null;

  function toggle(source: CatalogueSource) {
    // Kept in the library's order rather than the order of the clicks, so the
    // request reads the same however the boxes were ticked.
    const next = chosen.includes(source)
      ? chosen.filter((held) => held !== source)
      : catalogues.filter((one) => one === source || chosen.includes(one));
    onChange(next);
  }

  return (
    <details className="mt-2 text-sm text-paper-700 dark:text-paper-300">
      <summary className="cursor-pointer text-xs text-paper-600 dark:text-paper-400">
        {chosen.length > 0
          ? t("search.narrow.chosen", {
              names: names.format(
                chosen.map((source) => t(catalogueName(source))),
              ),
            })
          : t("search.narrow.title")}
      </summary>
      <fieldset className="mt-2">
        <legend className="sr-only">{t("search.narrow.title")}</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {catalogues.map((source) => (
            <label key={source} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={chosen.includes(source)}
                onChange={() => toggle(source)}
              />
              {t(catalogueName(source))}
            </label>
          ))}
        </div>
        <p className="mt-1 text-xs text-paper-600 dark:text-paper-400">
          {t(hint)}
        </p>
      </fieldset>
    </details>
  );
}

/**
 * The line beside an answer saying which catalogues its request was narrowed
 * to, or nothing where it asked every one.
 *
 * **The ticks are spent by the request they narrow**, so once an answer is on
 * screen the boxes are empty again. Without this, an empty narrowed answer
 * reads as no catalogue having the book, and a cataloguer types it in by hand.
 */
export function NarrowedTo({ asked }: { asked: CatalogueSource[] }) {
  const { t } = useTranslation();
  const names = useNameList();
  if (asked.length === 0) return null;
  return (
    <p className="mt-2 text-xs text-paper-600 dark:text-paper-400">
      {t("search.narrow.asked", {
        names: names.format(asked.map((source) => t(catalogueName(source)))),
      })}
    </p>
  );
}
