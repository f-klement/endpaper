/**
 * Data access for the settings page.
 *
 * Everything the page needs, exposed as intent-shaped hooks. Nothing outside
 * this file imports from `api/generated`, so regenerating the client cannot
 * ripple into the components.
 *
 * `useSettingsSections` is the one exception to the title: it holds no server
 * state, only which cards this device has folded away.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, downloadFile } from "../../api/mutator";
import {
  readSectionChoices,
  resolveOpen,
  writeSectionChoice,
  type SectionChoices,
} from "../../lib/sectionState";
import { useSwitchAccount as useSwitchAccountMutation } from "../../api/generated/endpoints/auth/auth";
import {
  getListTestAccountsQueryKey,
  useCreateTestAccount,
  useListTestAccounts,
} from "../../api/generated/endpoints/users/users";
import {
  getGetFeatureFlagsQueryKey,
  getGetSettingsQueryKey,
  useGetSettings,
  useUpdateSettings,
} from "../../api/generated/endpoints/settings/settings";
import {
  getDownloadBackupUrl,
  useRestoreBackup,
} from "../../api/generated/endpoints/backup/backup";
import {
  useImportCsv,
  usePreviewImport,
} from "../../api/generated/endpoints/imports/imports";
import {
  getListCustomFieldsQueryKey,
  useBackfillCovers,
  useDefineCustomField,
  useDeleteCustomField,
  useListCustomFields,
  useRenameCustomField,
} from "../../api/generated/endpoints/books/books";
import { useInvalidate } from "../../api/invalidate";
import { useNotifyOverdue } from "../../api/generated/endpoints/loans/loans";
import type {
  CoverBackfillOut,
  CustomFieldKind,
  CustomFieldOut,
  ImportResultOut,
  ImportPreviewOut,
  OverdueNotifyResult,
  SettingsOut,
  SettingsUpdate,
  Token,
  UserOut,
} from "../../api/generated/model";

/** The admin-only settings record, plus a saver that refreshes the flags. */
export function useSettings() {
  const queryClient = useQueryClient();
  const query = useGetSettings({ query: { retry: false } });

  const mutation = useUpdateSettings({
    mutation: {
      onSuccess: (updated: SettingsOut) => {
        queryClient.setQueryData(getGetSettingsQueryKey(), updated);
        // The flags drive rendering across the whole app (the enrichment
        // button, the Goodreads links), and they are a different endpoint
        // with its own cache entry, so saving here has to invalidate there.
        void queryClient.invalidateQueries({
          queryKey: getGetFeatureFlagsQueryKey(),
        });
      },
    },
  });

  return {
    settings: query.data,
    isLoading: query.isLoading,
    error: query.error,
    // 403 for a non-admin is a legitimate state rather than a failure, so the
    // page states it plainly instead of rendering an error. Orval types the
    // error as the endpoint's declared error body, not as what the mutator
    // actually throws, so the status is only reachable through the guard.
    isForbidden: query.error instanceof ApiError && query.error.status === 403,
    // `mutate`, not `mutateAsync`: nothing awaits this, and mutateAsync
    // rejects on failure, so every failed save left an unhandled promise
    // rejection in the console. The failure is already reported through
    // `saveError`, which is what the page renders.
    save: (data: SettingsUpdate) => mutation.mutate({ data }),
    isSaving: mutation.isPending,
    saveError: mutation.error,
    hasSaved: mutation.isSuccess,
  };
}

/**
 * Bringing a library across from another service.
 *
 * Two steps rather than one, and the first is the point: a column guessed
 * wrong is invisible until after the import, and after the import the fix is
 * finding and deleting a few hundred books. So the file is read and reported
 * on before anything is written.
 */
