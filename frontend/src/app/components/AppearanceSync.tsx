import { useEffect, useRef } from "react";

import { useStoredAppearance } from "../hooks";
import {
  readCachedAppearance,
  sameAppearance,
  useTheme,
  type Appearance,
} from "../../theme";

interface AppearanceSyncProps {
  /** The signed-in member. Their row is the authority. */
  accountId: number;
}

/**
 * Keeps the appearance on screen and the appearance on the account in step.
 *
 * Renders nothing. It exists because the two directions belong to different
 * layers: `ThemeProvider` sits above the router and knows nothing about
 * sessions or the API, and `hooks.ts` owns the generated client. This is the
 * one place that holds both.
 *
 * Down, on mount and on a change of account: this account's cached appearance
 * first, so switching members on a shared device does not leave the previous
 * one's palette on screen, and then the server's answer when it arrives.
 *
 * Up, whenever the member changes something: the whole appearance, replacing
 * the row.
 *
 * `synced` is what stops those two chasing each other. Adopting a value records
 * it there, so the effect that pushes sees no difference and sends nothing back.
 */
export default function AppearanceSync({ accountId }: AppearanceSyncProps) {
  const { appearance, adopt, release } = useTheme();
  const { stored, save } = useStoredAppearance(accountId);
  const synced = useRef<{ account: number; value: Appearance } | null>(null);
  // What this device had cached for this account, and therefore what is on
  // screen until the server answers. Anything else means the member changed
  // something in the meantime.
  const adopted = useRef<{ account: number; value: Appearance } | null>(null);

  useEffect(() => {
    const cached = readCachedAppearance(accountId);
    adopt(cached, accountId);
    adopted.current = { account: accountId, value: cached };
    synced.current = null;
    // The provider outlives this component, so unbinding is this component's
    // job: it is the only thing that knows an account is signed in.
    return release;
  }, [accountId, adopt, release]);

  useEffect(() => {
    if (!stored) return;
    if (synced.current?.account === accountId) return;
    if (adopted.current?.account !== accountId) return;

    // Somebody changed the appearance while the request was in flight. Their
    // choice is newer than the answer, so it wins and is pushed rather than
    // being reverted by it, which is a race a fast hand on the settings page
    // would otherwise lose.
    if (!sameAppearance(adopted.current.value, appearance)) {
      synced.current = { account: accountId, value: appearance };
      save(appearance);
      return;
    }

    synced.current = { account: accountId, value: stored };
    adopt(stored, accountId);
  }, [stored, appearance, accountId, adopt, save]);

  useEffect(() => {
    // Until the server has answered there is nothing to differ from, and
    // pushing here would overwrite a stored choice with this device's cache.
    if (synced.current === null || synced.current.account !== accountId) return;
    if (sameAppearance(synced.current.value, appearance)) return;
    synced.current = { account: accountId, value: appearance };
    save(appearance);
  }, [appearance, accountId, save]);

  return null;
}
