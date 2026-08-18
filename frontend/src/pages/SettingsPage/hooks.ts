/**
 * Data access for the settings page.
 *
 * Everything the page needs, exposed as intent-shaped hooks. Nothing outside
 * this file imports from `api/generated`, so regenerating the client cannot
 * ripple into the components.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "../../api/mutator";
import {
  getGetFeatureFlagsQueryKey,
  getGetSettingsQueryKey,
  useGetSettings,
  useUpdateSettings,
} from "../../api/generated/endpoints/settings/settings";
import { useImportGoodreads } from "../../api/generated/endpoints/imports/imports";
import type {
  GoodreadsImportOut,
  SettingsOut,
  SettingsUpdate,
} from "../../api/generated/model";

/** The admin-only settings record, plus a saver that refreshes the flags. */
export function useSettings() {
  const queryClient = useQueryClient();
  const query = useGetSettings({ query: { retry: false } });

  const mutation = useUpdateSettings({
    mutation: {
      onSuccess: (updated: SettingsOut) => {
        queryClient.setQueryData(getGetSettingsQueryKey(), updated);
        // The flags drive rendering across the whole app (the enrichment
        // button, the Goodreads links), and they are a different endpoint
        // with its own cache entry, so saving here has to invalidate there.
        void queryClient.invalidateQueries({
          queryKey: getGetFeatureFlagsQueryKey(),
        });
      },
    },
  });

  return {
    settings: query.data,
    isLoading: query.isLoading,
    error: query.error,
    // 403 for a non-admin is a legitimate state rather than a failure, so the
    // page states it plainly instead of rendering an error. Orval types the
    // error as the endpoint's declared error body, not as what the mutator
    // actually throws, so the status is only reachable through the guard.
    isForbidden: query.error instanceof ApiError && query.error.status === 403,
    // `mutate`, not `mutateAsync`: nothing awaits this, and mutateAsync
    // rejects on failure, so every failed save left an unhandled promise
    // rejection in the console. The failure is already reported through
    // `saveError`, which is what the page renders.
    save: (data: SettingsUpdate) => mutation.mutate({ data }),
    isSaving: mutation.isPending,
    saveError: mutation.error,
    hasSaved: mutation.isSuccess,
  };
}

/** Uploading a Goodreads CSV export. */
export function useGoodreadsImport() {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<GoodreadsImportOut | null>(null);

  const mutation = useImportGoodreads({
    mutation: {
      onSuccess: (data: GoodreadsImportOut) => {
        setResult(data);
        // An import can create books and change statuses, so every list view
        // is now stale.
        void queryClient.invalidateQueries();
      },
    },
  });

  return {
    // `mutate` for the same reason as above: the failure is surfaced through
    // `error`, not by rejecting a promise nobody is holding.
    upload: (file: File, createMissing: boolean) =>
      mutation.mutate({
        data: { file },
        params: { create_missing: createMissing },
      }),
    isUploading: mutation.isPending,
    error: mutation.error,
    result,
    reset: () => {
      setResult(null);
      mutation.reset();
    },
  };
}
