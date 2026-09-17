import { useCallback, useMemo, useState } from "react";

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
   * `pages/Home/hooks.ts`.
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
 * apart, which is why `pages/Home/hooks.ts` reads the state rather than this.
 */
export function useLibraryMode(): boolean {
  return useFeatureFlagsState().flags?.library_mode ?? false;
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
