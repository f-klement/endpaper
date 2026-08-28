import type { ReactNode } from "react";

import Icon from "./Icon";

interface CollapsibleSectionProps {
  /** Unique on the page. Wires the handle to the panel it controls. */
  id: string;
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  children: ReactNode;
}

/**
 * A labelled group of controls that can be folded away.
 *
 * A real disclosure: a `<button>` carrying `aria-expanded` and `aria-controls`,
 * so it is reachable by Tab, activated by Enter and Space without a keydown
 * handler, and announced as expanded or collapsed. A div with an onClick is
 * none of those things.
 *
 * **The panel stays in the DOM and is hidden with the `hidden` attribute**
 * rather than unmounted. Three reasons, and the first is why it is not a
 * preference: `aria-controls` must point at an element that exists, or the
 * relationship it describes is a dangling id. Unmounting would also throw away
 * whatever is half typed in a form inside the section, so collapsing by
 * accident would lose a note; and it is no more DOM than the flat page it
 * replaces. `hidden` keeps it out of the accessibility tree and out of the tab
 * order, which is the part that matters.
 *
 * **One framing, and it used to be two.** Sections stacked inside one surface,
 * separated by a rule: the book page, and since 2026-08-27 the only caller. A
 * `card` variant existed so that folding the settings list did not mean drawing
 * a settings card a second way; settings became a route tree, nothing there
 * folds any more, and a variant with no caller is a shape the next reader has
 * to work out the purpose of. `SettingsSection` is the settings card.
 *
 * The chevron is decorative: the state is already on the button.
 */
export default function CollapsibleSection({
  id,
  title,
  isOpen,
  onToggle,
  children,
}: CollapsibleSectionProps) {
  const panelId = `${id}-panel`;
  const handleId = `${id}-handle`;

  return (
    <section className="border-b border-paper-100 last:border-b-0 dark:border-paper-800">
      {/* The heading wraps the button so the section is a landmark in the
          document outline as well as a control. */}
      <h2>
        <button
          type="button"
          id={handleId}
          aria-expanded={isOpen}
          aria-controls={panelId}
          onClick={onToggle}
          // min-h-11 is 44px, the smallest thing a thumb hits reliably. This is
          // the control a phone reader uses most on this page.
          className="w-full min-h-11 flex items-center justify-between gap-3 py-3 text-left text-sm font-semibold text-paper-900 hover:text-accent-700 transition-colors dark:text-paper-100 dark:hover:text-accent-300"
        >
          <span className="flex items-center gap-2.5">{title}</span>
          <Icon
            name="chevron"
            className={`w-4 h-4 text-paper-600 transition-transform dark:text-paper-400 ${
              isOpen ? "rotate-90" : ""
            }`}
          />
        </button>
      </h2>

      <div
        id={panelId}
        role="group"
        aria-labelledby={handleId}
        hidden={!isOpen}
        className="pb-5 space-y-5"
      >
        {children}
      </div>
    </section>
  );
}
