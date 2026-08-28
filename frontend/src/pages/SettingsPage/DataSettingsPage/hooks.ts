/**
 * Data access for the Data and accounts route.
 *
 * The archive of the whole library, and the accounts an admin uses to see it
 * the way an ordinary member does. Nothing outside this file imports from
 * `api/generated`, so regenerating the client cannot ripple into the
 * components.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useSwitchAccount as useSwitchAccountMutation } from "../../../api/generated/endpoints/auth/auth";
import {
  getDownloadBackupUrl,
  useRestoreBackup,
} from "../../../api/generated/endpoints/backup/backup";
import {
  getListTestAccountsQueryKey,
  useCreateTestAccount,
  useListTestAccounts,
} from "../../../api/generated/endpoints/users/users";
import type { Token, UserOut } from "../../../api/generated/model";
import { useInvalidate } from "../../../api/invalidate";
import { downloadFile } from "../../../api/mutator";

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
  const invalidate = useInvalidate();
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);

  const restore = useRestoreBackup({
    mutation: {
      onSuccess: () => {
        // The other write that earns the whole cache, and the clearer of the
        // two: every book, account, note, loan and setting has just been
        // replaced, including the row behind the signed-in member.
        invalidate.everything();
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
