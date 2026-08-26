/**
 * Everything derived from the language the reader chose.
 *
 * No i18n library: there are two languages and a flat key set, so translation
 * here is an object lookup plus placeholder substitution. What a library would
 * add is a dependency, a bundle, and a plural-rules engine nothing in this app
 * needs.
 *
 * What it does keep is the property that matters: `de.ts` is typed as
 * `Messages`, so a key without a German translation fails the build rather
 * than surfacing as an English sentence inside a German page.
 *
 * **The module owns more than translation, and the boundary is written down
 * so it stays a boundary.** Every export is a function of the chosen locale:
 * the catalogue lookup, numbers through `interpolate`, name ordering through
 * `useSortedByName`. A hook that does not read the locale does not belong
 * here, and that test is what keeps this from becoming the file things land
 * in.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { Locale } from "../api/generated/model";
import { sortByName } from "../lib/nameOrder";
import { de } from "./de";
import { en, type MessageKey, type Messages } from "./en";

const CATALOGUES: Record<Locale, Messages> = {
  [Locale.en]: en,
  [Locale.de]: de,
};

const STORAGE_KEY = "locale";

/**
 * The stand-in for a list that has not arrived.
 *
 * Load bearing, and the reason `useSortedByName` takes `undefined` rather
 * than letting each caller write `?? []`: a fresh literal is a new reference
 * every render, which would defeat the memo for the whole time a query is
 * pending.
 */
const EMPTY: never[] = [];

/** Values a placeholder can take. Numbers are formatted for the locale. */
export type TranslateParams = Record<string, string | number>;

export type Translate = (key: MessageKey, params?: TranslateParams) => string;

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translate;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

function isSupported(value: string | null | undefined): value is Locale {
  // Derived from the catalogues rather than listed. Adding a third language
  // used to mean editing this line too, and forgetting it fails quietly: the
  // language would be translated and still never selected, because both the
  // stored choice and the browser's own language are read through here.
  return value != null && value in CATALOGUES;
}

export function readStoredLocale(): Locale | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isSupported(stored) ? stored : null;
  } catch {
    // Storage can be unavailable in a private window. Not worth failing over.
    return null;
  }
}

/** The primary language of the browser, if it is one we speak. */
export function detectBrowserLocale(): Locale | null {
  const languages = navigator.languages?.length
    ? navigator.languages
    : [navigator.language];
  for (const tag of languages) {
    // Match on the primary subtag: de-AT and de-CH are both German here.
    const primary = tag?.split("-")[0]?.toLowerCase();
    if (isSupported(primary)) return primary;
  }
  return null;
}

/**
 * Which language to show, in order of how strong the signal is:
 *
 * 1. An explicit choice made in Settings, which is per person and per device.
 * 2. The browser's own language, so a German library gets German without
 *    anyone configuring anything.
 * 3. The server's default, which is the admin's answer for browsers set to a
 *    language this app does not speak.
 * 4. English.
 */
export function resolveLocale(serverDefault?: Locale | null): Locale {
  return (
    readStoredLocale() ?? detectBrowserLocale() ?? serverDefault ?? Locale.en
  );
}

/** Replace `{name}` placeholders, formatting numbers for the locale. */
export function interpolate(
  template: string,
  params: TranslateParams,
  locale: Locale,
): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = params[name];
    if (value === undefined) {
      // Leave the placeholder visible rather than printing "undefined": a
      // literal {count} in the UI is obviously a bug, and silently blank text
      // is not.
      return whole;
    }
    return typeof value === "number"
      ? new Intl.NumberFormat(locale).format(value)
      : value;
  });
}

interface LocaleProviderProps {
  children: ReactNode;
  /** The server's configured default, used only when nothing stronger exists. */
  serverDefault?: Locale | null;
  /**
   * Start in this language, skipping detection. Tests use it so assertions do
   * not depend on the machine's browser language.
   *
   * An initial value, not a lock: a test that exercises the language switch
   * has to be able to switch. Forcing it permanently would make the toggle
   * untestable through the UI, which is the only place it exists.
   */
  initialLocale?: Locale;
}

export function LocaleProvider({
  children,
  serverDefault,
  initialLocale,
}: LocaleProviderProps) {
  const [chosen, setChosen] = useState<Locale | null>(
    () => initialLocale ?? readStoredLocale(),
  );

  const locale = chosen ?? resolveLocale(serverDefault);

  const setLocale = useCallback((next: Locale) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Unavailable storage means the choice lasts for this session only,
      // which is better than refusing to switch language at all.
    }
    setChosen(next);
  }, []);

  const t = useCallback<Translate>(
    (key, params) => {
      // English is the fallback catalogue as well as a language: if a key were
      // ever missing at runtime, showing the English text beats showing the
      // key itself to a reader.
      const template = CATALOGUES[locale][key] ?? en[key] ?? key;
      return params ? interpolate(template, params, locale) : template;
    },
    [locale],
  );

  const context = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t],
  );

  return (
    <LocaleContext.Provider value={context}>{children}</LocaleContext.Provider>
  );
}

export function useTranslation(): LocaleContextValue {
  const context = useContext(LocaleContext);
  if (context === null) {
    throw new Error("useTranslation must be used inside a LocaleProvider");
  }
  return context;
}

/**
 * A name list in the order a reader of the chosen language expects.
 *
 * The door to `lib/nameOrder`, and the only one a component should use.
 * Ordering names needs three things that are easy to get separately and easy
 * to forget: the chosen locale, a collator built for it, and a memo. This
 * supplies all three, so a new name list gets them by calling one hook rather
 * than by remembering a recipe.
 *
 * The memo matters more than it looks. These lists are query cache entries,
 * `sort` allocates, and a component that re-sorts inline re-sorts on every
 * keystroke into any input beside it.
 *
 * Lives here rather than in `lib/`, which holds no React, and it belongs
 * beside `interpolate` in any case: collation and number formatting are the
 * same question asked of the same locale.
 */
export function useSortedByName<T extends { name: string }>(
  items: readonly T[] | undefined,
): T[] {
  const { locale } = useTranslation();
  return useMemo(() => sortByName(items ?? EMPTY, locale), [items, locale]);
}

export type { MessageKey, Messages };
export { en, de };
