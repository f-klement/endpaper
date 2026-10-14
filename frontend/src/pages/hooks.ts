/**
 * Hooks that belong to no single page: the session, going back, a write
 * pressed on one row of a list, and returning a loan.
 *
 * The session is hoisted to this level because App gates routing on it and
 * LoginPage writes it, so it belongs to neither.
 *
 * Where the identity comes from depends on how the server is configured:
 *
 *   local / ldap   a JWT this app issued, kept in localStorage. A login form
 *                  is shown; under `ldap` it has no signup tab, because the
 *                  directory owns the accounts.
 *   proxy          an upstream has already authenticated the request and says
 *                  who it is in a header, so the identity is read back from
 *                  /auth/me and no auth screen is ever shown. A token is not
 *                  absent from that mode any more: an admin can exchange a
 *                  password for a session on a test account, and that session
 *                  has to win over the header until it is discarded. The
 *                  server decides that (see `auth._switch_session`); here it
 *                  means /auth/me is asked again whenever a token appears or
 *                  goes away, because its answer depends on one.
 */

import {
  useMutation,
  useMutationState,
  useQueryClient,
  type QueryClient,
  type UseMutationOptions,
} from "@tanstack/react-query";
import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  useAuthConfig,
  useLogout,
  useMe,
} from "../api/generated/endpoints/auth/auth";
import { getReturnLoanMutationOptions } from "../api/generated/endpoints/loans/loans";
import { AuthMode, type UserOut } from "../api/generated/model";
import { useInvalidate } from "../api/invalidate";
import { clearSession, setSession } from "../api/mutator";

const USER_KEY = "user";

/**
 * Read the cached account, tolerating a corrupt value.
 *
 * A half-written localStorage entry would otherwise throw during the very
 * first render and white-screen the app, with no way back short of clearing
 * site data by hand.
 */
export function readStoredUser(): UserOut | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as UserOut) : null;
  } catch {
    return null;
  }
}

export interface Session {
  mode: AuthMode;
  user: UserOut | null;
  /** True until we know both the mode and, under proxy, who the caller is. */
  isResolving: boolean;
  /**
   * Proxy mode is configured but the upstream did not identify anyone. Almost
   * always a deployment mistake rather than something the reader can fix, so
   * it is reported as a failure instead of a login form they cannot use.
   */
  proxyUnidentified: boolean;
  /**
   * This session is a switch into a test account, and can be handed back.
   *
   * Only ever true under proxy, and not because switching is unavailable in
   * the other two modes: there it is indistinguishable from a sign-in, because
   * the admin's own token was replaced by the new one and getting back means
   * signing in again. Under proxy nothing replaced anything, so dropping the
   * token is enough and the interface has to offer that somewhere.
   */
  isSwitched: boolean;
  signIn: (user: UserOut, token: string) => void;
  signOut: () => void;
}

export function useSession(): Session {
  const queryClient = useQueryClient();
  const config = useAuthConfig({ query: { retry: false } });
  const mode = config.data?.auth_mode ?? AuthMode.local;
  const isProxy = mode === AuthMode.proxy;

  // The local session: written and cleared as one with the token, by
  // `setSession` and `clearSession`. Under proxy it is not the identity, only
  // the fact that a switch token exists.
  const [storedUser, setStoredUser] = useState<UserOut | null>(readStoredUser);

  // Only asked for under proxy: in the other modes the account travels in the
  // token and a request here would be a round trip for something we hold.
  const me = useMe({ query: { enabled: isProxy, retry: false } });
  const refetchMe = me.refetch;

  // Under proxy the server is the authority on who this is, token or no token,
  // so nothing here has to reason about precedence: it asks again and reads
  // the answer. Storing the switched account and displaying it instead would
  // be a second opinion, and the two would disagree the moment a token expired.
  //
  // Nobody at all until the mode is known, rather than falling back to the
  // stored account while the config request is in flight. Under proxy that
  // fallback is a **different person**: whatever a previous session left in
  // localStorage, which is not who the upstream says is here. The app renders
  // a spinner throughout (`isResolving`), so this changes nothing on screen,
  // and it is what stops the identity flipping between two answers.
  const user = config.isPending
    ? null
    : isProxy
      ? (me.data ?? null)
      : storedUser;

  useCacheClearedOnIdentityChange(user?.id ?? null, queryClient);

  const signIn = useCallback(
    (account: UserOut, token: string) => {
      setSession(token, account);
      setStoredUser(account);
      // /auth/me answers differently now that the request carries a token, and
      // under proxy its answer is the identity. Nothing else would ask.
      if (isProxy) void refetchMe();
    },
    [isProxy, refetchMe],
  );

  const logout = useLogout();

  // The token is a stateless JWT, so there is nothing server-side to expire,
  // but the cover cookie is the server's and outlives the tab: on a shared
  // machine the next person's first page load would still fetch covers as
  // whoever left. `mutate`, not `mutateAsync`, and the local state is cleared
  // regardless: a failed request must not leave somebody apparently signed in.
  //
  // Under proxy this is "return to my own account" rather than a sign-out:
  // signing out is the upstream's business, and what this drops is the switch
  // token and the cover cookie that came with it. The proxy names the admin
  // again on the very next request, which is why /auth/me is asked for one.
  const signOut = useCallback(() => {
    logout.mutate();
    clearSession();
    // The one clear the effect below cannot own, and the comment there says
    // why: signing out is a known identity becoming nobody, which is spelled
    // the same way as not knowing yet.
    queryClient.clear();
    setStoredUser(null);
    if (isProxy) void refetchMe();
  }, [logout, queryClient, isProxy, refetchMe]);

  return {
    mode,
    user,
    isResolving: config.isPending || (isProxy && me.isPending),
    proxyUnidentified: isProxy && me.isError,
    // Both halves, because a stored token is not the same claim as a session
    // the server is honouring. It re-reads `is_switch_target` per request and
    // falls back to the header the moment a token stops qualifying: expiry,
    // the flag coming off the row, or a leftover entry from before this
    // deployment moved to proxy auth. On any of those the stored account and
    // the server's answer disagree, and offering "Return to my account" to
    // somebody who already is themselves is the same second opinion the
    // comment above `user` refuses.
    isSwitched: isProxy && storedUser !== null && me.data?.id === storedUser.id,
    signIn,
    signOut,
  };
}

