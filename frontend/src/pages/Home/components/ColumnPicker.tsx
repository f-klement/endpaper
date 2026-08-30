import { useId, useState } from "react";

import { Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import {
  ALWAYS_SHOWN,
  COLUMN_SPECS,
  type ColumnKey,
} from "../../../lib/libraryColumns";

interface ColumnPickerProps {
  /** Every column this mode offers, in the order the table draws them. */
  available: readonly ColumnKey[];
  /** The ones currently drawn. A subset of `available`. */
  visible: readonly ColumnKey[];
  onToggle: (key: ColumnKey) => void;
  /** Forget the choice and go back to this mode's default set. */
  onReset: () => void;
  /** False while the current set already is the default. */
  canReset: boolean;
}

/**
 * Which of the table's columns to draw.
 *
 * **Shaped like the tag and classification panels**, a pill that opens a strip
 * of chips, because it sits in the same place doing the same kind of thing:
 * narrowing what is on screen. A menu of checkboxes would be the third
 * interaction for the second concept on one page.
 *
 * **Drawn only over the table view.** The grid and the dense list have no
 * columns to choose, and a control that does nothing where it is shown is
 * worse than one that is not there: the reader presses it once and learns the
 * page lies.
 *
 * **The title chip is drawn and disabled rather than left out.** Leaving it
 * out makes the picker's list disagree with the table's headers, and the
 * reader looking for the column they cannot find has no way to learn that it
 * is not their mistake. `aria-disabled` and the hint below say why.
 */
export default function ColumnPicker({
  available,
  visible,
  onToggle,
  onReset,
  canReset,
}: ColumnPickerProps) {
  const { t } = useTranslation();
  const panelId = useId();
  // Closed on arrival. Somebody who has chosen their columns is not choosing
  // them again on every visit, and open by default would push the first row of
  // the table off a phone screen.
  const [open, setOpen] = useState(false);

  const shown = new Set<ColumnKey>(visible);

  return (
    <div className="mb-2">
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          aria-controls={panelId}
          className="inline-flex items-center gap-1.5 rounded-full border border-paper-200 bg-paper-0 px-3 py-1 text-xs text-paper-600 transition-colors hover:border-accent-300 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-300 dark:hover:border-accent-700"
        >
          <Icon
            name="chevron"
            aria-hidden="true"
            className={`h-3 w-3 transition-transform duration-150 ${
              open ? "rotate-90" : ""
            }`}
          />
          {t("columns.label")}
          <span className="opacity-70">
            {t("columns.summary", {
              shown: visible.length,
              total: available.length,
            })}
          </span>
        </button>
      </div>

      {/* Hidden rather than unmounted, which is the rule `CollapsibleSection`
          states and the reason is `aria-controls` on the button above: it has
          to point at an element that exists or the relationship it describes is
          a dangling id. `hidden` keeps the panel out of the accessibility tree
          and out of the tab order, which is the part that matters. */}
      <div
        id={panelId}
        role="group"
        aria-label={t("columns.label")}
        hidden={!open}
        className="mt-2 rounded-lg border border-paper-200 bg-paper-0 p-2.5 dark:border-paper-800 dark:bg-paper-900"
      >
        <div className="flex flex-wrap gap-1.5">
          {available.map((key) => {
            const locked = key === ALWAYS_SHOWN;
            const chosen = shown.has(key);
            return (
              <button
                key={key}
                type="button"
                aria-pressed={chosen}
                // No `opacity` on the locked chip. `opacity` on the button
                // composites the fill and its text together, which lowered
                // `on-accent` on `accent-fill` from 4.78:1 to 2.83:1 light
                // and 5.98:1 to 3.52:1 dark, against the 4.5 floor
                // `palettes.test.ts` holds for that pair. That dark figure is
                // the exact regression `index.css` records the `accent-fill`
                // tokens as existing to stop. `aria-disabled` and the note
                // below the chips say it is locked, in words.
                aria-disabled={locked || undefined}
                onClick={locked ? undefined : () => onToggle(key)}
                className={`inline-flex items-baseline gap-1.5 rounded-full border px-2 py-1 text-xs transition-colors ${
                  chosen
                    ? "border-accent-fill bg-accent-fill text-on-accent"
                    : "border-paper-200 bg-paper-0 text-paper-600 hover:border-accent-300 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-300 dark:hover:border-accent-700"
                } ${locked ? "cursor-default" : ""}`}
              >
                {t(COLUMN_SPECS[key].label)}
              </button>
            );
          })}
        </div>

        <div className="mt-2 flex items-baseline justify-between gap-2">
          <p className="text-xs text-paper-600 dark:text-paper-400">
            {t("columns.alwaysShown")}
          </p>
          {canReset && (
            <button
              type="button"
              onClick={onReset}
              className="shrink-0 text-xs text-accent-700 hover:underline dark:text-accent-300"
            >
              {t("columns.reset")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
