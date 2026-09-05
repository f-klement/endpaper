import { useCallback, useMemo, useState } from "react";

import { getExportBooksUrl } from "../api/generated/endpoints/books/books";
import { useGetFeatureFlags } from "../api/generated/endpoints/settings/settings";
import {
  useGetMyAppearance,
  useSetMyAppearance,
} from "../api/generated/endpoints/users/users";
import type { ExportFormat, FeatureFlagsOut } from "../api/generated/model";
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

/**
 * The server's feature flags, for the shell.
 *
 * Here rather than inline in `providers.tsx` so that the rule holds without an
 * exception: only a `hooks.ts` imports from `api/generated/endpoints`. One
 * exception is one more than a test can enforce, and the indirection is the
 * whole reason a regeneration does not ripple through the components.
 *
 * `retry: false` because the shell renders regardless: a failure here means
 * falling back to the browser's language, not an error screen.
 */
export function useFeatureFlags(): FeatureFlagsOut | undefined {
  return useFeatureFlagsState().flags;
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
 * `useFeatureFlags` is this with the second half dropped, rather than a second
 * query beside it: two call sites configuring one endpoint is how they come to
 * disagree about `retry` or `staleTime`.
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
