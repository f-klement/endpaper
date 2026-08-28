/**
 * The admin settings record, shared by four of the six settings routes.
 *
 * Everything else moved out. Appearance, Catalogue sources, Lending and Data
 * and accounts all read and write this one server record, so it stays here;
 * every hook that belonged to a single route now lives beside that route.
 *
 * That split is what this file exists to keep. It used to hold nine hooks and
 * the collapse table, at 554 lines, and two unrelated features touching two
 * unrelated sections had to be told in advance which of them owned it.
 *
 * Nothing outside a `hooks.ts` imports from `api/generated`, so regenerating
 * the client cannot ripple into the components.
 */

import { useQueryClient } from "@tanstack/react-query";

import {
  getGetFeatureFlagsQueryKey,
  getGetSettingsQueryKey,
  useGetSettings,
  useUpdateSettings,
} from "../../api/generated/endpoints/settings/settings";
import type { SettingsOut, SettingsUpdate } from "../../api/generated/model";
import { ApiError } from "../../api/mutator";

export interface UseSettingsResult {
  /** Undefined until it loads, and forever for a member who is not an admin. */
  settings: SettingsOut | undefined;
  isLoading: boolean;
  error: unknown;
  isForbidden: boolean;
  save: (data: SettingsUpdate) => void;
  isSaving: boolean;
  saveError: unknown;
  hasSaved: boolean;
}

/** The admin-only settings record, plus a saver that refreshes the flags. */
export function useSettings(): UseSettingsResult {
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
