import { useState } from "react";

import type { PatronOut } from "../../api/generated/model";
import { Button, EmptyState, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import { Page, PageHeader, SearchBar } from "../components";
import PatronForm from "./components/PatronForm";
import PatronRow from "./components/PatronRow";
import {
  usePatronSearch,
  usePatronWrites,
  type UsePatronSearchResult,
  type UsePatronWritesResult,
} from "./hooks";
import { BLANK_DRAFT, draftOf } from "./types";

/** Which form is open: none, a new patron, or one patron's record. */
type Editing =
  | { kind: "closed" }
  | { kind: "new" }
  | { kind: "edit"; patron: PatronOut };

/**
 * The patron register, for staff: find a patron, register one, correct one,
 * erase one.
 *
 * **Admin only, and the route is the whole of that here.** `routes.tsx` mounts
 * this page only for an admin and the menu offers it only to one, so a member
 * meets the 404 page and never a link; the API refuses a member every patron
 * route whatever this page does.
 *
 * **A search, never a list.** The register is the most sensitive data the
 * application holds, and the endpoint answers only a term, capped at a page.
 * The term travels in a request body, so no request log records it.
 */
export default function PatronsPage() {
  const { t } = useTranslation();
  const [term, setTerm] = useState("");
  const [editing, setEditing] = useState<Editing>({ kind: "closed" });
  const search = usePatronSearch(term);
  const writes = usePatronWrites();

  const open = (next: Editing) => {
    writes.resetSaveErrors();
    setEditing(next);
  };
  const close = () => open({ kind: "closed" });

  return (
    <Page width="narrow">
      <PageHeader
        icon="user"
        title={t("patrons.title")}
        actions={
          <Button size="sm" onClick={() => open({ kind: "new" })}>
            {t("patrons.new")}
          </Button>
        }
      />

      <p className="text-sm text-paper-600 mb-4 dark:text-paper-400">
        {t("patrons.explain")}
      </p>

      <div className="mb-4">
        <SearchBar
          onSearch={setTerm}
          label={t("patrons.search")}
          placeholder={t("patrons.searchPlaceholder")}
        />
      </div>

      {writes.removeError != null && (
        <div className="mb-4">
          <ErrorState
            error={writes.removeError}
            fallback={t("patrons.couldNotDelete")}
          />
        </div>
      )}

      <PatronList search={search} writes={writes} onEdit={open} />

      <OpenForm editing={editing} writes={writes} onClose={close} />
    </Page>
  );
}

/** The hint before a search, the load error, no match, or a row per patron. */
function PatronList({
  search,
  writes,
  onEdit,
}: {
  search: UsePatronSearchResult;
  writes: UsePatronWritesResult;
  onEdit: (editing: Editing) => void;
}) {
  const { t } = useTranslation();
  if (!search.hasTerm) {
    return <EmptyState icon="search" title={t("patrons.searchHint")} />;
  }
  if (search.isLoading) return <Spinner label={t("common.loading")} />;
  if (search.error != null) {
    return (
      <ErrorState
        error={search.error}
        fallback={t("patrons.couldNotLoad")}
        onRetry={search.refetch}
      />
    );
  }
  if (search.patrons.length === 0) {
    return <EmptyState icon="search" title={t("patrons.noMatch")} />;
  }
  return (
    <>
      <ul className="grid gap-3">
        {search.patrons.map((patron) => (
          <PatronRow
            key={patron.id}
            patron={patron}
            today={search.today}
            isBusy={writes.isRemoving}
            onEdit={(chosen) => onEdit({ kind: "edit", patron: chosen })}
            onDelete={writes.remove}
          />
        ))}
      </ul>
      {search.isCapped && (
        <p className="text-xs text-paper-600 mt-3 dark:text-paper-400">
          {t("patrons.capped", { count: search.patrons.length })}
        </p>
      )}
    </>
  );
}

/** The register form or the edit form, whichever is open. */
function OpenForm({
  editing,
  writes,
  onClose,
}: {
  editing: Editing;
  writes: UsePatronWritesResult;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  if (editing.kind === "closed") return null;
  if (editing.kind === "new") {
    return (
      <PatronForm
        title={t("patrons.newTitle")}
        initial={BLANK_DRAFT}
        submitLabel={t("patrons.register")}
        busyLabel={t("patrons.registering")}
        isSaving={writes.isCreating}
        error={writes.createError}
        onSubmit={(body) => writes.create(body, onClose)}
        onClose={onClose}
      />
    );
  }
  const { patron } = editing;
  return (
    <PatronForm
      // Keyed on the record, so opening a second patron's form starts from
      // that patron rather than from the draft the first one left behind.
      key={patron.id}
      title={t("patrons.editTitle", { name: patron.name })}
      initial={draftOf(patron)}
      submitLabel={t("common.save")}
      busyLabel={t("common.saving")}
      isSaving={writes.isUpdating}
      error={writes.updateError}
      onSubmit={(body) => writes.update(patron, body, onClose)}
      onClose={onClose}
    />
  );
}
