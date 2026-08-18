import { useEffect, useRef, useState } from "react";

import { useTranslation } from "../../../i18n";

interface SearchBarProps {
  onSearch: (query: string) => void;
  placeholder?: string;
}

/** Debounce window, in ms, before a keystroke turns into a request. */
export const DEBOUNCE_MS = 300;

/** Debounced search input. Used only by Home, so it lives here. */
export default function SearchBar({ onSearch, placeholder }: SearchBarProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Debounced so typing a title does not fire a request per keystroke.
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => onSearch(value), DEBOUNCE_MS);
    return () => clearTimeout(timer.current);
    // onSearch is intentionally omitted: Home passes an inline callback, so
    // including it would restart the debounce on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <div className="relative">
      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-500">
        🔍
      </span>
      <input
        type="search"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder ?? t("library.search")}
        aria-label={t("library.searchLabel")}
        className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-gray-200 bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-sky-400 text-sm dark:border-gray-700 dark:bg-gray-900"
      />
    </div>
  );
}
