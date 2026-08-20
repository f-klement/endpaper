import { useTranslation } from "../i18n";

interface HelpButtonProps {
  /** Announced to assistive tech, so name what it explains. */
  label: string;
  onClick: () => void;
}

/**
 * A small "?" that opens an explanation.
 *
 * A real button rather than an icon with a click handler, so it is reachable by
 * keyboard and announced as something activatable. The glyph is decorative and
 * the accessible name comes from the label, because "?" read aloud tells
 * nobody anything.
 */
export default function HelpButton({ label, onClick }: HelpButtonProps) {
  const { t } = useTranslation();

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={t("help.title")}
      className="shrink-0 w-5 h-5 rounded-full border border-paper-300 text-paper-500 text-xs font-semibold leading-none hover:border-accent-400 hover:text-accent-700 transition-colors dark:text-paper-400"
    >
      <span aria-hidden="true">?</span>
    </button>
  );
}