/**
 * Drop the whole query cache when the person at the keyboard changes.
 *
 * React Query's client is created once per page load and does not care who is
 * signed in, and none of the ways the identity changes reloads the page:
 * signing out stays put, "Switch account" is a router link to /login that is
 * deliberately reachable while signed in, switching into a test account is a
 * button in Settings, and under proxy the identity can change with nothing
 * happening in this app at all. So without this the next member is handed the
 * previous one's answers back under identical keys, and at the default
 * staleTime nothing refetches for another thirty seconds.
 *
 * What that leaks is the whole shelf. `visible_to()` is "public or mine", so a
 * cached listing carries **private** books, and `my_status`, `my_rating` and
 * `active_loan` are computed per caller.
 *
 * Keyed on the account id rather than called from each path, because the
 * defect is not in any one of them: it is that a member-scoped answer outlives
 * the member. A path added later gets this for free, which is the half a call
 * at each site could not have, and the proxy path could not have at all: there
 * is no call site, because nothing in this app made the change.
 *
 * **Only between two known accounts**, and the reason is not caution. `null`
 * here means "nobody" *and* "not known yet", and the identity is itself two
 * cached queries, so clearing the cache produces a null. Treating that as a
 * change clears again, which produces another null: an app that refetches for
 * as long as it is open. Signing out is the one known account becoming nobody
 * that matters, and it is deliberate, so `signOut` says so itself.
 *
 * `mutator.ts::endSession` reaches the same place on the 401 path by doing a
 * full navigation instead.
 */
function useCacheClearedOnIdentityChange(
  accountId: number | null,
  queryClient: QueryClient,
): void {
  // The last account actually known, not the last value seen: a null in
  // between must not be able to hide a change from one member to another.
  const previous = useRef(accountId);

  // `useLayoutEffect`, not `useEffect`, and the difference is a painted frame.
  // A passive effect runs after commit and may run after paint, so the render
  // that first shows the new member can be painted from the previous one's
  // cached listing: `staleTime` keeps it fresh, so nothing refetches, and it
  // is their private books on screen. This runs before the browser paints.
  // Signing in used to clear synchronously, and that property has to survive
  // the move into an effect.
  useLayoutEffect(() => {
    if (accountId === null) return;
    if (previous.current !== null && previous.current !== accountId) {
      queryClient.clear();
    }
    previous.current = accountId;
  }, [accountId, queryClient]);
}

/**
 * Back, with somewhere to go.
 *
 * `navigate(-1)` is not a back button. On a deep link, a reload or a PWA cold
 * start there is no prior entry in this router's history and the control does
 * nothing at all: no navigation, no error, nothing on screen. React Router
 * marks that case, `location.key` is the string `"default"` for the first
 * entry, so the fallback is used exactly then and the browser's own history
 * the rest of the time.
 *
 * Here rather than inlined at the call site because "what does back mean"
 * is one decision, and a second page would otherwise answer it differently.
 */
export function useGoBack(fallback = "/"): () => void {
  const navigate = useNavigate();
  const { key } = useLocation();

  return useCallback(() => {
    if (key === "default") navigate(fallback);
    else navigate(-1);
  }, [key, navigate, fallback]);
}