export function useLibraryImport() {
  const invalidate = useInvalidate();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreviewOut | null>(null);
  const [result, setResult] = useState<ImportResultOut | null>(null);

  const previewing = usePreviewImport({
    mutation: { onSuccess: (data: ImportPreviewOut) => setPreview(data) },
  });

  const importing = useImportCsv({
    mutation: {
      onSuccess: (data: ImportResultOut) => {
        setResult(data);
        setPreview(null);
        setFile(null);
        // An import creates books, tags, authors and shelves, so every
        // catalogue view is now stale. Not the accounts or the settings: a
        // CSV import writes neither.
        invalidate.catalogue();
      },
    },
  });

  return {
    file,
    preview,
    result,

    // `mutate` for the same reason as above: the failure is surfaced through
    // `error`, not by rejecting a promise nobody is holding.
    choose: (chosen: File) => {
      setFile(chosen);
      setResult(null);
      importing.reset();
      previewing.mutate({ data: { file: chosen } });
    },

    confirm: (options: { createMissing: boolean; applyTags: boolean }) => {
      if (!file) return;
      importing.mutate({
        data: { file },
        params: {
          create_missing: options.createMissing,
          apply_tags: options.applyTags,
        },
      });
    },

    isPreviewing: previewing.isPending,
    isImporting: importing.isPending,
    error: previewing.error ?? importing.error,

    reset: () => {
      setFile(null);
      setPreview(null);
      setResult(null);
      previewing.reset();
      importing.reset();
    },
  };
}

/**
 * Fetching the covers of books that have none.
 *
 * This is the repair for a library that already exists. Storing covers as
 * books are added only ever helps books added afterwards, and the ones that
 * need it most arrived through a CSV import, which never resolved a cover.
 *
 * The run is bounded server side, so the result says how many are left and the
 * reader presses again. Deliberately not looped here: an automatic retry would
 * hammer two free public image services from a button nobody is watching.
 *
 * **The cursor is what lets pressing again make progress.** The server picks
 * its batch by book id, and a book it could not fix is still a candidate next
 * time, so without carrying `next_after_id` back the same unfixable hundred
 * would be retried for ever and the counter would never move. It comes back as
 * 0 at the end of the library, which starts the next press over and re-tries
 * the failures, since a service that was down may not be.
 */
export function useCoverBackfill() {
  const invalidate = useInvalidate();
  const [result, setResult] = useState<CoverBackfillOut | null>(null);
  const [cursor, setCursor] = useState(0);

  const backfill = useBackfillCovers({
    mutation: {
      onSuccess: (data: CoverBackfillOut) => {
        setResult(data);
        setCursor(data.next_after_id);
        // A run rewrites `cover_url` on up to a hundred books at once, and
        // every list and detail view renders it. Covers themselves are `<img>`
        // elements rather than queries, so what goes stale is the catalogue.
        invalidate.catalogue();
      },
    },
  });

  return {
    result,
    // `mutate`, not `mutateAsync`: the failure is reported through `error`.
    run: () => backfill.mutate({ params: { after_id: cursor } }),
    isRunning: backfill.isPending,
    error: backfill.error,
  };
}

/**
 * Downloading the whole library, and putting one back.
 *
 * The CSV export has always been there and is not a backup: it carries one row
 * per book and drops the notes, the loans, every member's reading status, the
 * accounts and every cover. This is the archive that holds all of it.
 *
 * Restoring is guarded twice, because it is the one action in this app that
 * destroys data it was not given the id of. The endpoint requires
 * `confirm=true`, and the page asks before sending it.
 */
export function useBackup() {
  const invalidate = useInvalidate();
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);

  const restore = useRestoreBackup({
    mutation: {
      onSuccess: () => {
        // The other write that earns the whole cache, and the clearer of the
        // two: every book, account, note, loan and setting has just been
        // replaced, including the row behind the signed-in member.
        invalidate.everything();
      },
    },
  });

  return {
    isDownloading,
    downloadError,
    download: () => {
      setIsDownloading(true);
      setDownloadError(null);
      const today = new Date().toISOString().slice(0, 10);
      downloadFile(getDownloadBackupUrl(), `endpaper-backup-${today}.zip`)
        .catch(setDownloadError)
        .finally(() => setIsDownloading(false));
    },

    restore: (file: File) =>
      restore.mutate({ data: { file }, params: { confirm: true } }),
    isRestoring: restore.isPending,
    restoreError: restore.error,
    restored: restore.data ?? null,
  };
}

/**
 * The accounts an admin created for testing, and the making of a new one.
 *
 * `enabled` rather than an unconditional query: every member reaches this page
 * for the language switch, and this endpoint is admin only, so asking without
 * the flag would be a 403 on every visit by everybody.
 *
 * The list is the switch-target list and the server refuses anything that is
 * not on it, so the filtering here is presentation. That is the right way
 * round: a client cannot be the control on who may be signed in as.
 */
