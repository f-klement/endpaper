import { useEffect, useRef, useState } from "react";

import { Icon } from "../../components";
import { useTranslation } from "../../i18n";

/**
 * Debounce window, in ms, before a keystroke turns into a request.
 *
 * 300 was too short to do its job. A debounce only collapses keystrokes that
 * arrive closer together than the window, and typing a title on a phone, or
 * hunting for the keys, routinely leaves longer gaps than that. The result was
 * one request per character in practice, which is what the debounce exists to
 * prevent.
 */
export const DEBOUNCE_MS = 500;

/**
 * Below this, a search is noise.
 *
 * A single letter matches most of a library, so the request is expensive and
 * the answer is useless. Clearing the box is still passed through, since that
 * is how someone gets back to the full shelf.
 */
export const MIN_QUERY_LENGTH = 2;

interface SearchBarProps {
  onSearch: (query: string) => void;
  placeholder?: string;
  /**
   * The accessible name, when it is not "Search books".
   *
   * **Not optional in spirit, and it was hard coded.** The placeholder was
   * already a prop while the `aria-label` was not, so the public catalogue read
   * "Search this catalogue" on screen and announced "Search books" to a screen
   * reader: two different names for one control, and the one a non sighted
   * reader gets naming the wrong catalogue.
   */
  label?: string;
}

/**
 * Debounced search input.
 *
 * It lived in `Home/components` while Home was its only caller, and moved here
 * when the public catalogue became the second: the debounce window and the
 * minimum query length are one rule about when a keystroke is worth a request,
 * and a second copy of it would be a second answer.
 */
export default function SearchBar({
  onSearch,
  placeholder,
  label,
}: SearchBarProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // The effect below runs once on mount, when nobody has typed anything. Firing
  // then re-requests the unfiltered list the page has already loaded.
  const hasTyped = useRef(false);

  useEffect(() => {
    if (!hasTyped.current) return;

    const trimmed = value.trim();
    // A part-typed word is not a query yet, but an emptied box is: it means
    // "show me everything again".
    if (trimmed.length > 0 && trimmed.length < MIN_QUERY_LENGTH) return;

    clearTimeout(timer.current);
    timer.current = setTimeout(() => onSearch(trimmed), DEBOUNCE_MS);
    return () => clearTimeout(timer.current);
    // onSearch is intentionally omitted: Home passes an inline callback, so
    // including it would restart the debounce on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <div className="relative">
      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-paper-600 dark:text-paper-400">
        <Icon name="search" className="w-4 h-4" />
      </span>
      <input
        type="search"
        value={value}
        onChange={(event) => {
          hasTyped.current = true;
          setValue(event.target.value);
        }}
        placeholder={placeholder ?? t("library.search")}
        aria-label={label ?? t("library.searchLabel")}
        className="field pl-9"
      />
    </div>
  );
}
