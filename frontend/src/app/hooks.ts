import { useCallback, useMemo, useState, useSyncExternalStore } from "react";

import { getExportBooksUrl } from "../api/generated/endpoints/books/books";
import { useGetFeatureFlags } from "../api/generated/endpoints/settings/settings";
import {
  useGetMyAppearance,
  useSetMyAppearance,
} from "../api/generated/endpoints/users/users";
import type {
  ExportFormat,
  FeatureFlagsOut,
  Locale,
} from "../api/generated/model";
import { downloadFile } from "../api/mutator";
import { catalogueMode, type CatalogueMode } from "../lib/catalogueMode";
import type { Preference, ScopedPreference } from "../lib/preference";
import { resolveAppearance, type Appearance } from "../theme";

export interface UseExportLibraryResult {
  exportLibrary: (format: ExportFormat) => void;
  isExporting: boolean;
  error: unknown;
}

/**
 * Download the catalogue as CSV or plain text.
 *
 * Uses the generated URL builder but not a generated hook: this is an
 * imperative action triggered by a click, whereas a query would fire on render.
 */
export function useExportLibrary(): UseExportLibraryResult {
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  return {
    isExporting,
    error,
    exportLibrary: (format) => {
      setIsExporting(true);
      setError(null);
      downloadFile(getExportBooksUrl({ format }), `endpaper-export.${format}`)
        .catch(setError)
        .finally(() => setIsExporting(false));
    },
  };
}

export interface FeatureFlagsState {
  flags: FeatureFlagsOut | undefined;
  /**
   * Whether the request has finished, either way.
   *
   * **`flags === undefined` cannot answer this**, which is the reason this
   * exists: it is the same value before the request has answered and after it
   * has failed, and those two want opposite treatment. A failure is a settled
   * answer, and the documented one, because every flag falls back to what an
   * existing library already had. Still waiting is not an answer at all.
   *
   * Anything that only reads a flag can ignore this and take the fallback for
   * a render. Anything that **writes** something keyed on a flag cannot: a
   * wrong read costs one paint and a wrong write is permanent. See
   * `useCatalogueScope` below.
   */
  isResolved: boolean;
}

/**
 * The flags, and whether they have arrived.
 *
 * **The only place this endpoint is configured**, which is a rule with a test
 * rather than a hope: `tests/houseRules.test.ts` holds it, and holds the
 * measurement of what it prevents. Every reader below goes through here, and
 * so does the one caller that needs the second half.
 *
 * `retry: false` because everything reading this renders regardless: a failure
 * means the fallback each reader documents, not an error screen.
 */
export function useFeatureFlagsState(): FeatureFlagsState {
  const query = useGetFeatureFlags({
    query: { retry: false, staleTime: 60_000 },
  });
  // `isPending` is "no data and no error", so it goes false on a failure as
  // well as on an answer, and stays false through a background refetch. That
  // is the question this is asking.
  return { flags: query.data, isResolved: !query.isPending };
}

/**
 * The flags, one question at a time.
 *
 * A reader per flag rather than call sites reading fields off a shared object.
 * A caller holding the object also picks that field's fallback, and the
 * fallback is a property of the field rather than of the screen asking: there
 * is one right answer for a flag that has not arrived, and it is what an
 * existing library already had. Spelling it per caller is how `?? false` and
 * `=== true` came to sit beside each other for the same question.
 *
 * Each of them goes through `useFeatureFlagsState`, which is what keeps the
 * endpoint on one set of options. What that prevents, measured, is at the
 * guard: `tests/houseRules.test.ts`, "the feature flags query has one owner".
 */

/** Whether a Google Books lookup will reach Google: switched on, and keyed. */
export function useGoogleBooksReady(): boolean {
  return useFeatureFlagsState().flags?.google_books_ready ?? false;
}