export function useTestAccounts(enabled: boolean) {
  const queryClient = useQueryClient();
  const query = useListTestAccounts({ query: { enabled, retry: false } });

  const create = useCreateTestAccount({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getListTestAccountsQueryKey(),
        });
      },
    },
  });

  return {
    accounts: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    // `mutate`, not `mutateAsync`: the failure is rendered from `createError`,
    // and a rejected promise nobody holds is an unhandled rejection.
    create: (username: string, password: string) =>
      create.mutate({ data: { username, password } }),
    isCreating: create.isPending,
    createError: create.error,
    created: create.data ?? null,
  };
}

/**
 * Exchange a password for a session on a test account.
 *
 * A sign-in on somebody else's account, so it ends in the same place a login
 * does: `onSignIn` stores the token, and the session hook drops the cache
 * because the identity changed. Then away from Settings, which the new account
 * is not an admin of and would answer with "only an admin can change these".
 */
export function useSwitchToTestAccount(
  onSignIn: (user: UserOut, token: string) => void,
) {
  const navigate = useNavigate();

  const mutation = useSwitchAccountMutation({
    mutation: {
      onSuccess: (token: Token) => {
        onSignIn(token.user, token.access_token);
        navigate("/");
      },
    },
  });

  return {
    switchTo: (username: string, password: string) =>
      mutation.mutate({ data: { username, password } }),
    isSwitching: mutation.isPending,
    switchError: mutation.error,
  };
}

/**
 * Running the overdue digest by hand.
 *
 * The whole reason the endpoint exists: a webhook that only fires on an hourly
 * timer is a webhook nobody can tell they configured correctly. It reports
 * what it sent rather than "done", because "nothing is overdue" and "the
 * receiver refused it" are different answers and both look like silence.
 *
 * The result is held here rather than read from `mutation.data` at the call
 * site so the count survives the button being pressed again.
 */
export function useOverdueDigest() {
  const [result, setResult] = useState<OverdueNotifyResult | null>(null);

  const mutation = useNotifyOverdue({
    mutation: { onSuccess: (data: OverdueNotifyResult) => setResult(data) },
  });

  return {
    result,
    // `mutate`, not `mutateAsync`: nothing awaits it, and a rejected promise
    // nobody holds is an unhandled rejection. The failure renders from `error`.
    send: () => {
      setResult(null);
      mutation.mutate();
    },
    isSending: mutation.isPending,
    error: mutation.error,
  };
}

/**
 * This page's own localStorage entry. See `lib/sectionState.ts`: the book page
 * has a section called `about` too, and one shared key would merge them.
 */
const STORE = "settingsSections";

/**
 * The collapsible cards, in the order they are drawn.
 *
 * The ids are what reaches storage, so they are named after what a section is
 * rather than after its current title: `appearance`, not `theme.label`, and
 * `overdue`, not `reminders`. Renaming a title is then free; renaming an id
 * forgets what every reader said about that section.
 */
export const SETTINGS_SECTIONS = [
  "language",
  "appearance",
  "import",
  "covers",
  "customFields",
  "googleBooks",
  "goodreads",
  "defaultLanguage",
  "overdue",
  "reminderSenders",
  "testAccounts",
  "backup",
  "about",
] as const;

export type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number];

/**
 * Which cards arrive open, before anybody has said otherwise.
 *
 * The book page keys its defaults on the book. Settings has no equivalent fact
 * to test, so the rule is about what a section is for: **open when the current
 * setting is the whole of it and reading it is why you are here, closed when it
 * starts a job or holds a form.** Language, appearance, the Goodreads toggle
 * and the default language answer "what is this set to" in one glance; import,
 * the cover backfill, the webhook form, the mail and chat form, the custom
 * field list, test accounts
 * and backup are errands
 * somebody arrives at deliberately, and a deliberate arrival is what a fold
 * costs least.
 *
 * **`googleBooks` is the one exception, named here rather than left to be
 * noticed.** By the rule it should be closed: it holds a toggle, an API key
 * field with show, save and clear, and three hint paragraphs, which is the same
 * shape as `overdue` and the tallest open card on the page. It stays open
 * because the toggle *is* the setting and the key is its configuration, and
 * because closing it would put five closed handles in a row through the middle
 * of the page. A rule with a silent exception is worse than a rule with a
 * stated one.
 *
 * `about` is open under the same rule, and its openness is also the reason it
 * is not the only thing open. It carries a donation link, and a settings page
 * whose one expanded card asks for money is a donation prompt wearing a
 * settings page. Six open of thirteen is what keeps it one card among many for
 * an admin.
 *
 * **A member who is not an admin sees six cards** (language, appearance,
 * import, covers, custom fields, about), of which three are open, so the split
 * matters most there: folding `language` as well would leave that reader five
 * closed handles and nothing to read. Custom fields is the sixth and is closed,
 * because defining one is an errand: what a non-admin reads on arrival is
 * unchanged at three. It is also why About's own height is capped rather than
 * balanced against other cards: on that page there are no other cards to
 * balance it against, and every one of the extra open cards is admin only.
 *
 * A `Record` over every id rather than a partial, so adding a section without
 * deciding its default is a compile error rather than a silently closed panel.
 */
