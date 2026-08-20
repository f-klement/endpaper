import type { ReactNode } from "react";

interface ChoiceTileProps {
  /** The thing being chosen, named. A preview cannot be named. */
  name: string;
  /** One line under the name: what this choice does, where that is not obvious. */
  hint?: string;
  /**
   * Small print, one line each: where the colours came from, and what was built
   * here rather than published. A list because Nord's light member carries both
   * and an attribution that disappeared whenever a note appeared would be an
   * attribution that vanishes exactly where it is most needed.
   */
  notes?: readonly string[];
  selected: boolean;
  onSelect: () => void;
  /** The preview itself. Sits above the name and fills the tile's width. */
  children: ReactNode;
}

/**
 * One cell of the picker: a preview, a name, and the state of being chosen.
 *
 * Both grids use it, which is the point. A palette tile and a wallpaper tile
 * differ only in what is drawn inside them, and drawn twice they drift: the
 * selected state stops meaning one thing, and a reader has to learn the screen
 * twice.
 *
 * The selected border is `accent-500` with a ring, the same pair a selected
 * book card uses and for the same measured reason: WCAG 1.4.11 asks 3:1 of a
 * non-text indicator, and that rung holds it in every palette in both modes.
 *
 * A button rather than a radio, because there is no form and nothing to submit.
 * `aria-pressed` is what says which one is on, and the group around it carries
 * the label.
 */
export default function ChoiceTile({
  name,
  hint,
  notes,
  selected,
  onSelect,
  children,
}: ChoiceTileProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`card overflow-hidden text-left w-full ${
        selected
          ? "border-accent-500 ring-2 ring-accent-500"
          : "card-interactive"
      }`}
    >
      {children}
      <span className="block px-3 py-2.5 border-t border-paper-200 dark:border-paper-800">
        <span className="block text-sm font-semibold text-paper-900 dark:text-paper-100">
          {name}
        </span>
        {hint && (
          <span className="block text-xs text-paper-600 dark:text-paper-400">
            {hint}
          </span>
        )}
        {notes?.map((note) => (
          <span
            key={note}
            className="block mt-1 text-[11px] leading-snug text-paper-600 dark:text-paper-400"
          >
            {note}
          </span>
        ))}
      </span>
    </button>
  );
}
