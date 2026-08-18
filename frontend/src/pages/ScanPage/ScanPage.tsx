import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ErrorState, Spinner } from "../../components";
import { useTranslation, type MessageKey } from "../../i18n";
import { parseIsbn } from "../../lib/isbn";
import BarcodeScanner from "./components/BarcodeScanner";
import GoogleSearchPanel from "./components/GoogleSearchPanel";
import GoogleBooksHelp from "../components/GoogleBooksHelp";
import LookupResult from "./components/LookupResult";
import RapidQueue from "./components/RapidQueue";
import { useGoogleSearch, useRapidIntake, useScanFlow } from "./hooks";

export default function ScanPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const scan = useScanFlow((bookId) => navigate(`/book/${bookId}`));
  const search = useGoogleSearch();
  const rapid = useRapidIntake();
  const [showSearchHelp, setShowSearchHelp] = useState(false);
  const [manualIsbn, setManualIsbn] = useState("");
  const [manualError, setManualError] = useState<MessageKey | null>(null);

  // The scanner and the search box are both ways of choosing *which* book.
  // Once a draft exists that question is answered, so both step aside.
  const showEntry = scan.draft === null && !scan.isLookingUp && !rapid.isActive;

  function handleManualLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = manualIsbn.trim();
    if (!trimmed) return;

    // Validated here rather than at the server: a typo should be told to the
    // reader immediately, and the parser accepts the hyphenated form people
    // paste from a copyright page.
    const canonical = parseIsbn(trimmed);
    if (canonical === null) {
      setManualError("scan.invalidIsbn");
      return;
    }

    setManualError(null);
    scan.lookup(canonical);
  }

  function handleCancel() {
    scan.reset();
    setManualIsbn("");
    setManualError(null);
    search.clear();
  }

  return (
    <div className="max-w-lg mx-auto px-4 pt-5">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
          📷 {t("scan.title")}
        </h1>
        {scan.draft === null && (
          <button
            type="button"
            onClick={rapid.isActive ? rapid.stop : rapid.start}
            className="text-sm font-medium text-sky-600 hover:text-sky-700 dark:text-sky-400"
          >
            {rapid.isActive ? t("rapid.stop") : t("rapid.start")}
          </button>
        )}
      </div>

      {rapid.isActive && (
        <>
          <BarcodeScanner active onDetected={rapid.capture} />
          <p className="text-xs text-gray-500 mt-3 leading-relaxed dark:text-gray-400">
            {t("rapid.explain")}
          </p>
          <RapidQueue
            entries={rapid.entries}
            isAdding={rapid.isAdding}
            result={rapid.result}
            onRemove={rapid.remove}
            onAddAll={rapid.addAll}
            onDiscard={rapid.clear}
          />
        </>
      )}

      {showEntry && (
        <>
          <BarcodeScanner active onDetected={scan.lookup} />
          <p className="text-center text-sm text-gray-500 mt-3 mb-4 dark:text-gray-400">
            {t("scan.orEnterManually")}
          </p>
          <form onSubmit={handleManualLookup} className="flex gap-2">
            <input
              type="text"
              value={manualIsbn}
              onChange={(event) => setManualIsbn(event.target.value)}
              placeholder="9780743273565"
              aria-label={t("scan.isbnLabel")}
              className="flex-1 px-3 py-2.5 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-sky-400 text-sm dark:border-gray-700"
            />
            <button
              type="submit"
              className="px-4 py-2.5 bg-sky-500 text-white rounded-lg text-sm font-medium hover:bg-sky-600 transition-colors"
            >
              {t("scan.lookUp")}
            </button>
          </form>
          {manualError && (
            <div className="mt-2">
              <ErrorState error={t(manualError)} />
            </div>
          )}

          {/* The third way in, for a book with no barcode or a damaged one.
              Only when an admin has configured Google Books. */}
          {search.isEnabled && (
            <GoogleSearchPanel
              isConfigured={search.isConfigured}
              onOpenHelp={() => setShowSearchHelp(true)}
              query={search.query}
              matches={search.matches}
              isSearching={search.isSearching}
              isEmpty={search.isEmpty}
              error={search.error}
              onQueryChange={search.setQuery}
              onSubmit={search.submit}
              onChoose={scan.chooseMatch}
            />
          )}
        </>
      )}

      {scan.isLookingUp && (
        <div className="text-center py-12">
          <Spinner label={t("scan.lookingUp")} />
          <p className="text-gray-500 text-sm mt-3 dark:text-gray-400">
            {t("scan.lookingUp")}
          </p>
        </div>
      )}

      {showSearchHelp && (
        <GoogleBooksHelp
          isUnconfigured={!search.isConfigured}
          onClose={() => setShowSearchHelp(false)}
        />
      )}

      {scan.draft && (
        <LookupResult
          draft={scan.draft}
          tags={scan.tags}
          selectedTagIds={scan.selectedTagIds}
          coverFile={scan.coverFile}
          isPrivate={scan.isPrivate}
          isAdding={scan.isAdding}
          error={scan.error}
          onDraftChange={scan.setDraft}
          onToggleTag={scan.toggleTag}
          onCoverChange={scan.setCoverFile}
          onPrivateChange={scan.setIsPrivate}
          onConfirm={scan.confirm}
          onCancel={handleCancel}
        />
      )}
    </div>
  );
}