/** Whether Goodreads lookup links should be rendered. */
export function useGoodreadsLookup(): boolean {
  return useFeatureFlagsState().flags?.goodreads_lookup_enabled ?? false;
}

/**
 * Whether this deployment has a published catalogue to offer.
 *
 * `public_catalogue_published` is the **server's** conjunction of library mode
 * and the publish switch, not either row, so a browser cannot get the nesting
 * rule wrong by reading one of them.
 */
export function usePublishedCatalogue(): boolean {
  return useFeatureFlagsState().flags?.public_catalogue_published ?? false;
}

/**
 * Whether this Library is run as a small archive rather than a household.
 *
 * The raw row, and unlike the reader above it there is nothing to conjoin: the
 * server gates every MARC route on this row alone, so a client reading it gets
 * the answer those routes give. The export menu is one of them.
 *
 * **For rendering, not for writing.** False here is the same value before the
 * request has answered and after it has failed. Anything keying a stored
 * choice on the mode needs `useFeatureFlagsState().isResolved` to tell the two
 * apart, which is what `useCatalogueScope` below is for.
 */
export function useLibraryMode(): boolean {
  return useFeatureFlagsState().flags?.library_mode ?? false;
}

/**
 * Which reader the catalogue is being drawn for, or `undefined` while nobody
 * knows yet.
 *
 * **The third state is the whole point, and it is not the same as household.**
 * `catalogueMode(undefined)` answers household, which is the right answer for
 * *reading*: the household's set is what every existing library already sees,
 * and a cataloguer seeing it for a render or two is the cheaper way round. It
 * is not an answer for *writing*. A cataloguer's choice filed under the
 * household's key overwrites the choice the separate keys exist to protect and
 * leaves the cataloguer's key empty, with nothing saying so. A wrong read costs
 * one paint; a wrong write is permanent and silent.
 *
 * So this hands back `undefined` until the flags are settled, and
 * `useScopedPreference` refuses a write while it is. **Settled means answered
 * either way**: a failure is an answer, and reading it as "not ready" would
 * leave a library whose flags endpoint is down unable to change anything for
 * the whole session, with its controls greyed and nothing saying why.
 *
 * A reader per question, like the flags above it, so no call site pairs the
 * mode with its settledness itself.
 */
export function useCatalogueScope(): CatalogueMode | undefined {
  const { flags, isResolved } = useFeatureFlagsState();
  return isResolved ? catalogueMode(flags?.library_mode) : undefined;
}

/** A stored choice, and the way to change it. */
export interface Remembered<TValue> {
  value: TValue;
  set: (value: TValue) => void;
}

/**
 * A stored preference, re-read whenever anything writes one.
 *
 * `useSyncExternalStore` rather than a copy in state, because a second copy of
 * a value is how the two come to disagree. Storage is the single copy and this
 * subscribes to it, which is what retired the counter that used to sit in
 * `pages/Home/hooks.ts` bumping a dependency so a write would be re-read.
 *
 * **No selector, and no deriving a value after the read.** The snapshot has to
 * be the same value until the stored string changes, and a caller handed a
 * selector would be handed the one way to break that. Derive from `value`
 * afterwards in the component instead, where React can see it.
 */
export function usePreference<TValue>(
  preference: Preference<TValue>,
): Remembered<TValue> {
  const value = useSyncExternalStore(preference.subscribe, preference.read);
  return { value, set: preference.write };
}

