/**
 * The member's own address, and the whole list an admin may edit.
 *
 * Two queries rather than one, because they are two audiences: every member
 * may read their own, and only an admin may read anybody's. A single list
 * filtered in the browser would mean serving every address to every member,
 * which is the rule this feature exists to keep.
 *
 * Nothing outside a `hooks.ts` imports from `api/generated/endpoints`, so a
 * regeneration cannot ripple into the components.
 */

import { useQueryClient } from "@tanstack/react-query";

import {
  getGetMyEmailQueryKey,
  getListEmailsQueryKey,
  useGetMyEmail,
  useListEmails,
  useSetMemberEmail,
  useSetMyEmail,
} from "../../../api/generated/endpoints/users/users";
import type { MemberEmailOut } from "../../../api/generated/model";
import { ApiError } from "../../../api/mutator";

/** 409 is the one refusal this screen explains rather than reports. */
function isDirectoryOwned(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

export interface UseMyEmailResult {
  mine: MemberEmailOut | undefined;
  isLoading: boolean;
  error: unknown;
  save: (email: string | null) => void;
  isSaving: boolean;
  saveError: unknown;
  /** The save was refused because a directory owns the address. */
  isDirectoryOwned: boolean;
  hasSaved: boolean;
}

export function useMyEmail(): UseMyEmailResult {
  const queryClient = useQueryClient();
  const query = useGetMyEmail();

  const mutation = useSetMyEmail({
    mutation: {
      onSuccess: (updated: MemberEmailOut) => {
        queryClient.setQueryData(getGetMyEmailQueryKey(), updated);
        // An admin editing their own address is looking at both this field and
        // the list below it, and the list holds the same row.
        void queryClient.invalidateQueries({
          queryKey: getListEmailsQueryKey(),
        });
      },
    },
  });

  return {
    mine: query.data,
    isLoading: query.isLoading,
    error: query.error,
    // `mutate`, not `mutateAsync`: nothing awaits this, and mutateAsync rejects
    // on failure, leaving an unhandled promise rejection on every refusal.
    save: (email: string | null) => mutation.mutate({ data: { email } }),
    isSaving: mutation.isPending,
    saveError: mutation.error,
    isDirectoryOwned: isDirectoryOwned(mutation.error),
    hasSaved: mutation.isSuccess,
  };
}

export interface UseMemberEmailsResult {
  members: MemberEmailOut[] | undefined;
  /**
   * Whether this caller is offered the list at all.
   *
   * An explicit flag rather than reading react-query's state, because "the
   * request was never made" and "the request has not answered yet" are the same
   * `isPending` and the component has to draw different things for them.
   */
  isOffered: boolean;
  isLoading: boolean;
  /**
   * A member who is not an admin, which is a state rather than a failure.
   *
   * Still checked even though the request is no longer made for one: the prop
   * that gates it comes from the session and a stale one must not turn a 403
   * into an error banner.
   */
  isForbidden: boolean;
  error: unknown;
  save: (userId: number, email: string | null) => void;
  isSaving: boolean;
  saveError: unknown;
  isDirectoryOwned: boolean;
  hasSaved: boolean;
}

/**
 * Every member's address, for an admin.
 *
 * `isAdmin` gates the request rather than the rendering. It was rendering only,
 * and then every member's visit to this screen fired an admin endpoint and
 * threw the 403 away: a guaranteed refusal per page load, in the server log and
 * in the browser console, for the one screen every member is meant to use.
 *
 * It is not the authorisation. `require_admin` is, and `isForbidden` below
 * still handles the answer, because a prop is not a control.
 */
export function useMemberEmails(isAdmin: boolean): UseMemberEmailsResult {
  const queryClient = useQueryClient();
  // `retry: false` because a 403 here is the ordinary answer for a member who
  // reaches it anyway, and retrying it three times delays nothing useful.
  const query = useListEmails({ query: { retry: false, enabled: isAdmin } });

  const mutation = useSetMemberEmail({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getListEmailsQueryKey(),
        });
        // The admin's own row may be the one that changed.
        void queryClient.invalidateQueries({
          queryKey: getGetMyEmailQueryKey(),
        });
      },
    },
  });

  return {
    members: query.data,
    isOffered: isAdmin,
    isLoading: isAdmin && query.isLoading,
    // Orval types the error as the endpoint's declared body rather than what
    // the mutator throws, so the status is only reachable through the guard.
    isForbidden: query.error instanceof ApiError && query.error.status === 403,
    error: query.error,
    save: (userId: number, email: string | null) =>
      mutation.mutate({ userId, data: { email } }),
    isSaving: mutation.isPending,
    saveError: mutation.error,
    isDirectoryOwned: isDirectoryOwned(mutation.error),
    hasSaved: mutation.isSuccess,
  };
}
