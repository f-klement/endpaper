/**
 * Hooks that belong to no single page: the session, going back, a write
 * pressed on one row of a list, returning a loan, asking which Book already
 * holds a file, and re-checking the files saved from a re-picked folder.
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
import {
  findFileHolders,
  getListDigitalReferencesQueryKey,
  getListMissingDigitalReferencesQueryKey,
  listDigitalReferencesUnderRoot,
  sweepDigitalReferences,
} from "../api/generated/endpoints/books/books";
import { getReturnLoanMutationOptions } from "../api/generated/endpoints/loans/loans";
import {
  AuthMode,
  type BookFormat,
  type BookOut,
  type DigitalReferenceIn,
  type DigitalReferenceOut,
  type HoldersOut,
  type SightingIn,
  type UserOut,
} from "../api/generated/model";
import { useInvalidate } from "../api/invalidate";
import { clearSession, setSession } from "../api/mutator";
import { writeOneAtATime } from "../lib/bulkWrite";
import { referenceFor } from "../lib/digitalReference";
import { partialMd5 } from "../lib/fileDigest";

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

// ── Which Book already holds a file ─────────────────────────────────────────
//
// **Here because two pages ask it**: a folder picked on the scan page, and the
// Calibre import on the library settings page. Both follow one landing rule,
// so it has one home.

/**
 * Which copy of the title a file's ISBN already belongs to takes the file's
 * location, or `undefined` where none may.
 *
 * **A copy of the same kind of object, or one nobody said the kind of.**
 * Owner's ruling, 2026-10-15. A reference says where the file of
 * *this row* is, and `books.format` is per row, so which row carries it already
 * states the relationship: an EPUB carrying its print ISBN, which Calibre
 * produces often, used to land as a file location on the household's
 * hardcover. Where no copy matches, the file is a new copy in its own format,
 * and that is a press the member makes (`addAsCopy`), never one this page
 * guesses.
 *
 * **Every copy and not only the one the 409 names.** The server names the
 * lowest id holder, and a copy shares its ISBN, so after `addAsCopy` made the
 * ebook beside a hardcover every later 409 still names the hardcover. Asking
 * that row alone offered the copy again on a re-pick, and the press made a
 * duplicate ebook.
 *
 * An exact format first, then an unset one, so a recorded ebook beats a row
 * nobody described. `copies` is in id order with the holder in it, which is
 * what `GET /{id}/copies` answers. A row whose own format is blank matches
 * only an unset copy; no file row is blank today, because every extension in
 * `fileName.FORMAT_FOR_EXTENSION` answers a format.
 */
export function whereItLands(
  copies: readonly Pick<BookOut, "id" | "format">[],
  fileFormat: BookFormat | "",
): number | undefined {
  const exact = copies.find(
    (copy) => copy.format != null && copy.format === fileFormat,
  );
  return (exact ?? copies.find((copy) => copy.format == null))?.id;
}

/**
 * How many files one `POST /api/books/file-holders` may name.
 *
 * The schema's `maxItems` on `HoldersIn.files`, which
 * `tests/pages/hooks.test.ts` recomputes from `openapi.json`. A pick
 * larger than this is asked in chunks of it.
 */
export const FILES_PER_LOOKUP = 500;

/**
 * A Book already holding a file, and whether the file may land on it.
 *
 * `lands` is the landing rule's answer: the Book is the file's format or has
 * none recorded. A holder of another format is a match the file may not be
 * attached to, which is a reference left on a print row before that rule.
 */
export interface Held {
  readonly bookId: number;
  readonly lands: boolean;
  /**
   * Files of this book that another Book already holds and may take, by
   * `locationOf`, with that Book: `reportHeld` refreshes each there.
   */
  readonly elsewhere?: ReadonlyMap<string, number>;
}

/** Where a reference says a file is, as one key. */
function locationOf(reference: DigitalReferenceIn): string {
  return JSON.stringify([reference.root_label, reference.relative_path]);
}

/** Holders in the shape `whereItLands` reads. */
function asCopies(holders: HoldersOut["holders"]) {
  return holders.map((holder) => ({
    id: holder.book_id,
    format: holder.format,
  }));
}

