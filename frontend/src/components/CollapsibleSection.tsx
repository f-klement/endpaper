import type { ReactNode } from "react";

import Icon, { type IconName } from "./Icon";
import SectionIcon from "./SectionIcon";

/**
 * How the section is framed, and the two shapes are not interchangeable.
 *
 * A card carries an icon because every settings card has one; a row on the
 * book page carries none, and passing one there would be the settings look
 * arriving on a page that does not use it. Expressed as a union rather than
 * two optional props so both mistakes are compile errors rather than a card
 * with a hole where the badge goes.
 */
type Chrome =
  { variant?: "rows"; icon?: never } | { variant: "card"; icon: IconName };

type CollapsibleSectionProps = {
  /** Unique on the page. Wires the handle to the panel it controls. */
  id: string;
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  children: ReactNode;
} & Chrome;

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
 * **Two framings, one disclosure.** `rows` is the book page: sections stacked
 * inside one surface, separated by a rule. `card` is the settings pages, where
 * each section is its own card with an icon, and it exists so folding settings
 * does not mean drawing them a second way; `SettingsSection` draws the same
 * card for the appearance screen, which does not fold.
 *
 * The chevron is decorative: the state is already on the button.
 */
export default function CollapsibleSection({
  id,
  title,
  isOpen,
  onToggle,
  variant = "rows",
  icon,
  children,
}: CollapsibleSectionProps) {
  const panelId = `${id}-panel`;
  const handleId = `${id}-handle`;
  const isCard = variant === "card";

  return (
    <section
      className={
        isCard
          ? "card p-5"
          : "border-b border-paper-100 last:border-b-0 dark:border-paper-800"
      }
    >
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
          className={`w-full min-h-11 flex items-center justify-between gap-3 text-left text-sm font-semibold text-paper-900 hover:text-accent-700 transition-colors dark:text-paper-100 dark:hover:text-accent-300 ${
            isCard ? "" : "py-3"
          }`}
        >
          <span className="flex items-center gap-2.5">
            {icon && <SectionIcon name={icon} />}
            {title}
          </span>
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
        className={isCard ? "pt-4 space-y-4" : "pb-5 space-y-5"}
      >
        {children}
      </div>
    </section>
  );
}
