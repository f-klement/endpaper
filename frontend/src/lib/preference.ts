/**
 * What a stored preference is: a key this browser owns, and the rules for
 * reading and writing it.
 *
 * **This owns the mechanism. Every preference keeps its own meaning.** What is
 * duplicated once per preference and worth one owner is narrow: the two
 * failure paths, absence meaning the default, a stored value this version
 * cannot read meaning the default, and a write that no reader hears about.
 * What is not duplicated is what the value *is*, how it validates, what it
 * caps and why its key is spelled the way it is. Those stay in the module that
 * declares the preference, beside the prose that explains them, because moving
 * them here would put five unrelated rules in one file and leave five
 * docstrings pointing at values they no longer sit next to.
 *
 * **A preference is a choice this browser owns outright.** Stated as an
 * exclusion, because an inclusion list is what goes stale:
 *
 * * Not a cache of something the account owns. `theme/appearance.ts` keeps one
 *   key holding a record over accounts and a pointer to the last one, and the
 *   server is the owner. Nothing here models a key that does not vary with its
 *   scope, two values in one key, or a remote owner.
 * * Not a token and not an identity. `api/mutator.ts` owns those.
 * * Not a per tab marker, whose whole point is a lifetime this does not model.
 * * The locale would fit and is deliberately outside. Its one reader and its
 *   one writer are the same provider, so a subscription would buy it nothing.
 *
 * **There is deliberately no "forget every preference" call.** What survives a
 * sign out on a shared browser profile is recorded and accepted in
 * `docs/decisions.md`, and the fix it prescribes is a named pair of keys
 * cleared at one site rather than a sweep offered from here. A door that
 * offered the sweep would make reversing that acceptance a one line change
 * somebody makes without reading it.
 */

/**
 * The keys nothing here may claim.
 *
 * Not the population of stored keys, which is larger: these are the ones whose
 * names a preference declaring them by accident would collide with, and the
 * collision is refused at import rather than found later. The rule that keeps
 * this honest is not the list, which would go stale as the tree grows: it is
 * the guard in `tests/houseRules.test.ts` that reads every storage call site
 * under `src/` and requires each one to be this module or a named exemption.
 */
const NOT_A_PREFERENCE = [
  "token",
  "user",
  "appearance",
  "theme",
  "locale",
  // A per tab marker rather than a choice, and in `sessionStorage` rather than
  // here. Reserved anyway, so that the keys this refuses and the keys the guard
  // in `tests/houseRules.test.ts` exempts are the same set: they were two lists
  // maintained apart, and a key on one and not the other is a name a preference
  // could claim with the collision refused nowhere.
  "endpaper.edge-reload",
];

/** Every key declared so far, so a second claim on one is refused. */
const claimed = new Set<string>();

function claim(key: string): string {
  if (NOT_A_PREFERENCE.includes(key))
    throw new Error(`preference: "${key}" is not a preference's key to claim`);
  if (claimed.has(key))
    throw new Error(`preference: two preferences declare the key "${key}"`);
  claimed.add(key);
  return key;
}

/** The declared keys, for the guard that checks them against the call sites. */
export function declaredKeys(): readonly string[] {
  return [...claimed].sort();
}

/**
 * One set for every preference rather than one each.
 *
 * A snapshot is stable against the string it was decoded from, so a write to
 * one preference wakes the readers of the others, each re-reads, each is handed
 * back the value it already held, and React draws nothing. Two sets would be
 * accurate about which preference moved and nothing would read the difference.
 *
 * **What makes that safe is that this module is the only way to a snapshot.**
 * `usePreference` takes no selector and offers no hook for deriving a value
 * after the cache, so a caller cannot introduce an unstable snapshot. Without
 * that refusal a shared set would be worth arguing about, because an unstable
 * snapshot in one preference would loop when another was written and React's
 * warning would name the wrong feature.
 */
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Drop every cached snapshot and every listener.
 *
 * For the test setup only. The suite shares one module registry across the
 * files in a worker, so a cache and a listener set at module scope outlive the
 * test that filled them. Nothing in the application calls this: a snapshot is
 * invalidated by the stored string changing, never by being told to.
 */
export function forgetPreferences(): void {
  snapshots.clear();
  refused.clear();
  listeners.clear();
}

