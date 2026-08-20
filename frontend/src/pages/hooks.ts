/**
 * Session state, shared by every page.
 *
 * Hoisted to this level because App gates routing on it and LoginPage writes
 * it, so it belongs to neither.
 *
 * Where the identity comes from depends on how the server is configured:
 *
 *   local / ldap   a JWT this app issued, kept in localStorage. A login form
 *                  is shown; under `ldap` it has no signup tab, because the
 *                  directory owns the accounts.
 *   proxy          there is no token at all. An upstream has already
 *                  authenticated the request and says who it is in a header,
 *                  so the identity is simply read back from /auth/me and no
 *                  auth screen is ever shown.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  useAuthConfig,
  useLogout,
  useMe,
} from "../api/generated/endpoints/auth/auth";
import { AuthMode, type UserOut } from "../api/generated/model";
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
  signIn: (user: UserOut, token: string) => void;
  signOut: () => void;
}

export function useSession(): Session {
  const queryClient = useQueryClient();
  const config = useAuthConfig({ query: { retry: false } });
  const mode = config.data?.auth_mode ?? AuthMode.local;
  const isProxy = mode === AuthMode.proxy;

  const [storedUser, setStoredUser] = useState<UserOut | null>(readStoredUser);

  // Only asked for under proxy: in the other modes the account travels in the
  // token and a request here would be a round trip for something we hold.
  const me = useMe({ query: { enabled: isProxy, retry: false } });

  const signIn = useCallback(
    (account: UserOut, token: string) => {
      setSession(token, account);
      // Everything in the cache belongs to whoever was here before. The client
      // is created once per page load and survives an identity change, and
      // "Switch account" is a router link to /login rather than a navigation,
      // so signing in as somebody else would otherwise hand them the previous
      // member's entries back under identical keys: their books, including the
      // private ones, their reading status, their loans, their statistics. At
      // the default staleTime nothing refetches for another thirty seconds.
      //
      // `mutator.ts::endSession` already reasons this way on the 401 path, and
      // drops in-memory state by doing a full navigation. The deliberate paths
      // reach the same place through the router, so they have to say it.
      queryClient.clear();
      setStoredUser(account);
    },
    [queryClient],
  );

  const logout = useLogout();

  // The token is a stateless JWT, so there is nothing server-side to expire,
  // but the cover cookie is the server's and outlives the tab: on a shared
  // machine the next person's first page load would still fetch covers as
  // whoever left. `mutate`, not `mutateAsync`, and the local state is cleared
  // regardless: a failed request must not leave somebody apparently signed in.
  //
  // Under proxy there is nothing to sign out of here at all: signing out is
  // the upstream's business, and clearing local state would only make the app
  // flicker before the proxy identified the same person again.
  const signOut = useCallback(() => {
    logout.mutate();
    clearSession();
    // Before the state change rather than after, and for the reason above: the
    // next person at this browser must not be handed a cache belonging to the
    // person who just left.
    queryClient.clear();
    setStoredUser(null);
  }, [logout, queryClient]);

  return {
    mode,
    user: isProxy ? (me.data ?? null) : storedUser,
    isResolving: config.isPending || (isProxy && me.isPending),
    proxyUnidentified: isProxy && me.isError,
    signIn,
    signOut,
  };
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