/**
 * Which of the Books holding a file the row stands for, or `null` for none.
 *
 * **Only a holder the landing rule admits takes the file**, owner's ruling,
 * 2026-10-15, whether it matched by location or by fingerprint: a match on a
 * print row alone would otherwise write a new reference onto it. That case
 * answers the first holder with `lands` false, and the add offers the file
 * as its own copy, as a 409 of another format does.
 *
 * **Among the admitted, a holder at this very location first**, so a file
 * whose sighting is on an unset copy is refreshed there rather than gaining a
 * second reference on an exact copy that carries the same bytes elsewhere.
 */
function holderOf(
  answer: HoldersOut,
  fileFormat: BookFormat | "",
): Held | null {
  const first = answer.holders[0];
  if (first === undefined) return null;
  // `whereItLands` admits only the file's format or an unset one, which is
  // the landing rule, so a print holder is never picked here.
  const landing =
    whereItLands(
      asCopies(answer.holders.filter((holder) => holder.same_location)),
      fileFormat,
    ) ?? whereItLands(asCopies(answer.holders), fileFormat);
  return landing === undefined
    ? { bookId: first.book_id, lands: false }
    : { bookId: landing, lands: true };
}

/**
 * Where this file is, now with its fingerprint, while the `File` is in hand.
 *
 * **Only for a file that has a location**: a file picked one at a time has no
 * reference to carry the digest, so nothing is read for it. A digest that
 * cannot be read leaves the reference without one rather than losing it.
 */
export async function locate(
  file: File,
): Promise<DigitalReferenceIn | undefined> {
  if (referenceFor(file) === null) return undefined;
  const digest = await partialMd5(file).catch(() => null);
  return referenceFor(file, digest) ?? undefined;
}

/**
 * One book to ask about: its key, where each of its files is, and what format
 * it would be.
 *
 * **Every file and not the first alone.** A Calibre book is a file per format,
 * and the first may have been rewritten since the library was last picked
 * (Calibre's metadata embedding does that) while the second is unchanged, so
 * asking by one file calls a held book new.
 */
export interface HolderQuestion {
  readonly key: string;
  readonly references: readonly DigitalReferenceIn[];
  readonly format: BookFormat | "";
}

/**
 * The one answer a book's files add up to, or `undefined` for a book that was
 * not answered.
 *
 * A holder the file may land on first, then any holder, so a book held in its
 * own format is never reported as another kind's because one of its files is
 * also held by a print copy. `null` only where every file was answered and none is held: one
 * unanswered file leaves the book unasked rather than new.
 */
function oneAnswer(
  answers: readonly (Held | null | undefined)[],
): Held | null | undefined {
  const held = answers.filter((one) => one != null);
  const chosen = held.find((one) => one.lands) ?? held[0];
  if (chosen !== undefined) return chosen;
  return answers.every((one) => one === null) ? null : undefined;
}

/**
 * Which Book already holds each of these books' files, by key.
 *
 * **One request a `FILES_PER_LOOKUP` files**, every file of every book, sent
 * together.
 *
 * **A key missing from the answer was not answered**, because a chunk holding
 * one of its files failed. What that means is the caller's: the scan page
 * leaves the row unasked and asks again before it adds; the Settings import
 * asks once and adds such a book as new, where a duplicate ISBN still answers
 * 409. Never a reason to refuse the add: the lookup only stops a duplicate,
 * and the add is what the member pressed.
 */
export async function askWhoHolds(
  questions: readonly HolderQuestion[],
): Promise<Map<string, Held | null>> {
  const files = questions.flatMap((question) =>
    question.references.map((reference) => ({ question, reference })),
  );
  const chunks: (typeof files)[] = [];
  for (let start = 0; start < files.length; start += FILES_PER_LOOKUP) {
    chunks.push(files.slice(start, start + FILES_PER_LOOKUP));
  }
  // Together rather than one after another: each is a read, and a pick
  // needing more than one is a few thousand files.
  const answered = await Promise.all(
    chunks.map((chunk) =>
      findFileHolders({
        files: chunk.map(({ reference }) => ({
          root_label: reference.root_label,
          relative_path: reference.relative_path,
          partial_md5: reference.partial_md5 ?? null,
        })),
      }).catch(() => undefined),
    ),
  );
  type Answered = {
    readonly reference: DigitalReferenceIn;
    readonly answer: Held | null | undefined;
  };
  const byKey = new Map<string, Answered[]>();
  chunks.forEach((chunk, at) => {
    const answers = answered[at];
    const usable = answers !== undefined && answers.length === chunk.length;
    chunk.forEach(({ question, reference }, index) => {
      const answer = usable
        ? holderOf(answers[index]!, question.format)
        : undefined;
      byKey.set(question.key, [
        ...(byKey.get(question.key) ?? []),
        { reference, answer },
      ]);
    });
  });
  const held = new Map<string, Held | null>();
  for (const [key, ofThisBook] of byKey) {
    const one = oneAnswer(ofThisBook.map(({ answer }) => answer));
    if (one === undefined) continue;
    // **A file held by another Book stays on it.** Written onto the one
    // chosen, it became a second reference to the same file on a second
    // Book.
    const elsewhere = new Map(
      ofThisBook.flatMap(({ reference, answer }) =>
        one !== null && answer?.lands && answer.bookId !== one.bookId
          ? [[locationOf(reference), answer.bookId] as const]
          : [],
      ),
    );
    held.set(
      key,
      one !== null && elsewhere.size > 0 ? { ...one, elsewhere } : one,
    );
  }
  return held;
}

