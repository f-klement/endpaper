/**
 * Data for the patrons page: one search, and the three writes.
 *
 * There is no list of every patron to fetch. The endpoint requires a term and
 * caps the page, so no single request reads the register, and this page asks
 * nothing until somebody has typed one. The term goes in a POST body, never a
 * URL, so no proxy or server request log records whom staff looked up.
 */

import { useQueryClient } from "@tanstack/react-query";

import {
  getGetPatronQueryKey,
  getSearchPatronsQueryKey,
  useCreatePatron,
  useDeletePatron,
  useSearchPatrons,
  useUpdatePatron,
} from "../../api/generated/endpoints/patrons/patrons";
import type { PatronCreate, PatronOut } from "../../api/generated/model";
import { calendarToday } from "./types";

/**
 * The key every search shares, whatever its term: the method and the path.
 *
 * Cut from the generated key rather than taken whole, because the generated
 * key with no body still ends in `undefined`, and react-query matches a filter
 * key element by element: `undefined` matches no search's body, so an erased
 * patron would stay on the screen until the cache aged out.
 */
const EVERY_SEARCH = getSearchPatronsQueryKey().slice(0, 2);

/**
 * How many matches one search asks for: the endpoint's own ceiling.
 *
 * A full page is the only sign more exist, since the endpoint returns no
 * total (a count of matching people is itself something it declines to say).
 */
export const SEARCH_LIMIT = 50;

export interface UsePatronSearchResult {
  /** The matches, or empty while there is no term or no answer yet. */
  patrons: PatronOut[];
  /** True once a term has been sent, so "no match" and "not asked" differ. */
  hasTerm: boolean;
  isLoading: boolean;
  /** The search came back as full as it may, so there may be more. */
  isCapped: boolean;
  /**
   * The reader's calendar day when the matches arrived, `YYYY-MM-DD`, which
   * decides whether a registration has expired.
   *
   * Taken from the answer's own timestamp rather than a clock read during
   * render, so a render stays pure and every row is judged against one day.
   */
  today: string;
  error: unknown;
  refetch: () => void;
}

/**
 * The patrons matching `term`, which arrives trimmed from the search box.
 *
 * Disabled while the term is empty, because the endpoint refuses an empty one
 * and an empty one would otherwise be a request whose only answer is a 422.
 */
export function usePatronSearch(term: string): UsePatronSearchResult {
  const hasTerm = term !== "";
  const query = useSearchPatrons(
    { q: term, limit: SEARCH_LIMIT },
    { query: { enabled: hasTerm, retry: false } },
  );
  const patrons = hasTerm ? (query.data ?? []) : [];
  return {
    patrons,
    hasTerm,
    isLoading: hasTerm && query.isPending,
    isCapped: patrons.length >= SEARCH_LIMIT,
    today: calendarToday(new Date(query.dataUpdatedAt)),
    error: hasTerm ? query.error : null,
    refetch: () => void query.refetch(),
  };
}

export interface UsePatronWritesResult {
  /** Register a patron; `onDone` runs once the server has the record. */
  create: (body: PatronCreate, onDone: () => void) => void;
  isCreating: boolean;
  createError: unknown;

  update: (patron: PatronOut, body: PatronCreate, onDone: () => void) => void;
  isUpdating: boolean;
  updateError: unknown;

  /** Erase the patron, which anonymises their loans and keeps the dates. */
  remove: (patron: PatronOut) => void;
  isRemoving: boolean;
  removeError: unknown;

  /** Forget the last save's refusal, as the form closes or opens anew. */
  resetSaveErrors: () => void;
}

/**
 * Register, edit and erase.
 *
 * Every write invalidates the searches, since any of them can change which
 * patrons a term matches or what a match says. `EVERY_SEARCH` matches every
 * search whatever its term and none of the single record keys, so an edit or
 * erasure names its own record as well.
 *
 * **No loan cache is invalidated by an erasure**, and that is deliberate: a
 * loan's payload names a member or a typed name and never a patron, so the
 * anonymised rows read exactly as they did.
 */
export function usePatronWrites(): UsePatronWritesResult {
  const queryClient = useQueryClient();

  const refreshSearches = () =>
    void queryClient.invalidateQueries({ queryKey: EVERY_SEARCH });
  const refreshRecord = (patronId: number) => {
    refreshSearches();
    void queryClient.invalidateQueries({
      queryKey: getGetPatronQueryKey(patronId),
    });
  };

  const create = useCreatePatron({ mutation: { onSuccess: refreshSearches } });
  const update = useUpdatePatron({
    mutation: { onSuccess: (_, { patronId }) => refreshRecord(patronId) },
  });
  const remove = useDeletePatron({
    mutation: { onSuccess: (_, { patronId }) => refreshRecord(patronId) },
  });

  return {
    create: (body, onDone) =>
      create.mutate({ data: body }, { onSuccess: onDone }),
    isCreating: create.isPending,
    createError: create.error,

    update: (patron, body, onDone) =>
      update.mutate({ patronId: patron.id, data: body }, { onSuccess: onDone }),
    isUpdating: update.isPending,
    updateError: update.error,

    remove: (patron) => remove.mutate({ patronId: patron.id }),
    isRemoving: remove.isPending,
    removeError: remove.error,

    resetSaveErrors: () => {
      create.reset();
      update.reset();
    },
  };
}
