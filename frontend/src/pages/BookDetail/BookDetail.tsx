import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  OwnershipStatus,
  ReadStatus,
  type UserOut,
} from "../../api/generated/model";
import { CollapsibleSection, ErrorState, Spinner } from "../../components";
import { useTranslation } from "../../i18n";
import GoogleBooksHelp from "../components/GoogleBooksHelp";
import BookHeader from "./components/BookHeader";
import DiscussToggle from "./components/DiscussToggle";
import EnrichPanel from "./components/EnrichPanel";
import ReadingPanel from "./components/ReadingPanel";
import LoanBadge from "./components/LoanBadge";
import LoanPanel from "./components/LoanPanel";
import NoteList from "./components/NoteList";
import OwnershipPicker from "./components/OwnershipPicker";
import ProgressPanel from "./components/ProgressPanel";
import QuoteList from "./components/QuoteList";
import CollectionPicker from "./components/CollectionPicker";
import CopiesPanel from "./components/CopiesPanel";
import CopyPanel from "./components/CopyPanel";
import CustomFieldsPanel from "./components/CustomFieldsPanel";
import EnrichPicker from "./components/EnrichPicker";
import ShelfPanel from "./components/ShelfPanel";
import StatusPicker from "./components/StatusPicker";
import TagEditor from "./components/TagEditor";
import { Icon } from "../../components";
import { useGoBack } from "../hooks";
import {
  hasAbout,
  sectionDefaults,
  useBook,
  useBookActions,
  useBookCopies,
  useBookCustomFields,
  useBookEnrichment,
  useBookLoan,
  useBookNotes,
  useBookProgress,
  useBookQuotes,
  useBookSections,
  useGoodreadsLookup,
} from "./hooks";

interface BookDetailProps {
  currentUser: UserOut;
}

/**
 * One book, in six collapsible groups under an identity block that never folds.
 *
 * The page was seventeen panels in one column, three of them free text forms,
 * which on a phone is a form rather than a page. Grouping alone would not have
 * fixed that: the length is the problem, so the groups collapse, and which
 * ones arrive open depends on the book (`sectionDefaults`) until a reader says
 * otherwise (`useBookSections`).
 *
 * What is deliberately outside every section: the cover, title and author; the
 * loan badge, which is the one thing a member scans for; the privacy
 * control, because a control over who can see a book must not be something you
 * have to go looking for; the delete button, because a destructive action
 * hidden in a fold is a worse surprise than a long page; and the enrichment
 * button, for the reason recorded where it is rendered.
 *
 * Five of the six groups are always drawn, empty or not, because an empty one
 * still offers its act (lending a book nobody has borrowed). `about` is the
 * exception and is drawn only when there is something in it.
 */
