import { useMemo } from "react";

import { CatalogueSource } from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";
import { catalogueName } from "../../../lib/catalogueName";

/**
 * A list of catalogue names, joined in the reader's language.
 *
 * The same conjunction list the settings screen uses for registration groups,
 * and for the same reason: it gets "and" right in both languages and handles
 * one, two and three without a branch at the caller.
 */
export function useNameList(): Intl.ListFormat {
  const { locale } = useTranslation();
  return useMemo(
    () => new Intl.ListFormat(locale, { type: "conjunction" }),
    [locale],
  );
}

const ROSTER: ReadonlySet<string> = new Set(Object.values(CatalogueSource));

/**
 * The catalogues a merged row came from, by the names the settings show.
 *
 * `source` is `catalogue.Record.sources` joined with `+`, the catalogue that
 * led first. **A part the roster does not know is shown as sent rather than
 * dropped**: a row whose source vanished from the label would claim fewer
 * catalogues than answered, which is the one thing this line exists to state.
 */
function sourceNames(source: string, t: (key: MessageKey) => string): string[] {
  return source
    .split("+")
    .filter(Boolean)
    .map((part) =>
      ROSTER.has(part) ? t(catalogueName(part as CatalogueSource)) : part,
    );
}

/**
 * Which catalogues produced a candidate, or nothing where it does not say.
 * Both pickers on the scan page render it: the title search and the rapid
 * queue's file name candidates.
 *
 * **It wraps rather than truncates.** A row merged from three catalogues is
 * wider than a phone, and an ellipsis would hide the catalogue named last,
 * which is the fact this line exists to state.
 */
export default function MatchSource({ source }: { source: string }) {
  const { t } = useTranslation();
  const names = useNameList();
  const parts = sourceNames(source, t);
  if (parts.length === 0) return null;
  return (
    <span className="block text-xs text-paper-600 mt-0.5 dark:text-paper-400">
      {t("search.source.from", { names: names.format(parts) })}
    </span>
  );
}