/**
 * Every file of a book already held: each onto the Book `held.elsewhere`
 * names for it, the rest onto `held.bookId`, one after another through
 * `reportEach`, stopping at the first refusal and rethrowing it.
 */
export async function reportHeld(
  held: Held,
  references: readonly DigitalReferenceIn[],
  post: (bookId: number, reference: DigitalReferenceIn) => Promise<unknown>,
): Promise<void> {
  await reportEach(
    references.map((reference) => ({
      reference,
      bookId: held.elsewhere?.get(locationOf(reference)) ?? held.bookId,
    })),
    ({ bookId, reference }) => post(bookId, reference),
  );
}

/**
 * Every reference onto one Book, one after another, stopping at the first the
 * server refuses and rethrowing it. A folder sweep sends its chunks through it
 * too, for the same one writer.
 *
 * **One after another, through the loop every bulk write here shares**, for
 * that loop's reason (one SQLite writer) and for the per book ceiling: the
 * server holds it whatever arrives, and a client sending a book's files at
 * once is the client that makes it race. What was reported before a refusal
 * stays reported; each sighting is idempotent on its location.
 */
export async function reportEach<T = DigitalReferenceIn>(
  references: readonly T[],
  post: (reference: T) => Promise<unknown>,
): Promise<void> {
  // An object rather than a `let`: the loop's callbacks set it, and a
  // narrowed `let` reads `undefined` after the await whatever they did.
  const refusal: { refused: boolean; thrown?: unknown } = { refused: false };
  await writeOneAtATime(references, {
    post: (reference) =>
      post(reference).catch((thrown: unknown) => {
        refusal.refused = true;
        refusal.thrown = thrown;
        throw thrown;
      }),
    onProgress: () => {},
    stopped: () => refusal.refused,
  });
  if (refusal.refused) throw refusal.thrown;
}

/** The most references one page of the listing under a root carries. */
export const REFERENCES_PER_PAGE = 200;

/** A stored reference a re-pick did not find, as the member is shown it. */
export interface NotFound {
  readonly referenceId: number;
  readonly bookId: number;
  /** The raw stored path. Rendered through `plainName`, never as it is. */
  readonly path: string;
}

/**
 * What re-picking one folder found among the files saved under its name.
 *
 * `checked`: sightings were written, and `notFound` waits for the member's
 * press before any of it is marked. `different`: the pick held none of the
 * saved paths, so it is taken for another folder sharing the name and
 * nothing was written.
 */
export type FolderSweep =
  | {
      readonly kind: "checked";
      readonly root: string;
      /** References whose file the pick held, so they were confirmed again. */
      readonly seen: number;
      /** Absent by path, found by fingerprint under another path. */
      readonly moved: number;
      readonly notFound: readonly NotFound[];
      /** How many the member's press marked, or `null` before the press. */
      readonly marked: number | null;
      /** Every Book whose references the sweep wrote, for the caches. */
      readonly bookIds: readonly number[];
    }
  | {
      readonly kind: "different";
      readonly root: string;
      readonly saved: number;
    };

/**
 * Every reference the member can see under one root, from this page on.
 *
 * Page after page rather than together, because the total is learned from
 * the first answer. Ends on a short page as well as on the total, so a total
 * that moved under the walk cannot keep it asking.
 */