/**
 * Every decoded value, against the exact string it came from.
 *
 * **Two things rest on this and the second is why it exists.** A decode runs
 * once per stored string rather than once per render, and a read hands back the
 * *same* value until that string changes, which is what `useSyncExternalStore`
 * requires of a snapshot: a read building a fresh array every call would redraw
 * for ever.
 *
 * **Correct rather than merely fresh.** Every read still asks storage for the
 * string and compares, so a value written past this door, by a test seeding
 * storage or by another tab, is decoded again instead of being served stale.
 *
 * Keyed on the storage key, which is safe because no two preferences may claim
 * one key and no preference may spell one key for two scopes: both are refused
 * at import, so a key identifies a scope.
 */
const snapshots = new Map<string, { raw: string | null; value: unknown }>();

/**
 * One frozen default per key, for the path where storage would not answer.
 *
 * **Held rather than rebuilt, because a snapshot has to be stable even when it
 * is a default.** There is no stored string to key a cached value on when
 * `getItem` itself throws, and handing back a freshly built default every call
 * would redraw for ever: a private window would be the one place the library
 * never finished rendering, which is the failure a default exists to prevent.
 */
const refused = new Map<string, unknown>();

/** Frozen, keeping the type: a snapshot is shared, so it is not writable. */
function freeze<TValue>(value: TValue): TValue {
  return Object.freeze(value) as TValue;
}

function refusedValue<TScope, TValue>(
  key: string,
  scope: TScope,
  codec: Codec<TScope, TValue>,
): TValue {
  const held = refused.get(key);
  if (held !== undefined) return held as TValue;
  const value = freeze(codec.fallback(scope));
  refused.set(key, value);
  return value;
}

/** What a stored string means, what to store, and what absence means. */
interface Codec<TScope, TValue> {
  /** The value this string carries, or undefined for anything unreadable. */
  decode: (raw: string, scope: TScope) => TValue | undefined;
  /** What to store, or null to clear the key. */
  encode: (value: TValue, scope: TScope) => string | null;
  /** What this scope shows when nothing readable is stored. */
  fallback: (scope: TScope) => TValue;
}

/**
 * Read, decode and freeze, and answer with the default rather than throwing.
 *
 * **Nothing here may throw, and the reason is not tidiness.** React calls this
 * while rendering, so a throw is a blank screen rather than a fallback, and
 * every failure it has to absorb is real: a private window that refuses to
 * answer, storage that has been cleared, a string written by a version whose
 * values were spelled differently, a half written entry. None of those is a
 * reason to fail to draw a library. So the lookup, the read, the decode and
 * the default all sit inside one try.
 *
 * **The value is frozen, because it is shared.** Two readers of one preference
 * are handed one value, so a caller that sorted or spliced what it was given
 * would edit it for every later reader. A copy would hide that rather than
 * prevent it, and the stability above is what a copy cannot give.
 *
 * **This freeze is shallow, and a codec whose value is nested owes the rest.**
 * Said the other way round for a while, that a nested value was refused by its
 * type and so nothing was weaker than the copies this replaced. Both halves
 * were wrong for the one preference of the five with a nested value: the saved
 * searches used to be re-parsed from JSON on every read, which is a fresh graph
 * each time rather than a shallow copy of a shared one, and neither
 * `SavedSearch` nor `BookFilters` carries a `readonly`, so the type refuses
 * nothing below the top level. `savedSearches.ts` freezes its entries and their
 * filters in its own decode; the other four are strings, arrays of strings and
 * a record of string literals, which a shallow freeze covers completely.
 */
function snapshot<TScope, TValue>(
  key: string,
  scope: TScope,
  codec: Codec<TScope, TValue>,
): TValue {
  try {
    let raw: string | null;
    try {
      raw = localStorage.getItem(key);
    } catch {
      // Storage would not answer at all. Held default, not a built one.
      return refusedValue(key, scope, codec);
    }

    const held = snapshots.get(key);
    if (held !== undefined && held.raw === raw) return held.value as TValue;

    // **Cached against the string that failed, not only against one that
    // read.** A string this version cannot decode is decoded once rather than
    // on every render, which matters most when the decode is what threw.
    let value: TValue;
    try {
      value =
        raw === null
          ? codec.fallback(scope)
          : (codec.decode(raw, scope) ?? codec.fallback(scope));
    } catch {
      value = codec.fallback(scope);
    }
    const frozen = freeze(value);
    snapshots.set(key, { raw, value: frozen });
    return frozen;
  } catch {
    // Nothing above should reach here: a default is a literal or a copy of
    // one. Kept because React calls this while rendering, so the cost of being
    // wrong about that is a blank screen rather than a wrong value.
    return refusedValue(key, scope, codec);
  }
}