/** A stored choice kept per scope, and whether it may be changed yet. */
export interface RememberedPerScope<TScope, TValue> extends Remembered<TValue> {
  /**
   * False while the scope has not arrived.
   *
   * **Offered to the control, not only enforced here.** The write is refused
   * either way, and a control that answers a press with nothing teaches the
   * reader the page lies, so every control that writes a scoped preference
   * draws itself disabled on this.
   */
  canSet: boolean;
  /**
   * Write a value computed from the scope it is being written under.
   *
   * **This is the one property the wrapper it replaced had and a plain setter
   * does not.** `writeForMode` handed the mode to its caller, so a value could
   * not be computed from one mode and stored under another; `set(value)` takes
   * a value computed somewhere else, and the gate is then the only thing
   * holding the two together. A caller that derives its value from the mode,
   * which is every caller that resets to a default or toggles a member of a
   * per mode set, uses this instead and the skew becomes unspellable rather
   * than merely refused.
   *
   * What the skew would cost, so nobody removes this as ceremony: a reset built
   * from a stale household mode and stored under the cataloguer's scope is not
   * equal to the cataloguer's default, so it is stored rather than clearing the
   * key, and the control that offers the reset stays drawn and never resets.
   */
  setFromScope: (compute: (scope: TScope) => TValue) => void;
}

/**
 * A preference kept per scope, refusing every write until the scope is known.
 *
 * **The gate takes `undefined` rather than a flag beside a value**, so "this
 * scope, and it is settled" is not a thing a call site can assemble. The scope
 * comes from a reader such as `useCatalogueScope` and a hard coded one is
 * visible in a diff.
 */
export function useScopedPreference<TScope extends string, TValue>(
  preference: ScopedPreference<TScope, TValue>,
  scope: TScope | undefined,
): RememberedPerScope<TScope, TValue> {
  const reading = scope ?? preference.whenUnknown;
  const value = useSyncExternalStore(preference.subscribe, () =>
    preference.read(reading),
  );
  const setFromScope = (compute: (scope: TScope) => TValue) => {
    if (scope === undefined) return;
    preference.write(scope, compute(scope));
  };
  return {
    value,
    canSet: scope !== undefined,
    set: (next) => setFromScope(() => next),
    setFromScope,
  };
}

/**
 * The language a browser falls back to when its own is not one this app
 * speaks. `undefined` until the flags arrive, and that is the answer the
 * locale provider wants: the browser's own language is known synchronously and
 * is right for almost everyone, so there is nothing to substitute here.
 *
 * The one reader that is not a boolean, which is why it is not written `??`.
 */
export function useServerDefaultLocale(): Locale | undefined {
  return useFeatureFlagsState().flags?.default_locale;
}

export interface UseStoredAppearanceResult {
  /** The account's stored appearance, once the server has answered. */
  stored: Appearance | undefined;
  /** Write one back. Fire and forget: nothing on screen waits for it. */
  save: (appearance: Appearance) => void;
}

/**
 * The signed-in member's appearance, as the server holds it.
 *
 * **The account is in the query key**, which the generated hook does not do on
 * its own: the path has no member id in it, so every account would share one
 * cache entry. The client outlives a sign-out, so on a shared device the next
 * person to sign in would be handed the previous one's palette from the cache
 * and keep it until something refetched.
 *
 * `retry: false` and no error handling for the same reason as the flags above:
 * the page is already painted from this device's cache by the time this asks,
 * so a failure here means the reader keeps the look they had rather than seeing
 * anything go wrong.
 *
 * `mutate`, not `mutateAsync`: a rejected promise nobody awaits is an unhandled
 * rejection on every failed write, and there is nothing useful to do with one.
 * The choice is already applied and cached locally, so the worst case is that it
 * stays on this device.
 */
export function useStoredAppearance(
  accountId: number,
): UseStoredAppearanceResult {
  const query = useGetMyAppearance({
    query: {
      queryKey: ["appearance", accountId],
      retry: false,
      staleTime: Infinity,
    },
  });
  const { mutate } = useSetMyAppearance();

  // Stable, because the effect that pushes a change depends on it: rebuilt
  // every render it would re-run on every render instead of on a change.
  const save = useCallback(
    (appearance: Appearance) => mutate({ data: appearance }),
    [mutate],
  );

  const stored = query.data;
  return {
    stored: useMemo(
      () => (stored ? resolveAppearance(stored) : undefined),
      [stored],
    ),
    save,
  };
}
