import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Button, ErrorState, Icon, Spinner } from "../../components";
import { LocationField } from "../components";
import { useTranslation, type MessageKey } from "../../i18n";
import { parseIsbn } from "../../lib/isbn";
import BarcodeScanner from "./components/BarcodeScanner";
import SearchPanel from "./components/SearchPanel";
import GoogleBooksHelp from "../components/GoogleBooksHelp";
import LookupResult from "./components/LookupResult";
import RapidQueue from "./components/RapidQueue";
import { useBookSearch, useRapidIntake, useScanFlow } from "./hooks";

export default function ScanPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const scan = useScanFlow((bookId) => navigate(`/book/${bookId}`));
  const search = useBookSearch();
  const rapid = useRapidIntake();
  const [showSearchHelp, setShowSearchHelp] = useState(false);
  const [manualIsbn, setManualIsbn] = useState("");
  const [manualError, setManualError] = useState<MessageKey | null>(null);

  // The camera is opened on request, never on arrival.
  //
  // It used to start the moment this tab was opened and run until the tab was
  // left, so walking past the Scan tab lit the phone's camera indicator and
  // held it there. Opening a camera is not something a page should do because
  // somebody looked at it.
  const [isCameraOn, setIsCameraOn] = useState(false);
  const [rejectedCode, setRejectedCode] = useState<string | null>(null);

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
    setRejectedCode(null);
    search.clear();
  }

  function handleDetected(isbn: string) {
    // Close the camera on a hit. The next step is confirming a draft, and
    // leaving the stream running behind that form keeps the indicator lit for
    // as long as somebody takes to check a title.
    setIsCameraOn(false);
    setRejectedCode(null);
    scan.lookup(isbn);
  }

  return (
    <div className="max-w-lg mx-auto px-4 pt-5">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-paper-900 dark:text-paper-100">
          {t("scan.title")}
        </h1>
        {scan.draft === null && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setIsCameraOn(false);
              setRejectedCode(null);
              if (rapid.isActive) rapid.stop();
              else rapid.start();
            }}
          >
            {rapid.isActive ? t("rapid.stop") : t("rapid.start")}
          </Button>
        )}
      </div>

      {rapid.isActive && (
        <>
          {/* Rapid mode has its own start and stop in the header, so the
              camera follows that switch rather than needing a second one. */}
          <BarcodeScanner
            active
            onDetected={rapid.capture}
            onRejected={setRejectedCode}
          />
          <p className="text-xs text-paper-600 mt-3 leading-relaxed dark:text-paper-400">
            {t("rapid.explain")}
          </p>
          {/* Above the queue rather than inside it, so the shelf can be named
              before the first barcode instead of remembered afterwards. */}
          <div className="mt-4">
            <LocationField
              value={rapid.location}
              onChange={rapid.setLocation}
              locations={rapid.locations}
              label={t("location.batchLabel")}
            />
          </div>
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
          {isCameraOn ? (
            <BarcodeScanner
              active
              onDetected={handleDetected}
              onRejected={setRejectedCode}
            />
          ) : (
            <div className="w-full aspect-[4/3] rounded-2xl border border-dashed border-paper-300 bg-paper-100/50 flex flex-col items-center justify-center gap-3 dark:border-paper-700 dark:bg-paper-900/50">
              <span className="grid place-items-center w-11 h-11 rounded-full bg-paper-200/60 text-paper-600 dark:bg-paper-800 dark:text-paper-400">
                <Icon name="camera" className="w-5 h-5" />
              </span>
              <p className="text-sm font-medium text-paper-600 dark:text-paper-300">
                {t("scan.cameraIdle")}
              </p>
              <p className="text-xs text-paper-600 text-center px-8 dark:text-paper-400">
                {t("scan.cameraIdleHint")}
              </p>
            </div>
          )}

          <Button
            variant={isCameraOn ? "secondary" : "primary"}
            fullWidth
            className="mt-3"
            icon={isCameraOn ? null : <Icon name="camera" className="w-4 h-4" />}
            onClick={() => {
              setRejectedCode(null);
              setIsCameraOn((on) => !on);
            }}
          >
            {isCameraOn ? t("scan.stopScanning") : t("scan.startScanning")}
          </Button>

          {/* A barcode that decoded but is not a book. Saying so is the whole
              point: silence here reads as a scanner that does not work, when
              what actually happened is that the price code was read instead of
              the ISBN. */}
          {rejectedCode && (
            <p
              role="status"
              className="mt-2 text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 dark:text-amber-300 dark:bg-amber-950/40"
            >
              {t("scan.notABook", { code: rejectedCode })}
            </p>
          )}

          <p className="text-center text-sm text-paper-600 mt-4 mb-4 dark:text-paper-400">
            {t("scan.orEnterManually")}
          </p>
          <form onSubmit={handleManualLookup} className="flex gap-2">
            <input
              type="text"
              value={manualIsbn}
              onChange={(event) => setManualIsbn(event.target.value)}
              placeholder="9780743273565"
              aria-label={t("scan.isbnLabel")}
              className="field flex-1"
            />
            <Button type="submit">{t("scan.lookUp")}</Button>
          </form>
          {manualError && (
            <div className="mt-2">
              <ErrorState error={t(manualError)} />
            </div>
          )}

          {/* The third way in, for a book with no barcode, a damaged one, or
              one printed before ISBNs existed. Always available: it no longer
              needs an API key, and hiding it from a household without one left
              them unable to add such a book at all. */}
          <SearchPanel
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
        </>
      )}

      {scan.isLookingUp && (
        <div className="text-center py-12">
          <Spinner label={t("scan.lookingUp")} />
          <p className="text-paper-600 text-sm mt-3 dark:text-paper-400">
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
          location={scan.location}
          locations={scan.locations}
          format={scan.format}
          isAdding={scan.isAdding}
          error={scan.error}
          onDraftChange={scan.setDraft}
          onToggleTag={scan.toggleTag}
          onCoverChange={scan.setCoverFile}
          onPrivateChange={scan.setIsPrivate}
          onLocationChange={scan.setLocation}
          onCreateTag={scan.createTag}
          isCreatingTag={scan.isCreatingTag}
          onFormatChange={scan.setFormat}
          onConfirm={scan.confirm}
          onCancel={handleCancel}
          onAddCopy={scan.addCopy}
          isAddingCopy={scan.isAddingCopy}
        />
      )}
    </div>
  );
}
