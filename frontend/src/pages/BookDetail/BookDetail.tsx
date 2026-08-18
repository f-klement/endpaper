import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  OwnershipStatus,
  ReadStatus,
  type UserOut,
} from "../../api/generated/model";
import { ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import GoogleBooksHelp from "../components/GoogleBooksHelp";
import BookHeader from "./components/BookHeader";
import EnrichPanel from "./components/EnrichPanel";
import ReadingPanel from "./components/ReadingPanel";
import LoanBadge from "./components/LoanBadge";
import LoanPanel from "./components/LoanPanel";
import NoteList from "./components/NoteList";
import OwnershipPicker from "./components/OwnershipPicker";
import ShelfPanel from "./components/ShelfPanel";
import StatusPicker from "./components/StatusPicker";
import TagEditor from "./components/TagEditor";
import {
  useBook,
  useBookActions,
  useBookEnrichment,
  useBookLoan,
  useBookNotes,
  useGoodreadsLookup,
} from "./hooks";

interface BookDetailProps {
  currentUser: UserOut;
}

export default function BookDetail({ currentUser }: BookDetailProps) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const bookId = Number(id);

  const { book, tags, users, locations, isLoading, error, refetch } =
    useBook(bookId);
  const actions = useBookActions(bookId, () => navigate("/"));
  const notes = useBookNotes(bookId);
  const loan = useBookLoan(bookId);
  const enrichment = useBookEnrichment(bookId);
  const showGoodreadsLink = useGoodreadsLookup();
  const [showEnrichHelp, setShowEnrichHelp] = useState(false);

  if (isLoading) return <Spinner label={t("common.loading")} />;

  if (error || !book) {
    return (
      <div className="max-w-lg mx-auto px-4 pt-5">
        <ErrorState
          error={error}
          fallback={t("book.notFound")}
          onRetry={refetch}
        />
      </div>
    );
  }

  const isOwner = book.added_by?.id === currentUser.id;
  const otherMembers = users.filter((member) => member.id !== currentUser.id);
  const pageError = actions.error ?? notes.error ?? loan.error;

  return (
    <div className="max-w-lg mx-auto">
      <BookHeader
        book={book}
        isRefreshing={actions.isRefreshing}
        refreshError={actions.refreshError}
        showGoodreadsLink={showGoodreadsLink}
        onBack={() => navigate(-1)}
        onUploadCover={actions.uploadCover}
        onRefreshMetadata={actions.refreshMetadata}
      />

      <div className="px-4 py-5 space-y-5">
        {pageError != null && <ErrorState error={pageError} />}

        {/* Privacy is the owner's decision alone: making someone else's book
            private would hide it from everyone. */}
        {isOwner ? (
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={book.is_private}
              onChange={(event) => actions.setPrivacy(event.target.checked)}
              className="w-4 h-4 rounded border-gray-300 text-sky-500 focus:ring-sky-400"
            />
            <span className="text-sm text-gray-600 dark:text-gray-300">
              {t("book.privateToggle")}
            </span>
          </label>
        ) : (
          book.is_private && (
            <span className="inline-flex items-center gap-1 text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded dark:text-gray-500 dark:bg-gray-800">
              🔒 {t("book.privateBadge")}
            </span>
          )
        )}

        <TagEditor
          bookTags={book.tags ?? []}
          allTags={tags}
          onAdd={actions.addTag}
          onRemove={actions.removeTag}
        />

        {book.active_loan && <LoanBadge loan={book.active_loan} />}

        <StatusPicker
          current={book.my_status ?? ReadStatus.unread}
          onChange={actions.setStatus}
        />

        <ReadingPanel book={book} onRate={actions.setRating} />

        <OwnershipPicker
          value={book.ownership ?? OwnershipStatus.owned}
          onChange={actions.setOwnership}
        />

        <ShelfPanel
          book={book}
          knownLocations={locations}
          isSaving={actions.isSavingDetails}
          onSave={actions.updateDetails}
        />

        <LoanPanel
          book={book}
          members={otherMembers}
          isBusy={loan.isBusy}
          onLend={loan.lend}
          onMarkReturned={loan.markReturned}
        />

        {/* Only when an admin has switched the lookup on and configured a key.
            A button that always failed would be worse than no button. */}
        {enrichment.isEnabled && (
          <EnrichPanel
            isConfigured={enrichment.isConfigured}
            onOpenHelp={() => setShowEnrichHelp(true)}
            isWorking={enrichment.isWorking}
            result={enrichment.result}
            error={enrichment.error}
            onEnrich={enrichment.enrich}
            onDismiss={enrichment.dismiss}
          />
        )}

        {book.description && (
          <div>
            <p className="text-sm font-semibold text-gray-700 mb-1 dark:text-gray-200">
              {t("book.description")}
            </p>
            <p className="text-sm text-gray-600 leading-relaxed dark:text-gray-300">
              {book.description}
            </p>
          </div>
        )}

        {book.categories && book.categories.length > 0 && (
          <div>
            <p className="text-sm font-semibold text-gray-700 mb-1.5 dark:text-gray-200">
              {t("book.categories")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {book.categories.map((category) => (
                <span
                  key={category}
                  className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded dark:text-gray-400 dark:bg-gray-800"
                >
                  {category}
                </span>
              ))}
            </div>
          </div>
        )}

        <NoteList
          notes={notes.notes}
          currentUser={currentUser}
          isAdding={notes.isAdding}
          onAdd={notes.add}
          onEdit={notes.edit}
          onRemove={notes.remove}
        />

        {showEnrichHelp && (
          <GoogleBooksHelp
            isUnconfigured={!enrichment.isConfigured}
            onClose={() => setShowEnrichHelp(false)}
          />
        )}

        <button
          onClick={() => {
            if (confirm(t("book.removeConfirm", { title: book.title })))
              actions.remove();
          }}
          className="w-full py-2.5 border border-red-200 text-red-500 hover:bg-red-50 rounded-lg text-sm font-medium transition-colors mt-2 dark:border-red-900 dark:text-red-400"
        >
          {t("book.remove")}
        </button>
      </div>
    </div>
  );
}
