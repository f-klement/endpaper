import {
  Button,
  EmptyState,
  ErrorState,
  Icon,
  Spinner,
} from "../../components";
import type { BookOut, UserOut } from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import { Page, PageCount, PageHeader } from "../components";
import TrashRow from "./components/TrashRow";
import { useTrash } from "./hooks";

/**
 * What has been deleted, and the two things that can happen to it.
 *
 * The trash does not empty itself, and the page says so. This app has no
 * scheduler, so an automatic sweep would run at whatever moment the container
 * happened to restart, which is not a retention policy anybody chose.
 *
 * The trash lists every member's deleted public books, but a member may delete
 * for good only the ones they added, and an admin also the ones nobody is
 * recorded as adding, so the page offers that verb on those alone. The server
 * refuses the rest, and emptying the trash skips them.
 *
 * The page holds only the first page of the listing, so the empty the trash
 * button is drawn also while rows are unlisted: the caller's own may be among
 * them, and the button is their only way to reach those.
 */
export default function TrashPage({ currentUser }: { currentUser: UserOut }) {
  const { t } = useTranslation();
  const trash = useTrash();

  if (trash.isLoading) return <Spinner label={t("common.loading")} />;

  return (
    <Page width="narrow">
      <PageHeader
        icon="trash"
        title={t("trash.title")}
        badge={trash.total > 0 && <PageCount>{trash.total}</PageCount>}
        actions={
          (trash.books.some((book) => mayPurge(book, currentUser)) ||
            trash.total > trash.books.length) && (
            <EmptyTrashButton
              isAdmin={currentUser.is_admin}
              isEmptying={trash.isEmptying}
              onEmpty={trash.empty}
            />
          )
        }
      />

      {trash.error != null ? (
        <ErrorState
          error={trash.error}
          fallback={t("common.somethingWentWrong")}
          onRetry={trash.refetch}
        />
      ) : trash.books.length === 0 ? (
        <EmptyState
          icon="trash"
          title={t("trash.empty")}
          hint={t("trash.emptyHint")}
        />
      ) : (
        <>
          <p className="mb-4 text-sm text-paper-600 dark:text-paper-400">
            {t("trash.explain")}
          </p>
          <ul className="space-y-2">
            {trash.books.map((book) => (
              <TrashRow
                key={book.id}
                book={book}
                isBusy={trash.busyIds.has(book.id)}
                canPurge={mayPurge(book, currentUser)}
                onRestore={() => trash.restore(book.id)}
                onPurge={() => trash.purge(book.id)}
              />
            ))}
          </ul>
        </>
      )}
    </Page>
  );
}

/** Whether this member may delete the book for good, by the rule the page doc states. */
function mayPurge(book: BookOut, currentUser: UserOut): boolean {
  return book.added_by == null
    ? currentUser.is_admin
    : book.added_by.id === currentUser.id;
}

function EmptyTrashButton({
  isAdmin,
  isEmptying,
  onEmpty,
}: {
  isAdmin: boolean;
  isEmptying: boolean;
  onEmpty: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Button
      variant="secondary"
      size="sm"
      isLoading={isEmptying}
      onClick={() => {
        if (
          confirm(
            t(isAdmin ? "trash.emptyAllConfirmAdmin" : "trash.emptyAllConfirm"),
          )
        )
          onEmpty();
      }}
      icon={<Icon name="trash" className="h-4 w-4" />}
    >
      {t("trash.emptyAll")}
    </Button>
  );
}
