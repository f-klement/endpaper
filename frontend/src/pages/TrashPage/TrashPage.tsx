import {
  Button,
  EmptyState,
  ErrorState,
  Icon,
  Spinner,
} from "../../components";
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
 */
export default function TrashPage() {
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
          trash.total > 0 && (
            <Button
              variant="secondary"
              size="sm"
              isLoading={trash.isEmptying}
              onClick={() => {
                if (confirm(t("trash.emptyAllConfirm", { count: trash.total })))
                  trash.empty();
              }}
              icon={<Icon name="trash" className="h-4 w-4" />}
            >
              {t("trash.emptyAll")}
            </Button>
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
                isBusy={trash.busyId === book.id}
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
