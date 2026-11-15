import { useState, type FormEvent } from "react";

import { EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import CollectionCard from "./components/CollectionCard";
import { useCollections, type UseCollectionsResult } from "./hooks";
import { Page, PageHeader } from "../components";

/**
 * The library's collections: make one, rename one, delete one, browse one.
 *
 * Its own page rather than a section of Settings, for two reasons. Settings is
 * admin only in practice (its first request is), and any member may make a
 * collection. And this is a browse surface as much as an editing one: the card
 * links into the library filtered to the collection, which is the same shape
 * the series page already has.
 */
export default function CollectionsPage() {
  const { t } = useTranslation();
  const collections = useCollections();
  const [name, setName] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    collections.create(trimmed);
    setName("");
  }

  if (collections.isLoading) return <Spinner label={t("common.loading")} />;

  // Whichever write last failed. One line rather than three, because only one
  // of them can be in flight at a time from this page.
  const writeError =
    collections.createError ??
    collections.renameError ??
    collections.removeError;

  return (
    <Page width="narrow">
      <PageHeader icon="library" title={t("collections.title")} />

      <p className="text-sm text-paper-600 mb-4 dark:text-paper-400">
        {t("collections.explain")}
      </p>

      <CreateForm
        name={name}
        onNameChange={setName}
        onSubmit={submit}
        isCreating={collections.isCreating}
      />

      {writeError != null && (
        <div className="mb-4">
          <ErrorState
            error={writeError}
            fallback={t("common.somethingWentWrong")}
          />
        </div>
      )}

      <CollectionList collections={collections} />
    </Page>
  );
}

function CreateForm({
  name,
  onNameChange,
  onSubmit,
  isCreating,
}: {
  name: string;
  onNameChange: (name: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  isCreating: boolean;
}) {
  const { t } = useTranslation();
  return (
    <form onSubmit={onSubmit} className="flex gap-2 mb-4">
      <input
        type="text"
        value={name}
        onChange={(event) => onNameChange(event.target.value)}
        placeholder={t("collections.newPlaceholder")}
        aria-label={t("collections.newName")}
        maxLength={80}
        className="flex-1 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
      />
      <button
        type="submit"
        disabled={isCreating || name.trim() === ""}
        className="px-4 py-2 rounded-xl bg-accent-fill text-on-accent text-sm font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
      >
        {isCreating ? t("collections.creating") : t("collections.create")}
      </button>
    </form>
  );
}

/** The load error, the empty shelf, or a card per collection. */
function CollectionList({
  collections,
}: {
  collections: UseCollectionsResult;
}) {
  const { t } = useTranslation();
  if (collections.error != null) {
    return (
      <ErrorState
        error={collections.error}
        fallback={t("collections.couldNotLoad")}
        onRetry={collections.refetch}
      />
    );
  }
  if (collections.collections.length === 0) {
    return (
      <EmptyState
        icon="library"
        title={t("collections.empty")}
        hint={t("collections.emptyHint")}
      />
    );
  }
  const busy = collections.isRenaming || collections.isRemoving;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {collections.collections.map((collection) => (
        <CollectionCard
          key={collection.id}
          collection={collection}
          isBusy={busy}
          onRename={collections.rename}
          onDelete={collections.remove}
        />
      ))}
    </div>
  );
}
