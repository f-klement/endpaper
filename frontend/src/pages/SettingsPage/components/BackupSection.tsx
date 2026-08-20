import { useRef, useState } from "react";

import { Button, ErrorState, Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import SettingsSection from "./SettingsSection";

interface BackupSectionProps {
  isDownloading: boolean;
  downloadError: unknown;
  onDownload: () => void;

  isRestoring: boolean;
  restoreError: unknown;
  restored: { books: number; covers: number } | null;
  onRestore: (file: File) => void;
}

/**
 * The whole library out, and back in again.
 *
 * The two halves are not laid out as a pair, deliberately. Downloading is
 * routine and restoring destroys everything, so they do not get matching
 * buttons side by side where the wrong one is a slip of the thumb.
 */
export default function BackupSection({
  isDownloading,
  downloadError,
  onDownload,
  isRestoring,
  restoreError,
  restored,
  onRestore,
}: BackupSectionProps) {
  const { t } = useTranslation();
  const fileInput = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<File | null>(null);

  return (
    <SettingsSection title={t("backup.title")} icon="inbox">
      <p className="text-sm text-paper-500 dark:text-paper-400">
        {t("backup.explain")}
      </p>

      <Button
        variant="secondary"
        className="mt-3"
        isLoading={isDownloading}
        onClick={onDownload}
        icon={<Icon name="inbox" className="h-4 w-4" />}
      >
        {t("backup.download")}
      </Button>
      {downloadError != null && (
        <div className="mt-2">
          <ErrorState error={downloadError} fallback={t("backup.downloadFailed")} />
        </div>
      )}

      <hr className="my-5 border-paper-200 dark:border-paper-800" />

      <h3 className="text-sm font-semibold text-paper-800 dark:text-paper-100">
        {t("backup.restoreTitle")}
      </h3>
      <p className="mt-1 text-sm text-bloom-700 dark:text-bloom-300">
        {t("backup.restoreWarning")}
      </p>

      <input
        ref={fileInput}
        type="file"
        accept=".zip,application/zip"
        aria-label={t("backup.chooseFile")}
        onChange={(event) => setPending(event.target.files?.[0] ?? null)}
        className="mt-3 block w-full text-sm text-paper-500 file:mr-3 file:rounded-lg file:border-0 file:bg-paper-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-paper-700 dark:text-paper-400 dark:file:bg-paper-800 dark:file:text-paper-200"
      />

      {pending && (
        <Button
          variant="danger"
          className="mt-3"
          isLoading={isRestoring}
          onClick={() => {
            if (confirm(t("backup.restoreConfirm"))) {
              onRestore(pending);
              setPending(null);
              if (fileInput.current) fileInput.current.value = "";
            }
          }}
        >
          {t("backup.restoreAction", { name: pending.name })}
        </Button>
      )}

      {restoreError != null && (
        <div className="mt-2">
          <ErrorState error={restoreError} fallback={t("backup.restoreFailed")} />
        </div>
      )}
      {restored && (
        <p
          role="status"
          className="mt-3 rounded-lg bg-green-50 px-3 py-2 text-sm text-green-800 dark:bg-green-950 dark:text-green-200"
        >
          {t("backup.restored", {
            books: restored.books,
            covers: restored.covers,
          })}
        </p>
      )}
    </SettingsSection>
  );
}
