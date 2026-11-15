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
  const synced = useRef<Mark | null>(null);
  // What this device had cached for this account, and therefore what is on
  // screen until the server answers. Anything else means the member changed
  // something in the meantime.
  const adopted = useRef<Mark | null>(null);

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
    const answer = readTheAnswer(
      accountId,
      stored,
      appearance,
      synced.current,
      adopted.current,
    );
    if (answer === null) return;
    synced.current = { account: accountId, value: answer.value };
    if (answer.kind === "push") save(answer.value);
    else adopt(answer.value, accountId);
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

/** An appearance, and the account it was taken from or sent to. */
interface Mark {
  account: number;
  value: Appearance;
}

/**
 * What the server's answer means for this account, once: nothing yet, an
 * appearance to adopt, or a newer local choice to push over it.
 */
function readTheAnswer(
  accountId: number,
  stored: Appearance | undefined,
  appearance: Appearance,
  synced: Mark | null,
  adopted: Mark | null,
): { kind: "push" | "adopt"; value: Appearance } | null {
  if (!stored) return null;
  if (synced?.account === accountId) return null;
  if (adopted?.account !== accountId) return null;

  // Somebody changed the appearance while the request was in flight. Their
  // choice is newer than the answer, so it wins and is pushed rather than
  // being reverted by it, which is a race a fast hand on the settings page
  // would otherwise lose.
  if (!sameAppearance(adopted.value, appearance)) {
    return { kind: "push", value: appearance };
  }
  return { kind: "adopt", value: stored };
}