export const SETTINGS_SECTION_DEFAULTS: Record<SettingsSectionId, boolean> = {
  language: true,
  appearance: true,
  import: false,
  covers: false,
  customFields: false,
  googleBooks: true,
  goodreads: true,
  defaultLanguage: true,
  overdue: false,
  reminderSenders: false,
  testAccounts: false,
  backup: false,
  about: true,
};

export interface UseCustomFieldsResult {
  fields: CustomFieldOut[];
  define: (name: string, kind: CustomFieldKind) => void;
  rename: (fieldId: number, name: string) => void;
  remove: (fieldId: number) => void;
  isBusy: boolean;
  error: unknown;
}

/**
 * The path of one book's custom field values, as a pattern.
 *
 * A pattern rather than a key because the book id is **inside the path**, so
 * there is no prefix a key filter could match and no id to hand here anyway: a
 * rename changes the label every book draws and a delete removes rows from
 * every book. Same shape and same reason as `BOOK_RECORD` in
 * `api/invalidate.ts`.
 *
 * Deliberately not part of the `catalogue()` vocabulary there: these rows are
 * not derived from the books table, they change only when written, and
 * `tests/api/invalidate.test.ts` is where that classification is recorded.
 */
const BOOK_CUSTOM_FIELDS = /^\/api\/books\/\d+\/custom-fields$/;

/**
 * The library's own field definitions.
 *
 * Every write drops the list and every book's values with it: a renamed field
 * is the label a book draws, and a deleted one takes its values off every
 * book, so leaving those cached would show a name nobody uses any more.
 */
export function useCustomFields(): UseCustomFieldsResult {
  const queryClient = useQueryClient();
  const fields = useListCustomFields();

  const mutation = {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getListCustomFieldsQueryKey(),
      });
      void queryClient.invalidateQueries({
        predicate: (query) => {
          const path = query.queryKey[0];
          return typeof path === "string" && BOOK_CUSTOM_FIELDS.test(path);
        },
      });
    },
  };

  const define = useDefineCustomField({ mutation });
  const rename = useRenameCustomField({ mutation });
  const remove = useDeleteCustomField({ mutation });

  return {
    fields: fields.data ?? [],
    define: (name, kind) => define.mutate({ data: { name, kind } }),
    rename: (fieldId, name) => rename.mutate({ fieldId, data: { name } }),
    remove: (fieldId) => remove.mutate({ fieldId }),
    isBusy: define.isPending || rename.isPending || remove.isPending,
    error: fields.error ?? define.error ?? rename.error ?? remove.error,
  };
}

export interface UseSettingsSectionsResult {
  isOpen: (section: SettingsSectionId) => boolean;
  toggle: (section: SettingsSectionId) => void;
}

/**
 * Open or closed, per card, remembered per device.
 *
 * The three state rule `resolveOpen()` holds, with a fixed table where the book
 * page has a conditional one: absence follows the table, and a stored choice
 * beats it forever. Nothing here is frozen per arrival, because no default
 * depends on data that can change while the page is open.
 */
export function useSettingsSections(): UseSettingsSectionsResult {
  // Read once, on mount: storage is a starting point, and re-reading it on
  // every render would fight the state this component already holds.
  const [choices, setChoices] = useState<SectionChoices>(() =>
    readSectionChoices(STORE),
  );

  const isOpen = (section: SettingsSectionId) =>
    resolveOpen(choices[section], SETTINGS_SECTION_DEFAULTS[section]);

  return {
    isOpen,
    toggle: (section: SettingsSectionId) => {
      const next = !isOpen(section);
      writeSectionChoice(STORE, section, next);
      setChoices((current) => ({
        ...current,
        [section]: next ? "open" : "closed",
      }));
    },
  };
}
