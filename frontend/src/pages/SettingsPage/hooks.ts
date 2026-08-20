/**
 * Data access for the settings page.
 *
 * Everything the page needs, exposed as intent-shaped hooks. Nothing outside
 * this file imports from `api/generated`, so regenerating the client cannot
 * ripple into the components.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, downloadFile } from "../../api/mutator";
import { useSwitchAccount as useSwitchAccountMutation } from "../../api/generated/endpoints/auth/auth";
import {
  getListTestAccountsQueryKey,
  useCreateTestAccount,
  useListTestAccounts,
} from "../../api/generated/endpoints/users/users";
import {
  getGetFeatureFlagsQueryKey,
  getGetSettingsQueryKey,
  useGetSettings,
  useUpdateSettings,
} from "../../api/generated/endpoints/settings/settings";
import {
  getDownloadBackupUrl,
  useRestoreBackup,
} from "../../api/generated/endpoints/backup/backup";
import {
  useImportCsv,
  usePreviewImport,
} from "../../api/generated/endpoints/imports/imports";
import type {
  ImportResultOut,
  ImportPreviewOut,
  SettingsOut,
  SettingsUpdate,
  Token,
  UserOut,
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

/**
 * Bringing a library across from another service.
 *
 * Two steps rather than one, and the first is the point: a column guessed
 * wrong is invisible until after the import, and after the import the fix is
 * finding and deleting a few hundred books. So the file is read and reported
 * on before anything is written.
 */
export function useLibraryImport() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreviewOut | null>(null);
  const [result, setResult] = useState<ImportResultOut | null>(null);

  const previewing = usePreviewImport({
    mutation: { onSuccess: (data: ImportPreviewOut) => setPreview(data) },
  });

  const importing = useImportCsv({
    mutation: {
      onSuccess: (data: ImportResultOut) => {
        setResult(data);
        setPreview(null);
        setFile(null);
        // An import can create books and change statuses, so every list view
        // is now stale.
        void queryClient.invalidateQueries();
      },
    },
  });

  return {
    file,
    preview,
    result,

    // `mutate` for the same reason as above: the failure is surfaced through
    // `error`, not by rejecting a promise nobody is holding.
    choose: (chosen: File) => {
      setFile(chosen);
      setResult(null);
      importing.reset();
      previewing.mutate({ data: { file: chosen } });
    },

    confirm: (options: { createMissing: boolean; applyTags: boolean }) => {
      if (!file) return;
      importing.mutate({
        data: { file },
        params: {
          create_missing: options.createMissing,
          apply_tags: options.applyTags,
        },
      });
    },

    isPreviewing: previewing.isPending,
    isImporting: importing.isPending,
    error: previewing.error ?? importing.error,

    reset: () => {
      setFile(null);
      setPreview(null);
      setResult(null);
      previewing.reset();
      importing.reset();
    },
  };
}


/**
 * Downloading the whole library, and putting one back.
 *
 * The CSV export has always been there and is not a backup: it carries one row
 * per book and drops the notes, the loans, every member's reading status, the
 * accounts and every cover. This is the archive that holds all of it.
 *
 * Restoring is guarded twice, because it is the one action in this app that
 * destroys data it was not given the id of. The endpoint requires
 * `confirm=true`, and the page asks before sending it.
 */
export function useBackup() {
  const queryClient = useQueryClient();
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);

  const restore = useRestoreBackup({
    mutation: {
      onSuccess: () => {
        // Every book, account, note and loan has just been replaced. Nothing
        // in the cache survives that, so all of it goes.
        void queryClient.invalidateQueries();
      },
    },
  });

  return {
    isDownloading,
    downloadError,
    download: () => {
      setIsDownloading(true);
      setDownloadError(null);
      const today = new Date().toISOString().slice(0, 10);
      downloadFile(getDownloadBackupUrl(), `endpaper-backup-${today}.zip`)
        .catch(setDownloadError)
        .finally(() => setIsDownloading(false));
    },

    restore: (file: File) =>
      restore.mutate({ data: { file }, params: { confirm: true } }),
    isRestoring: restore.isPending,
    restoreError: restore.error,
    restored: restore.data ?? null,
  };
}


/**
 * The accounts an admin created for testing, and the making of a new one.
 *
 * `enabled` rather than an unconditional query: every member reaches this page
 * for the language switch, and this endpoint is admin only, so asking without
 * the flag would be a 403 on every visit by everybody.
 *
 * The list is the switch-target list and the server refuses anything that is
 * not on it, so the filtering here is presentation. That is the right way
 * round: a client cannot be the control on who may be signed in as.
 */
export function useTestAccounts(enabled: boolean) {
  const queryClient = useQueryClient();
  const query = useListTestAccounts({ query: { enabled, retry: false } });

  const create = useCreateTestAccount({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getListTestAccountsQueryKey(),
        });
      },
    },
  });

  return {
    accounts: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    // `mutate`, not `mutateAsync`: the failure is rendered from `createError`,
    // and a rejected promise nobody holds is an unhandled rejection.
    create: (username: string, password: string) =>
      create.mutate({ data: { username, password } }),
    isCreating: create.isPending,
    createError: create.error,
    created: create.data ?? null,
  };
}

/**
 * Exchange a password for a session on a test account.
 *
 * A sign-in on somebody else's account, so it ends in the same place a login
 * does: `onSignIn` stores the token, and the session hook drops the cache
 * because the identity changed. Then away from Settings, which the new account
 * is not an admin of and would answer with "only an admin can change these".
 */
export function useSwitchToTestAccount(
  onSignIn: (user: UserOut, token: string) => void,
) {
  const navigate = useNavigate();

  const mutation = useSwitchAccountMutation({
    mutation: {
      onSuccess: (token: Token) => {
        onSignIn(token.user, token.access_token);
        navigate("/");
      },
    },
  });

  return {
    switchTo: (username: string, password: string) =>
      mutation.mutate({ data: { username, password } }),
    isSwitching: mutation.isPending,
    switchError: mutation.error,
  };
}