/** The fields of a write's variables that hold a number, which a row id is. */
type RowKey<TVariables> = {
  [K in keyof TVariables]-?: TVariables[K] extends number ? K : never;
}[keyof TVariables] &
  string;

/**
 * A generated `get<Operation>MutationOptions`, which is what a row write is
 * built from. The hook of the same name would hide the mutation key, and the
 * key is what finds the calls still out.
 */
type WriteOptions<TData, TVariables> = (options?: {
  mutation?: UseMutationOptions<TData, unknown, TVariables>;
}) => UseMutationOptions<TData, unknown, TVariables>;

/**
 * What a write answers and what it is called with, read off its options.
 *
 * Read rather than inferred from `WriteOptions` at the call, because the
 * generated getters are generic in their error and context types and the
 * compiler then infers nothing at all for the other two.
 */
type Built<W> = W extends (...args: never) => infer R ? R : never;
// Every position inferred: `UseMutationOptions` is invariant in its variables,
// so matching one position against `unknown` would answer `never`.
type Parts<W> =
  Built<W> extends UseMutationOptions<infer D, infer E, infer V, infer C>
    ? { data: D; variables: V; others: [E, C] }
    : never;
type DataOf<W> = Parts<W>["data"];
type VariablesOf<W> = Parts<W>["variables"];

export interface RowWrite<TVariables> {
  mutate: (variables: TVariables) => void;
  /** Every row with a call of this write out, so each such row shows it. */
  pendingRows: ReadonlySet<number>;
  /** The most recent failure of any call, until the next press. */
  error: unknown;
}

/**
 * A write pressed on one row of a list, whichever row it was pressed on.
 *
 * A mutation hook's `error` and `isPending` describe its latest call only. So
 * a write pressed on a second row while the first is out unmarks the first,
 * and a failure on the first is silent once the second succeeds. This reads
 * the calls out of the mutation cache instead, by the key of the mutation it
 * runs, so the key cannot name a different write; and it reports failures
 * from the write's own options, which every call keeps.
 *
 * The cache match is by prefix and from anywhere, so a call still out from
 * another page marks its row here too. A press clears the failure, as the
 * latest call's `error` did, and a later failure replaces it: the slot holds
 * one failure, the most recent.
 *
 * `row` must be a number field of the write's variables, so a misspelt key
 * fails the type check rather than marking nothing. Any number field passes,
 * a sibling one too (`bookId` on a note's write), so which is the row is the
 * caller's to pick. The row is that id alone: a write whose row is the pair of
 * an id and a parent, such as a tag taken off one book, marks that id under
 * every parent, since a tag's id is the same on every book that carries it.
 */
export function useRowWrite<W extends (...args: never) => unknown>(
  write: W & WriteOptions<DataOf<W>, VariablesOf<W>>,
  row: RowKey<VariablesOf<W>>,
  onSuccess?: (data: DataOf<W>, variables: VariablesOf<W>) => void,
): RowWrite<VariablesOf<W>> {
  const build: WriteOptions<DataOf<W>, VariablesOf<W>> = write;
  const [error, setError] = useState<unknown>(null);
  const options = build({
    mutation: {
      onMutate: () => setError(null),
      // An updater, because `setError` would call a thrown function as one.
      onError: (failure) => setError(() => failure),
      onSuccess: (data, variables) => onSuccess?.(data, variables),
    },
  });
  // Without a key the filter below matches every write in the app.
  if (options.mutationKey === undefined)
    throw new Error("A row write needs a mutation key");
  const mutation = useMutation(options);
  const calls = useMutationState({
    filters: { mutationKey: options.mutationKey, status: "pending" },
    select: (call) => call.state.variables,
  });

  const pendingRows = new Set<number>();
  for (const call of calls) {
    // Typed, but read from a cache any write can reach, so checked: a call
    // with nothing under the key marks nothing, and row zero still marks.
    const id: unknown = (call as Record<string, unknown> | undefined)?.[row];
    if (typeof id === "number") pendingRows.add(id);
  }

  return {
    mutate: (variables) => mutation.mutate(variables),
    pendingRows,
    error,
  };
}

export interface UseLoanReturnResult {
  /** Every loan whose return is out, so each such row shows it. */
  returningIds: ReadonlySet<number>;
  markReturned: (loanId: number) => void;
  /** A return's failure, for the page's own error slot. */
  error: unknown;
}

/**
 * Marking a loan returned from a list of loans.
 *
 * Both loan lists draw `LoanRow` and return through this, so the write and
 * what it makes stale, `invalidate.loans()`, are named once.
 */
export function useLoanReturn(): UseLoanReturnResult {
  const invalidate = useInvalidate();
  const returning = useRowWrite(getReturnLoanMutationOptions, "loanId", () =>
    invalidate.loans(),
  );

  return {
    returningIds: returning.pendingRows,
    markReturned: (loanId) => returning.mutate({ loanId }),
    error: returning.error,
  };
}