async function storedUnder(
  root: string,
  page = 1,
): Promise<DigitalReferenceOut[]> {
  const answer = await listDigitalReferencesUnderRoot({
    root_label: root,
    page,
    page_size: REFERENCES_PER_PAGE,
  });
  const done =
    answer.items.length < REFERENCES_PER_PAGE ||
    page * REFERENCES_PER_PAGE >= answer.total;
  return done
    ? answer.items
    : [...answer.items, ...(await storedUnder(root, page + 1))];
}

/** Items in runs of `FILES_PER_LOOKUP`, the most one sweep request takes. */
function inChunks<T>(items: readonly T[]): T[][] {
  const chunks: T[][] = [];
  for (let start = 0; start < items.length; start += FILES_PER_LOOKUP) {
    chunks.push(items.slice(start, start + FILES_PER_LOOKUP));
  }
  return chunks;
}

/**
 * The absent references whose file the pick holds under another path.
 *
 * Matched on KOReader's digest, read only for a held file at no saved path
 * whose size equals an absent reference's: a size that matches nothing
 * cannot carry the digest, so a large folder is not read through for one
 * moved file.
 */
async function movedAmong(
  absent: readonly DigitalReferenceOut[],
  unclaimed: readonly File[],
): Promise<Set<number>> {
  const sized = absent.filter(
    (one) => one.partial_md5 != null && one.size_bytes != null,
  );
  const sizes = new Set(sized.map((one) => one.size_bytes));
  const candidates = unclaimed.filter((file) => sizes.has(file.size));
  const digests = new Set(
    await Promise.all(
      candidates.map((file) => partialMd5(file).catch(() => null)),
    ),
  );
  return new Set(
    sized.filter((one) => digests.has(one.partial_md5!)).map((one) => one.id),
  );
}

/**
 * Compare one root's saved references with the files a pick holds under it,
 * and write the sightings.
 *
 * **A file is matched by its path beneath the root, as raw text**, the same
 * text `referenceFor` sent when the reference was written.
 *
 * **Misses are not written here.** A root is only a folder name, and two
 * members' folders can share one (Calibre names every library alike), so a
 * pick cannot tell another member's file from a file that is gone. The
 * absent ones are returned for a person to mark. A pick holding none of the
 * saved paths is taken for a different folder and writes nothing at all.
 *
 * Sent in chunks of `FILES_PER_LOOKUP`, one after another, for the reason
 * `reportEach` is sequential: one SQLite writer.
 */
async function sweepRoot(
  root: string,
  held: ReadonlyMap<string, File>,
): Promise<FolderSweep | null> {
  const stored = await storedUnder(root);
  if (stored.length === 0) return null;
  const present = stored.filter((one) => held.has(one.relative_path));
  if (present.length === 0) {
    return { kind: "different", root, saved: stored.length };
  }
  const absent = stored.filter((one) => !held.has(one.relative_path));
  const saved = new Set(stored.map((one) => one.relative_path));
  const unclaimed = [...held]
    .filter(([path]) => !saved.has(path))
    .map(([, file]) => file);

  const [sightings, moved] = await Promise.all([
    Promise.all(
      present.map(async (one): Promise<SightingIn> => {
        const look = await locate(held.get(one.relative_path)!);
        return {
          reference_id: one.id,
          size_bytes: look?.size_bytes ?? null,
          file_modified_at: look?.file_modified_at ?? null,
          partial_md5: look?.partial_md5 ?? null,
        };
      }),
    ),
    movedAmong(absent, unclaimed),
  ]);

  const byId = new Map(stored.map((one) => [one.id, one]));
  const seen: number[] = [];
  await reportEach(inChunks(sightings), async (chunk) => {
    const answer = await sweepDigitalReferences({
      root_label: root,
      seen: chunk,
      missing: [],
    });
    seen.push(...answer.seen);
  });

  return {
    kind: "checked",
    root,
    seen: seen.length,
    moved: moved.size,
    notFound: absent
      .filter((one) => !moved.has(one.id))
      .map((one) => ({
        referenceId: one.id,
        bookId: one.book_id,
        path: one.relative_path,
      })),
    marked: null,
    bookIds: [
      ...new Set(
        seen.flatMap((id) => {
          const bookId = byId.get(id)?.book_id;
          return bookId === undefined ? [] : [bookId];
        }),
      ),
    ],
  };
}

