/**
 * Data access for catalogue logins and the key that seals them.
 *
 * Beside the route rather than in the shared settings hook, which is the split
 * `SettingsPage/hooks.ts` describes: that file holds the one admin record four
 * routes share, and everything belonging to a single route lives next to it.
 *
 * Nothing outside a `hooks.ts` imports from `api/generated/endpoints`, so
 * regenerating the client cannot ripple into the components.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getGetCatalogueRegistryQueryKey,
  getGetCredentialKeyQueryKey,
  getGetSettingsQueryKey,
  useCreateCredentialKey,
  useDropRegistryCatalogue,
  useForgetCredentialKey,
  useForgetSourceCredential,
  useGetCatalogueRegistry,
  useGetCredentialKey,
  usePickRegistryCatalogue,
  useProbeCatalogueSource,
  useRestoreCredentialKey,
  useSetSourceCredential,
} from "../../../api/generated/endpoints/settings/settings";
import type {
  CatalogueRegistryOut,
  CredentialKeyOut,
  ProbeEvidenceOut,
  SettingsOut,
} from "../../../api/generated/model";

export interface UseCredentialKeyResult {
  key: CredentialKeyOut | undefined;
  isLoading: boolean;
  /**
   * The phrase, held only in this hook's state and only until it is dismissed.
   *
   * **Never read back from the server**, because there is no call that would
   * answer: `POST` refuses once a key exists. Losing it to a page reload is the
   * design working, not a defect, which is why the screen says to write it down
   * before it offers a way past.
   */
  phrase: string;
  dismissPhrase: () => void;
  create: () => void;
  /**
   * `onDone` runs only when the server accepted the phrase.
   *
   * **The caller needs that, and a fire and forget write could not give it.**
   * The checksum is the reason this encoding is a standard one, and a component
   * that cleared its field before the answer arrived threw away all 24 typed
   * words on the refusal the checksum exists to produce.
   */
  restore: (phrase: string, onDone?: () => void) => void;
  forget: () => void;
  isWorking: boolean;
  error: unknown;
}

/** The encryption key: what is in place, making one, taking one back in. */
export function useCredentialKey(): UseCredentialKeyResult {
  const queryClient = useQueryClient();
  const [phrase, setPhrase] = useState("");
  const query = useGetCredentialKey({ query: { retry: false } });

  // Both writes change what the settings screen can say about every source, so
  // both drop that record as well as this one.
  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: getGetCredentialKeyQueryKey(),
    });
    void queryClient.invalidateQueries({ queryKey: getGetSettingsQueryKey() });
  };

  const create = useCreateCredentialKey({
    mutation: {
      onSuccess: (made) => {
        setPhrase(made.phrase);
        refresh();
      },
    },
  });
  const restore = useRestoreCredentialKey({ mutation: { onSuccess: refresh } });
  const forget = useForgetCredentialKey({ mutation: { onSuccess: refresh } });

  return {
    key: query.data,
    isLoading: query.isLoading,
    phrase,
    dismissPhrase: () => {
      setPhrase("");
      // The mutation cache holds the same words on `create.data`, and clearing
      // one copy while claiming the phrase is gone is a docstring that is not
      // true. Nothing renders that copy and nothing persists it, so this is an
      // accuracy fix rather than a leak closed.
      create.reset();
    },
    // `mutate`, not `mutateAsync`: nothing awaits these, and mutateAsync
    // rejects on failure, leaving an unhandled rejection on every failed write.
    create: () => create.mutate(),
    restore: (words: string, onDone?: () => void) =>
      restore.mutate({ data: { phrase: words } }, { onSuccess: onDone }),
    forget: () => forget.mutate(),
    isWorking: create.isPending || restore.isPending || forget.isPending,
    error: create.error ?? restore.error ?? forget.error,
  };
}

/**
 * Whether a key is in place, for a caller that only needs to know.
 *
 * The same query key as `useCredentialKey`, so react-query serves both from one
 * request. Separate because the logins section needs the answer and none of the
 * writes.
 */
export function useCredentialKeyStatus(): CredentialKeyOut | undefined {
  return useGetCredentialKey({ query: { retry: false } }).data;
}

export interface UseSourceCredentialsResult {
  /** `onDone` runs only on success, so the fields survive a refusal. */
  save: (
    source: string,
    username: string,
    password: string,
    onDone?: () => void,
  ) => void;
  remove: (source: string) => void;
  isWorking: boolean;
  error: unknown;
}

/** Storing and removing one catalogue's login. */
export function useSourceCredentials(): UseSourceCredentialsResult {
  const queryClient = useQueryClient();

  // Both answer with the whole settings record, so it is written into the cache
  // rather than invalidated: the response is already the fresh value.
  const onSuccess = (updated: SettingsOut) => {
    queryClient.setQueryData(getGetSettingsQueryKey(), updated);
    void queryClient.invalidateQueries({
      queryKey: getGetCredentialKeyQueryKey(),
    });
  };

  const save = useSetSourceCredential({ mutation: { onSuccess } });
  const remove = useForgetSourceCredential({ mutation: { onSuccess } });

  return {
    save: (source, username, password, onDone) =>
      save.mutate(
        { source, data: { username, password } },
        { onSuccess: onDone },
      ),
    remove: (source) => remove.mutate({ source }),
    isWorking: save.isPending || remove.isPending,
    error: save.error ?? remove.error,
  };
}

export interface UseCatalogueRegistryResult {
  registry: CatalogueRegistryOut | undefined;
  setPicked: (source: string, picked: boolean) => void;
  isWorking: boolean;
  error: unknown;
}

/** The curated registry this build ships, and picking from it. */
export function useCatalogueRegistry(): UseCatalogueRegistryResult {
  const queryClient = useQueryClient();
  const query = useGetCatalogueRegistry({ query: { retry: false } });

  // Both answer with the whole registry, so it goes straight into the cache.
  const onSuccess = (updated: CatalogueRegistryOut) => {
    queryClient.setQueryData(getGetCatalogueRegistryQueryKey(), updated);
  };
  const pick = usePickRegistryCatalogue({ mutation: { onSuccess } });
  const drop = useDropRegistryCatalogue({ mutation: { onSuccess } });

  return {
    registry: query.data,
    setPicked: (source, picked) => (picked ? pick : drop).mutate({ source }),
    isWorking: pick.isPending || drop.isPending,
    error: query.error ?? pick.error ?? drop.error,
  };
}

export interface UseSourceTestResult {
  /** The last answer, a disposition and never what the catalogue sent. */
  result: ProbeEvidenceOut | undefined;
  run: () => void;
  isRunning: boolean;
  error: unknown;
}

/**
 * Testing one catalogue, seeded or from the registry.
 *
 * No ISBN is sent, so the server asks its default: a registry entry's own
 * evidence ISBN, which makes the result comparable with what the list shows.
 */
export function useSourceTest(source: string): UseSourceTestResult {
  const test = useProbeCatalogueSource();
  return {
    result: test.data,
    run: () => test.mutate({ source, data: {} }),
    isRunning: test.isPending,
    error: test.error,
  };
}
