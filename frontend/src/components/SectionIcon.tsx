import Icon, { type IconName } from "./Icon";

interface SectionIconProps {
  name: IconName;
}

/**
 * The rounded badge that carries a section heading's icon.
 *
 * Its own component because two things draw that heading: `SettingsSection`
 * for a card that does not fold, and `CollapsibleSection`'s card variant for
 * one that does. The same badge from two class lists is the kind of difference
 * nobody notices until the two sit next to each other on one page.
 *
 * Decorative, and left to `Icon` to say so: it is `aria-hidden` unless given a
 * title, so repeating that on the badge would state the same fact twice.
 */
export default function SectionIcon({ name }: SectionIconProps) {
  return (
    <span className="grid place-items-center w-7 h-7 rounded-lg bg-paper-100 text-paper-600 dark:bg-paper-800 dark:text-paper-400">
      <Icon name={name} className="w-4 h-4" />
    </span>
  );
}