/**
 * Re-check the references saved under each folder this pick names, writing
 * the sightings and returning what was not found.
 *
 * **Only a folder pick has a root**, so a pick of single files sweeps
 * nothing: `referenceFor` answers `null` for a file with no path, and a
 * browser that ignores `webkitdirectory` hands over exactly those.
 *
 * A root with nothing saved under it answers no sweep at all, so a first
 * pick of a folder says nothing.
 */
export async function sweepFolder(
  files: readonly File[],
): Promise<FolderSweep[]> {
  const roots = new Map<string, Map<string, File>>();
  for (const file of files) {
    const where = referenceFor(file);
    if (where === null) continue;
    const under = roots.get(where.root_label) ?? new Map<string, File>();
    under.set(where.relative_path, file);
    roots.set(where.root_label, under);
  }
  const swept: FolderSweep[] = [];
  await reportEach([...roots], async ([root, held]) => {
    const one = await sweepRoot(root, held);
    if (one !== null) swept.push(one);
  });
  return swept;
}

/**
 * Mark what a sweep did not find as missing, on the member's press.
 *
 * The server writes only references under `root` on Books the member may
 * write; the answer is the ids it flagged. A flag never deletes.
 */
export async function markMissing(
  root: string,
  notFound: readonly NotFound[],
): Promise<number[]> {
  const marked: number[] = [];
  await reportEach(
    inChunks(notFound.map((one) => one.referenceId)),
    async (chunk) => {
      const answer = await sweepDigitalReferences({
        root_label: root,
        seen: [],
        missing: chunk,
      });
      marked.push(...answer.missing);
    },
  );
  return marked;
}

export interface UseFolderSweepResult {
  /** Sweep the folders a pick names. Fire and forget. */
  sweep: (files: readonly File[]) => void;
  /** What the last sweep found, or `null` before one has finished. */
  swept: readonly FolderSweep[] | null;
  /** Mark what one root's sweep did not find as missing. */
  markMissing: (root: string) => void;
  isMarking: boolean;
  /** The last sweep or press stopped on a refusal; what it wrote stays. */
  failed: boolean;
}

/**
 * A re-picked folder confirms the files still in it and lists the ones that
 * are not, for the member to mark as missing.
 *
 * Shared by every door that takes a folder of book files, so the scan page
 * and the Calibre card sweep the same way.
 *
 * **Only the latest pick's answer is shown.** Two picks close together race,
 * and the earlier one finishing last would otherwise replace the later one's
 * notice with a stale one.
 */
export function useFolderSweep(): UseFolderSweepResult {
  const queryClient = useQueryClient();
  const [swept, setSwept] = useState<readonly FolderSweep[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [isMarking, setIsMarking] = useState(false);
  const latest = useRef(0);

  const refresh = useCallback(
    (bookIds: Iterable<number>) => {
      for (const bookId of new Set(bookIds)) {
        void queryClient.invalidateQueries({
          queryKey: getListDigitalReferencesQueryKey(bookId),
        });
      }
      void queryClient.invalidateQueries({
        queryKey: getListMissingDigitalReferencesQueryKey(),
      });
    },
    [queryClient],
  );

  const sweep = useCallback(
    (files: readonly File[]) => {
      const pick = (latest.current += 1);
      setSwept(null);
      setFailed(false);
      sweepFolder(files).then(
        (result) => {
          if (pick !== latest.current) return;
          setSwept(result);
          refresh(
            result.flatMap((one) =>
              one.kind === "checked" ? one.bookIds : [],
            ),
          );
        },
        () => {
          if (pick === latest.current) setFailed(true);
        },
      );
    },
    [refresh],
  );

  const mark = useCallback(
    (root: string) => {
      const one = swept?.find(
        (each) => each.kind === "checked" && each.root === root,
      );
      if (one?.kind !== "checked" || one.notFound.length === 0) return;
      const pick = latest.current;
      setIsMarking(true);
      setFailed(false);
      markMissing(root, one.notFound)
        .then(
          (ids) => {
            if (pick !== latest.current) return;
            const done = { ...one, marked: ids.length };
            setSwept((current) =>
              (current ?? []).map((each) => (each === one ? done : each)),
            );
            refresh(one.notFound.map((file) => file.bookId));
          },
          () => {
            if (pick === latest.current) setFailed(true);
          },
        )
        .finally(() => setIsMarking(false));
    },
    [swept, refresh],
  );

  return { sweep, swept, markMissing: mark, isMarking, failed };
}
