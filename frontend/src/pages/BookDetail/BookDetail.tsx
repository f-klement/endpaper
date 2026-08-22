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
import ProgressPanel from "./components/ProgressPanel";
import CopyPanel from "./components/CopyPanel";
import EnrichPicker from "./components/EnrichPicker";
import ShelfPanel from "./components/ShelfPanel";
import StatusPicker from "./components/StatusPicker";
import TagEditor from "./components/TagEditor";
import { Icon } from "../../components";
import { useGoBack } from "../hooks";
import {
  useBook,
  useBookActions,
  useBookEnrichment,
  useBookLoan,
  useBookNotes,
  useBookProgress,
  useGoodreadsLookup,
} from "./hooks";

interface BookDetailProps {
  currentUser: UserOut;
}

export default function BookDetail({ currentUser }: BookDetailProps) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  // Not navigate(-1): on a deep link, a reload or a PWA cold start there is no
  // prior entry and that does nothing at all. See useGoBack.
  const goBack = useGoBack();
  const { t } = useTranslation();
  const bookId = Number(id);

  const { book, tags, users, locations, isLoading, error, refetch } =
    useBook(bookId);
  const actions = useBookActions(bookId, () => navigate("/"));
  const notes = useBookNotes(bookId);
  const loan = useBookLoan(bookId);
  const progress = useBookProgress(bookId);
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
  const pageError =
    actions.error ?? notes.error ?? loan.error ?? progress.error;

  return (
    <div className="max-w-lg mx-auto">
      <BookHeader
        book={book}
        isRefreshing={actions.isRefreshing}
        refreshError={actions.refreshError}
        showGoodreadsLink={showGoodreadsLink}
        onBack={goBack}
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
              className="w-4 h-4 rounded border-paper-300 text-accent-600"
            />
            <span className="text-sm text-paper-600 dark:text-paper-300">
              {t("book.privateToggle")}
            </span>
          </label>
        ) : (
          book.is_private && (
            <span className="inline-flex items-center gap-1 text-xs text-paper-600 bg-paper-100 px-2 py-0.5 rounded dark:text-paper-400 dark:bg-paper-800">
              <Icon name="lock" className="w-3.5 h-3.5" />{" "}
              {t("book.privateBadge")}
            </span>
          )
        )}

        <TagEditor
          bookTags={book.tags ?? []}
          allTags={tags}
          onAdd={actions.addTag}
          onRemove={actions.removeTag}
          onCreate={actions.createTag}
          isCreating={actions.isCreatingTag}
          onDelete={actions.deleteTag}
        />

        {book.active_loan && <LoanBadge loan={book.active_loan} />}

        <StatusPicker
          current={book.my_status ?? ReadStatus.unread}
          onChange={actions.setStatus}
        />

        <ReadingPanel book={book} onRate={actions.setRating} />

        {/* Below the status buttons, because the first entry promotes an
            unstarted book to reading: the control that asserts that sits next
            to the one that says so. */}
        <ProgressPanel
          book={book}
          entries={progress.entries}
          isRecording={progress.isRecording}
          onRecord={progress.record}
          onRemove={progress.remove}
        />

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

        <CopyPanel
          book={book}
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

        {/* Always offered. It used to need an API key and hid itself without
            one, which left a household unable to fill in exactly the books
            the national catalogues cover best. */}
        {enrichment.isEnabled && (
          <EnrichPanel
            isConfigured={enrichment.isConfigured}
            onOpenHelp={() => setShowEnrichHelp(true)}
            isWorking={enrichment.isWorking}
            result={enrichment.result}
            error={enrichment.error}
            onBrowse={enrichment.browse}
            onDismiss={enrichment.dismiss}
          />
        )}

        {enrichment.isPickerOpen && (
          <EnrichPicker
            candidates={enrichment.candidates}
            isSearching={enrichment.isSearching}
            isWorking={enrichment.isWorking}
            isConfigured={enrichment.isConfigured}
            error={enrichment.error}
            onChoose={enrichment.choose}
            onClose={enrichment.close}
          />
        )}

        {book.description && (
          <div>
            <p className="text-sm font-semibold text-paper-700 mb-1 dark:text-paper-200">
              {t("book.description")}
            </p>
            <p className="text-sm text-paper-600 leading-relaxed dark:text-paper-300">
              {book.description}
            </p>
          </div>
        )}

        {book.categories && book.categories.length > 0 && (
          <div>
            <p className="text-sm font-semibold text-paper-700 mb-1.5 dark:text-paper-200">
              {t("book.categories")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {book.categories.map((category) => (
                <span
                  key={category}
                  className="text-xs text-paper-600 bg-paper-100 px-2 py-0.5 rounded dark:text-paper-400 dark:bg-paper-800"
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

        {/* No confirmation dialog. The delete is reversible and raises a
            toast offering exactly that, so a modal here would be friction in
            front of an action that can be taken back in one tap. The
            irreversible verb lives in the trash and does ask. */}
        <button
          onClick={actions.remove}
          className="w-full py-2.5 border border-danger-300 text-danger-500 hover:bg-danger-100 rounded-lg text-sm font-medium transition-colors mt-2 dark:border-danger-700 dark:text-danger-300"
        >
          {t("book.remove")}
        </button>
      </div>
    </div>
  );
}
