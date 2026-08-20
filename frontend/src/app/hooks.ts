import { useState } from "react";

import { getExportBooksUrl } from "../api/generated/endpoints/books/books";
import { useGetFeatureFlags } from "../api/generated/endpoints/settings/settings";
import type { ExportFormat, FeatureFlagsOut } from "../api/generated/model";
import { downloadFile } from "../api/mutator";

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
  return useGetFeatureFlags({ query: { retry: false, staleTime: 60_000 } }).data;
}