export default function BookDetail({ currentUser }: BookDetailProps) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  // Not navigate(-1): on a deep link, a reload or a PWA cold start there is no
  // prior entry and that does nothing at all. See useGoBack.
  const goBack = useGoBack();
  const { t } = useTranslation();
  const bookId = Number(id);

  const {
    book,
    tags,
    users,
    locations,
    collections,
    isLoading,
    error,
    refetch,
  } = useBook(bookId);
  const actions = useBookActions(bookId, () => navigate("/"));
  const notes = useBookNotes(bookId);
  const quotes = useBookQuotes(bookId);
  const loan = useBookLoan(bookId);
  const progress = useBookProgress(bookId);
  const enrichment = useBookEnrichment(bookId);
  const copies = useBookCopies(bookId);
  const customFields = useBookCustomFields(bookId);
  const showGoodreadsLink = useGoodreadsLookup();
  const [showEnrichHelp, setShowEnrichHelp] = useState(false);
  // Above the early returns, because hooks are. Null until the book lands, and
  // the page shows a spinner until then, so no section is ever drawn against a
  // default computed from a book that was not there.
  const sections = useBookSections(bookId, book ? sectionDefaults(book) : null);

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
    actions.error ??
    notes.error ??
    quotes.error ??
    loan.error ??
    progress.error;

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

      <div className="px-4 py-5 space-y-4">
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

        {book.active_loan && <LoanBadge loan={book.active_loan} />}

        <div>
          <CollapsibleSection
            id="reading"
            title={t("section.reading")}
            isOpen={sections.isOpen("reading")}
            onToggle={() => sections.toggle("reading")}
          >
            <StatusPicker
              current={book.my_status ?? ReadStatus.unread}
              onChange={actions.setStatus}
            />

            <ReadingPanel book={book} onRate={actions.setRating} />

            {/* Under the status and the rating, because it is the third thing
                this reader has to say about this book, and the only one
                anybody else gets to see. Not in the lending group: it is a
                fact about a reader, not about where the object is. */}
            <DiscussToggle
              book={book}
              currentUserId={currentUser.id}
              onChange={actions.setDiscuss}
            />

            {/* Below the status buttons, because the first entry promotes an
                unstarted book to reading: the control that asserts that sits
                next to the one that says so. */}
            <ProgressPanel
              book={book}
              entries={progress.entries}
              isRecording={progress.isRecording}
              onRecord={progress.record}
              onRemove={progress.remove}
            />
          </CollapsibleSection>

          <CollapsibleSection
            id="filing"
            title={t("section.filing")}
            isOpen={sections.isOpen("filing")}
            onToggle={() => sections.toggle("filing")}
          >
            <TagEditor
              bookTags={book.tags ?? []}
              allTags={tags}
              onAdd={actions.addTag}
              onRemove={actions.removeTag}
              onCreate={actions.createTag}
              isCreating={actions.isCreatingTag}
              onDelete={actions.deleteTag}
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

            {/* Under the shelf, because both answer "where does this one
                live": one physically, one in this library's own filing. */}
            <CollectionPicker
              book={book}
              collections={collections}
              isSaving={actions.isFiling}
              onChange={actions.setCollection}
              onCreate={actions.createCollection}
            />

            {/* Last in the group, and in this group rather than a sixth
                section, because a custom field is this library's own filing of
                a fact about the book, beside its tags, its shelf and its
                collection. It draws nothing at all until somebody defines a
                field in Settings, so a household that never uses the feature
                never sees a handle for it. */}
            <CustomFieldsPanel
              definitions={customFields.definitions}
              values={customFields.values}
              isSaving={customFields.isSaving}
              error={customFields.error}
              onSave={customFields.save}
            />
          </CollapsibleSection>

          <CollapsibleSection
            id="copies"
            title={t("section.copies")}
            isOpen={sections.isOpen("copies")}
            onToggle={() => sections.toggle("copies")}
          >
            <CopyPanel
              book={book}
              isSaving={actions.isSavingDetails}
              onSave={actions.updateDetails}
            />

            {/* After the details of this copy, because it only means anything
                once the reader has seen that those details are per object. */}
            <CopiesPanel
              book={book}
              copies={copies.copies}
              isAdding={copies.isAdding}
              error={copies.error}
              listError={copies.listError}
              onAdd={copies.add}
            />
          </CollapsibleSection>

          <CollapsibleSection
            id="lending"
            title={t("section.lending")}
            isOpen={sections.isOpen("lending")}
            onToggle={() => sections.toggle("lending")}
          >
            <LoanPanel
              book={book}
              members={otherMembers}
              isBusy={loan.isBusy}
              isSavingDetails={actions.isSavingDetails}
              onSaveLending={actions.updateDetails}
              onLend={loan.lend}
              onMarkReturned={loan.markReturned}
            />
          </CollapsibleSection>

          <CollapsibleSection
            id="writing"
            title={t("section.writing")}
            isOpen={sections.isOpen("writing")}
            onToggle={() => sections.toggle("writing")}
          >
            <NoteList
              notes={notes.notes}
              currentUser={currentUser}
              isAdding={notes.isAdding}
              onAdd={notes.add}
              onEdit={notes.edit}
              onRemove={notes.remove}
            />

            {/* Below the notes, deliberately. A note is written about the book
                and is the thing a reader reaches for first; a quote is copied
                out of it and is longer, so putting it above would push the
                shorter, commoner control off the first screen on a phone. */}
            <QuoteList
              quotes={quotes.quotes}
              currentUser={currentUser}
              isAdding={quotes.isAdding}
              onAdd={quotes.add}
              onEdit={quotes.edit}
              onRemove={quotes.remove}
            />
          </CollapsibleSection>

          {/* Drawn only when the catalogue knows something. Unlike the other
              five it offers no action of its own, so with no blurb and no
              categories its handle would open onto nothing. */}
          {hasAbout(book) && (
            <CollapsibleSection
              id="about"
              title={t("section.about")}
              isOpen={sections.isOpen("about")}
              onToggle={() => sections.toggle("about")}
            >
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
            </CollapsibleSection>
          )}
        </div>

        {/* Outside every section, with the two dialogues it raises.
            Deliberately not inside "About this book": that section is drawn
            only when the catalogue already knows something, which is exactly
            the book that needs no enrichment. It used to hide itself without
            an API key, and that left a library unable to fill in exactly the
            books the national catalogues cover best. Folding it away on a bare
            book is the same fault by a different route. */}
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

        {/* A dialogue is not part of any group, and one opened from a section
            that is then collapsed would go with it. */}
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
