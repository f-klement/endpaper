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

import {
  useAuthConfig,
  useSwitchAccount as useSwitchAccountMutation,
} from "../../../api/generated/endpoints/auth/auth";
import {
  getDownloadBackupUrl,
  useRestoreBackup,
} from "../../../api/generated/endpoints/backup/backup";
import {
  getListPasswordResetsQueryKey,
  getListTestAccountsQueryKey,
  getListVerificationQueryKey,
  useApprovePasswordReset,
  useCreateTestAccount,
  useDeclinePasswordReset,
  useListPasswordResets,
  useListTestAccounts,
  useListVerification,
  useVerifyMember,
} from "../../../api/generated/endpoints/users/users";
import type {
  ResetCodeOut,
  Token,
  UserOut,
} from "../../../api/generated/model";
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
    // An empty box sends no field at all, the same shape registration sends.
    // `UserCreate` reads "" as no address, and agreeing with it here rather
    // than relying on it keeps one meaning of "left blank" across both forms.
    create: (username: string, password: string, email: string) =>
      create.mutate({
        data: { username, password, ...(email ? { email } : {}) },
      }),
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

/** A code an approval produced, and when the server says it stops working. */
export interface ApprovedCode {
  code: string;
  expiresAt: string;
}

/**
 * The password reset queue, and what an admin may do with it.
 *
 * **There is no way to start a reset here, and there is no endpoint for one.**
 * That asymmetry is what separates approving a member's request from taking
 * their account, and it is a property of the API rather than of this screen.
 *
 * The approval's code is kept in this hook's own state rather than refetched,
 * because it exists in exactly one response and there is no route that would
 * serve it again: the server stores a hash. Reading it off `mutation.data`
 * alone would drop it the moment a second approval reset that field, so it is
 * kept per member.
 */
export function useResetRequests(enabled: boolean) {
  const queryClient = useQueryClient();
  // The expiry travels with the code rather than being written into a string.
  // `RESET_CODE_TTL` is the server's fact, so a screen that spelled "an hour"
  // would be a second copy of it that stops being true when it moves.
  const [codes, setCodes] = useState<Record<number, ApprovedCode>>({});
  const query = useListPasswordResets({ query: { enabled, retry: false } });

  const refresh = () =>
    void queryClient.invalidateQueries({
      queryKey: getListPasswordResetsQueryKey(),
    });

  const approve = useApprovePasswordReset({
    mutation: {
      onSuccess: (result: ResetCodeOut, variables) => {
        setCodes((current) => ({
          ...current,
          [variables.userId]: {
            code: result.code,
            expiresAt: result.expires_at,
          },
        }));
        refresh();
      },
    },
  });

  const decline = useDeclinePasswordReset({
    mutation: {
      onSuccess: (_result, variables) => {
        // Drop the code with the request. Leaving it on screen would show a
        // code for a request that no longer exists.
        setCodes((current) => {
          const next = { ...current };
          delete next[variables.userId];
          return next;
        });
        refresh();
      },
    },
  });

  return {
    requests: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    codes,
    approve: (userId: number) => approve.mutate({ userId }),
    decline: (userId: number) => decline.mutate({ userId }),
    isWorking: approve.isPending || decline.isPending,
    actionError: approve.error ?? decline.error,
  };
}

/**
 * Every member's confirmation state, and the admin override.
 *
 * The override is an assertion about a person, so the server records which
 * admin made it; this hook simply refetches, because the recorded name is what
 * the list then shows.
 */
export function useMemberVerification(enabled: boolean) {
  const queryClient = useQueryClient();
  const query = useListVerification({ query: { enabled, retry: false } });

  const confirm = useVerifyMember({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getListVerificationQueryKey(),
        });
      },
    },
  });

  return {
    members: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    confirm: (userId: number) => confirm.mutate({ userId }),
    isConfirming: confirm.isPending,
    confirmError: confirm.error,
  };
}

/**
 * Whether this deployment resets a local password at all.
 *
 * The server's own answer, from `/auth/config`, rather than a second derivation
 * from the `mode` prop this page already holds: `accounts.reset_refusal` is the
 * rule, and a browser recomputing it is a place for the two to disagree. That is
 * the same reasoning `public_catalogue_published` carries.
 *
 * False while the config is loading, which is the safe direction here: the cost
 * is a section that appears a moment late, and the alternative is a queue drawn
 * on a deployment that refuses every request into it.
 */
export function useResetOffered(): boolean {
  const config = useAuthConfig({ query: { retry: false, staleTime: 60_000 } });
  return config.data?.password_reset_enabled === true;
}