/**
 * Store it, or clear the key, and tell every reader either way.
 *
 * **Readers are told whether or not the write landed.** A refused write has to
 * reach the reader too: the reader is drawing whatever a control just tried to
 * change, and a notification that only fired on success would leave that
 * control drawn as though the press had taken. Storage is the single copy, so
 * a write that did not land reads back as whatever was there before.
 */
function store<TScope, TValue>(
  key: string,
  scope: TScope,
  value: TValue,
  codec: Codec<TScope, TValue>,
): void {
  try {
    const raw = codec.encode(value, scope);
    if (raw === null) localStorage.removeItem(key);
    else localStorage.setItem(key, raw);
  } catch {
    // Storage refused, or the codec did. The choice goes with it.
  }
  for (const listener of [...listeners]) listener();
}

/** A preference every reader of this browser shares, under one key. */
export interface Preference<TValue> {
  readonly key: string;
  read: () => TValue;
  write: (value: TValue) => void;
  subscribe: (listener: () => void) => () => void;
}

/**
 * A preference kept once per scope, under a key declared for each.
 *
 * **A key per scope rather than one key holding a record.** Writing one cannot
 * touch another, so independence is structural and there is no merge to get
 * wrong. `whenUnknown` is which scope a reader is answered with before the real
 * one has arrived, and it is a reading answer only: a write under an unknown
 * scope is refused by `usePreference`, never guessed.
 */
export interface ScopedPreference<TScope extends string, TValue> {
  keyFor: (scope: TScope) => string;
  read: (scope: TScope) => TValue;
  write: (scope: TScope, value: TValue) => void;
  subscribe: (listener: () => void) => () => void;
  readonly whenUnknown: TScope;
}

/**
 * Declare a preference under one literal key.
 *
 * **A literal, never a function that builds one.** A door that took
 * `(scope) => string` would make producing any key in this origin a typed and
 * exported capability of this module, and the names beside these hold an
 * identity and a token. A declared literal is checkable when the module loads,
 * and no preference here needs a key it has to compute.
 */
export function declarePreference<TValue>(
  key: string,
  codec: {
    decode: (raw: string) => TValue | undefined;
    encode: (value: TValue) => string | null;
    fallback: () => TValue;
  },
): Preference<TValue> {
  const claimedKey = claim(key);
  const scoped: Codec<undefined, TValue> = {
    decode: (raw) => codec.decode(raw),
    encode: (value) => codec.encode(value),
    fallback: () => codec.fallback(),
  };
  return {
    key: claimedKey,
    read: () => snapshot(claimedKey, undefined, scoped),
    write: (value) => store(claimedKey, undefined, value, scoped),
    subscribe,
  };
}

/**
 * Declare a preference kept once per scope.
 *
 * Every scope's key is a declared literal for the reason above, and two scopes
 * may not share one: they would share a cached snapshot and, worse, one mode's
 * choice would be the other's.
 */
export function declareScopedPreference<TScope extends string, TValue>(
  keys: Readonly<Record<TScope, string>>,
  whenUnknown: TScope,
  codec: Codec<TScope, TValue>,
): ScopedPreference<TScope, TValue> {
  // **A null prototype, so a scope outside the union resolves to nothing rather
  // than to an inherited member.** `Object.fromEntries` alone carries
  // `Object.prototype`, so `keyFor("__proto__" as TScope)` handed back an object
  // and `keyFor("toString" as TScope)` a function, either of which `getItem`
  // would coerce into a key nothing declared and nothing reserved. The type is
  // what keeps a scope inside the union and this is what happens when a cast
  // gets past it. Not a throw: a read may not throw.
  const claimedKeys = Object.assign(
    Object.create(null) as Record<TScope, string>,
    Object.fromEntries(
      Object.entries(keys).map(([scope, key]) => [scope, claim(key as string)]),
    ) as Record<TScope, string>,
  );
  const keyFor = (scope: TScope) => claimedKeys[scope];
  return {
    keyFor,
    read: (scope) => snapshot(keyFor(scope), scope, codec),
    write: (scope, value) => store(keyFor(scope), scope, value, codec),
    subscribe,
    whenUnknown,
  };
}
