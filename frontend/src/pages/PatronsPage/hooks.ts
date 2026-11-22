/**
 * Data for the patrons page: the three writes. The search, and the register
 * write the loan form shares, are `pages/hooks.ts`.
 *
 * There is no list of every patron to fetch. The endpoint requires a term and
 * caps the page, so no single request reads the register, and this page asks
 * nothing until somebody has typed one.
 */

import { useQueryClient } from "@tanstack/react-query";

import {
  getGetPatronQueryKey,
  useDeletePatron,
  useUpdatePatron,
} from "../../api/generated/endpoints/patrons/patrons";
import type { PatronCreate, PatronOut } from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";
import { EVERY_PATRON_SEARCH, useRegisterPatron } from "../hooks";

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
 * patrons a term matches or what a match says. `EVERY_PATRON_SEARCH` matches
 * every search whatever its term and none of the single record keys, so an
 * edit or erasure names its own record as well.
 *
 * **An edit or an erasure also forgets the loans that name the patron.** An
 * admin's loan carries the patron's name and card (`LoanOut.patron`), so a
 * cached badge or loan row would go on naming an erased patron, or an old
 * name, until its next fetch. The loan lists go whole, and each book the
 * patron has out by its own key, which the row's `open_loans` lists.
 */
export function usePatronWrites(): UsePatronWritesResult {
  const queryClient = useQueryClient();

  const refreshSearches = () =>
    void queryClient.invalidateQueries({ queryKey: EVERY_PATRON_SEARCH });
  const refreshRecord = (patronId: number) => {
    refreshSearches();
    void queryClient.invalidateQueries({
      queryKey: getGetPatronQueryKey(patronId),
    });
  };

  const invalidate = useInvalidate();
  const forgetLoansOf = (patron: PatronOut) => {
    invalidate.loans();
    for (const loan of patron.open_loans ?? []) invalidate.book(loan.book_id);
  };

  const registration = useRegisterPatron();
  const update = useUpdatePatron({
    mutation: { onSuccess: (_, { patronId }) => refreshRecord(patronId) },
  });
  const remove = useDeletePatron({
    mutation: { onSuccess: (_, { patronId }) => refreshRecord(patronId) },
  });

  return {
    create: (body, onDone) => registration.register(body, () => onDone()),
    isCreating: registration.isRegistering,
    createError: registration.error,

    update: (patron, body, onDone) =>
      update.mutate(
        { patronId: patron.id, data: body },
        {
          onSuccess: () => {
            forgetLoansOf(patron);
            onDone();
          },
        },
      ),
    isUpdating: update.isPending,
    updateError: update.error,

    remove: (patron) =>
      remove.mutate(
        { patronId: patron.id },
        { onSuccess: () => forgetLoansOf(patron) },
      ),
    isRemoving: remove.isPending,
    removeError: remove.error,

    resetSaveErrors: () => {
      registration.reset();
      update.reset();
    },
  };
}
